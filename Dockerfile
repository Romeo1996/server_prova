# Usa immagine astral/uv che ha già Python e UV installati
FROM astral/uv:latest

# Imposta la directory di lavoro
WORKDIR /app

# Copia il file di progetto
COPY pyproject.toml .

# Sincronizza le dipendenze usando uv
RUN uv sync --no-dev

# Copia il codice sorgente
COPY src ./src

# Espone la porta 8080
EXPOSE 8080

# Comando di avvio con uv
CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]

