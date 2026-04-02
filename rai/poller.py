"""Poller for RAI Ad Alta Voce episodi feed.

Polls /programmi/adaltavoce.json, detects the currently-airing audiobook,
and downloads new episodes idempotently.

Directory structure (Audiobookshelf-compatible):
    <DOWNLOADS_DIR>/<Author>/<Title>/001 - Episode.mp3
"""

import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from rai import core, tagger

log = logging.getLogger(__name__)

DOWNLOADS_DIR = Path(os.environ.get("DOWNLOADS_DIR", "/audiobooks"))
STATE_DIR = Path(os.environ.get("POLLER_STATE_DIR", "/state"))
STATE_FILE = STATE_DIR / "poller-state.json"


def _load_state():
    """Load poller state from disk."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError, OSError:
            log.warning("Corrupt state file, starting fresh")
    return {
        "current_audiobook": None,
        "last_poll": None,
        "episodes_seen": {},
    }


def _save_state(state):
    """Persist poller state to disk."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _audiobook_dir(author, title):
    """Build the output directory path: <DOWNLOADS_DIR>/<Author>/<Title>."""
    author_clean = core.sanitize_filename(author) if author else "Ad Alta Voce"
    title_clean = core.sanitize_filename(title)
    return DOWNLOADS_DIR / author_clean / title_clean


def _save_metadata(
    output_dir, title, author, reader, description, cover_url, episodes, completed, session,
    source="episodi",
):
    """Save audiobook metadata and cover to disk."""
    meta = {
        "title": title,
        "author": author or "",
        "reader": reader or "",
        "description": description or "",
        "cover_url": cover_url or "",
        "cover_cached": False,
        "episode_count": len(episodes),
        "episodes": episodes,
        "source": source,
        "completed": completed,
        "last_updated": datetime.now(UTC).isoformat(),
    }

    # Cache cover image to disk
    if cover_url and session:
        try:
            cover_path = output_dir / "cover.jpg"
            if not cover_path.exists():
                resp = session.get(core.full_image_url(cover_url), timeout=30)
                resp.raise_for_status()
                if len(resp.content) > 100:
                    cover_path.write_bytes(resp.content)
                    meta["cover_cached"] = True
                    log.info("Saved cover art to %s", cover_path)
            else:
                meta["cover_cached"] = True
        except Exception as e:
            log.warning("Failed to cache cover: %s", e)

    meta_path = output_dir / "metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    log.info("Saved metadata to %s", meta_path)


