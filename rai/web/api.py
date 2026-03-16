"""REST API for Ad Alta Voce downloader (flask-restx, OpenAPI/Swagger)."""

import logging
import threading

from flask_restx import Api, Resource, fields

from rai import core, poller, tagger

log = logging.getLogger(__name__)


def create_api(app):
    """Create and register the REST API on the Flask app."""
    # Import shared state from app module
    from rai.web import app as app_mod

    api = Api(
        app,
        version="1.0",
        title="Ad Alta Voce API",
        description="REST API for browsing and downloading RAI Ad Alta Voce audiobooks",
        prefix="/api/v1",
        doc="/api/v1/",
    )

    # --- Models ---

    episode_model = api.model(
        "Episode",
        {
            "number": fields.Integer(description="Episode number"),
            "title": fields.String(description="Episode title"),
            "duration": fields.String(description="Duration string"),
            "downloaded": fields.Boolean(description="Whether episode is downloaded"),
        },
    )

    catalog_item_model = api.model(
        "CatalogItem",
        {
            "slug": fields.String(description="URL slug"),
            "title": fields.String(description="Audiobook title"),
            "subtitle": fields.String(description="Subtitle or author info"),
            "cover_url": fields.String(description="Cover image URL"),
            "downloaded": fields.Boolean(description="Has any downloaded episodes"),
        },
    )

    audiobook_detail_model = api.model(
        "AudiobookDetail",
        {
            "slug": fields.String(description="URL slug"),
            "title": fields.String(description="Audiobook title"),
            "author": fields.String(description="Author name"),
            "reader": fields.String(description="Reader/narrator name"),
            "description": fields.String(description="Book description"),
            "cover_url": fields.String(description="Cover image URL"),
            "total_episodes": fields.Integer(description="Total episode count"),
            "downloaded_count": fields.Integer(description="Downloaded episode count"),
            "episodes": fields.List(fields.Nested(episode_model)),
        },
    )

    downloaded_book_model = api.model(
        "DownloadedBook",
        {
            "title": fields.String(description="Audiobook title"),
            "author": fields.String(description="Author name"),
            "reader": fields.String(description="Reader/narrator"),
            "episode_count": fields.Integer(description="Number of episodes"),
            "completed": fields.Boolean(description="Download completed"),
            "cover_url": fields.String(description="Cover image URL"),
        },
    )

    download_status_model = api.model(
        "DownloadStatus",
        {
            "active": fields.Boolean(description="Whether a download is in progress"),
            "slug": fields.String(description="Slug of audiobook being downloaded"),
            "title": fields.String(description="Title of audiobook being downloaded"),
            "total_episodes": fields.Integer(description="Total episodes to download"),
            "episodes_downloaded": fields.Integer(description="Episodes downloaded so far"),
            "episodes_skipped": fields.Integer(description="Episodes skipped (already existed)"),
            "episodes_failed": fields.Integer(description="Episodes that failed"),
            "current_episode": fields.String(description="Currently downloading episode title"),
            "current_episode_progress": fields.Float(
                description="Download progress of current episode (0-100)"
            ),
        },
    )

    download_trigger_model = api.model(
        "DownloadTrigger",
        {
            "message": fields.String(description="Status message"),
            "slug": fields.String(description="Slug of audiobook being downloaded"),
        },
    )

    health_model = api.model(
        "HealthResponse",
        {
            "status": fields.String(description="Health status"),
        },
    )

    error_model = api.model(
        "ErrorResponse",
        {
            "message": fields.String(description="Error message"),
        },
    )

    # --- Namespaces ---

    ns_catalog = api.namespace("catalog", description="Browse audiobook catalog")
    ns_current = api.namespace("current", description="Currently airing audiobook")
    ns_downloaded = api.namespace("downloaded", description="Downloaded audiobooks")
    ns_download = api.namespace("download", description="Download management")
    ns_system = api.namespace("system", description="System operations")

    # --- Catalog ---

    @ns_catalog.route("/")
    class CatalogList(Resource):
        @ns_catalog.marshal_list_with(catalog_item_model)
        @ns_catalog.doc(description="List all available audiobooks from the RAI catalog")
        def get(self):
            """List all audiobooks in the catalog."""
            try:
                cards = core.fetch_catalog(app_mod._session)
            except Exception as e:
                api.abort(502, f"Failed to fetch catalog: {e}")

            result = []
            for card in cards:
                slug = core.extract_slug(card.get("weblink", ""))
                result.append(
                    {
                        "slug": slug,
                        "title": card.get("title", ""),
                        "subtitle": card.get("subtitle", ""),
                        "cover_url": core.full_image_url(card.get("image", "")),
                        "downloaded": app_mod._is_audiobook_downloaded(card),
                    }
                )
            return result

    @ns_catalog.route("/<string:slug>")
    @ns_catalog.param("slug", "Audiobook slug (e.g. 'agostino')")
    class CatalogDetail(Resource):
        @ns_catalog.marshal_with(audiobook_detail_model)
        @ns_catalog.response(404, "Audiobook not found", error_model)
        @ns_catalog.doc(description="Get audiobook details including episode list")
        def get(self, slug):
            """Get audiobook details with episodes."""
            try:
                data = core.fetch_audiobook(f"/audiolibri/{slug}", app_mod._session)
            except Exception:
                api.abort(404, "Audiobook not found")

            cards = core.extract_cards(data)
            if not cards:
                api.abort(404, "No episodes found")

            title = data.get("title") or data.get("name") or slug

            desc = cards[0].get("description", "")
            reader_name, _, author_name = core.parse_description(desc)
            if not author_name:
                pi = data.get("podcast_info", {})
                if isinstance(pi, dict):
                    author_name = pi.get("author", "")

            catalog_card = core.find_catalog_card(title, app_mod._session)
            cover_url = ""
            if catalog_card:
                images = catalog_card.get("images", {})
                cover_url = (
                    images.get("square") or images.get("cover") or catalog_card.get("image", "")
                )
                cover_url = core.full_image_url(cover_url)

            book_description = ""
            if catalog_card:
                book_description = catalog_card.get("description", "")
            if not book_description:
                pi = data.get("podcast_info", {})
                if isinstance(pi, dict):
                    book_description = pi.get("description", "")

            author_clean = core.sanitize_filename(author_name) if author_name else "Ad Alta Voce"
            title_clean = core.sanitize_filename(title)
            output_dir = app_mod.DOWNLOADS_DIR / author_clean / title_clean

            sorted_cards = sorted(cards, key=lambda c: int(c.get("episode", 0) or 0))
            episodes = []
            for i, ep in enumerate(sorted_cards):
                filename = core.build_episode_filename(ep, i)
                episodes.append(
                    {
                        "number": i + 1,
                        "title": ep.get("title", ep.get("name", "")),
                        "duration": ep.get(
                            "literal_duration", ep.get("duration_small_format", "")
                        ),
                        "downloaded": (output_dir / filename).exists(),
                    }
                )

            return {
                "slug": slug,
                "title": title,
                "author": author_name or "",
                "reader": reader_name or "",
                "description": book_description,
                "cover_url": cover_url,
                "total_episodes": len(episodes),
                "downloaded_count": sum(1 for e in episodes if e["downloaded"]),
                "episodes": episodes,
            }

    # --- Current ---

    @ns_current.route("/")
    class CurrentAudiobook(Resource):
        @ns_current.marshal_with(audiobook_detail_model)
        @ns_current.response(404, "No audiobook currently airing", error_model)
        @ns_current.doc(description="Get the currently airing audiobook with episodes")
        def get(self):
            """Get currently airing audiobook."""
            current = app_mod._fetch_current_audiobook()
            if not current:
                api.abort(404, "No audiobook currently airing")

            episodes = []
            for i, ep in enumerate(current.get("episodes", [])):
                episodes.append(
                    {
                        "number": ep.get("episode", i + 1),
                        "title": ep.get("episode_title", ep.get("toptitle", ep.get("title", ""))),
                        "duration": ep.get("_duration", ""),
                        "downloaded": ep.get("_downloaded", False),
                    }
                )

            return {
                "slug": "current",
                "title": current["name"],
                "author": current.get("author", ""),
                "reader": current.get("reader", ""),
                "description": current.get("description", ""),
                "cover_url": current.get("cover_url", ""),
                "total_episodes": current.get("total", 0),
                "downloaded_count": current.get("downloaded_count", 0),
                "episodes": episodes,
            }

    # --- Downloaded ---

    @ns_downloaded.route("/")
    class DownloadedList(Resource):
        @ns_downloaded.marshal_list_with(downloaded_book_model)
        @ns_downloaded.doc(description="List all audiobooks that have been downloaded to disk")
        def get(self):
            """List downloaded audiobooks."""
            books = app_mod._get_downloaded_audiobooks()
            return [
                {
                    "title": b.get("title", b["name"]),
                    "author": b.get("author", ""),
                    "reader": b.get("reader", ""),
                    "episode_count": b["episode_count"],
                    "completed": b.get("completed", False),
                    "cover_url": b.get("cover_url", ""),
                }
                for b in books
            ]

    # --- Download ---

    @ns_download.route("/status")
    class DownloadStatusResource(Resource):
        @ns_download.marshal_with(download_status_model)
        @ns_download.doc(description="Get current download status (active/idle, progress)")
        def get(self):
            """Get download status."""
            with app_mod._download_lock:
                return dict(app_mod._download_status)

    @ns_download.route("/<string:slug>")
    @ns_download.param("slug", "Audiobook slug to download")
    class DownloadTrigger(Resource):
        @ns_download.marshal_with(download_trigger_model, code=202)
        @ns_download.response(404, "Audiobook not found", error_model)
        @ns_download.response(409, "Download already in progress", error_model)
        @ns_download.doc(description="Trigger download of a catalog audiobook (fire-and-forget)")
        def post(self, slug):
            """Trigger download of a catalog audiobook."""
            if app_mod._is_any_download_active():
                api.abort(409, "Download already in progress")

            # Fetch audiobook metadata
            try:
                data = core.fetch_audiobook(f"/audiolibri/{slug}", app_mod._session)
            except Exception:
                api.abort(404, "Audiobook not found")

            cards = core.extract_cards(data)
            if not cards:
                api.abort(404, "No episodes found")

            title = data.get("title") or data.get("name") or slug

            desc = cards[0].get("description", "")
            reader_name, _, author_name = core.parse_description(desc)
            if not author_name:
                pi = data.get("podcast_info", {})
                if isinstance(pi, dict):
                    author_name = pi.get("author", "")

            catalog_card = core.find_catalog_card(title, app_mod._session)
            cover_url = ""
            if catalog_card:
                images = catalog_card.get("images", {})
                cover_url = (
                    images.get("square") or images.get("cover") or catalog_card.get("image", "")
                )

            author_clean = core.sanitize_filename(author_name) if author_name else "Ad Alta Voce"
            title_clean = core.sanitize_filename(title)
            output_dir = app_mod.DOWNLOADS_DIR / author_clean / title_clean
            sorted_cards = sorted(cards, key=lambda c: int(c.get("episode", 0) or 0))

            dl_session = core.make_session()

            def do_download():
                import time

                total = len(sorted_cards)
                episode_meta_list = []
                with app_mod._download_lock:
                    app_mod._download_status.update(
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

                        if filepath.exists() and filepath.stat().st_size > 0:
                            with app_mod._download_lock:
                                app_mod._download_status["episodes_skipped"] += 1
                            continue

                        audio_url = core.get_audio_url(card)
                        if not audio_url:
                            with app_mod._download_lock:
                                app_mod._download_status["episodes_failed"] += 1
                            continue

                        with app_mod._download_lock:
                            app_mod._download_status["current_episode"] = ep_title
                            app_mod._download_status["current_episode_progress"] = 0.0

                        try:
                            direct_url = core.resolve_relinker(audio_url, dl_session)

                            last_emit_time = [0.0]

                            def progress_cb(
                                bytes_dl, total_bytes, _ep=ep_num, _total=total
                            ):
                                now = time.monotonic()
                                if (
                                    now - last_emit_time[0] >= 0.5
                                    or bytes_dl >= total_bytes
                                ):
                                    last_emit_time[0] = now
                                    pct = (
                                        round(bytes_dl / total_bytes * 100, 1)
                                        if total_bytes > 0
                                        else 0.0
                                    )
                                    with app_mod._download_lock:
                                        app_mod._download_status[
                                            "current_episode_progress"
                                        ] = pct

                            core.download_file(direct_url, filepath, dl_session, progress_cb)

                            audiobook_data = {
                                "title": title,
                                "podcast_info": {
                                    "author": author_name or "",
                                    "genres": (
                                        catalog_card.get("genres", [])
                                        if catalog_card
                                        else []
                                    ),
                                    "images": (
                                        catalog_card.get("images", {})
                                        if catalog_card
                                        else {}
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

                            with app_mod._download_lock:
                                app_mod._download_status["episodes_downloaded"] += 1

                        except Exception as e:
                            tmp = filepath.with_suffix(".tmp")
                            if tmp.exists():
                                tmp.unlink()
                            with app_mod._download_lock:
                                app_mod._download_status["episodes_failed"] += 1
                            log.error("Failed to download %s: %s", ep_title, e)

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
                    log.error("Download failed for %s: %s", slug, e)
                finally:
                    with app_mod._download_lock:
                        app_mod._download_status["active"] = False
                        app_mod._download_status["current_episode"] = None

            thread = threading.Thread(target=do_download, daemon=True)
            app_mod._active_downloads[slug] = thread
            thread.start()

            return {"message": "Download started", "slug": slug}, 202

    @ns_download.route("/current")
    class DownloadCurrentTrigger(Resource):
        @ns_download.marshal_with(download_trigger_model, code=202)
        @ns_download.response(409, "Download already in progress", error_model)
        @ns_download.doc(
            description="Trigger download of the currently airing audiobook (fire-and-forget)"
        )
        def post(self):
            """Trigger download of the currently airing audiobook."""
            if app_mod._is_any_download_active():
                api.abort(409, "Download already in progress")

            dl_session = core.make_session()

            def do_download():
                with app_mod._download_lock:
                    app_mod._download_status.update(
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
                        with app_mod._download_lock:
                            if msg.get("type") == "episode_start":
                                app_mod._download_status["current_episode"] = msg.get("title")
                                app_mod._download_status["current_episode_progress"] = 0.0
                                app_mod._download_status["total_episodes"] = msg.get(
                                    "total", 0
                                )
                            elif msg.get("type") == "progress":
                                tb = msg.get("total_bytes", 0)
                                if tb > 0:
                                    app_mod._download_status[
                                        "current_episode_progress"
                                    ] = round(msg.get("bytes", 0) / tb * 100, 1)
                            elif msg.get("type") == "episode_done":
                                s = msg.get("status", "")
                                if s == "downloaded":
                                    app_mod._download_status["episodes_downloaded"] += 1
                                elif s == "skipped":
                                    app_mod._download_status["episodes_skipped"] += 1
                                elif s.startswith("error"):
                                    app_mod._download_status["episodes_failed"] += 1

                    poller.poll_episodi(session=dl_session, progress_callback=progress_cb)
                except Exception as e:
                    log.error("Download of current audiobook failed: %s", e)
                finally:
                    with app_mod._download_lock:
                        app_mod._download_status["active"] = False
                        app_mod._download_status["current_episode"] = None

            thread = threading.Thread(target=do_download, daemon=True)
            app_mod._active_downloads["current"] = thread
            thread.start()

            return {"message": "Download started", "slug": "current"}, 202

    # --- System ---

    @ns_system.route("/poll")
    class PollTrigger(Resource):
        @ns_system.marshal_with(download_trigger_model, code=202)
        @ns_system.response(409, "Download already in progress", error_model)
        @ns_system.doc(description="Trigger a poll for new episodes of the currently airing book")
        def post(self):
            """Trigger a poll for new episodes."""
            if app_mod._is_any_download_active():
                api.abort(409, "Download already in progress")

            dl_session = core.make_session()

            def do_poll():
                with app_mod._download_lock:
                    app_mod._download_status.update(
                        {
                            "active": True,
                            "slug": "poll",
                            "title": "Polling for new episodes",
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
                        with app_mod._download_lock:
                            if msg.get("type") == "episode_start":
                                app_mod._download_status["current_episode"] = msg.get("title")
                                app_mod._download_status["current_episode_progress"] = 0.0
                                app_mod._download_status["total_episodes"] = msg.get(
                                    "total", 0
                                )
                            elif msg.get("type") == "progress":
                                tb = msg.get("total_bytes", 0)
                                if tb > 0:
                                    app_mod._download_status[
                                        "current_episode_progress"
                                    ] = round(msg.get("bytes", 0) / tb * 100, 1)
                            elif msg.get("type") == "episode_done":
                                s = msg.get("status", "")
                                if s == "downloaded":
                                    app_mod._download_status["episodes_downloaded"] += 1
                                elif s == "skipped":
                                    app_mod._download_status["episodes_skipped"] += 1
                                elif s.startswith("error"):
                                    app_mod._download_status["episodes_failed"] += 1

                    poller.poll_episodi(session=dl_session, progress_callback=progress_cb)
                except Exception as e:
                    log.error("Poll failed: %s", e)
                finally:
                    with app_mod._download_lock:
                        app_mod._download_status["active"] = False
                        app_mod._download_status["current_episode"] = None

            thread = threading.Thread(target=do_poll, daemon=True)
            app_mod._active_downloads["poll"] = thread
            thread.start()

            return {"message": "Poll started", "slug": "poll"}, 202

    @ns_system.route("/health")
    class HealthCheck(Resource):
        @ns_system.marshal_with(health_model)
        @ns_system.doc(description="Health check endpoint")
        def get(self):
            """Health check."""
            return {"status": "ok"}

    return api
