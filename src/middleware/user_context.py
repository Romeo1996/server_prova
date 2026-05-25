from fastapi import Request
from ag_ui.core import RunAgentInput


async def extract_user_context(
    request: Request, input_data: RunAgentInput
) -> dict:
    """Extract X-User-Id from request headers into AG-UI session state.

    Called by add_adk_fastapi_endpoint's extract_state_from_request pipeline.
    The returned dict is merged into input_data.state before agent.run().
    """
    user_id = request.headers.get("x-user-id")
    if not user_id:
        return {}
    return {"user_id": user_id}


def extract_user_id(input: RunAgentInput) -> str:
    """Read user_id from AG-UI state (injected by extract_user_context).

    Used as ADKAgent's user_id_extractor. Falls back to 'default_user'.
    """
    if isinstance(input.state, dict):
        user_id = input.state.get("user_id")
        if user_id:
            return user_id
    return "default_user"
