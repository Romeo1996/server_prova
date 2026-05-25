import logging

from fastapi import FastAPI
from ag_ui_adk import ADKAgent
from ag_ui_adk.endpoint import add_adk_fastapi_endpoint

from src.middleware.user_context import extract_user_context

logger = logging.getLogger(__name__)


def setup_chat_endpoint(app: FastAPI, adk_agent: ADKAgent, path: str = "/chat"):
    """Register the AG-UI chat endpoint with user-context extraction.

    The endpoint is served at *path* (default ``/chat``) and uses the
    ``extract_user_context`` hook to inject ``X-User-Id`` into session
    state so the ADK agent can resolve per-request user identity.
    """
    logger.info(
        "Registering chat endpoint at %s with extract_state_from_request=%s",
        path,
        extract_user_context,
    )
    add_adk_fastapi_endpoint(
        app,
        adk_agent,
        path=path,
        extract_state_from_request=extract_user_context,
    )
    logger.info("AG-UI chat endpoint registered at %s", path)
