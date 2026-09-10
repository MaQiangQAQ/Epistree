FROM python:3.14-slim

# Non-root user
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy deps first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --python 3.14 --no-dev --no-install-project && rm -rf /root/.cache/uv

# Copy source
COPY src/ ./src/
COPY .env.example ./
RUN uv sync --frozen --python 3.14 --no-dev

# Data directory
RUN mkdir -p /data && chown -R app:app /data
VOLUME /data

USER app
EXPOSE 8050

# Warmup data copied at deployment time or mounted at /data/warmup/
ENV DATA_DIR=/data

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8050/_dash-layout')"
CMD ["uv", "run", "--frozen", "--no-dev", "--no-sync", "epistree-demo"]
