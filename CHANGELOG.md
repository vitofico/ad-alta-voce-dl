# Changelog

## [Unreleased]

### Fixed
- Episodi feed mixing episodes from previous audiobook into the current one during transitions

### Changed
- ID3 date tag (`TDRC`) now stores full date (YYYY-MM-DD) instead of year-only
- Downloads now use `Author/Title/` directory structure (Audiobookshelf-compatible)
- Replaced internal Python scheduler with external scheduling (K8s CronJob)
- Downloads directory defaults to `/audiobooks` (was `/downloads`)
- Poller state stored in separate `/state` directory
- `make_session()` reads `HTTP_PROXY`/`HTTPS_PROXY` from environment

### Added
- Custom SVG favicon for the web UI (open book with sound waves)
- `python -m rai.poller` CLI entrypoint for CronJob / cron usage
- Configurable `DOWNLOADS_DIR` and `POLLER_STATE_DIR` env vars
- Kubernetes manifests for theficos-cluster (gluetun VPN gateway, web deployment, CronJob poller)

### Removed
- `rai/scheduler.py` — scheduling now handled by K8s CronJob
- `schedule` Python dependency

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
