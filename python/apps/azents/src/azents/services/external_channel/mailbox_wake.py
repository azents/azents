"""Canonical-mailbox External Channel Session wake dispatch."""

import asyncio
import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from redis.exceptions import RedisError

from azents.broker.deps import get_broker
from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.external_channel_conversation_data import (
    ExternalChannelOperationDeadline,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelWakeDispatchResult,
    ExternalChannelWakeDispatchUnavailable,
)
from azents.repos.external_channel.mailbox_wake import (
    ExternalChannelMailboxWakeRepository,
)
from azents.services.external_channel.ingress_test_control import (
    ExternalChannelIngressTestControl,
    get_external_channel_ingress_test_control,
)


@dataclasses.dataclass
class ExternalChannelMailboxWakeDispatcher:
    """Wake a Session while its accepted canonical mailbox item remains pending."""

    operations: Annotated[
        ExternalChannelMailboxWakeRepository,
        Depends(ExternalChannelMailboxWakeRepository),
    ]
    broker: Annotated[SessionBroker, Depends(get_broker)]
    test_control: Annotated[
        ExternalChannelIngressTestControl,
        Depends(get_external_channel_ingress_test_control),
    ]

    async def dispatch(
        self,
        *,
        mailbox_item_id: str,
        session_id: str,
        now: datetime.datetime,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelWakeDispatchResult:
        """Send a recoverable wake using the mailbox item as durable identity."""
        del now
        if self.test_control.consume_wake_failure(session_id=session_id):
            raise ExternalChannelWakeDispatchUnavailable(
                "Testenv injected External Channel wake failure."
            )
        pending = await self.operations.prepare_dispatch(
            mailbox_item_id=mailbox_item_id, session_id=session_id
        )
        if not pending:
            return "already_dispatched"
        try:
            async with asyncio.timeout(deadline.remaining_seconds()):
                await self.broker.send_message(SessionWakeUp(session_id=session_id))
        except asyncio.CancelledError:
            raise
        except (RedisError, OSError, TimeoutError) as error:
            raise ExternalChannelWakeDispatchUnavailable(
                "External Channel Session wake dispatch is unavailable."
            ) from error
        return "dispatched"
