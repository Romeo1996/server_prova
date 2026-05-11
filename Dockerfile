FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1  \
    PYTHONPATH=/app/src

WORKDIR /app

RUN echo "=== Installing uv ===" && pip install --no-cache-dir uv

# Copia il file di progetto e lockfile
COPY pyproject.toml uv.lock ./

# Installa in modalità deterministica (frozen)
RUN echo "=== Syncing dependencies with uv ===" && uv sync --frozen --no-dev

# Copia il codice sorgente
COPY src ./src
COPY main.py ./

EXPOSE 8086 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
    CMD curl -f http://localhost:8086/health || exit 1
