import logging
import time
from typing import Optional

from google.adk.sessions import BaseSessionService
from google.adk.events import Event, EventActions
from ag_ui_adk.event_translator import adk_events_to_messages

logger = logging.getLogger(__name__)

THREAD_TITLE_KEY = "thread_title"
THREAD_ID_STATE_KEY = "_ag_ui_thread_id"

FALLBACK_USER_IDS = ["default_user"]


def _state_to_dict(state) -> dict:
    if state is None:
        return {}
    return state.to_dict() if hasattr(state, "to_dict") else dict(state)


def _iter_user_ids(user_id: str):
    """Yield the primary user_id first, then fallback IDs."""
    yield user_id
    for fid in FALLBACK_USER_IDS:
        if fid != user_id:
            yield fid


def _extract_relevant_state(state_dict: dict) -> dict | None:
    relevant = {
        k: v
        for k, v in state_dict.items()
        if k.startswith("__fork") or k in (THREAD_TITLE_KEY,)
    }
    return relevant if relevant else None


def _assemble_thread_messages(events: list) -> list[dict]:
    """Convert AG-UI events to ThreadMessage-compatible dicts.

    Assembles ``text_start`` / ``text_content`` / ``text_end`` sequences
    into single assistant messages; keeps ``user`` events as-is.
    """
    result: list[dict] = []
    buf: dict[str, list[str]] = {}

    for event in events:
        etype = getattr(event, "type", None)
        mid = getattr(event, "message_id", None)

        if etype == "user":
            content = []
            for part in getattr(event, "content", []) or []:
                d = part.model_dump() if hasattr(part, "model_dump") else dict(part)
                content.append(d)
            result.append({"id": mid, "role": "user", "content": content})

        elif etype == "tool_call":
            content = [{
                "type": "tool_call",
                "toolCallId": getattr(event, "tool_call_id", ""),
                "toolName": getattr(event, "tool_name", ""),
                "args": getattr(event, "args", "{}"),
            }]
            result.append({"id": mid, "role": "assistant", "content": content})

        elif etype == "tool_result":
            content = [{
                "type": "tool_result",
                "toolCallId": getattr(event, "tool_call_id", ""),
                "result": getattr(event, "content", []),
            }]
            result.append({"id": mid, "role": "tool", "content": content})

        elif etype == "text_start":
            buf[mid] = []

        elif etype == "text_content":
            if mid in buf:
                buf[mid].append(getattr(event, "delta", ""))

        elif etype == "text_end":
            texts = buf.pop(mid, None)
            if texts is not None:
                result.append({
                    "id": mid,
                    "role": "assistant",
                    "content": [{"type": "text", "text": "".join(texts)}],
                })

    return result


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
                state_dict = _state_to_dict(session.state)
                thread_id = state_dict.get(THREAD_ID_STATE_KEY, session.id)
                if thread_id in seen_ids:
                    continue
                seen_ids.add(thread_id)
                threads.append(
                    {
                        "id": thread_id,
                        "title": state_dict.get(THREAD_TITLE_KEY),
                        "updated_at": getattr(session, "last_update_time", None),
                        "state": _extract_relevant_state(state_dict),
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
                state_dict = _state_to_dict(session.state)
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
        return await self._find_session_by_thread_id(thread_id, user_ids)

    async def get_thread_messages(self, thread_id: str, user_id: str) -> Optional[dict]:
        """Return thread data with assembled messages, or None if not found."""
        session = await self.get_session(thread_id, user_id)
        if not session:
            return None
        state_dict = _state_to_dict(session.state)
        events = getattr(session, "events", []) or []
        agui_msgs = adk_events_to_messages(events)
        messages = _assemble_thread_messages(agui_msgs)
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
