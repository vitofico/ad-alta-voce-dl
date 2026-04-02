"""Flask web application for browsing and downloading RAI Ad Alta Voce audiobooks."""

import json
import logging
import os
import threading
import time
from pathlib import Path
from queue import Queue

from flask import Flask, Response, render_template, send_file, stream_with_context

from rai import core, poller, tagger

log = logging.getLogger(__name__)

DOWNLOADS_DIR = Path(os.environ.get("DOWNLOADS_DIR", "/audiobooks"))

# Shared session for API calls (catalog, detail pages)
_session = core.make_session()

# Track active downloads
_active_downloads: dict[str, threading.Thread] = {}
_download_lock = threading.Lock()

# Download status for API polling (updated by download threads)
_download_status: dict = {}


def _reset_download_status():
    """Reset download status to idle."""
    _download_status.clear()
    _download_status.update(
        {
            "active": False,
            "slug": None,
            "title": None,
            "total_episodes": 0,
            "episodes_downloaded": 0,
            "episodes_skipped": 0,
            "episodes_failed": 0,
            "current_episode": None,
            "current_episode_progress": 0.0,
        }
    )


_reset_download_status()


def _is_any_download_active():
    """Check if any download thread is currently running."""
    return any(t.is_alive() for t in _active_downloads.values())


