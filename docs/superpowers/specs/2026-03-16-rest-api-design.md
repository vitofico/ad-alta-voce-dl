# REST API with OpenAPI Spec

**Date:** 2026-03-16
**Status:** Approved

## Problem

The web UI exposes HTML pages and SSE streams but no JSON API. Automation clients (scripts, cron jobs, Home Assistant) need a programmatic interface to browse the catalog, trigger downloads, and check status.

## Solution

Add a JSON REST API under `/api/v1/` using `flask-restx`, which auto-generates OpenAPI 2.0 specs and bundles Swagger UI. Downloads use a fire-and-forget pattern: POST returns 202 Accepted, clients poll a status endpoint.

## Endpoints

### Catalog

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/catalog` | List all ~196 audiobooks |
| `GET` | `/api/v1/catalog/{slug}` | Audiobook detail with episodes |

### Currently Airing

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/current` | Currently airing audiobook with episodes |

### Downloaded

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/downloaded` | List all downloaded audiobooks |

### Downloads

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/download/{slug}` | Trigger download of a catalog audiobook. Returns 202. |
| `POST` | `/api/v1/download/current` | Trigger download of the currently-airing audiobook. Returns 202. |
| `GET` | `/api/v1/download/status` | Current download status (active/idle, slug, progress) |

### System

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/poll` | Trigger a poll for new episodes. Returns 202. |
| `GET` | `/api/v1/health` | Health check. Returns `{"status": "ok"}`. |

## Design

### New File: `rai/web/api.py`

Contains all API routes using flask-restx namespaces. Imports shared state (`_active_downloads`, `_is_any_download_active`, `_session`, `DOWNLOADS_DIR`) and helper functions from `app.py`.

### Shared State Refactoring

Move shared state and helpers out of `app.py` into module-level variables that both `app.py` and `api.py` can access. Specifically:
- `_active_downloads`, `_is_any_download_active()`, `_session`, `DOWNLOADS_DIR` stay in `app.py` as they are (already module-level).
- `_fetch_current_audiobook()`, `_get_downloaded_audiobooks()`, `_load_audiobook_metadata()`, `_is_audiobook_downloaded()` stay in `app.py`.
- `api.py` imports these from `app.py` directly (they're module-level functions, not route handlers).

### Changes to `app.py`

In `create_app()`:
1. Import and initialize the flask-restx Api from `api.py`.
2. Register it on the Flask app.

### Download Status Tracking

Add a module-level dict `_download_status` in `app.py` to track the current download's progress:

```python
_download_status: dict = {
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
```

The existing download threads (SSE routes and the new API trigger) update this dict as they progress. The status endpoint reads it.

The existing SSE download functions (`do_download` in both `/api/download/current` and `/api/download/<slug>`) will be updated to also write to `_download_status` as a side effect, so the status endpoint works regardless of how the download was triggered.

### Fire-and-Forget Downloads

`POST /api/v1/download/{slug}` and `POST /api/v1/download/current`:
1. Check `_is_any_download_active()`. Return 409 if busy.
2. Start the download thread (reusing the same logic as the existing SSE routes, but without the SSE Queue — instead just update `_download_status`).
3. Return 202 with `{"message": "Download started", "slug": "..."}`.

To avoid duplicating the download logic, extract the download loop into a shared function `_run_catalog_download(slug, status_dict)` and `_run_current_download(status_dict)` that both SSE and API routes can call. The SSE routes pass a Queue for events; the API routes pass None and rely on `_download_status` for tracking.

### Swagger UI

flask-restx serves Swagger UI at the API root (`/api/v1/`). The OpenAPI spec is auto-generated at `/api/v1/swagger.json`.

### Response Models

Define flask-restx models for consistent JSON responses:

- `CatalogItem`: `{slug, title, subtitle, cover_url, downloaded}`
- `AudiobookDetail`: `{slug, title, author, reader, description, cover_url, total_episodes, downloaded_count, episodes: [Episode]}`
- `Episode`: `{number, title, duration, downloaded}`
- `DownloadedBook`: `{title, author, reader, episode_count, completed, cover_url}`
- `DownloadStatus`: `{active, slug, title, total_episodes, episodes_downloaded, episodes_skipped, episodes_failed, current_episode, current_episode_progress}`
- `DownloadTrigger`: `{message, slug}`
- `HealthResponse`: `{status}`
- `ErrorResponse`: `{message}`

### Dependencies

Add `flask-restx` to `pyproject.toml`. No other new dependencies.

### Files Changed

| File | Action | What |
|------|--------|------|
| `rai/web/api.py` | Create | All API routes, flask-restx namespaces and models |
| `rai/web/app.py` | Modify | Register API, add `_download_status` dict, extract shared download functions |
| `pyproject.toml` | Modify | Add `flask-restx` dependency |

### Files NOT Changed

- `core.py`, `cli.py`, `poller.py`, `tagger.py` — untouched
- Templates — untouched, web UI continues to work as before
