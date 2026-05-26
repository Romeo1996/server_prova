import logging
import time
from typing import Optional

from google.adk.sessions import BaseSessionService
from google.adk.events import Event, EventActions
from ag_ui_adk.event_translator import adk_events_to_messages
from ag_ui.core import UserMessage, AssistantMessage, ToolMessage, ReasoningMessage

logger = logging.getLogger(__name__)

THREAD_TITLE_KEY = "thread_title"
THREAD_ID_STATE_KEY = "_ag_ui_thread_id"
FALLBACK_USER_IDS = ["default_user"]


def _state(state) -> dict:
    """Normalize ADK state to a plain dict."""
    if state is None:
        return {}
    return state.to_dict() if hasattr(state, "to_dict") else dict(state)


def _iter_user_ids(user_id: str):
    """Yield the primary user_id first, then fallback IDs."""
    yield user_id
    for fid in FALLBACK_USER_IDS:
        if fid != user_id:
            yield fid


def _to_thread_message(msg) -> dict | None:
    """Convert an AG-UI Message to a ThreadMessage-compatible dict."""
    match msg:
        case UserMessage():
            if isinstance(msg.content, str):
                parts = [{"type": "text", "text": msg.content}]
            else:
                parts = [
                    {"type": "text", "text": p.text}
                    if getattr(p, "type", None) == "text"
                    else p.model_dump() if hasattr(p, "model_dump") else {"type": "unknown"}
                    for p in (msg.content or [])
                ]
            return {"id": msg.id, "role": "user", "content": parts}

        case AssistantMessage():
            text = [{"type": "text", "text": msg.content}] if msg.content else []
            tools = [
                {"type": "tool_call", "toolCallId": tc.id, "toolName": tc.function.name, "args": tc.function.arguments}
                for tc in (msg.tool_calls or [])
            ]
            return {
                "id": msg.id,
                "role": "assistant",
                "content": text + tools,
                "status": {"type": "complete", "reason": "unknown"},
            }

        case ToolMessage():
            return {
                "id": msg.id,
                "role": "tool",
                "content": [{"type": "tool_result", "toolCallId": msg.tool_call_id, "result": msg.content}],
            }

        case _:
            return None


class AdkSessionService:
    """Wraps ADK BaseSessionService for thread CRUD operations.

    Backward compatibility:
    - Sessions created with ``user_id="default_user"`` (pre-refactoring) are
      still discoverable via a fallback lookup on ``"default_user"``.
    - Sessions with auto-generated ``session_id`` (pre-``use_thread_id_as_session_id``)
      are found by scanning ``_ag_ui_thread_id`` in session state.
    """

    def __init__(self, session_service: BaseSessionService, app_name: str):
        self._service = session_service
        self._app_name = app_name

    async def list_threads(self, user_id: str) -> list[dict]:
        """List threads across primary and fallback user IDs (deduplicated)."""
        seen_ids: set[str] = set()
        threads: list[dict] = []

        for uid in _iter_user_ids(user_id):
            try:
                response = await self._service.list_sessions(
                    app_name=self._app_name,
                    user_id=uid,
                )
            except Exception as e:
                logger.debug("list_sessions failed for user %s: %s", uid, e)
                continue

            for session in response.sessions:
                state_dict = _state(session.state)
                thread_id = state_dict.get(THREAD_ID_STATE_KEY, session.id)
                if thread_id in seen_ids:
                    continue
                seen_ids.add(thread_id)
                threads.append(
                    {
                        "id": thread_id,
                        "title": state_dict.get(THREAD_TITLE_KEY),
                        "updated_at": getattr(session, "last_update_time", None),
                        "state": state_dict or None,
                    }
                )

        return threads

    async def _find_session_by_thread_id(
        self, thread_id: str, user_ids: list[str]
    ):
        """Scan sessions for a given thread_id (covers old auto-generated session_ids)."""
        for uid in user_ids:
            try:
                response = await self._service.list_sessions(
                    app_name=self._app_name,
                    user_id=uid,
                )
            except Exception:
                continue
            for session in response.sessions:
                state_dict = _state(session.state)
                if state_dict.get(THREAD_ID_STATE_KEY) == thread_id:
                    return session
        return None

    async def get_session(self, thread_id: str, user_id: str):
        """Get session by thread_id with backward-compatible fallback.

        1. Direct ``get_session(session_id=thread_id, …)`` — covers
           ``use_thread_id_as_session_id=True`` sessions.
        2. Scan sessions by ``_ag_ui_thread_id`` — covers older sessions.
        """
        user_ids = list(_iter_user_ids(user_id))
        for uid in user_ids:
            try:
                session = await self._service.get_session(
                    session_id=thread_id,
                    app_name=self._app_name,
                    user_id=uid,
                )
                if session:
                    return session
            except Exception:
                continue
        session = await self._find_session_by_thread_id(thread_id, user_ids)
        if session:
            session = await self._service.get_session(
                session_id=session.id,
                app_name=self._app_name,
                user_id=session.user_id,
            )
        return session

    async def get_thread_messages(self, thread_id: str, user_id: str) -> Optional[dict]:
        """Return thread data with assembled messages, or None if not found."""
        session = await self.get_session(thread_id, user_id)
        if not session:
            return None
        state_dict = _state(session.state)
        agui_msgs = adk_events_to_messages(getattr(session, "events", []) or [])
        messages = [m for msg in agui_msgs if (m := _to_thread_message(msg)) is not None]
        return {
            "id": thread_id,
            "title": state_dict.get(THREAD_TITLE_KEY),
            "state": state_dict,
            "messages": messages,
        }

    async def update_thread_metadata(
        self, thread_id: str, user_id: str, metadata: dict
    ) -> bool:
        session = await self.get_session(thread_id, user_id)
        if not session:
            return False
        try:
            actions = EventActions(state_delta=metadata)
            event = Event(
                invocation_id=f"meta_{int(time.time())}",
                author="user",
                actions=actions,
                timestamp=time.time(),
            )
            await self._service.append_event(session, event)
            return True
        except Exception as e:
            logger.error("Error updating thread %s: %s", thread_id, e)
            return False

    async def delete_thread(self, thread_id: str, user_id: str) -> bool:
        session = await self.get_session(thread_id, user_id)
        if not session:
            return False
        try:
            await self._service.delete_session(
                session_id=session.id,
                app_name=self._app_name,
                user_id=session.user_id,
            )
            return True
        except Exception as e:
            logger.error("Error deleting thread %s: %s", thread_id, e)
            return False

    async def list_sessions(self, user_id: str) -> list:
        try:
            response = await self._service.list_sessions(
                app_name=self._app_name,
                user_id=user_id,
            )
            return list(response.sessions)
        except Exception as e:
            logger.error("Error listing sessions for user %s: %s", user_id, e)
            return []