def create_app():
    app = Flask(__name__)

    # Register REST API (flask-restx under /api/v1/)
    from rai.web.api import create_api

    create_api(app)

    @app.route("/")
    def home():
        """Home page: Ora in onda, Scaricati, Catalogo."""
        current = _fetch_current_audiobook()
        downloaded = _get_downloaded_audiobooks()

        catalog = []
        try:
            catalog_cards = core.fetch_catalog(_session)
            for card in catalog_cards:
                card["_cover_url"] = core.full_image_url(card.get("image", ""))
                card["_slug"] = core.extract_slug(card.get("weblink", ""))
                card["_downloaded"] = _is_audiobook_downloaded(card)
            catalog = catalog_cards
        except Exception as e:
            log.warning("Failed to fetch catalog: %s", e)

        return render_template(
            "home.html",
            current=current,
            downloaded=downloaded,
            catalog=catalog,
        )

    @app.route("/downloaded/<author>/<name>")
    def downloaded_detail(author, name):
        """Show episodes for a downloaded audiobook (reads from disk)."""
        audiobook_dir = DOWNLOADS_DIR / author / name
        if not audiobook_dir.is_dir():
            return "Not found", 404

        meta = _load_audiobook_metadata(audiobook_dir)
        mp3_files = sorted(audiobook_dir.glob("*.mp3"))

        episodes = []
        for f in mp3_files:
            episodes.append(
                {
                    "filename": f.name,
                    "size_mb": f"{f.stat().st_size / 1024 / 1024:.1f}",
                }
            )

        has_cover = (audiobook_dir / "cover.jpg").exists()
        cover_url = ""
        if has_cover:
            cover_url = f"/dl-files/{author}/{name}/cover.jpg"
        elif meta.get("cover_url"):
            cover_url = core.full_image_url(meta["cover_url"])

        return render_template(
            "downloaded_detail.html",
            name=name,
            author=author,
            meta=meta,
            episodes=episodes,
            has_cover=has_cover,
            cover_url=cover_url,
        )

    @app.route("/api/download/current")
    def download_current():
        """Stream download of the currently-airing audiobook via SSE."""
        if _is_any_download_active():
            return Response("Download already in progress", status=409)

        q: Queue = Queue()
        dl_session = core.make_session()

        def do_download():
            with _download_lock:
                _download_status.update(
                    {
                        "active": True,
                        "slug": "current",
                        "title": "Currently airing",
                        "total_episodes": 0,
                        "episodes_downloaded": 0,
                        "episodes_skipped": 0,
                        "episodes_failed": 0,
                        "current_episode": None,
                        "current_episode_progress": 0.0,
                    }
                )
            try:

                def progress_cb(msg):
                    with _download_lock:
                        if msg.get("type") == "episode_start":
                            _download_status["current_episode"] = msg.get("title")
                            _download_status["current_episode_progress"] = 0.0
                            _download_status["total_episodes"] = msg.get("total", 0)
                        elif msg.get("type") == "progress":
                            tb = msg.get("total_bytes", 0)
                            if tb > 0:
                                _download_status["current_episode_progress"] = round(
                                    msg.get("bytes", 0) / tb * 100, 1
                                )
                        elif msg.get("type") == "episode_done":
                            s = msg.get("status", "")
                            if s == "downloaded":
                                _download_status["episodes_downloaded"] += 1
                            elif s == "skipped":
                                _download_status["episodes_skipped"] += 1
                            elif s.startswith("error"):
                                _download_status["episodes_failed"] += 1
                    q.put(json.dumps(msg))

                poller.poll_episodi(session=dl_session, progress_callback=progress_cb)
            except Exception as e:
                q.put(json.dumps({"type": "error", "message": str(e)}))
            finally:
                with _download_lock:
                    _download_status["active"] = False
                    _download_status["current_episode"] = None
                q.put(None)

        thread = threading.Thread(target=do_download, daemon=True)
        _active_downloads["current"] = thread
        thread.start()

        def generate():
            while True:
                msg = q.get()
                if msg is None:
                    yield "event: complete\ndata: {}\n\n"
                    break
                yield f"data: {msg}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.route("/api/poll")
    def manual_poll():
        """Trigger a manual poll (returns SSE stream)."""
        if _is_any_download_active():
            return Response("Download already in progress", status=409)

        q: Queue = Queue()

        def do_poll():
            try:

                def progress_cb(msg):
                    q.put(json.dumps(msg))

                poller.poll_episodi(session=core.make_session(), progress_callback=progress_cb)
            except Exception as e:
                q.put(json.dumps({"type": "error", "message": str(e)}))
            finally:
                q.put(None)

        thread = threading.Thread(target=do_poll, daemon=True)
        _active_downloads["current"] = thread
        thread.start()

        def generate():
            while True:
                msg = q.get()
                if msg is None:
                    yield "event: complete\ndata: {}\n\n"
                    break
                yield f"data: {msg}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.route("/health")
    def health():
        """Health check endpoint for Docker."""
        return "ok"

    @app.route("/dl-files/<path:filepath>")
    def serve_download_file(filepath):
        """Serve files from the downloads directory (covers, etc.)."""
        full_path = DOWNLOADS_DIR / filepath
        if not full_path.exists() or not full_path.is_file():
            return "Not found", 404
        try:
            full_path.resolve().relative_to(DOWNLOADS_DIR.resolve())
        except ValueError:
            return "Forbidden", 403
        return send_file(full_path)

    @app.route("/audiobook/<slug>")
    def audiobook_detail(slug):
        """Detail page for a catalog audiobook."""
        try:
            data = core.fetch_audiobook(f"/audiolibri/{slug}", _session)
        except Exception:
            return "Audiobook not found", 404

        cards = core.extract_cards(data)
        if not cards:
            return "No episodes found", 404

        title = data.get("title") or data.get("name") or slug

        # Parse author from first episode description
        desc = cards[0].get("description", "")
        reader_name, _, author_name = core.parse_description(desc)

        # Fallback author from podcast_info
        if not author_name:
            pi = data.get("podcast_info", {})
            if isinstance(pi, dict):
                author_name = pi.get("author", "")

        # Cover from catalog card
        catalog_card = core.find_catalog_card(title, _session)
        cover_url = ""
        if catalog_card:
            images = catalog_card.get("images", {})
            cover_url = images.get("square") or images.get("cover") or catalog_card.get("image", "")
            cover_url = core.full_image_url(cover_url)

        # Book description from catalog or podcast_info
        book_description = ""
        if catalog_card:
            book_description = catalog_card.get("description", "")
        if not book_description:
            pi = data.get("podcast_info", {})
            if isinstance(pi, dict):
                book_description = pi.get("description", "")

        # Check download status per episode
        author_clean = core.sanitize_filename(author_name) if author_name else "Ad Alta Voce"
        title_clean = core.sanitize_filename(title)
        output_dir = DOWNLOADS_DIR / author_clean / title_clean

        sorted_cards = sorted(cards, key=lambda c: int(c.get("episode", 0) or 0))
        for i, ep in enumerate(sorted_cards):
            filename = core.build_episode_filename(ep, i)
            ep["_downloaded"] = (output_dir / filename).exists()
            ep["_duration"] = ep.get("literal_duration", ep.get("duration_small_format", ""))

        downloaded_count = sum(1 for e in sorted_cards if e.get("_downloaded"))
        downloading = _is_any_download_active()

        return render_template(
            "audiobook.html",
            title=title,
            author=author_name or "",
            description=book_description,
            cover_url=cover_url,
            slug=slug,
            episodes=sorted_cards,
            total=len(sorted_cards),
            downloaded_count=downloaded_count,
            downloading=downloading,
        )

    @app.route("/api/download/<slug>")
    def download_audiobook(slug):
        """Stream download of a catalog audiobook via SSE."""
        if _is_any_download_active():
            return Response("Download already in progress", status=409)

        # Fetch audiobook metadata
        try:
            data = core.fetch_audiobook(f"/audiolibri/{slug}", _session)
        except Exception:
            return Response("Audiobook not found", status=404)

        cards = core.extract_cards(data)
        if not cards:
            return Response("No episodes found", status=404)

        title = data.get("title") or data.get("name") or slug

        # Parse author
        desc = cards[0].get("description", "")
        reader_name, _, author_name = core.parse_description(desc)
        if not author_name:
            pi = data.get("podcast_info", {})
            if isinstance(pi, dict):
                author_name = pi.get("author", "")

        # Cover URL
        catalog_card = core.find_catalog_card(title, _session)
        cover_url = ""
        if catalog_card:
            images = catalog_card.get("images", {})
            cover_url = images.get("square") or images.get("cover") or catalog_card.get("image", "")

        author_clean = core.sanitize_filename(author_name) if author_name else "Ad Alta Voce"
        title_clean = core.sanitize_filename(title)
        output_dir = DOWNLOADS_DIR / author_clean / title_clean

        q: Queue = Queue()
        dl_session = core.make_session()
        sorted_cards = sorted(cards, key=lambda c: int(c.get("episode", 0) or 0))

        def do_download():
            total = len(sorted_cards)
            episode_meta_list = []
            with _download_lock:
                _download_status.update(
                    {
                        "active": True,
                        "slug": slug,
                        "title": title,
                        "total_episodes": total,
                        "episodes_downloaded": 0,
                        "episodes_skipped": 0,
                        "episodes_failed": 0,
                        "current_episode": None,
                        "current_episode_progress": 0.0,
                    }
                )
            try:
                output_dir.mkdir(parents=True, exist_ok=True)

                for idx, card in enumerate(sorted_cards):
                    ep_title = card.get("title", card.get("name", f"episode_{idx + 1}"))
                    ep_num = idx + 1
                    filename = core.build_episode_filename(card, idx)
                    filepath = output_dir / filename

                    episode_meta_list.append(
                        {
                            "episode": ep_num,
                            "title": ep_title,
                            "path_id": card.get("path_id", ""),
                        }
                    )

                    # Skip if already downloaded
                    if filepath.exists() and filepath.stat().st_size > 0:
                        with _download_lock:
                            _download_status["episodes_skipped"] += 1
                        q.put(
                            json.dumps(
                                {
                                    "type": "episode_done",
                                    "episode": ep_num,
                                    "total": total,
                                    "status": "skipped",
                                }
                            )
                        )
                        continue

                    audio_url = core.get_audio_url(card)
                    if not audio_url:
                        with _download_lock:
                            _download_status["episodes_failed"] += 1
                        q.put(
                            json.dumps(
                                {
                                    "type": "episode_done",
                                    "episode": ep_num,
                                    "total": total,
                                    "status": "error: no audio URL",
                                }
                            )
                        )
                        continue

                    with _download_lock:
                        _download_status["current_episode"] = ep_title
                        _download_status["current_episode_progress"] = 0.0
                    q.put(
                        json.dumps(
                            {
                                "type": "episode_start",
                                "episode": ep_num,
                                "total": total,
                                "title": ep_title,
                            }
                        )
                    )

                    try:
                        direct_url = core.resolve_relinker(audio_url, dl_session)

                        last_emit_time = [0.0]

                        def progress_cb(bytes_dl, total_bytes, _ep=ep_num, _total=total):
                            now = time.monotonic()
                            if now - last_emit_time[0] >= 0.5 or bytes_dl >= total_bytes:
                                last_emit_time[0] = now
                                pct = (
                                    round(bytes_dl / total_bytes * 100, 1)
                                    if total_bytes > 0
                                    else 0.0
                                )
                                with _download_lock:
                                    _download_status["current_episode_progress"] = pct
                                q.put(
                                    json.dumps(
                                        {
                                            "type": "progress",
                                            "episode": _ep,
                                            "total": _total,
                                            "bytes": bytes_dl,
                                            "total_bytes": total_bytes,
                                        }
                                    )
                                )

                        core.download_file(direct_url, filepath, dl_session, progress_cb)

                        # Tag MP3
                        audiobook_data = {
                            "title": title,
                            "podcast_info": {
                                "author": author_name or "",
                                "genres": (
                                    catalog_card.get("genres", []) if catalog_card else []
                                ),
                                "images": (
                                    catalog_card.get("images", {}) if catalog_card else {}
                                ),
                                "image": cover_url,
                            },
                        }
                        try:
                            tagger.tag_episode(
                                filepath, card, audiobook_data, idx, total, dl_session
                            )
                        except Exception as e:
                            log.warning("Tagging failed for %s: %s", filename, e)

                        with _download_lock:
                            _download_status["episodes_downloaded"] += 1
                        q.put(
                            json.dumps(
                                {
                                    "type": "episode_done",
                                    "episode": ep_num,
                                    "total": total,
                                    "status": "downloaded",
                                }
                            )
                        )

                    except Exception as e:
                        tmp = filepath.with_suffix(".tmp")
                        if tmp.exists():
                            tmp.unlink()
                        with _download_lock:
                            _download_status["episodes_failed"] += 1
                        q.put(
                            json.dumps(
                                {
                                    "type": "episode_done",
                                    "episode": ep_num,
                                    "total": total,
                                    "status": f"error: {e}",
                                }
                            )
                        )

                # Save metadata and cover
                poller._save_metadata(
                    output_dir=output_dir,
                    title=title,
                    author=author_name,
                    reader=reader_name,
                    description=(
                        catalog_card.get("description", "") if catalog_card else ""
                    ),
                    cover_url=cover_url,
                    episodes=episode_meta_list,
                    completed=True,
                    session=dl_session,
                    source="catalog",
                )

            except Exception as e:
                q.put(json.dumps({"type": "error", "message": str(e)}))
            finally:
                with _download_lock:
                    _download_status["active"] = False
                    _download_status["current_episode"] = None
                q.put(None)

        thread = threading.Thread(target=do_download, daemon=True)
        _active_downloads[slug] = thread
        thread.start()

        def generate():
            while True:
                msg = q.get()
                if msg is None:
                    yield "event: complete\ndata: {}\n\n"
                    break
                yield f"data: {msg}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def _fetch_current_audiobook():
    """Fetch currently-airing audiobook info from episodi feed."""
    try:
        data = core.fetch_episodi(_session)
        cards = core.extract_cards(data)
        if not cards:
            return None

        audiobook_name = core.parse_audiobook_from_episodi(cards)
        if not audiobook_name:
            return None

        # Filter out episodes from other audiobooks (feed may mix old + new)
        cards = core.filter_cards_by_audiobook(cards, audiobook_name)
        if not cards:
            return None

        desc = cards[0].get("description", "")
        reader_name, _, author_name = core.parse_description(desc)

        # Get cover from catalog
        catalog_card = core.find_catalog_card(audiobook_name, _session)
        cover_url = ""
        if catalog_card:
            images = catalog_card.get("images", {})
            cover_url = images.get("square") or images.get("cover") or catalog_card.get("image", "")
            cover_url = core.full_image_url(cover_url)

        # Sort episodes by number
        sorted_cards = sorted(cards, key=lambda c: int(c.get("episode", 0) or 0))

        # Check download status using author/title structure
        output_dir = poller._audiobook_dir(author_name, audiobook_name)
        for i, ep in enumerate(sorted_cards):
            filename = core.build_episode_filename(ep, i)
            ep["_downloaded"] = (output_dir / filename).exists()
            ep["_duration"] = ep.get("literal_duration", ep.get("duration_small_format", ""))

        downloading = _is_any_download_active()

        return {
            "name": audiobook_name,
            "author": author_name or "",
            "reader": reader_name or "",
            "description": catalog_card.get("description", desc) if catalog_card else desc,
            "cover_url": cover_url,
            "episodes": sorted_cards,
            "total": len(sorted_cards),
            "downloaded_count": sum(1 for e in sorted_cards if e.get("_downloaded")),
            "downloading": downloading,
        }
    except Exception as e:
        log.warning("Failed to fetch episodi: %s", e)
        return None


