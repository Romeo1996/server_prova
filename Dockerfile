# Immagine con Python 3.11 e UV pre-installati
FROM astral/uv:latest-python3.11-slim

# Variabili di ambiente
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Imposta la directory di lavoro
WORKDIR /app

# Copia il file di progetto
COPY pyproject.toml .

# Sincronizza le dipendenze usando uv
RUN uv sync --frozen --no-dev

# Copia il codice sorgente
COPY src ./src

# Espone la porta 8080
EXPOSE 8080

# Comando di avvio
CMD ["uv", "run", "--no-sync", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
