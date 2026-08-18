FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim

LABEL org.opencontainers.image.title="Ad Alta Voce DL" \
      org.opencontainers.image.description="Downloads RAI Radio 3 Ad Alta Voce audiobooks, tagged and laid out for Audiobookshelf." \
      org.opencontainers.image.url="https://github.com/vitofico/ad-alta-voce-dl" \
      org.opencontainers.image.source="https://github.com/vitofico/ad-alta-voce-dl" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.authors="Vito Fico"

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies only. This layer is rebuilt when pyproject.toml or uv.lock change,
# not when application code does.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project

# Application code. LICENSE and README are needed to build the project wheel,
# and shipping the licence inside a GPL image is the right thing anyway.
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY rai_download.py ./
COPY rai/ rai/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Run unprivileged. The venv is on PATH, so `python` and `rai-dl` resolve without
# `uv run` and without a network round trip at container start.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /audiobooks /state \
    && chown app:app /audiobooks /state
USER app

ENV DOWNLOADS_DIR=/audiobooks \
    POLLER_STATE_DIR=/state

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')"]

EXPOSE 5000

CMD ["python", "-m", "rai.web.app"]
