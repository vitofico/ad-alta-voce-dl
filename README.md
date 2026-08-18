<p align="center">
  <img src="rai/web/static/favicon.svg" alt="Ad Alta Voce DL" width="96" height="96">
</p>

<h1 align="center">Ad Alta Voce DL</h1>

<p align="center">
  <em>RAI Radio 3 reads you a book every weekday.<br>
  This keeps it, tagged and shelved, for your own player.</em>
</p>

<p align="center">
  <a href="https://github.com/vitofico/ad-alta-voce-dl/actions/workflows/lint.yml"><img src="https://github.com/vitofico/ad-alta-voce-dl/actions/workflows/lint.yml/badge.svg" alt="Lint"></a>
  <a href="https://github.com/vitofico/ad-alta-voce-dl/actions/workflows/docker.yml"><img src="https://github.com/vitofico/ad-alta-voce-dl/actions/workflows/docker.yml/badge.svg" alt="Docker"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPLv3-blue.svg" alt="License: GPL v3"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+">
</p>

## What it is

[Ad Alta Voce](https://www.raiplaysound.it/programmi/adaltavoce) is RAI Radio 3's serialized audiobook programme: a novel read aloud across dozens of episodes, one per weekday, free to stream. The catch is that it lives in RAI's own player, arrives an episode at a time, and carries no metadata your audiobook app understands.

This turns it into a proper library. It downloads episodes, tags them with title, author, reader, track number and cover art, and lays them out in the `Author/Title/001 - Episode.mp3` structure [Audiobookshelf](https://www.audiobookshelf.org/) and friends expect. A poller watches the currently airing book and picks up new episodes as they broadcast, so a serialization in progress fills itself in.

Three ways to drive it:

- **Web UI** for browsing the catalog and watching downloads progress live.
- **Background poller** that grabs new episodes on a schedule.
- **CLI** (`rai-dl`) for one-off downloads.

```
    [RAI Play Sound]
           │  geo-restricted to Italian IPs
           ▼
      [gluetun VPN]
           │
           ▼
   [ad-alta-voce-dl] ──> web UI  :5000
           │         ──> REST API /api/v1/
           │         ──> poller (scheduled)
           ▼
  Author/Title/001 - Episode.mp3   + cover.jpg + ID3v2.4 tags
           │
           ▼
    [Audiobookshelf]
```

## Contents

- [Disclaimer](#disclaimer)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Web UI](#web-ui)
- [REST API](#rest-api)
- [CLI](#cli)
- [How it works](#how-it-works)
- [Development](#development)
- [License](#license)

## Disclaimer

This is an independent personal project. It is **not affiliated with, endorsed by, or connected to RAI**.

Ad Alta Voce is public-service radio, broadcast free to air and streamed without DRM. This tool exists for one purpose: letting an individual keep a personal offline copy of programmes they can already listen to for free, in a form their own player can read. It is not a redistribution tool.

The recordings remain the copyright of RAI and of the rights holders of the works being read. **Do not redistribute, republish, or share the downloaded audio.** RAI restricts this content to Italian IP addresses, and routing around that restriction may conflict with RAI's terms of service; if you are outside Italy, consider whether you are entitled to access it before you do. You are responsible for your own use and for keeping request volume reasonable. The software is provided without warranty, and the author accepts no liability for how it is used.

## Quick start

```bash
git clone https://github.com/vitofico/ad-alta-voce-dl.git
cd ad-alta-voce-dl

cp .env.example .env
$EDITOR .env          # add your VPN credentials

docker compose up -d
```

Open http://localhost:5000.

### Without a VPN

You do not need VPN credentials to see the UI. This starts the app on its own, no gluetun, no `.env`:

```bash
docker compose up -d dl-local
```

Open http://127.0.0.1:5000. Naming the service activates its compose profile, so the VPN sidecar stays out of it, and the port is bound to loopback rather than the LAN. Downloads will fail unless you are in Italy, which is expected: this path is for working on the app, not for filling a library. Use `docker compose up -d` for that.

> [!WARNING]
> **Keep this on your own machine or LAN.** The web UI has **no authentication of any kind**: anyone who can reach port 5000 can browse your library and trigger downloads. It also runs on Flask's development server, which is not built for public exposure. Do not port-forward it. If you need remote access, put it behind a reverse proxy that handles auth, and run it under a production WSGI server such as gunicorn or waitress.

## Configuration

RAI serves this content to Italian IP addresses only, so the container routes its traffic through [gluetun](https://github.com/qdm12/gluetun). Set your provider's credentials in `.env`:

| Provider | Where to get credentials |
|----------|--------------------------|
| ProtonVPN (OpenVPN) | [account.protonvpn.com](https://account.protonvpn.com/account#openvpn) |
| NordVPN (OpenVPN) | [Manual configuration](https://my.nordaccount.com/dashboard/nordvpn/manual-configuration/) |
| Custom WireGuard | See the commented block in `.env.example` |

Use the **service credentials** your provider issues for manual configuration, not your account login.

| Variable | Default | Description |
|----------|---------|-------------|
| `VPN_SERVICE_PROVIDER` | `protonvpn` | gluetun provider name |
| `VPN_TYPE` | `openvpn` | `openvpn` or `wireguard` |
| `OPENVPN_USER` / `OPENVPN_PASSWORD` | | Provider service credentials |
| `SERVER_COUNTRIES` | `Italy` | Must stay Italy for RAI to serve content |
| `AUDIOBOOKS_DIR` | `./downloads` | Host directory mounted as the library. Point it at your Audiobookshelf library and finished books land there directly |
| `WEB_BIND_ADDR` | `0.0.0.0` | Host address the UI is published on. Set to `127.0.0.1` to keep it off the LAN |
| `PROXY_BIND_ADDR` | `127.0.0.1` | Host address gluetun's HTTP proxy is published on. Loopback by default: an open proxy lets anyone route traffic through your VPN account |
| `PUID` / `PGID` | `1000` | UID and GID the container runs as. It must be able to write `AUDIOBOOKS_DIR` |
| `DOWNLOADS_DIR` | `/audiobooks` | Where the app writes, inside the container |
| `POLLER_STATE_DIR` | `/state` | Where poller progress is persisted, inside the container |
| `HTTP_PROXY` / `HTTPS_PROXY` | | Proxy for RAI requests. Only applies when running outside Docker |

The container runs as an unprivileged user. If downloads fail with permission errors, `AUDIOBOOKS_DIR` is owned by a different account: either `chown` it, or set `PUID`/`PGID` to match (`id -u`, `id -g`).

### Scheduling the poller

The poller runs one cycle and exits, so the schedule lives outside the app. Trigger it from **Controlla ora** in the UI, from the API, or from cron:

```bash
# every day at 07:00
0 7 * * *  curl -fsS -X POST http://127.0.0.1:5000/api/v1/system/poll
```

A one-off cycle inside the running container works too:

```bash
docker compose exec dl python -m rai.poller
```

## Web UI

Served on port 5000, in Italian, matching the source programme:

- **Ora in onda** shows the audiobook currently being broadcast, with a one-click download of everything aired so far.
- **Catalogo** browses the full back catalogue as a searchable grid of cover art.
- **Scaricati** lists what you already have, reading straight from disk.

Downloads stream their progress over Server-Sent Events, so the progress bar and the per-episode state update live without reloading the page. Each episode shows one of four states at a glance: *In attesa* (queued), *In corso* (downloading), *Scaricata* (done), or *Errore* (failed).

The interface follows your system light or dark theme automatically, works down to narrow phone screens, and respects `prefers-reduced-motion`. Colours meet the WCAG AA contrast ratio in both themes, and covers that are missing or slow to load fall back to a lettered tile rather than a broken image.

## REST API

A documented REST API ships alongside the UI. Interactive Swagger docs are served at **http://localhost:5000/api/v1/**.

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/catalog/` | List the full catalogue |
| `GET /api/v1/catalog/<slug>` | Detail for one audiobook |
| `GET /api/v1/current/` | The currently airing audiobook |
| `GET /api/v1/downloaded/` | What is already on disk |
| `GET /api/v1/download/status` | Progress of the active download |
| `POST /api/v1/download/<slug>` | Download a catalogue audiobook |
| `POST /api/v1/download/current` | Download the currently airing one |
| `POST /api/v1/system/poll` | Trigger a poll immediately |
| `GET /api/v1/system/health` | Health check, used by Docker |

## CLI

```bash
uv run rai-dl https://www.raiplaysound.it/audiolibri/agostino
```

| Option | Default | Description |
|--------|---------|-------------|
| `-o, --output` | `/downloads` | Output directory |
| `-w, --workers` | `3` | Parallel episode downloads |
| `--proxy` | | HTTP proxy URL, unnecessary inside Docker |
| `--dump-json` | | Dump the raw feed JSON and exit, for debugging |

The CLI checks its own egress geolocation before starting and warns if it is not routing through an Italian IP, which is the usual cause of empty results.

## How it works

1. **Metadata.** RAI Play Sound renders a JSON view of any page by appending `.json` to the URL. That is the whole discovery mechanism: no scraping of markup, no reverse-engineered private API. Responses are cached in memory for 10 minutes.
2. **Audio resolution.** Each episode exposes a downloadable MP3. Where a page hands back a `relinker` URL instead, the tool follows the redirect to the real CDN file.
3. **Naming.** The reader, book title, and author are parsed out of the episode description, then sanitized into `Author/Title/NNN - Episode.mp3`.
4. **Tagging.** Episodes get ID3v2.4 tags (title, artist, album, track number, full release date) plus embedded cover art, so audiobook players group them correctly.
5. **Polling.** The poller records which episodes it has already fetched, detects when the programme moves on to a new book, and marks the previous one complete.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow.

```bash
uv sync
uv run python -m rai.web.app     # web UI on :5000
uv run python -m rai.poller      # one poll cycle

uvx ruff check .                 # lint
uvx ruff format .                # format
```

Or use the Makefile. Run `make` on its own to list every target.

| Target | What it does |
|--------|--------------|
| `make run` | Web UI on port 5000, writing to `./downloads` |
| `make poll` | One poll cycle |
| `make lint` | `uvx ruff check .` |
| `make format` | `uvx ruff format .` |
| `make up` | Start the stack behind the VPN |
| `make up-local` | Start the stack without the VPN, UI only |
| `make logs` | Follow container logs |
| `make down` | Stop and remove both stacks |
| `make docker-build` | Build the image from this working tree |

`docker compose up -d dl-local` builds and runs your working tree directly, so there is nothing to uncomment for local work.

```
rai/
  cli.py       Command-line downloader
  core.py      RAI Play Sound client, parsing, naming
  poller.py    Scheduled episode polling and state tracking
  tagger.py    ID3v2.4 tagging and cover art embedding
  web/
    app.py     Flask UI, SSE progress streaming
    api.py     REST API (flask-restx, Swagger at /api/v1/)
```

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

This project uses [mutagen](https://github.com/quodlibet/mutagen) for ID3 tagging, which is GPL-2.0-or-later, and that is why the project as a whole is copyleft rather than permissive. See [NOTICE](NOTICE) for the full dependency breakdown.
