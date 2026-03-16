# Changelog

## [Unreleased]

### Changed
- Dockerfile: use `ghcr.io/astral-sh/uv:python3.14-trixie-slim` as base image
- docker-compose.yml: pull from GHCR instead of local build
- Upgraded to Python 3.14
- Switched to CalVer versioning (YYYY.MM.DD)

### Added
- GitHub Actions workflow to build and push Docker image to GHCR
- `/health` endpoint for Docker health checks
- `.dockerignore` for smaller build context
- `README.md` with setup and usage instructions
- Ruff linter configuration in `pyproject.toml`

## [2026.03.16]

### Added
- CLI downloader for RAI Ad Alta Voce audiobooks with parallel downloads
- Flask web UI with catalog browsing, download progress via SSE, and downloaded library
- Periodic poller for currently-airing episodes with configurable interval
- ID3v2.4 metadata tagging with cover art
- Docker Compose setup with gluetun VPN for Italian geo-restriction
- Support for ProtonVPN, NordVPN, and custom WireGuard configurations
