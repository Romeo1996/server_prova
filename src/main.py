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
        except BaseException:
            exc_type, exc_value, exc_tb = _sys.exc_info()
            print(f"=== CANCEL_AWARE_EXCEPTION type={exc_type.__name__ if exc_type else '?'} msg={exc_value} ===", flush=True, file=_sys.stderr)
            self.logger.warning(
                "=== EXCEPTION CAUGHT === type=%s msg=%s user_id=%s session_id=%s",
                exc_type.__name__ if exc_type else '?',
                str(exc_value) if exc_value else '?',
                getattr(input_data, 'user_id', None) or getattr(input_data, 'userId', None),
                getattr(input_data, 'session_id', None) or getattr(input_data, 'sessionId', None),
            )
            if isinstance(exc_value, BaseException):
                import traceback
                tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
                print(f"=== EXCEPTION TRACEBACK ===\n{tb_text}===", flush=True, file=_sys.stderr)
            user_id = getattr(input_data, 'user_id', None) or getattr(input_data, 'userId', None)
            session_id = getattr(input_data, 'session_id', None) or getattr(input_data, 'sessionId', None)
            if session_id and user_id:
                exec_key = (session_id, user_id)
                async with self._execution_lock:
                    execution = self._active_executions.get(exec_key)
                    if execution:
                        if execution.task.done():
                            self.logger.warning(
                                "=== ADK execution already done for %s/%s ===",
                                session_id, user_id,
                            )
                        else:
                            await execution.cancel()
                            self.logger.warning(
                                "=== ADK execution CANCELLED for %s/%s ===",
                                session_id, user_id,
                            )
                    else:
                        self.logger.warning(
                            "=== No active ADK execution found for %s/%s ===",
                            session_id, user_id,
                        )
            else:
                self.logger.warning(
                    "=== Missing session_id or user_id: session_id=%s user_id=%s ===",
                    session_id, user_id,
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
