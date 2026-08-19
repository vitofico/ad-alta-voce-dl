# Contributing

Thanks for taking an interest. This is a small personal project, so please read this before opening a PR.

## Ground rules

- **Scope is deliberately narrow.** This downloads RAI Ad Alta Voce for personal offline listening and lays it out for audiobook players. PRs that turn it into a general media grabber, add other broadcasters, or add sharing, seeding, or redistribution features will be closed.
- **Stay polite to the upstream.** RAI is a public broadcaster serving this for free. Anything that raises request volume, adds aggressive concurrency, or hammers the CDN will not be merged.
- **No credentials in the repo, ever.** VPN details live in `.env`, which is gitignored. Never commit a real `.env`, and never add a credential to `.env.example` beyond an empty placeholder.
- **No downloaded audio in the repo.** `downloads/` is gitignored for a reason. Do not add media files, cover art, or test fixtures containing RAI audio.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/vitofico/ad-alta-voce-dl.git
cd ad-alta-voce-dl
uv sync

cp .env.example .env
$EDITOR .env      # your own VPN service credentials
```

Run the pieces directly:

```bash
uv run python -m rai.web.app     # web UI on :5000
uv run python -m rai.poller      # a single poll cycle
uv run rai-dl <url>              # one-off download
```

You need an Italian IP for anything to return content. Without the VPN the catalog comes back empty, which is the single most common cause of "it does not work".

## The checks

CI runs these on every push and PR:

```bash
uvx ruff check .
uvx ruff format --check .
uv run python -m compileall -q rai/
```

`uvx ruff format .` fixes formatting in place.

The `compileall` step is not busywork. It catches syntax that only parses on newer interpreters, which is exactly how three `except A, B:` clauses once made the whole package unimportable on Python 3.13 and below.

## Python version

The floor is **3.11**, set in `pyproject.toml` and mirrored by `[tool.ruff] target-version`. Keep those two in sync. If you raise the floor, raise both, and say why in the PR.

Be careful with ruff's `target-version`: it decides which modern syntax ruff considers canonical, so setting it too high will make the formatter rewrite code into a form older interpreters cannot parse.

## Tests

There is no test suite yet. This is the most useful contribution available if you want one: the pure functions in `rai/core.py` (`parse_description`, `sanitize_filename`, `extract_cards`, `filter_cards_by_audiobook`) are self-contained and easy to cover without touching the network.

If you add tests, use pytest, put them in `tests/`, and add the job to `.github/workflows/lint.yml`. Never hit the live RAI API from a test; use recorded JSON fixtures.

## Pull requests

- Branch from `main`, one topic per PR.
- Keep diffs reviewable. Under ~400 lines is ideal.
- Update the README and `CHANGELOG.md` in the same PR as the code.
- If you change a route or an API response shape, update the REST API table in the README.
- If you change the on-disk layout or tagging, say so loudly. People point Audiobookshelf at these directories and a rename can orphan an existing library.

## Commit messages

Gitmoji + conventional commits. The emoji goes after the type, before the colon-space:

```
:sparkles: feat(web): add per-episode retry button
:bug: fix(poller): stop mixing episodes across audiobook transitions
:memo: docs: document the REST API endpoints
:whale: chore(docker): add a healthcheck to the poller service
:wrench: chore: bump ruff to 0.9
```

Common gitmoji here: `:sparkles:` (feat), `:bug:` (fix), `:memo:` (docs),
`:white_check_mark:` (tests), `:construction_worker:` (CI), `:wrench:` (chore),
`:art:` (refactor/style), `:fire:` (removals), `:lock:` (security),
`:page_facing_up:` (legal/license), `:whale:` (Docker).

Types in use: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`, `build`, `style`.

## Reporting bugs

Open an issue with what you ran, the relevant log output, and confirmation that your egress IP is Italian (the CLI prints this at startup). Include the audiobook URL if it is specific to one title.

For security issues, see [SECURITY.md](SECURITY.md); please do not open a public issue.
