"""Flask web application for browsing and downloading RAI Ad Alta Voce audiobooks."""

import json
import logging
import os
import threading
from pathlib import Path
from queue import Queue

from flask import Flask, Response, render_template, send_file, stream_with_context

from rai import core, poller

log = logging.getLogger(__name__)

DOWNLOADS_DIR = Path(os.environ.get("DOWNLOADS_DIR", "/audiobooks"))

# Shared session for API calls (catalog, detail pages)
_session = core.make_session()

# Track active downloads
_active_downloads: dict[str, threading.Thread] = {}


def _is_any_download_active():
    """Check if any download thread is currently running."""
    return any(t.is_alive() for t in _active_downloads.values())


def create_app():
    app = Flask(__name__)

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
            try:

                def progress_cb(msg):
                    q.put(json.dumps(msg))

                poller.poll_episodi(session=dl_session, progress_callback=progress_cb)
            except Exception as e:
                q.put(json.dumps({"type": "error", "message": str(e)}))
            finally:
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
