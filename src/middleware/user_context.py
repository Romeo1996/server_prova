import logging

from fastapi import Request
from ag_ui.core import RunAgentInput

logger = logging.getLogger(__name__)


async def extract_user_context(
    request: Request, input_data: RunAgentInput
) -> dict:
    """Extract X-User-Id from request headers into AG-UI session state."""
    user_id = request.headers.get("x-user-id")
    logger.info(
        "extract_user_context: x-user-id=%s | all headers keys=%s",
        user_id,
        sorted(request.headers.keys()),
    )
    if not user_id:
        return {}
    return {"user_id": user_id}


def extract_user_id(input: RunAgentInput) -> str:
    """Read user_id from AG-UI state (injected by extract_user_context)."""
    if isinstance(input.state, dict):
        uid = input.state.get("user_id")
        logger.info(
            "extract_user_id: state.user_id=%s | full state=%s",
            uid,
            input.state,
        )
        if uid:
            return uid
    logger.info(
        "extract_user_id: fallback default_user (state type=%s)",
        type(input.state).__name__,
    )
    return "default_user"
