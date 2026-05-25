import logging

from fastapi import APIRouter, Query, HTTPException

from src.dto.threads import ThreadListResponse, ThreadResponse, ThreadUpdateRequest
from src.services.session import AdkSessionService

logger = logging.getLogger(__name__)


def create_thread_router(session_service: AdkSessionService) -> APIRouter:
    """Factory that builds the ``/api/threads`` CRUD router.

    All endpoints accept either a ``user_id`` query-param **or** the
    ``X-User-Id`` request header (provisional auth-free routing).
    """

    router = APIRouter(prefix="/api")

    async def _resolve_user_id(
        user_id: str = Query(None),
    ) -> str:
        """Normalise user identity from query-param or header."""
        if not user_id:
            raise HTTPException(
                status_code=400,
                detail="user_id query parameter is required",
            )
        return user_id

    @router.get("/threads", response_model=ThreadListResponse)
    async def list_threads(user_id: str = Query(...)):
        threads = await session_service.list_threads(user_id)
        return ThreadListResponse(
            threads=[
                    ThreadResponse(
                        id=t["id"],
                        title=t["title"],
                        updated_at=t["updated_at"],
                        state=t.get("state"),
                    )
                for t in threads
            ]
        )

    @router.patch("/threads/{thread_id}")
    async def update_thread(
        thread_id: str,
        body: ThreadUpdateRequest,
        user_id: str = Query(...),
    ):
        updates = body.model_dump(exclude_none=True)
        if not updates:
            return {"success": True}
        success = await session_service.update_thread_metadata(
            thread_id, user_id, updates
        )
        if not success:
            raise HTTPException(status_code=404, detail="Thread not found")
        return {"success": True}

    @router.delete("/threads/{thread_id}")
    async def delete_thread(
        thread_id: str,
        user_id: str = Query(...),
    ):
        success = await session_service.delete_thread(thread_id, user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Thread not found")
        return {"success": True}

    return router
