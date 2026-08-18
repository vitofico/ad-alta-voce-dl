# Ad Alta Voce DL

Download audiobooks from [RAI Radio 3 — Ad Alta Voce](https://www.raiplaysound.it/programmi/adaltavoce).

Runs behind a VPN (via [gluetun](https://github.com/qdm12/gluetun)) because RAI serves this content to Italian IP addresses only. Includes a web UI for browsing the catalog and monitoring downloads, plus a background poller that automatically grabs new episodes as they air.

## Disclaimer

This is an independent personal project. It is **not affiliated with, endorsed by, or connected to RAI**.

Ad Alta Voce is public-service radio programming, broadcast free to air and streamed without DRM. This tool is intended for one thing: letting an individual keep a personal offline copy of programmes they can already listen to for free, in a form their own audiobook player can read. It is not a redistribution tool.

The recordings remain the copyright of RAI and the rights holders of the works being read. **Do not redistribute, republish, or share the downloaded audio.** RAI restricts this content to Italian IP addresses, and routing around that restriction may conflict with RAI's terms of service; if you are outside Italy, consider whether you are entitled to access it before you do. You are responsible for your own use, and for keeping request volume reasonable. The software is provided without warranty, and the author accepts no liability for how it is used.

## Quick Start

```bash
cp .env.example .env
# Edit .env with your VPN credentials

docker compose up -d
```

The web UI is available at `http://localhost:5000`.

> **Keep this on your own machine or LAN.** The web UI has no authentication of any kind: anyone who can reach port 5000 can browse your library and trigger downloads. It also runs on Flask's built-in development server, which is not built for public exposure. Do not port-forward it or bind it to a public interface; if you need that, put it behind a reverse proxy with authentication and run it under a production WSGI server such as gunicorn or waitress.

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

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

This project uses [mutagen](https://github.com/quodlibet/mutagen) for ID3 tagging, which is GPL-2.0-or-later; that is why the project as a whole is GPL rather than permissively licensed. See [NOTICE](NOTICE) for the full dependency breakdown.
