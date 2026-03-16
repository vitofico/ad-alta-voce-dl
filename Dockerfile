FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY rai_download.py .
COPY rai/ rai/

ENTRYPOINT ["uv", "run"]
CMD ["python", "-m", "rai.web.app"]
