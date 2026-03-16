# Ad Alta Voce DL

Download audiobooks from [RAI Radio 3 — Ad Alta Voce](https://www.raiplaysound.it/programmi/adaltavoce).

Runs behind a VPN (via [gluetun](https://github.com/qdm12/gluetun)) to satisfy Italian geo-restrictions. Includes a web UI for browsing the catalog and monitoring downloads, plus a background poller that automatically grabs new episodes as they air.

## Quick Start

```bash
cp .env.example .env
# Edit .env with your VPN credentials

docker compose up -d
```

The web UI is available at `http://localhost:5000`.

## Features

- **Web UI** — browse the full Ad Alta Voce catalog, see what's currently airing, download with progress tracking
- **Automatic poller** — checks for new episodes on a configurable schedule (`POLL_INTERVAL` in `.env`)
- **CLI** — `rai-dl <url>` for one-off downloads
- **ID3 tagging** — episodes are tagged with title, author, album, track number, and cover art
- **Docker** — single `docker compose up` with VPN included

## Configuration

Copy `.env.example` to `.env` and fill in your VPN credentials. Supported providers:

| Provider | Docs |
|----------|------|
| ProtonVPN (OpenVPN) | [Get credentials](https://account.protonvpn.com/account#openvpn) |
| NordVPN (OpenVPN) | [Get credentials](https://my.nordaccount.com/dashboard/nordvpn/manual-configuration/) |
| Custom WireGuard | See `.env.example` for details |

## CLI Usage

```bash
# Inside the container
uv run rai-dl https://www.raiplaysound.it/audiolibri/agostino

# With options
uv run rai-dl --workers 5 --output ./my-books <url>
```

## Local Development

```bash
uv sync
uv run python -m rai.web.app
```

Or build the Docker image locally:

```bash
docker compose build   # uncomment 'build: .' in docker-compose.yml
docker compose up -d
```
