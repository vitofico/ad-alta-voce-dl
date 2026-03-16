# Episodi Poller & Web UI Rework

## Problem

RAI Ad Alta Voce streams one audiobook at a time via the "episodi" feed at `/programmi/adaltavoce.json`. Episodes air Mon-Fri and the feed shows only the current audiobook (~10 episodes). When a book finishes, it's replaced by the next one. The old `/audiolibri/<slug>.json` detail API returns 559 for all titles, breaking the existing web UI.

Additionally, the CDN now requires a `Referer` header for relinker URLs, and new episodes use `downloadable_audio.url` for MP3 (while `audio.url` returns HLS streams).

## Solution

### 1. Bug Fixes (core.py)

- Add `Referer: https://www.raiplaysound.it/` to `make_session()`.
- In `get_audio_url()`, prefer `downloadable_audio.url` when present, fall back to `audio.url`.

### 2. Poller (rai/poller.py)

`poll_episodi(session)`:
1. Fetch `/programmi/adaltavoce.json` → `block.cards`
2. Extract audiobook name from `episode_title` (regex: `\d+\.\s*(.*)`)
3. Extract author/reader from `description` (regex: `(.+)\s+legge\s+(.+)\s+[Dd]i\s+(.+)`)
4. Match name against catalog for book-specific cover image
5. Download missing episodes to `/downloads/<BookName>/`, tag with ID3
6. Save `metadata.json` per audiobook and `state.json` in `/downloads/.poller/`

State file tracks current audiobook name, last poll time, and episode path_ids per audiobook. Completed flag set when audiobook rotates.

### 3. Scheduler (rai/scheduler.py)

- Background thread using `schedule` library
- Configurable via `POLL_INTERVAL` env var (e.g. `1h`, `6h`, `1d`, `7d`; default `1d`)
- Runs immediately on startup, then repeats at interval
- Exposes `get_scheduler_status()` for web UI

### 4. Web UI Rework

Three-section home page:
- **Ora in onda**: current audiobook from episodi feed, download button
- **Scaricati**: audiobooks on disk from `/downloads/`, reads metadata.json
- **Catalogo**: 196-title directory (title/cover/description only, no detail pages)

New routes:
- `GET /` — home with three sections
- `GET /downloaded/<name>` — episode list for downloaded audiobook
- `POST /api/poll` — manual poll trigger
- `GET /api/download/current` — SSE download of current airing audiobook
- `GET /api/scheduler` — scheduler status JSON

### 5. Metadata Persistence

Per audiobook: `metadata.json` + `cover.jpg` in `/downloads/<BookName>/`.
Global: `state.json` in `/downloads/.poller/`.

### 6. Dependencies

- Add `schedule` to pyproject.toml
- Add `POLL_INTERVAL` to .env.example
