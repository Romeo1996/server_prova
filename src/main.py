"""
FastAPI server with ADK agent + AG-UI protocol.

MVC structure:
  - controllers/     → route handlers (chat, threads)
  - services/        → business logic (AdkSessionService)
  - middleware/       → request-level user-context extraction
  - dto/             → Pydantic request/response schemas
  - agents/          → ADK agent definitions
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from google.adk.apps import App as AdkApp, ResumabilityConfig
from ag_ui_adk import ADKAgent

from src.agents.example_agent.agent import root_agent
from src.middleware.user_context import extract_user_id
from src.controllers.chat import setup_chat_endpoint
from src.controllers.threads import create_thread_router
from src.services.session import AdkSessionService

import ag_ui_adk.endpoint as _ep
from sse_starlette.sse import EventSourceResponse


print(f"=== MAIN.PY LOADED __name__={__name__} ===", flush=True)


class CancelAwareADKAgent(ADKAgent):
    logger = logging.getLogger(f"{__name__}.CancelAwareADKAgent")

    async def run(self, input_data):
        import sys as _sys
        print("=== CANCEL_AWARE_RUN ENTERED ===", flush=True, file=_sys.stderr)
        self.logger.warning(
            "=== AGENT RUN ENTERED === thread_id=%s user_id=%s session_id=%s",
            getattr(input_data, 'thread_id', None) or getattr(input_data, 'threadId', None),
            getattr(input_data, 'user_id', None) or getattr(input_data, 'userId', None),
            getattr(input_data, 'session_id', None) or getattr(input_data, 'sessionId', None),
        )
        try:
            async for event in super().run(input_data):
                yield event
            self.logger.warning(
                "=== AGENT RUN COMPLETED NORMALLY === thread_id=%s",
                getattr(input_data, 'thread_id', None) or getattr(input_data, 'threadId', None),
            )
        except (GeneratorExit, asyncio.CancelledError):
            self.logger.warning(
                "=== AGENT RUN INTERRUPTED === thread_id=%s",
                getattr(input_data, 'thread_id', None) or getattr(input_data, 'threadId', None),
            )
            raise

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
APP_NAME = "example_app"

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    google_api_key = os.environ.get("GOOGLE_API_KEY", "NOT SET")
    groq_api_key = os.environ.get("GROQ_API_KEY", "NOT SET")
    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "NOT SET")
    llm_provider = os.environ.get("LLM_PROVIDER", "google")

    logger.info("=== API Keys ===")
    logger.info("GOOGLE_API_KEY: %s", google_api_key)
    logger.info("GROQ_API_KEY: %s", groq_api_key)
    logger.info("OPENROUTER_API_KEY: %s", openrouter_api_key)
    logger.info("LLM_PROVIDER: %s", llm_provider)
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="ADK Server",
    version="1.0.0",
    description="FastAPI + Google ADK with multi-user support",
    lifespan=lifespan,
)

cors_origins = os.environ.get("CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# ADK Agent (Model)
# ---------------------------------------------------------------------------
adk_app = AdkApp(
    name=APP_NAME,
    root_agent=root_agent,
    resumability_config=ResumabilityConfig(is_resumable=True),
)

logger.info("Creating ADKAgent with user_id_extractor=%s", extract_user_id)
adk_agent = CancelAwareADKAgent.from_app(
    adk_app,
    user_id_extractor=extract_user_id,
    plugin_close_timeout=10.0,
    use_thread_id_as_session_id=True,
)

# ---------------------------------------------------------------------------
# Monkey-patches for disconnect cancellation
# ---------------------------------------------------------------------------

_original_sse_stream = _ep._sse_stream

_sse_info_queue: list = []

def _cancel_aware_sse(agent, input_data):
    cancel_event = asyncio.Event()
    _sse_info_queue.append((cancel_event, agent, input_data))

    async def _wrapped():
        async for event in _original_sse_stream(agent, input_data):
            if cancel_event.is_set():
                break
            yield event

    return _wrapped()

_ep._sse_stream = _cancel_aware_sse

_orig_esr_init = EventSourceResponse.__init__

def _patched_esr_init(self, content, **kwargs):
    if _sse_info_queue:
        cancel_event, agent, input_data = _sse_info_queue.pop(0)

        async def on_disconnect(message):
            logger.warning(
                "=== DISCONNECT HANDLER CALLED === thread_id=%s msg_type=%s",
                getattr(input_data, 'thread_id', None),
                message.get('type', '?'),
            )
            cancel_event.set()
            user_id = agent._get_user_id(input_data)
            exec_key = (input_data.thread_id, user_id)
            logger.warning(
                "=== DISCONNECT cancelling exec_key=%s/%s ===",
                exec_key[0], exec_key[1],
            )
            async with agent._execution_lock:
                execution = agent._active_executions.get(exec_key)
                if execution:
                    if execution.task.done():
                        logger.warning(
                            "=== DISCONNECT execution already done for %s/%s ===",
                            exec_key[0], exec_key[1],
                        )
                    else:
                        await execution.cancel()
                        logger.warning(
                            "=== DISCONNECT cancelled execution for %s/%s ===",
                            exec_key[0], exec_key[1],
                        )
                else:
                    logger.warning(
                        "=== DISCONNECT no execution found for %s/%s ===",
                        exec_key[0], exec_key[1],
                    )

        kwargs['client_close_handler_callable'] = on_disconnect

    _orig_esr_init(self, content, **kwargs)

EventSourceResponse.__init__ = _patched_esr_init

logger.info("=== Monkey-patches installed: cancel-aware SSE + disconnect handler ===")

# ---------------------------------------------------------------------------
# Controllers
# ---------------------------------------------------------------------------

# AG-UI chat endpoint — uses extract_state_from_request internally to
# inject X-User-Id into session state before every run.
setup_chat_endpoint(app, adk_agent, path="/chat")

# Thread CRUD API — backed by ADK's InMemorySessionService.
session_service = AdkSessionService(
    adk_agent._session_manager._session_service,
    APP_NAME,
)
app.include_router(create_thread_router(session_service))

# ---------------------------------------------------------------------------
# Utility endpoints
# ---------------------------------------------------------------------------


@app.get("/")
async def read_root():
    return JSONResponse({"message": "Hello Worldd!"})


@app.get("/health")
async def health_check():
    return JSONResponse({"status": "healthy"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8086)