def _get_downloaded_audiobooks():
    """Scan downloads dir for audiobooks (Author/Title structure)."""
    downloaded = []
    if not DOWNLOADS_DIR.exists():
        return downloaded

    for author_dir in sorted(DOWNLOADS_DIR.iterdir()):
        if not author_dir.is_dir() or author_dir.name.startswith("."):
            continue
        for book_dir in sorted(author_dir.iterdir()):
            if not book_dir.is_dir() or book_dir.name.startswith("."):
                continue
            mp3_count = len(list(book_dir.glob("*.mp3")))
            if mp3_count == 0:
                continue

            meta = _load_audiobook_metadata(book_dir)
            has_cover = (book_dir / "cover.jpg").exists()
            rel_path = f"{author_dir.name}/{book_dir.name}"

            downloaded.append(
                {
                    "name": book_dir.name,
                    "author_dir": author_dir.name,
                    "rel_path": rel_path,
                    "title": meta.get("title", book_dir.name),
                    "author": meta.get("author", author_dir.name),
                    "reader": meta.get("reader", ""),
                    "episode_count": mp3_count,
                    "completed": meta.get("completed", False),
                    "cover_url": (
                        f"/dl-files/{rel_path}/cover.jpg"
                        if has_cover
                        else core.full_image_url(meta.get("cover_url", ""))
                    ),
                }
            )

    return downloaded


def _load_audiobook_metadata(audiobook_dir):
    """Load metadata.json from an audiobook directory."""
    meta_path = audiobook_dir / "metadata.json"
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text())
        except json.JSONDecodeError, OSError:
            pass
    return {}


def _is_audiobook_downloaded(card):
    """Check if any episodes of an audiobook are downloaded."""
    title = card.get("title", "")
    if not title:
        return False
    # Check all author directories for a matching title
    if not DOWNLOADS_DIR.exists():
        return False
    for author_dir in DOWNLOADS_DIR.iterdir():
        if not author_dir.is_dir() or author_dir.name.startswith("."):
            continue
        book_dir = author_dir / core.sanitize_filename(title)
        if book_dir.exists() and any(book_dir.glob("*.mp3")):
            return True
    return False


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
