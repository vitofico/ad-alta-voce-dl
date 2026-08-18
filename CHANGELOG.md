# Changelog

## [2026.08.18]

### Added
- GPL-3.0-or-later license and third-party dependency NOTICE
- Custom SVG favicon for the web UI (open book with sound waves)
- `python -m rai.poller` CLI entrypoint for cron / scheduled usage
- Configurable `DOWNLOADS_DIR` and `POLLER_STATE_DIR` env vars

### Changed
- Minimum supported Python lowered from 3.14 to 3.11
- ID3 date tag (`TDRC`) now stores full date (YYYY-MM-DD) instead of year-only
- Downloads now use `Author/Title/` directory structure (Audiobookshelf-compatible)
- Replaced the internal Python scheduler with external scheduling
- Downloads directory defaults to `/audiobooks` (was `/downloads`)
- Poller state stored in separate `/state` directory
- `make_session()` reads `HTTP_PROXY`/`HTTPS_PROXY` from environment

### Fixed
- Episodi feed mixing episodes from previous audiobook into the current one during transitions
- Multi-exception `except` clauses now use parenthesized syntax, so the package
  imports on Python 3.11 through 3.13 instead of raising `SyntaxError`
- Containment check on the downloaded-audiobook detail route, matching the
  existing guard on the file-serving route

### Removed
- `rai/scheduler.py` — scheduling now handled externally
- `schedule` Python dependency
- Unused `main.py` project stub

## [2026.03.16]

### Added
- CLI downloader for RAI Ad Alta Voce audiobooks with parallel downloads
- Flask web UI with catalog browsing, download progress via SSE, and downloaded library
- Periodic poller for currently-airing episodes with configurable interval
- ID3v2.4 metadata tagging with cover art
- Docker Compose setup with gluetun VPN for Italian geo-restriction
- GitHub Actions workflow to build and push Docker image to GHCR
- `/health` endpoint for Docker health checks
- Support for ProtonVPN, NordVPN, and custom WireGuard configurations
