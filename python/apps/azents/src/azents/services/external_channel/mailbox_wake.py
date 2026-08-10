"""Canonical-mailbox External Channel Session wake dispatch."""

import asyncio
import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.deps import get_broker
from azents.broker.types import SessionBroker, SessionWakeUp
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.services.external_channel.conversation import (
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelWakeDispatchResult,
    ExternalChannelWakeDispatchUnavailable,
)
from azents.services.external_channel.ingress_test_control import (
    ExternalChannelIngressTestControl,
    get_external_channel_ingress_test_control,
)
from azents.services.mailbox import MailboxService


@dataclasses.dataclass
class ExternalChannelMailboxWakeDispatcher:
    """Wake a Session while its accepted canonical mailbox item remains pending."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    mailbox_service: Annotated[MailboxService, Depends(MailboxService)]
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
        async with self.session_manager() as session:
            mailbox_item = await self.mailbox_service.get_by_id(
                session,
                buffer_id=mailbox_item_id,
            )
            if mailbox_item is None:
                await session.commit()
                return "already_dispatched"
            if mailbox_item.session_id != session_id:
                raise ValueError("External Channel mailbox wake ownership is invalid.")
            await session.commit()
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
