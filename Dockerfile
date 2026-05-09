FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN pip install --no-cache-dir uv

# 👇 IMPORTANTISSIMO: copia anche il lock
COPY pyproject.toml uv.lock ./

# debug utile (opzionale ma consigliato)
RUN ls -la

# installa in modalità deterministica
RUN uv sync --frozen --no-dev

COPY src ./src

EXPOSE 8080

CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]