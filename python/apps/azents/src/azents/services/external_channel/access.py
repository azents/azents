"""External Channel access decision orchestration and provider replay."""

import datetime
import logging
from dataclasses import dataclass
from typing import Annotated, assert_never

from fastapi import Depends

from azents.core.enums import (
    ExternalChannelAccessGrantScope,
)
from azents.core.external_channel_access import (
    ExternalChannelAccessDecisionError,
    ExternalChannelAllowedAccess,
    ExternalChannelRemovedBlock,
    ExternalChannelResolvedAccess,
    ExternalChannelRevokedAccess,
)
from azents.core.external_channel_conversation_preparation import (
    ExternalChannelConversationProvisioningError,
)
from azents.core.external_channel_ingestion import ExternalChannelIngestionOutcomeKind
from azents.repos.external_channel.access_operations import (
    ExternalChannelAccessOperations,
)
from azents.services.external_channel.conversation_provisioning import (
    ExternalChannelConversationProvisioningService,
)
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
    external_channel_replay_deadline,
)

logger = logging.getLogger(__name__)


@dataclass
class ExternalChannelAccessService:
    """Prepare providers, commit repository decisions, then replay external work."""

    operations: Annotated[
        ExternalChannelAccessOperations, Depends(ExternalChannelAccessOperations)
    ]
    conversation_provisioning: Annotated[
        ExternalChannelConversationProvisioningService,
        Depends(ExternalChannelConversationProvisioningService),
    ]
    ingestion_replay_service: Annotated[
        ExternalChannelIngestionReplayService,
        Depends(ExternalChannelIngestionReplayService),
    ]

    async def allow(
        self,
        *,
        access_request_id: str,
        scope: ExternalChannelAccessGrantScope,
        decided_by_user_id: str,
        decision_summary: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelAllowedAccess:
        target = await self.operations.prepare_allowed_target(
            access_request_id=access_request_id, now=now
        )
        provider_preparation = None
        if target is not None:
            try:
                provider_preparation = await self.conversation_provisioning.prepare(
                    connection_id=target.connection_id,
                    target_resource_id=target.resource_id,
                )
            except ExternalChannelConversationProvisioningError as error:
                raise ExternalChannelAccessDecisionError(
                    "The external conversation could not be prepared."
                ) from error
        committed = await self.operations.allow(
            access_request_id=access_request_id,
            scope=scope,
            decided_by_user_id=decided_by_user_id,
            decision_summary=decision_summary,
            now=now,
            provider_preparation=provider_preparation,
        )
        if committed.provider_event_type is not None:
            assert committed.provider is not None
            logger.info(
                "Created External Channel AgentSession",
                extra={
                    "external_channel_provider": committed.provider.value,
                    "provider_event_type": committed.provider_event_type,
                },
            )
        if committed.replay_request_id is not None:
            await self._replay_allowed_request(
                access_request_id=committed.replay_request_id,
                now=now,
                initial_title_eligible=committed.initial_title_eligible,
            )
        return committed.result

    async def _replay_allowed_request(
        self,
        *,
        access_request_id: str,
        now: datetime.datetime,
        initial_title_eligible: bool,
    ) -> None:
        """Resume one committed typed Allow without reverting its decision."""
        outcome = await self.ingestion_replay_service.replay_access_allow(
            access_request_id=access_request_id,
            deadline=external_channel_replay_deadline(now=now),
            initial_title_eligible=initial_title_eligible,
        )
        match outcome.kind:
            case (
                ExternalChannelIngestionOutcomeKind.ACCEPTED
                | ExternalChannelIngestionOutcomeKind.DUPLICATE
            ):
                return
            case (
                ExternalChannelIngestionOutcomeKind.AWAITING_SELECTION
                | ExternalChannelIngestionOutcomeKind.AWAITING_ACCESS
                | ExternalChannelIngestionOutcomeKind.IGNORED
                | ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
                | ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION
            ):
                raise ExternalChannelAccessDecisionError(
                    "The allowed External Channel invocation could not be resumed."
                )
            case _ as unreachable:
                assert_never(unreachable)

    async def deny(
        self,
        *,
        access_request_id: str,
        decided_by_user_id: str,
        decision_summary: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelResolvedAccess:
        """Sequence one completed repository-owned policy decision."""
        return await self.operations.deny(
            access_request_id=access_request_id,
            decided_by_user_id=decided_by_user_id,
            decision_summary=decision_summary,
            now=now,
        )

    async def block(
        self,
        *,
        access_request_id: str,
        decided_by_user_id: str,
        decision_summary: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelResolvedAccess:
        """Sequence one completed repository-owned policy decision."""
        return await self.operations.block(
            access_request_id=access_request_id,
            decided_by_user_id=decided_by_user_id,
            decision_summary=decision_summary,
            now=now,
        )

    async def revoke_grant(
        self,
        *,
        grant_id: str,
    ) -> ExternalChannelRevokedAccess:
        """Sequence one completed repository-owned policy decision."""
        return await self.operations.revoke_grant(grant_id=grant_id)

    async def remove_block(
        self,
        *,
        block_id: str,
        removed_by_user_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelRemovedBlock:
        """Sequence one completed repository-owned policy decision."""
        return await self.operations.remove_block(
            block_id=block_id, removed_by_user_id=removed_by_user_id, now=now
        )
