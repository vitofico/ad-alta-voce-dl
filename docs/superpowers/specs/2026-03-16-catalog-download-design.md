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

1. Call `core.fetch_audiobook(f"/audiolibri/{slug}.json", session)` to get audiobook metadata from RAI.
2. Extract episodes via `core.extract_cards(data)`.
3. Parse author from first episode's description via `core.parse_description()`.
4. Look up cover image from catalog card via `core.find_catalog_card()`.
5. Build output directory path as `DOWNLOADS_DIR / Author / Title` to check per-episode download status.
6. Render `audiobook.html` with: title, author, description, cover URL, slug, episodes list, download counts, and whether a download is active.

Returns 404 if the RAI API returns no data or no episodes.

#### `GET /api/download/<slug>` — SSE download endpoint

1. Check `_is_any_download_active()`. Return 409 if any download is running.
2. Fetch audiobook JSON and extract episodes (same as detail page).
3. Parse author, build `Author/Title/` output directory. Create it if needed.
4. Spawn a daemon thread that loops through episodes sequentially:
   - For each episode, call `cli.process_episode(idx, card, session, output_dir, total, data, progress_callback=cb)`.
   - The callback emits SSE events: `episode_start`, `progress`, `episode_done`.
5. After all episodes, save `metadata.json` and cache cover art.
6. Store the thread in `_active_downloads[slug]`.
7. Stream SSE events from a Queue, ending with `event: complete`.

SSE event format matches the existing `/api/download/current` endpoint exactly, so `audiobook.html`'s JavaScript works without changes.

### Changes to `cli.py`

Add an optional `progress_callback` parameter to `process_episode()`:

```python
def process_episode(idx, card, session, output_dir, total, audiobook_meta=None, progress_callback=None):
```

- When `progress_callback` is provided, call it instead of `print()`.
- When `None`, keep existing `print()` behavior (CLI unchanged).
- The callback receives dicts like `{"type": "episode_start", "episode": 1, "total": 10, "title": "..."}`.

### Changes to `home.html`

Wrap each catalog card `<div>` in an `<a href="/audiobook/{{ book._slug }}">` tag, matching the pattern already used in `catalog.html`.

### Active Download Tracking

Add `_is_any_download_active()` helper:

```python
def _is_any_download_active():
    return any(t.is_alive() for t in _active_downloads.values())
```

All three download endpoints (`/api/download/current`, `/api/download/<slug>`, `/api/poll`) check this before starting. This enforces the one-download-at-a-time constraint globally.

The detail page checks `_active_downloads.get(slug)` to set the button's initial disabled state.

### Directory Structure

Downloads use `Author/Title/` layout:
- Author extracted from episode description via `core.parse_description()`.
- Falls back to the audiobook's `podcast_info` author field if available.
- Author is required (from user decision) — no fallback to flat structure.

### Error Handling

| Scenario | Response |
|----------|----------|
| Invalid slug (RAI returns error) | 404 page |
| Download already in progress | 409 (existing pattern) |
| Individual episode fails | SSE error event, continues to next episode |
| No audio URL for episode | Skipped, reported in SSE |

### Files NOT Changed

- `core.py` — already has all needed functions
- `poller.py` — handles only currently-airing book
- `audiobook.html` — template and JS already built for this flow
- `tagger.py` — called by `process_episode` as before
- `catalog.html` — standalone catalog page, not used by home page

### Metadata & Tagging

After download completes, save `metadata.json` to the audiobook directory with: title, author, reader, description, cover URL, episode list, source ("catalog"). Cache `cover.jpg` from the cover URL. This reuses the same schema as the poller's `_save_metadata()`.

The full audiobook JSON response is passed as `audiobook_meta` to `process_episode()` so `tagger.tag_episode()` produces correct ID3 tags (title, artist, album, track number, cover art).
