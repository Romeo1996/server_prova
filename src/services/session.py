import json
import logging
import time
import uuid
from typing import Optional

from google.adk.sessions import BaseSessionService
from google.adk.events import Event, EventActions

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


def _adk_events_to_thread_messages(events: list) -> list[dict]:
    """Convert raw ADK events directly to ThreadMessage-compatible dicts.

    Bypasses ``adk_events_to_messages`` because the streaming workaround
    in ``main.py`` sets ``partial=True`` on every stored event, which that
    library function interprets as "skip this event".

    Strategy: group consecutive events by ``author`` and concatenate their
    text parts, then emit one message per group.  This collapses streaming
    chunks into a single assistant message while preserving user/tool events.
    """
    result: list[dict] = []

    for event in events:
        content = getattr(event, "content", None)
        if not content or not getattr(content, "parts", None):
            continue

        author = getattr(event, "author", None)
        if not author:
            continue

        parts = content.parts
        event_id = getattr(event, "id", None) or str(uuid.uuid4())

        # --- User message ------------------------------------------------
        if author == "user":
            text_parts = []
            for p in parts:
                if getattr(p, "text", None) and not getattr(p, "thought", False):
                    text_parts.append(p.text)
            if text_parts:
                result.append({
                    "id": event_id,
                    "role": "user",
                    "content": [{"type": "text", "text": "".join(text_parts)}],
                })
            continue

        # --- Function response (tool result) -----------------------------
        func_responses = []
        for p in parts:
            fr = getattr(p, "function_response", None)
            if fr:
                func_responses.append(fr)

        if func_responses:
            for fr in func_responses:
                resp_text = ""
                if hasattr(fr, "response"):
                    resp_text = json.dumps(fr.response) if not isinstance(fr.response, str) else fr.response
                result.append({
                    "id": str(uuid.uuid4()),
                    "role": "tool",
                    "content": [{
                        "type": "tool_result",
                        "toolCallId": getattr(fr, "id", ""),
                        "result": resp_text,
                    }],
                })
            continue

        # --- Assistant message (text + function calls) -------------------
        text_parts = []
        func_calls = []
        for p in parts:
            if getattr(p, "text", None) and not getattr(p, "thought", False):
                text_parts.append(p.text)
            fc = getattr(p, "function_call", None)
            if fc:
                func_calls.append(fc)

        if not text_parts and not func_calls:
            continue

        content_items = []
        if text_parts:
            content_items.append({"type": "text", "text": "".join(text_parts)})
        for fc in func_calls:
            content_items.append({
                "type": "tool_call",
                "toolCallId": getattr(fc, "id", ""),
                "toolName": getattr(fc, "name", ""),
                "args": json.dumps(getattr(fc, "args", {})),
            })

        result.append({
            "id": event_id,
            "role": "assistant",
            "content": content_items,
        })

    # --- Merge consecutive assistant events (streaming chunks) ----------
    # Combine adjacent text parts so chunked streaming text isn't split
    # across multiple content items.
    if not result:
        return result

    merged: list[dict] = [result[0]]
    for msg in result[1:]:
        prev = merged[-1]
        if msg["role"] == "assistant" and prev["role"] == "assistant":
            prev_content = prev["content"]
            for item in msg["content"]:
                if item["type"] == "text" and prev_content and prev_content[-1]["type"] == "text":
                    prev_content[-1]["text"] += item["text"]
                else:
                    prev_content.append(item)
        else:
            merged.append(msg)
    return merged


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
        session = await self._find_session_by_thread_id(thread_id, user_ids)
        if session:
            session = await self._service.get_session(
                session_id=session.id,
                app_name=self._app_name,
                user_id=session.user_id,
            )
        return session

    async def get_thread_messages(self, thread_id: str, user_id: str) -> Optional[dict]:
        """Return thread data with assembled messages, or None if not found.

        Processes ADK events directly instead of using ``adk_events_to_messages``
        because the streaming workaround in ``main.py`` marks every stored event
        as ``partial=True``, which causes the library function to filter them all
        out (it skips partial events).
        """
        session = await self.get_session(thread_id, user_id)
        if not session:
            return None
        state_dict = _state_to_dict(session.state)
        events = getattr(session, "events", []) or []
        messages = _adk_events_to_thread_messages(events)
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
