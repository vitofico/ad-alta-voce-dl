"""Flask web application for browsing and downloading RAI Ad Alta Voce audiobooks."""

import json
import logging
import threading
from pathlib import Path
from queue import Queue

from flask import Flask, Response, jsonify, render_template, send_file, stream_with_context

from rai import core, poller
from rai.scheduler import get_scheduler

log = logging.getLogger(__name__)

DOWNLOADS_DIR = Path("/downloads")

# Shared session for API calls (catalog, detail pages)
_session = core.make_session()

# Track active downloads
_active_downloads: dict[str, threading.Thread] = {}


def create_app():
    app = Flask(__name__)

    # Start the scheduler on app init
    sched = get_scheduler()
    sched.start()
    log.info("Scheduler started with interval: %s", sched.interval_human)

    @app.route("/")
    def home():
        """Home page: Ora in onda, Scaricati, Catalogo."""
        # 1. Ora in onda (currently airing)
        current = _fetch_current_audiobook()

        # 2. Scaricati (downloaded audiobooks)
        downloaded = _get_downloaded_audiobooks()

        # 3. Catalogo
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

        # Scheduler status
        sched_status = sched.get_status()

        return render_template(
            "home.html",
            current=current,
            downloaded=downloaded,
            catalog=catalog,
            scheduler=sched_status,
        )

    @app.route("/downloaded/<name>")
    def downloaded_detail(name):
        """Show episodes for a downloaded audiobook (reads from disk)."""
        audiobook_dir = DOWNLOADS_DIR / name
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
            cover_url = f"/dl-files/{name}/cover.jpg"
        elif meta.get("cover_url"):
            cover_url = core.full_image_url(meta["cover_url"])

        return render_template(
            "downloaded_detail.html",
            name=name,
            meta=meta,
            episodes=episodes,
            has_cover=has_cover,
            cover_url=cover_url,
        )

    @app.route("/api/download/current")
    def download_current():
        """Stream download of the currently-airing audiobook via SSE."""
        if "current" in _active_downloads and _active_downloads["current"].is_alive():
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
        if "current" in _active_downloads and _active_downloads["current"].is_alive():
            return jsonify({"error": "Download already in progress"}), 409

        q: Queue = Queue()

        def do_poll():
            try:

                def progress_cb(msg):
                    q.put(json.dumps(msg))

                sched.poll_now(progress_callback=progress_cb)
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

    @app.route("/api/scheduler")
    def scheduler_status():
        """Return scheduler status as JSON."""
        return jsonify(sched.get_status())

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

        # Check download status
        output_dir = DOWNLOADS_DIR / core.sanitize_filename(audiobook_name)
        for i, ep in enumerate(sorted_cards):
            filename = core.build_episode_filename(ep, i)
            ep["_downloaded"] = (output_dir / filename).exists()
            ep["_duration"] = ep.get("literal_duration", ep.get("duration_small_format", ""))

        downloading = "current" in _active_downloads and _active_downloads["current"].is_alive()

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
    """Scan /downloads/ for downloaded audiobooks."""
    downloaded = []
    if not DOWNLOADS_DIR.exists():
        return downloaded

    for d in sorted(DOWNLOADS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        mp3_count = len(list(d.glob("*.mp3")))
        if mp3_count == 0:
            continue

        meta = _load_audiobook_metadata(d)
        has_cover = (d / "cover.jpg").exists()

        downloaded.append(
            {
                "name": d.name,
                "title": meta.get("title", d.name),
                "author": meta.get("author", ""),
                "reader": meta.get("reader", ""),
                "episode_count": mp3_count,
                "completed": meta.get("completed", False),
                "cover_url": (
                    f"/dl-files/{d.name}/cover.jpg"
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
    output_dir = DOWNLOADS_DIR / core.sanitize_filename(title)
    if not output_dir.exists():
        return False
    return any(output_dir.glob("*.mp3"))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
