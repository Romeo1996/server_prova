# FastAPI Hello World Server

Progetto FastAPI containerizzato con Docker e gestito con UV.

## Descrizione

Questo progetto contiene un server FastAPI semplice con endpoint "hello world" che viene eseguito in un container Docker. Non è necessario avere Python installato sulla macchina, solo Docker.

## Requisiti

- Docker Desktop (o Docker Engine)
- Docker Compose (generalmente incluso con Docker Desktop)

## Avvio del Server

### Opzione 1: Usando Docker Compose (Consigliato)

```bash
docker-compose up
```

Il server sarà disponibile su: `http://localhost:8086`

### Opzione 2: Usando Docker direttamente

```bash
# Build dell'immagine
docker build -t fastapi-hello .

# Avvio del container
docker run -p 8086:8086 fastapi-hello
```

## Endpoint disponibili

- **GET `/`** - Ritorna "Hello World!"
  ```
  curl http://localhost:8086/
  ```

- **GET `/health`** - Verifica della salute del server
  ```
  curl http://localhost:8086/health
  ```

- **GET `/docs`** - Documentazione interattiva (Swagger UI)
  ```
  http://localhost:8086/docs
  ```

- **GET `/redoc`** - Documentazione alternativa (ReDoc)
  ```
  http://localhost:8086/redoc
  ```

## Struttura del progetto

```
server_prova/
├── src/
│   ├── main.py             # Applicazione FastAPI
│   └── __init__.py         # Package marker
├── pyproject.toml          # Configurazione UV con dipendenze
├── Dockerfile              # Definizione del container
├── docker-compose.yml      # Configurazione Docker Compose
├── .dockerignore            # File da escludere dal build
└── README.md               # Questo file
```

## Stopp del server

Per fermare il server:

```bash
docker-compose down
```

## Note

- La porta predefinita è 8086, ma può essere modificata nel `docker-compose.yml`
- Tutte le dipendenze Python sono gestite automaticamente dal Dockerfile
- Il progetto usa UV come gestore di pacchetti per migliori performance

