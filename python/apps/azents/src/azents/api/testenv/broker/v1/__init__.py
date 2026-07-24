"""Broker devtools v1 API (Testenv).

Provides an endpoint that directly injects ``SessionWakeUp`` messages into
the broker. Because it passes through the real Redis to Engine pipeline, it can
verify the engine activity tracking branch live.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from azents.broker.deps import get_broker
from azents.broker.types import SessionBroker, SessionWakeUp
from azents.utils.fastapi.route import RouteMounter

logger = logging.getLogger(__name__)

router = APIRouter()


class InjectResumeRequest(BaseModel):
    """RESUME message injection request."""

    model_config = ConfigDict(extra="forbid")

    session_id: str


class InjectResumeResponse(BaseModel):
    """RESUME message injection response."""

    ok: bool


@router.post("/inject-resume")
async def inject_resume(
    body: InjectResumeRequest,
    broker: Annotated[SessionBroker, Depends(get_broker)],
) -> InjectResumeResponse:
    """Inject a ``SessionWakeUp`` message into the broker.

    It passes through the real Redis LIST to AgentWorker.receive_messages() path,
    so it can verify engine wake-up branch behavior.
    """
    logger.info(
        "Testenv: injecting session wake-up",
        extra={"session_id": body.session_id},
    )
    message = SessionWakeUp(session_id=body.session_id)
    await broker.send_message(message)
    return InjectResumeResponse(ok=True)


def mount(mounter: RouteMounter) -> None:
    """Mount Broker devtools v1 routes."""
    mounter(
        router,
        prefix="/broker/v1",
        tag="Broker v1",
        description="Broker devtools (session wake-up injection)",
    )
