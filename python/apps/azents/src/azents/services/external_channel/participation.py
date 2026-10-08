"""Orchestrate completed participation operations and post-commit replay."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelResponseMode,
    ExternalChannelSetupClaimStatus,
)
from azents.core.external_channel_conversation_data import (
    ExternalChannelConversationLock,
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
    ExternalChannelParticipationLock,
    ExternalChannelParticipationScope,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelIngestionOutcomeKind,
)
from azents.core.external_channel_participation import (
    ExternalChannelLocationSelection,
    ExternalChannelParticipationError,
    ExternalChannelParticipationSettings,
    ExternalChannelParticipationSettingsMutation,
)
from azents.core.external_channel_participation_state import (
    setup_source_from_projection,
)
from azents.repos.external_channel.participation_operations import (
    ExternalChannelParticipationOperations,
)
from azents.services.external_channel.deps import (
    get_external_channel_conversation_lock,
    get_external_channel_participation_lock,
)
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
)


@dataclass
class ExternalChannelParticipationService:
    """Authorize and commit provider-neutral participation settings."""

    operations: Annotated[
        ExternalChannelParticipationOperations,
        Depends(ExternalChannelParticipationOperations),
    ]
    ingestion_replay_service: Annotated[
        ExternalChannelIngestionReplayService,
        Depends(ExternalChannelIngestionReplayService),
    ]
    conversation_lock: Annotated[
        ExternalChannelConversationLock, Depends(get_external_channel_conversation_lock)
    ]
    participation_lock: Annotated[
        ExternalChannelParticipationLock,
        Depends(get_external_channel_participation_lock),
    ]

    async def mutate_parent_settings(
        self,
        *,
        connection_id: str,
        provider_parent_channel_id: str,
        principal_id: str,
        expected_setting_id: str,
        expected_settings_generation: int,
        location: ExternalChannelConversationLocation,
        response_mode: ExternalChannelResponseMode,
        now: datetime.datetime,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelParticipationSettingsMutation:
        """Atomically mutate a parent setting and its concrete Channel binding."""
        conversation_scope = ExternalChannelConversationScope(
            connection_id=connection_id,
            kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
            provider_channel_id=provider_parent_channel_id,
            provider_thread_key=None,
        )
        participation_scope = ExternalChannelParticipationScope(
            connection_id=connection_id,
            provider_parent_channel_id=provider_parent_channel_id,
        )
        async with self.conversation_lock.acquire(
            scope=conversation_scope, deadline=deadline
        ) as conversation_lease:
            await conversation_lease.assert_owned()
            async with self.participation_lock.acquire(
                scope=participation_scope, deadline=deadline
            ) as participation_lease:
                await participation_lease.assert_owned()
                await conversation_lease.assert_owned()
                mutation = await self.operations.mutate_parent_settings(
                    connection_id=connection_id,
                    provider_parent_channel_id=provider_parent_channel_id,
                    principal_id=principal_id,
                    expected_setting_id=expected_setting_id,
                    expected_settings_generation=expected_settings_generation,
                    location=location,
                    response_mode=response_mode,
                    now=now,
                )
        return mutation

    async def mutate_thread_settings(
        self,
        *,
        connection_id: str,
        provider_parent_channel_id: str,
        resource_id: str,
        binding_id: str,
        principal_id: str,
        expected_response_mode: ExternalChannelResponseMode,
        expected_binding_updated_at: datetime.datetime,
        response_mode: ExternalChannelResponseMode,
        now: datetime.datetime,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelParticipationSettingsMutation:
        """Mutate only one exact connected thread binding."""
        conversation_scope = await self.operations.read_thread_scope(
            connection_id=connection_id,
            resource_id=resource_id,
            provider_parent_channel_id=provider_parent_channel_id,
        )
        async with self.conversation_lock.acquire(
            scope=conversation_scope, deadline=deadline
        ) as conversation_lease:
            await conversation_lease.assert_owned()
            mutation = await self.operations.mutate_thread_settings(
                connection_id=connection_id,
                provider_parent_channel_id=provider_parent_channel_id,
                resource_id=resource_id,
                binding_id=binding_id,
                principal_id=principal_id,
                expected_response_mode=expected_response_mode,
                expected_binding_updated_at=expected_binding_updated_at,
                response_mode=response_mode,
                now=now,
            )
        return mutation

    async def select_location(
        self,
        *,
        setup_claim_id: str,
        expected_claim_generation: int,
        expected_source_revision: int,
        location: ExternalChannelConversationLocation,
        configured_by_principal_id: str,
        now: datetime.datetime,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelLocationSelection:
        """Commit one first valid location selection and recover its source."""
        snapshot = await self.operations.read_setup_claim(setup_claim_id)
        if snapshot is None:
            raise ExternalChannelParticipationError(
                "External Channel setup is unavailable."
            )
        source = setup_source_from_projection(snapshot.source_projection)
        conversation_scope = ExternalChannelConversationScope(
            connection_id=snapshot.connection_id,
            kind=source.scope_kind,
            provider_channel_id=source.provider_channel_id,
            provider_thread_key=source.provider_thread_key,
        )
        participation_scope = ExternalChannelParticipationScope(
            connection_id=snapshot.connection_id,
            provider_parent_channel_id=snapshot.provider_parent_channel_id,
        )
        async with self.conversation_lock.acquire(
            scope=conversation_scope, deadline=deadline
        ) as conversation_lease:
            await conversation_lease.assert_owned()
            async with self.participation_lock.acquire(
                scope=participation_scope, deadline=deadline
            ) as participation_lease:
                await participation_lease.assert_owned()
                await conversation_lease.assert_owned()
                committed = await self.operations.commit_location(
                    setup_claim_id=setup_claim_id,
                    expected_claim_generation=expected_claim_generation,
                    expected_source_revision=expected_source_revision,
                    location=location,
                    configured_by_principal_id=configured_by_principal_id,
                    source=source,
                    now=now,
                )
        setting = committed.setting
        claim = committed.claim
        created = committed.created
        if claim.status is ExternalChannelSetupClaimStatus.COMPLETED:
            return ExternalChannelLocationSelection(
                status="already_selected",
                setting=setting,
                claim=claim,
                replay_outcome=None,
            )
        outcome = await self.ingestion_replay_service.replay_setup_claim(
            setup_claim_id=claim.id, deadline=deadline
        )
        if outcome.kind in {
            ExternalChannelIngestionOutcomeKind.ACCEPTED,
            ExternalChannelIngestionOutcomeKind.DUPLICATE,
        }:
            completed = await self.operations.read_setup_claim(claim.id)
            if completed is not None:
                claim = completed
            return ExternalChannelLocationSelection(
                status="selected" if created else "already_selected",
                setting=setting,
                claim=claim,
                replay_outcome=outcome,
            )
        return ExternalChannelLocationSelection(
            status="pending_recovery",
            setting=setting,
            claim=claim,
            replay_outcome=outcome,
        )

    async def resolve_settings(
        self,
        *,
        connection_id: str,
        provider_parent_channel_id: str,
        provider_thread_resource_key: str | None,
        expected_binding_id: str | None,
        principal_id: str,
    ) -> ExternalChannelParticipationSettings:
        """Resolve one authorized settings surface without mutating provider state."""
        return await self.operations.resolve_settings(
            connection_id=connection_id,
            provider_parent_channel_id=provider_parent_channel_id,
            provider_thread_resource_key=provider_thread_resource_key,
            expected_binding_id=expected_binding_id,
            principal_id=principal_id,
        )
