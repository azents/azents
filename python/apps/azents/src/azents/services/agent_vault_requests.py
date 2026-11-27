"""Orchestrate Vault request access and post-commit Session notification."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.broker.broadcast import BaseWebSocketBroadcast
from azents.broker.deps import get_broker
from azents.broker.types import SessionBroker, SessionWakeUp
from azents.broker.websocket_deps import get_websocket_broadcast
from azents.core.vault_request import VaultRequestSubmission
from azents.repos.agent_vault import AgentVaultRepository
from azents.repos.agent_vault_requests import (
    AgentVaultRequestRepository,
    VaultRequestChange,
    VaultRequestScope,
    VaultRequestView,
)
from azents.repos.mailbox.admission import MailboxAdmissionRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VaultRequestInvalidation:
    """Notify existing Session subscribers to refresh authorized request status."""

    broadcast: Annotated[BaseWebSocketBroadcast, Depends(get_websocket_broadcast)]

    async def publish(self, change: VaultRequestChange) -> None:
        """Send identity only after the corresponding database commit."""
        try:
            async with asyncio.timeout(1):
                await self.broadcast.publish(
                    change.session_id,
                    {
                        "type": "vault_request_changed",
                        "session_id": change.session_id,
                        "request_id": change.request_id,
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Vault request status broadcast unavailable",
                extra={
                    "session_id": change.session_id,
                    "request_id": change.request_id,
                },
            )


@dataclass(frozen=True)
class AgentVaultRequestService:
    """Expose value-free request reads and submit to the original Session only."""

    repository: Annotated[
        AgentVaultRequestRepository, Depends(AgentVaultRequestRepository)
    ]
    vault: Annotated[AgentVaultRepository, Depends(AgentVaultRepository)]
    admission: Annotated[
        MailboxAdmissionRepository, Depends(MailboxAdmissionRepository)
    ]
    broker: Annotated[SessionBroker, Depends(get_broker)]
    invalidation: Annotated[VaultRequestInvalidation, Depends(VaultRequestInvalidation)]

    async def read(self, scope: VaultRequestScope, request_id: str) -> VaultRequestView:
        """Read current, authorized request state."""
        return await self.repository.get_view(scope, request_id, vault=self.vault)

    async def submit(
        self, scope: VaultRequestScope, request_id: str, body: VaultRequestSubmission
    ) -> None:
        """Signal once after settlement commits; a missed signal cannot undo it."""
        await self.repository.submit(
            scope, request_id, body, vault=self.vault, admission=self.admission
        )
        try:
            async with asyncio.timeout(3):
                await self.broker.send_message(
                    SessionWakeUp(session_id=scope.session_id)
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Vault request completion committed without a confirmed wake signal",
                extra={"session_id": scope.session_id, "request_id": request_id},
            )
        await self.invalidation.publish(
            VaultRequestChange(scope.session_id, request_id)
        )
