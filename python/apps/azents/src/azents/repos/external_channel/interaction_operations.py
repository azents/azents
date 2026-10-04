"""Completed interaction processing and selector ownership operations."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
)
from azents.core.external_channel_interaction import (
    InteractionSelectorMetadata,
    ProcessingInteractionScope,
    SelectorOwners,
    SelectorScope,
    SelectorSubmissionScope,
)
from azents.core.external_channel_selector_state import selector_state_from_interaction
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelInteraction,
    ExternalChannelSetupClaim,
)
from azents.repos.external_channel.repository import ExternalChannelRepository


@dataclass
class ExternalChannelInteractionOperations:
    """Complete processing-owner and selector scope database observations."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def load_processing_interaction(
        self, interaction_id: str
    ) -> ProcessingInteractionScope:
        """Reload one authenticated processing interaction and its connection."""
        async with self.read_session_manager() as session:
            interaction = await self._read_interaction(
                session, interaction_id=interaction_id
            )
            if (
                interaction is None
                or interaction.status is not ExternalChannelInteractionStatus.PROCESSING
                or interaction.principal_id is None
            ):
                raise ValueError("Slack interaction is unavailable.")
            configuration = await self.repository.get_connection_configuration(
                session, connection_id=interaction.connection_id
            )
            if configuration is None or configuration.status not in {
                ExternalChannelConnectionStatus.ACTIVE,
                ExternalChannelConnectionStatus.DEGRADED,
            }:
                raise ValueError("Slack interaction connection is unavailable.")
            return ProcessingInteractionScope(
                interaction=interaction, configuration=configuration
            )

    async def load_scope(
        self,
        interaction_id: str,
        *,
        selector_interaction_id: str | None,
        now: datetime.datetime,
    ) -> SelectorScope:
        """Reload trusted interaction and selector owners before provider I/O."""
        async with self.read_session_manager() as session:
            interaction = await self._read_interaction(
                session, interaction_id=interaction_id
            )
            if (
                interaction is None
                or interaction.status is not ExternalChannelInteractionStatus.PROCESSING
                or interaction.principal_id is None
                or (
                    interaction.interaction_type
                    not in {
                        ExternalChannelInteractionType.SHORTCUT,
                        ExternalChannelInteractionType.BLOCK_ACTION,
                    }
                )
            ):
                raise ValueError("Slack selector interaction is unavailable.")
            selector_id = selector_interaction_id or interaction.id
            selector = await self._read_interaction(session, interaction_id=selector_id)
            owners = await self._selector_owners(
                session,
                selector=selector,
                principal_id=interaction.principal_id,
                now=now,
            )
            assert selector is not None
            return SelectorScope(
                interaction=interaction,
                configuration=owners.configuration,
                resource=owners.resource,
                selector=selector,
            )

    async def load_submission_scope(
        self,
        interaction_id: str,
        *,
        metadata: InteractionSelectorMetadata,
        now: datetime.datetime,
    ) -> SelectorSubmissionScope:
        """Join one transient submission to its signed selector interaction."""
        async with self.read_session_manager() as session:
            interaction = await self._read_interaction(
                session, interaction_id=interaction_id
            )
            if (
                interaction is None
                or interaction.status is not ExternalChannelInteractionStatus.PROCESSING
                or interaction.principal_id is None
                or (interaction.principal_id != metadata.principal_id)
                or (
                    interaction.interaction_type
                    not in {
                        ExternalChannelInteractionType.BLOCK_ACTION,
                        ExternalChannelInteractionType.VIEW_SUBMISSION,
                    }
                )
            ):
                raise ValueError("Slack selector submission is unavailable.")
            selector = await self._read_interaction(
                session, interaction_id=metadata.selector_interaction_id
            )
            owners = await self._selector_owners(
                session,
                selector=selector,
                principal_id=interaction.principal_id,
                now=now,
            )
            assert selector is not None
            opened = await self._read_interaction(
                session, interaction_id=metadata.interaction_id
            )
            if (
                opened is None
                or opened.connection_id != owners.configuration.id
                or opened.principal_id != interaction.principal_id
                or (
                    opened.status
                    not in {
                        ExternalChannelInteractionStatus.PROCESSING,
                        ExternalChannelInteractionStatus.COMPLETED,
                    }
                )
            ):
                raise ValueError("Slack selector modal is unavailable.")
            return SelectorSubmissionScope(
                interaction=interaction,
                configuration=owners.configuration,
                resource=owners.resource,
                selector=selector,
                metadata=metadata,
            )

    async def _selector_owners(
        self,
        session: ReadSession,
        *,
        selector: ExternalChannelInteraction | None,
        principal_id: str,
        now: datetime.datetime,
    ) -> SelectorOwners:
        if (
            selector is None
            or selector.principal_id != principal_id
            or selector.expires_at <= now
            or (
                selector.status
                in {
                    ExternalChannelInteractionStatus.EXPIRED,
                    ExternalChannelInteractionStatus.REJECTED,
                    ExternalChannelInteractionStatus.FAILED,
                }
            )
        ):
            raise ValueError("Slack selector interaction is unavailable.")
        state = selector_state_from_interaction(selector)
        if state.principal_id != principal_id:
            raise ValueError("Slack selector interaction is unavailable.")
        configuration = await self.repository.get_connection_configuration(
            session, connection_id=state.connection_id
        )
        resource = await self.repository.get_resource(
            session, resource_id=state.resource_id
        )
        if (
            configuration is None
            or configuration.status
            not in {
                ExternalChannelConnectionStatus.ACTIVE,
                ExternalChannelConnectionStatus.DEGRADED,
            }
            or configuration.app_mode is not ExternalChannelAppMode.MULTI
            or (resource is None)
            or (resource.connection_id != configuration.id)
        ):
            raise ValueError("Slack selector interaction is unavailable.")
        return SelectorOwners(configuration=configuration, resource=resource)

    async def read_setup_claim(self, claim_id: str) -> ExternalChannelSetupClaim | None:
        """Finish an independent claim read before service orchestration."""
        async with self.read_session_manager() as session:
            return await self.repository.get_setup_claim(session, claim_id=claim_id)

    async def validate_settings_origin(
        self,
        *,
        origin_interaction_id: str,
        interaction: ExternalChannelInteraction,
        configuration: ExternalChannelConnectionConfiguration,
    ) -> None:
        """Bind a new submission to the current authorized origin snapshot."""
        async with self.read_session_manager() as session:
            row = await session.read_session.scalar(
                sa.select(RDBExternalChannelInteraction).where(
                    RDBExternalChannelInteraction.id == origin_interaction_id
                )
            )
            origin = (
                ExternalChannelInteraction.model_validate(row)
                if row is not None
                else None
            )
            if (
                origin is None
                or origin.id == interaction.id
                or origin.connection_id != configuration.id
                or (origin.principal_id != interaction.principal_id)
                or (
                    origin.status
                    not in {
                        ExternalChannelInteractionStatus.PROCESSING,
                        ExternalChannelInteractionStatus.COMPLETED,
                    }
                )
            ):
                raise ValueError("Slack settings submission scope is unavailable.")

    async def _read_interaction(
        self, session: ReadSession, *, interaction_id: str
    ) -> ExternalChannelInteraction | None:
        """Read current interaction through the repository's plain observation API."""
        return await self.repository.get_interaction(
            session, interaction_id=interaction_id
        )
