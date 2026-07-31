"""Bounded recovery and delivery ownership for durable provider controls."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelDeliveryStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.conversation import (
    ExternalChannelOperationDeadline,
)

logger = logging.getLogger(__name__)

_DEFAULT_STALE_THRESHOLD = datetime.timedelta(minutes=2)
_DEFAULT_INTERVAL = datetime.timedelta(seconds=1)
_DEFAULT_LIMIT = 20


@dataclasses.dataclass(frozen=True)
class ExternalChannelProviderControlDrain:
    """Aggregate content-free result of one bounded provider-control drain."""

    stale_unknown: int
    attempted: int


@dataclasses.dataclass(frozen=True)
class ExternalChannelProviderControlService:
    """Recover interrupted controls and attempt committed pending intents."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelWorkRepository,
        Depends(ExternalChannelWorkRepository),
    ]
    action_service: Annotated[
        ExternalChannelActionService,
        Depends(ExternalChannelActionService),
    ]
    stale_threshold: datetime.timedelta = _DEFAULT_STALE_THRESHOLD
    interval: datetime.timedelta = _DEFAULT_INTERVAL
    limit: int = _DEFAULT_LIMIT

    def start(self, shutdown_event: asyncio.Event) -> asyncio.Task[None]:
        """Start the provider-control recovery loop."""
        return asyncio.create_task(self.run(shutdown_event))

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Drain once at startup and periodically until Worker shutdown."""
        while not shutdown_event.is_set():
            try:
                result = await self.drain_once()
                if result.stale_unknown or result.attempted:
                    logger.info(
                        "Drained External Channel provider controls",
                        extra={
                            "stale_unknown": result.stale_unknown,
                            "attempted": result.attempted,
                        },
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("External Channel provider-control drain failed")
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=self.interval.total_seconds(),
                )
                return
            except asyncio.TimeoutError:
                continue

    async def drain_once(
        self,
        *,
        now: datetime.datetime | None = None,
    ) -> ExternalChannelProviderControlDrain:
        """Recover stale claims, then attempt each bounded pending control once."""
        current = now or datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            stale_unknown = (
                await self.repository.recover_stale_provider_control_deliveries(
                    session,
                    stale_before=current - self.stale_threshold,
                    completed_at=current,
                    limit=self.limit,
                )
            )
            delivery_attempt_ids = (
                await self.repository.list_pending_provider_control_delivery_ids(
                    session,
                    limit=self.limit,
                )
            )
            await session.commit()
        attempted = 0
        for delivery_attempt_id in delivery_attempt_ids:
            outcome = await self.action_service.attempt_delivery(delivery_attempt_id)
            if outcome is not None:
                attempted += 1
        return ExternalChannelProviderControlDrain(
            stale_unknown=stale_unknown,
            attempted=attempted,
        )

    async def attempt_delivery(self, delivery_attempt_id: str) -> None:
        """Attempt one committed provider control through the shared fence."""
        await self.action_service.attempt_delivery(delivery_attempt_id)

    async def ensure_delivered(
        self,
        *,
        delivery_attempt_id: str,
        deadline: ExternalChannelOperationDeadline,
    ) -> bool:
        """Synchronously settle one required delivery before mailbox acceptance."""
        while True:
            remaining = deadline.remaining_seconds()
            if remaining <= 0:
                return False
            async with self.session_manager() as session:
                status = await self.repository.get_delivery_status(
                    session,
                    delivery_attempt_id=delivery_attempt_id,
                )
            match status:
                case ExternalChannelDeliveryStatus.DELIVERED:
                    return True
                case ExternalChannelDeliveryStatus.PENDING:
                    try:
                        async with asyncio.timeout(remaining):
                            await self.action_service.attempt_delivery(
                                delivery_attempt_id
                            )
                    except TimeoutError:
                        return False
                case ExternalChannelDeliveryStatus.ATTEMPTING:
                    await asyncio.sleep(min(0.01, remaining))
                case (
                    ExternalChannelDeliveryStatus.FAILED
                    | ExternalChannelDeliveryStatus.UNKNOWN
                    | ExternalChannelDeliveryStatus.NOT_ATTEMPTED
                    | None
                ):
                    return False


def get_external_channel_provider_control_service(
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ],
    repository: Annotated[
        ExternalChannelWorkRepository,
        Depends(ExternalChannelWorkRepository),
    ],
    action_service: Annotated[
        ExternalChannelActionService,
        Depends(ExternalChannelActionService),
    ],
) -> ExternalChannelProviderControlService:
    """Compose provider-control delivery without exposing worker tuning as API input."""
    return ExternalChannelProviderControlService(
        session_manager=session_manager,
        repository=repository,
        action_service=action_service,
    )
