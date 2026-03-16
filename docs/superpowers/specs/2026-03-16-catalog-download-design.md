# Catalog Audiobook Download Feature

**Date:** 2026-03-16
**Status:** Approved

## Problem

The web UI displays a catalog of ~196 RAI Ad Alta Voce audiobooks, but the cards are not clickable. Users can only download the currently-airing audiobook. The templates for a detail page (`audiobook.html`) and a clickable catalog grid (`catalog.html`) already exist but are not wired to any routes.

## Solution

Add two new Flask routes and make minimal changes to existing code so users can browse the catalog, view any audiobook's episodes, and download them.

## Design

### New Routes in `app.py`

#### `GET /audiobook/<slug>` — Detail page

1. Call `core.fetch_audiobook(f"/audiolibri/{slug}", session)` to get audiobook metadata from RAI. Note: `fetch_json()` appends `.json` automatically.
2. Extract episodes via `core.extract_cards(data)`.
3. Parse author from first episode's description via `core.parse_description()`. Fall back to `data["podcast_info"]["author"]` if available.
4. Look up cover image from catalog card via `core.find_catalog_card()`.
5. Build output directory path as `DOWNLOADS_DIR / Author / Title` to check per-episode download status.
6. Populate `_duration` on each episode from `literal_duration` or `duration_small_format` fields (same as home page does for current episodes). If neither field exists, set to empty string.
7. Render `audiobook.html` with: title, author, description, cover URL, slug, episodes list, download counts, and whether a download is active.
8. **Button state**: disable if `_is_any_download_active()` returns True (not just this slug's download — any global download blocks the button).

Returns 404 if the RAI API returns no data or no episodes.

#### `GET /api/download/<slug>` — SSE download endpoint

1. Check `_is_any_download_active()`. Return 409 if any download is running.
2. Fetch audiobook JSON and extract episodes (same as detail page).
3. Parse author, build `Author/Title/` output directory. Create it if needed.
4. Spawn a daemon thread that loops through episodes sequentially, following the poller's download loop pattern (not `cli.process_episode`):
   - Emit `episode_start` SSE event.
   - Call `core.get_audio_url()`, `core.resolve_relinker()`, `core.download_file()` with a byte-level `progress_callback` that emits throttled `progress` SSE events (same 0.5s throttle as poller).
   - Call `tagger.tag_episode()` on successful downloads.
   - Emit `episode_done` SSE event with status.
   - On failure: clean up `.tmp` file, emit `episode_done` with error status, continue to next episode.
5. After all episodes, save metadata and cover using `poller._save_metadata()` (or equivalent inline logic).
6. Store the thread in `_active_downloads[slug]`.
7. Stream SSE events from a Queue, ending with `event: complete`.

SSE event format matches the existing `/api/download/current` endpoint exactly, so `audiobook.html`'s JavaScript works without changes.

### Changes to `home.html`

Wrap each catalog card `<div>` in an `<a href="/audiobook/{{ book._slug }}">` tag, matching the pattern already used in `catalog.html`.

### Changes to Existing Download Endpoints

Update `/api/download/current` and `/api/poll` to use `_is_any_download_active()` instead of only checking `_active_downloads["current"]`. This ensures the one-download-at-a-time constraint is enforced globally across all endpoints.

### No Changes to `cli.py`

The download loop in the new route follows the poller's pattern directly (resolve relinker, download file, tag, emit SSE), which avoids modifying `cli.process_episode`. The CLI continues to work independently.

### Active Download Tracking

Add `_is_any_download_active()` helper:

```python
def _is_any_download_active():
    return any(t.is_alive() for t in _active_downloads.values())
```

Used by all download endpoints and the detail page's button state.

### Directory Structure

Downloads use `Author/Title/` layout:
- Author extracted from episode description via `core.parse_description()`.
- Falls back to `podcast_info.author` from the audiobook JSON.
- If author is still unknown, falls back to `"Ad Alta Voce"` (same as poller).

### Error Handling

| Scenario | Response |
|----------|----------|
| Invalid slug (RAI returns error) | 404 page |
| Download already in progress (any) | 409 (existing pattern) |
| Individual episode fails | SSE error event, continues to next episode |
| No audio URL for episode | Skipped, reported in SSE |

### Files NOT Changed

- `core.py` — already has all needed functions
- `cli.py` — download loop is replicated from poller pattern, CLI untouched
- `poller.py` — handles only currently-airing book
- `audiobook.html` — template and JS already built for this flow
- `tagger.py` — called within the download loop as before
- `catalog.html` — standalone catalog page, not used by home page

### Metadata & Tagging

After download completes, save `metadata.json` to the audiobook directory with: title, author, reader, description, cover URL, episode list, source ("catalog"). Cache `cover.jpg` from the cover URL. This reuses the same schema as the poller's `_save_metadata()`.

A synthetic `audiobook_data` dict is constructed (matching the structure `tagger.tag_episode()` expects) with title, podcast_info (author, genres, images), so ID3 tags are correct.
