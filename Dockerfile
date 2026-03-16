FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim

WORKDIR /app

# Install dependencies (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY rai_download.py .
COPY rai/ rai/

ENV DOWNLOADS_DIR=/audiobooks
ENV POLLER_STATE_DIR=/state

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')"]

EXPOSE 5000

ENTRYPOINT ["uv", "run"]
CMD ["python", "-m", "rai.web.app"]