def poll_episodi(session=None, progress_callback=None):
    """Poll the episodi feed and download new episodes.

    Args:
        session: Optional requests.Session. Created if not provided.
        progress_callback: Optional callable(message_dict) for real-time updates.

    Returns:
        dict with results: audiobook name, episodes downloaded, errors, etc.
    """
    if session is None:
        session = core.make_session()

    result = {
        "success": True,
        "audiobook": None,
        "episodes_downloaded": 0,
        "episodes_skipped": 0,
        "episodes_failed": 0,
        "is_new_audiobook": False,
        "error": None,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    def emit(msg):
        if progress_callback:
            progress_callback(msg)

    try:
        # 1. Fetch episodi feed
        emit({"type": "status", "message": "Fetching episodi feed..."})
        data = core.fetch_episodi(session)
        cards = core.extract_cards(data)

        if not cards:
            result["error"] = "No episodes found in feed"
            result["success"] = False
            log.warning("No episodes found in episodi feed")
            return result

        # 2. Extract audiobook info
        audiobook_name = core.parse_audiobook_from_episodi(cards)
        if not audiobook_name:
            audiobook_name = data.get("block", {}).get("title", "Unknown")

        result["audiobook"] = audiobook_name
        log.info("Current audiobook: %s", audiobook_name)
        emit({"type": "status", "message": f"Current audiobook: {audiobook_name}"})

        # Filter out episodes from other audiobooks (the feed may mix old + new)
        cards = core.filter_cards_by_audiobook(cards, audiobook_name)
        if not cards:
            result["error"] = f"No episodes found for '{audiobook_name}' after filtering"
            result["success"] = False
            return result

        # Parse author/reader from description
        desc = cards[0].get("description", "")
        reader, _book, author = core.parse_description(desc)

        # 3. Load state and detect audiobook change
        state = _load_state()
        prev_audiobook = state.get("current_audiobook")
        prev_author = state.get("current_author")

        if prev_audiobook and prev_audiobook != audiobook_name:
            result["is_new_audiobook"] = True
            log.info("Audiobook changed: %s -> %s", prev_audiobook, audiobook_name)

            # Mark previous audiobook as completed
            prev_dir = _audiobook_dir(prev_author, prev_audiobook)
            prev_meta_path = prev_dir / "metadata.json"
            if prev_meta_path.exists():
                try:
                    prev_meta = json.loads(prev_meta_path.read_text())
                    prev_meta["completed"] = True
                    prev_meta["last_updated"] = datetime.now(UTC).isoformat()
                    prev_meta_path.write_text(json.dumps(prev_meta, indent=2, ensure_ascii=False))
                    log.info("Marked %s as completed", prev_audiobook)
                except Exception as e:
                    log.warning("Failed to mark %s as completed: %s", prev_audiobook, e)

        state["current_audiobook"] = audiobook_name
        state["current_author"] = author

        # 4. Find book-specific cover from catalog
        catalog_card = core.find_catalog_card(audiobook_name, session)
        cover_url = ""
        book_description = ""
        if catalog_card:
            images = catalog_card.get("images", {})
            cover_url = images.get("square") or images.get("cover") or catalog_card.get("image", "")
            book_description = catalog_card.get("description", "")
        if not book_description:
            book_description = desc

        # 5. Download episodes (Author/Title structure for Audiobookshelf)
        output_dir = _audiobook_dir(author, audiobook_name)
        output_dir.mkdir(parents=True, exist_ok=True)
        total = len(cards)

        # Sort by episode number
        sorted_cards = sorted(
            cards,
            key=lambda c: int(c.get("episode", 0) or 0),
        )

        episode_meta_list = []
        seen_paths = state.get("episodes_seen", {}).get(audiobook_name, [])

        for idx, card in enumerate(sorted_cards):
            ep_num = card.get("episode", idx + 1)
            ep_title = card.get("episode_title", card.get("toptitle", card.get("title", "")))
            path_id = card.get("path_id", "")
            filename = core.build_episode_filename(card, idx)
            filepath = output_dir / filename

            episode_meta_list.append(
                {
                    "episode": ep_num,
                    "title": ep_title,
                    "path_id": path_id,
                    "filename": filename,
                }
            )

            # Track seen episodes
            if path_id and path_id not in seen_paths:
                seen_paths.append(path_id)

            # Skip if already downloaded
            if filepath.exists() and filepath.stat().st_size > 0:
                result["episodes_skipped"] += 1
                emit(
                    {
                        "type": "episode_skip",
                        "episode": ep_num,
                        "total": total,
                        "title": ep_title,
                    }
                )
                log.debug("Skipping %s (already exists)", filename)
                continue

            # Download
            audio_url = core.get_audio_url(card)
            if not audio_url:
                result["episodes_failed"] += 1
                log.warning("No audio URL for episode %s", ep_num)
                continue

            try:
                emit(
                    {
                        "type": "episode_start",
                        "episode": ep_num,
                        "total": total,
                        "title": ep_title,
                    }
                )

                direct_url = core.resolve_relinker(audio_url, session)

                last_emit_time = [0.0]

                def progress_cb(bytes_dl, total_bytes, _ep=ep_num, _total=total):
                    now = time.monotonic()
                    if now - last_emit_time[0] >= 0.5 or bytes_dl >= total_bytes:
                        last_emit_time[0] = now
                        emit(
                            {
                                "type": "progress",
                                "episode": _ep,
                                "total": _total,
                                "bytes": bytes_dl,
                                "total_bytes": total_bytes,
                            }
                        )

                core.download_file(direct_url, filepath, session, progress_cb)

                # Tag MP3
                audiobook_data = {
                    "title": audiobook_name,
                    "podcast_info": {
                        "author": author or "",
                        "genres": catalog_card.get("genres", []) if catalog_card else [],
                        "images": catalog_card.get("images", {}) if catalog_card else {},
                        "image": cover_url,
                    },
                }
                try:
                    tagger.tag_episode(filepath, card, audiobook_data, idx, total, session)
                except Exception as e:
                    log.warning("Tagging failed for %s: %s", filename, e)

                result["episodes_downloaded"] += 1
                emit(
                    {
                        "type": "episode_done",
                        "episode": ep_num,
                        "total": total,
                        "status": "downloaded",
                    }
                )
                log.info("Downloaded %s", filename)

            except Exception as e:
                result["episodes_failed"] += 1
                tmp = filepath.with_suffix(".tmp")
                if tmp.exists():
                    tmp.unlink()
                emit(
                    {
                        "type": "episode_done",
                        "episode": ep_num,
                        "total": total,
                        "status": f"error: {e}",
                    }
                )
                log.error("Failed to download %s: %s", filename, e)

        # 6. Save metadata and state
        if audiobook_name not in state.get("episodes_seen", {}):
            state["episodes_seen"] = state.get("episodes_seen", {})
        state["episodes_seen"][audiobook_name] = seen_paths
        state["last_poll"] = datetime.now(UTC).isoformat()
        _save_state(state)

        _save_metadata(
            output_dir=output_dir,
            title=audiobook_name,
            author=author,
            reader=reader,
            description=book_description,
            cover_url=cover_url,
            episodes=episode_meta_list,
            completed=False,
            session=session,
        )

        log.info(
            "Poll complete: %d downloaded, %d skipped, %d failed",
            result["episodes_downloaded"],
            result["episodes_skipped"],
            result["episodes_failed"],
        )

    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        log.error("Poll failed: %s", e, exc_info=True)

    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    result = poll_episodi()
    if result["success"]:
        log.info(
            "Done: %s — %d downloaded, %d skipped, %d failed",
            result["audiobook"],
            result["episodes_downloaded"],
            result["episodes_skipped"],
            result["episodes_failed"],
        )
    else:
        log.error("Poll failed: %s", result["error"])
        sys.exit(1)
