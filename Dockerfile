FROM python:3.14-slim

# Non-root user
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy deps first for layer caching
COPY pyproject.toml ./
RUN uv sync --python 3.14 --no-dev && rm -rf $HOME/.cache/uv

# Copy source
COPY src/ ./src/
COPY .env.example ./

# Data directory
RUN mkdir -p /data && chown -R app:app /data
VOLUME /data

USER app
EXPOSE 8050

# Warmup data copied at deployment time or mounted at /data/warmup/
ENV DATA_DIR=/data

CMD ["uv", "run", "--no-dev", "python", "-m", "epistree_demo.app"]
