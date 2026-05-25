import logging
import time
from typing import Optional

from google.adk.sessions import BaseSessionService
from google.adk.events import Event, EventActions

logger = logging.getLogger(__name__)

THREAD_TITLE_KEY = "thread_title"
THREAD_ID_STATE_KEY = "_ag_ui_thread_id"


class AdkSessionService:
    """Wraps ADK BaseSessionService for thread CRUD operations.

    ADK Sessions are the persistence layer — no custom DB entities.
    Thread metadata (title, etc.) is stored in ADK session state.
    """

    def __init__(self, session_service: BaseSessionService, app_name: str):
        self._service = session_service
        self._app_name = app_name

    async def list_threads(self, user_id: str) -> list[dict]:
        """List all threads (ADK sessions) for a user."""
        try:
            response = await self._service.list_sessions(
                app_name=self._app_name,
                user_id=user_id,
            )
            threads = []
            for session in response.sessions:
                state = session.state or {}
                state_dict = (
                    state.to_dict() if hasattr(state, "to_dict") else dict(state)
                )
                thread_id = state_dict.get(THREAD_ID_STATE_KEY, session.id)
                relevant_state = {
                    k: v
                    for k, v in state_dict.items()
                    if k.startswith("__fork") or k in ("thread_title",)
                }
                threads.append(
                    {
                        "id": thread_id,
                        "title": state_dict.get(THREAD_TITLE_KEY),
                        "updated_at": getattr(session, "last_update_time", None),
                        "state": relevant_state if relevant_state else None,
                    }
                )
            return threads
        except Exception as e:
            logger.error("Error listing threads for user %s: %s", user_id, e)
            return []

    async def list_sessions(
        self, user_id: str
    ) -> list:
        """List raw ADK sessions for a user."""
        try:
            response = await self._service.list_sessions(
                app_name=self._app_name,
                user_id=user_id,
            )
            return list(response.sessions)
        except Exception as e:
            logger.error("Error listing sessions for user %s: %s", user_id, e)
            return []

    async def get_session(
        self, thread_id: str, user_id: str
    ):
        """Get ADK session by thread_id (= session_id with use_thread_id_as_session_id)."""
        try:
            return await self._service.get_session(
                session_id=thread_id,
                app_name=self._app_name,
                user_id=user_id,
            )
        except Exception as e:
            logger.error("Error getting session %s: %s", thread_id, e)
            return None

    async def update_thread_metadata(
        self, thread_id: str, user_id: str, metadata: dict
    ) -> bool:
        """Update thread metadata stored in ADK session state."""
        try:
            session = await self._service.get_session(
                session_id=thread_id,
                app_name=self._app_name,
                user_id=user_id,
            )
            if not session:
                return False

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
        """Delete thread (ADK session)."""
        try:
            await self._service.delete_session(
                session_id=thread_id,
                app_name=self._app_name,
                user_id=user_id,
            )
            return True
        except Exception as e:
            logger.error("Error deleting thread %s: %s", thread_id, e)
            return False
