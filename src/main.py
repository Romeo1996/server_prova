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
import contextvars
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

from fastapi import FastAPI, Request
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
# Thread-level state for disconnect-driven cancellation.
# ---------------------------------------------------------------------------
@dataclass
class ThreadCancelState:
    cancel_event: asyncio.Event
    request: Optional[Request] = None
    monitor_task: Optional[asyncio.Task] = None

_cancel_states: dict[str, ThreadCancelState] = {}

# Contextvar for passing (thread_id, agent, user_id, cancel_event) from
# _cancel_aware_sse to _patched_esr_init.  Both run synchronously in the
# same task (no await between them) — safe in Python 3.11.
_disconnect_info_var: contextvars.ContextVar[Optional[dict]] = \
    contextvars.ContextVar('_disconnect_info', default=None)

# Contextvar set by _store_current_request middleware so that
# _cancel_aware_sse and _patched_stream_events can read the Request and
# call request.is_disconnected() for early disconnect detection.
_current_request_var: contextvars.ContextVar[Optional[Request]] = \
    contextvars.ContextVar('_current_request', default=None)

# ---------------------------------------------------------------------------
# Store current Request in a contextvar so the cancel machinery can read
# the ASGI receive channel directly (request.is_disconnected()).
# FastAPI awaits the response inside call_next() — the contextvar survives
# for the entire SSE stream duration.
# ---------------------------------------------------------------------------

@app.middleware("http")
async def _store_current_request(request: Request, call_next):
    _current_request_var.set(request)
    try:
        response = await call_next(request)
        return response
    finally:
        _current_request_var.set(None)

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

def _cancel_aware_sse(agent, input_data):
    cancel_event = asyncio.Event()
    thread_id = input_data.thread_id
    user_id = agent._get_user_id(input_data)
    request = _current_request_var.get()
    logger.warning(
        "=== CANCEL_AWARE_SSE: request=%s (None=%s) ===",
        id(request) if request is not None else None,
        request is None,
    )

    state = ThreadCancelState(cancel_event=cancel_event, request=request)
    _cancel_states[thread_id] = state
    _disconnect_info_var.set({
        'thread_id': thread_id,
        'user_id': user_id,
        'agent': agent,
        'cancel_event': cancel_event,
    })

    async def _monitor_disconnect():
        logger.warning(
            "=== MONITOR STARTED for %s/%s (request=%s) ===",
            thread_id, user_id,
            id(request) if request is not None else None,
        )
        try:
            while True:
                await asyncio.sleep(0.5)
                if request is not None and await request.is_disconnected():
                    cancel_event.set()
                    logger.warning(
                        "=== MONITOR detected disconnect for %s/%s ===",
                        thread_id, user_id,
                    )
                    return
        except asyncio.CancelledError:
            pass

    async def _wrapped():
        monitor_task = None
        try:
            if request is not None:
                monitor_task = asyncio.create_task(_monitor_disconnect())
                state.monitor_task = monitor_task

            async for event in _original_sse_stream(agent, input_data):
                if cancel_event.is_set():
                    logger.warning(
                        "=== CANCEL_AWARE_SSE: cancel_event set, breaking stream for %s/%s ===",
                        thread_id, user_id,
                    )
                    break
                yield event
        finally:
            if monitor_task is not None:
                monitor_task.cancel()
            _cancel_states.pop(thread_id, None)

    return _wrapped()

_ep._sse_stream = _cancel_aware_sse

_orig_esr_init = EventSourceResponse.__init__

def _patched_esr_init(self, content, **kwargs):
    info = _disconnect_info_var.get()
    logger.warning(
        "=== PATCHED_ESR_INIT: info is None=%s, kwargs=%s ===",
        info is None,
        list(kwargs.keys()),
    )
    if info is not None:
        thread_id = info['thread_id']
        user_id = info['user_id']
        agent = info['agent']
        cancel_event = info['cancel_event']
        exec_key = (thread_id, user_id)

        async def on_disconnect(message):
            logger.warning(
                "=== DISCONNECT HANDLER CALLED === thread_id=%s msg_type=%s",
                thread_id,
                message.get('type', '?'),
            )
            cancel_event.set()

            async with agent._execution_lock:
                execution = agent._active_executions.get(exec_key)

                if execution is None:
                    logger.warning(
                        "=== DISCONNECT no execution found for %s/%s ===",
                        exec_key[0], exec_key[1],
                    )
                    return

                if execution.task.done():
                    logger.warning(
                        "=== DISCONNECT execution already done for %s/%s ===",
                        exec_key[0], exec_key[1],
                    )
                    return

                await execution.event_queue.put(None)
                logger.warning(
                    "=== DISCONNECT put None on event queue for %s/%s (qsize=%d) ===",
                    exec_key[0], exec_key[1],
                    execution.event_queue.qsize(),
                )

                execution.task.cancel()
                logger.warning(
                    "=== DISCONNECT task.cancel() fired for %s/%s ===",
                    exec_key[0], exec_key[1],
                )

        kwargs.pop('client_close_handler_callable', None)
        kwargs['client_close_handler_callable'] = on_disconnect

    _orig_esr_init(self, content, **kwargs)

EventSourceResponse.__init__ = _patched_esr_init

# ---------------------------------------------------------------------------
# Monkey-patch _stream_events to log at WARNING when None is received
# ---------------------------------------------------------------------------

_original_stream_events = ADKAgent._stream_events

async def _patched_stream_events(self, execution):
    try:
        async for event in _original_stream_events(self, execution):
            yield event
            state = _cancel_states.get(execution.thread_id)
            if state is None:
                continue
            if state.cancel_event.is_set():
                logger.warning(
                    "=== CLIENT DISCONNECTED (cancel_event) after event for %s ===",
                    execution.thread_id,
                )
                raise asyncio.CancelledError()
            if state.request is not None and await state.request.is_disconnected():
                logger.warning(
                    "=== CLIENT DISCONNECTED (is_disconnected) after event for %s ===",
                    execution.thread_id,
                )
                raise asyncio.CancelledError()
    except asyncio.CancelledError:
        logger.warning(
            "=== STREAM_EVENTS INTERRUPTED for %s ===",
            execution.thread_id,
        )
        raise
    logger.warning(
        "=== STREAM_EVENTS EXITED for %s (is_complete=%s, task_done=%s) ===",
        execution.thread_id,
        execution.is_complete,
        execution.task.done(),
    )

ADKAgent._stream_events = _patched_stream_events

# ---------------------------------------------------------------------------
# Monkey-patch _start_new_execution to cancel the background task on
# GeneratorExit (client disconnect).  task.cancel() injects CancelledError
# into the background task; if it is mid-httpx (google.genai → LLM provider)
# the in-flight HTTP request is aborted immediately.
# ---------------------------------------------------------------------------

_original_start_new_execution = ADKAgent._start_new_execution

async def _patched_start_new_execution(self, input_data, **kwargs):
    exec_key = (input_data.thread_id, self._get_user_id(input_data))
    execution = None
    try:
        async for event in _original_start_new_execution(self, input_data, **kwargs):
            if execution is None:
                async with self._execution_lock:
                    execution = self._active_executions.get(exec_key)
            yield event
    except (GeneratorExit, asyncio.CancelledError):
        if execution is not None and not execution.task.done():
            logger.warning(
                "=== CANCEL_BACKGROUND_TASK for %s/%s ===",
                exec_key[0], exec_key[1],
            )
            execution.task.cancel()
        raise

ADKAgent._start_new_execution = _patched_start_new_execution

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
