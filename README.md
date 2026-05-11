# ADK Server Template — FastAPI + ADK Web

Template per applicazioni AI agent con **Google ADK (Agent Development Kit)** e **LiteLLM**, multi-provider.

## Architettura

Il progetto fornisce due servizi Docker:

```
┌─────────────────────────────────────────────────────┐
│                   docker-compose.yml                 │
│                                                      │
│  ┌──────────────┐           ┌──────────────────────┐ │
│  │ fastapi-server│           │      adk-web         │ │
│  │  :8086        │           │      :3000           │ │
│  │               │           │                      │ │
│  │ FastAPI app   │           │ ADK Web Interface    │ │
│  │ + endpoints   │           │ + Visual Builder     │ │
│  │ REST          │           │ + Runtime SSE        │ │
│  └──────────────┘           └──────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### Servizi

| Servizio | Porta | Descrizione |
|----------|-------|-------------|
| **fastapi-server** | `8086` | Server FastAPI con health check ed endpoint REST |
| **adk-web** | `3000` | Interfaccia web ADK per eseguire e costruire agenti |

## Struttura del progetto

```
server_prova/
├── .env                        # Variabili d'ambiente condivise
├── .dockerignore
├── .gitignore
├── .python-version
├── docker-compose.yml          # Orchestrazione Docker
├── Dockerfile                  # Build immagine Python + uv
├── main.py                     # Entry point semplice (CLI)
├── pyproject.toml              # Dipendenze: fastapi, google-adk, litellm
├── uv.lock                     # Lockfile deterministica
└── src/
    ├── __init__.py
    ├── config.py               # Configurazione provider LLM + flag STRIP_THINKING
    ├── main.py                 # FastAPI app con CORS e health endpoint
    ├── models.py               # Modelli LLM personalizzati (strip thinking)
    └── agents/
        └── example_agent/
            ├── __init__.py
            └── agent.py        # Agente ADK di esempio (root_agent)
```

## Provider LLM supportati

Il progetto supporta più provider LLM tramite **LiteLLM**, configurabili via env var `LLM_PROVIDER`:

| Provider | Modello | API Key |
|----------|---------|---------|
| `google` | `gemini-flash-latest` (nativo) | `GOOGLE_API_KEY` |
| `groq` | `qwen/qwen3-32b` | `GROQ_API_KEY` |
| `openrouter` | `nvidia/nemotron-3-super-120b-a12b:free` | `OPENROUTER_API_KEY` |

### Configurazione

Copia e modifica il file `.env`:

```bash
LLM_PROVIDER=google          # google | groq | openrouter
GOOGLE_API_KEY=your_key_here
GROQ_API_KEY=your_key_here
OPENROUTER_API_KEY=your_key_here
STRIP_THINKING=true          # rimuove il thinking/reasoning dall'output
```

## Strip Thinking/Reasoning

I modelli LLM moderni (DeepSeek R1, Qwen 3, Claude, ecc.) restituiscono spesso il **ragionamento interno** (*thinking/reasoning*) insieme alla risposta finale. Questo può essere utile per debug ma indesiderato nell'output visivo all'utente.

### Come funziona

Il flag `STRIP_THINKING` (default: `true`) controlla se rimuovere automaticamente il thinking dall'output:

1. **`src/config.py`** — Legge `STRIP_THINKING` dall'env var e passa il modello appropriato
2. **`src/models.py`** — `StripThinkingLiteLlm` wrappa `LiteLlm` e filtra due formati di thinking:
   - **Formato strutturato**: `Part(thought=True)` — usato da ADK per Claude (thinking_blocks), DeepSeek, Qwen via LiteLLM
   - **Formato testuale**: tag XML `<think>...</think>` — usato da Qwen 3 su Groq, DeepSeek R1
3. **`src/agents/example_agent/agent.py`** — Nessun `after_model_callback`. Lo strip è gestito internamente dal modello.

Il filtro agisce a **livello di modello** (non di agente), evitando problemi di serializzazione Pydantic con il Visual Builder di ADK.

### Disabilitare lo strip

```bash
STRIP_THINKING=false
```

## Avvio

### Con Docker

```bash
# Build immagine
docker compose build

# Avvia entrambi i servizi
docker compose up -d

# Log in tempo reale
docker compose logs -f

# Solo un servizio specifico
docker compose up -d adk-web
```

### Senza Docker (sviluppo locale)

```bash
# Installa dipendenze (richiede uv)
uv sync

# Avvia FastAPI server
uv run uvicorn src.main:app --host 0.0.0.0 --port 8086

# Avvia ADK Web (in un altro terminale)
cd src/agents
uv run adk web --host 0.0.0.0 --port 3000
```

## Endpoint

### FastAPI Server (`:8086`)

| Endpoint | Metodo | Descrizione |
|----------|--------|-------------|
| `/` | GET | Health check semplice |
| `/health` | GET | Health check dettagliato |

### ADK Web (`:3000`)

| Endpoint | Descrizione |
|----------|-------------|
| `/dev-ui/` | Interfaccia Visual Builder per agenti |
| `/list-apps` | Elenco agenti disponibili |
| `/run_sse` | Esecuzione agent via Server-Sent Events |
| `/debug/trace/` | Trace delle sessioni |

## Creare un nuovo agente

Crea una nuova cartella in `src/agents/`:

```bash
mkdir -p src/agents/mio_agente
touch src/agents/mio_agente/__init__.py
```

Poi crea `src/agents/mio_agente/agent.py`:

```python
from google.adk.agents import LlmAgent
from config import get_model_instance

model_instance, llm_config = get_model_instance()

root_agent = LlmAgent(
    model=model_instance,
    name='mio_agente',
    description=f'Agente con {llm_config.display_name}',
    instruction='Sei un assistente utile.',
)
```

ADK Web rileverà automaticamente il nuovo agente.

## Variabili d'ambiente

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `LLM_PROVIDER` | `google` | Provider LLM: `google`, `groq`, `openrouter`, `openai`, `anthropic` |
| `GOOGLE_API_KEY` | — | API Key per Google Gemini |
| `GROQ_API_KEY` | — | API Key per Groq |
| `OPENROUTER_API_KEY` | — | API Key per OpenRouter |
| `STRIP_THINKING` | `true` | Rimuove il thinking/reasoning dall'output |
| `PYTHONUNBUFFERED` | `1` | Output Python senza buffer |

## Dipendenze

- **Python >= 3.11**
- [FastAPI](https://fastapi.tiangolo.com/) — Web framework
- [google-adk](https://adk.dev/) — Google Agent Development Kit
- [LiteLLM](https://docs.litellm.ai/) — Interfaccia unificata per 100+ LLM
- [uv](https://docs.astral.sh/uv/) — Package manager deterministico