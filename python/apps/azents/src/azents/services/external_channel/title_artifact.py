"""Creation-boundary artifacts for External Channel automatic titles."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelDiscordThreadTitleProvisioningStatus,
    ExternalChannelDiscordThreadTitleStatus,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    ExternalChannelSessionTitleCandidateStatus,
)
from azents.repos.external_channel.data import (
    ExternalChannelDiscordThreadTitleProjection,
    ExternalChannelDiscordThreadTitleProjectionCreate,
    ExternalChannelResource,
    ExternalChannelSessionTitleCandidate,
    ExternalChannelSessionTitleCandidateCreate,
)
from azents.repos.external_channel.title import (
    SUPPORTED_DISCORD_THREAD_TITLE_PROVISIONING_PROTOCOL_VERSION,
    ExternalChannelTitleRepository,
)
from azents.services.external_channel.conversation import DiscordRootThreadObservation
from azents.services.external_channel.discord_delivery import (
    normalize_discord_thread_name,
)


@dataclass(frozen=True)
class ExternalChannelTitleArtifactRequest:
    """Exact immutable creation provenance for title persistence artifacts."""

    connection_id: str
    agent_session_id: str
    binding_id: str
    resource: ExternalChannelResource
    trigger_provider_message_key: str
    provider: ExternalChannelProvider
    provisional_title_source: str | None
    access_request_id: str | None
    discord_root_thread_observation: DiscordRootThreadObservation | None


@dataclass(frozen=True)
class ExternalChannelTitleArtifacts:
    """Durable title artifacts created from one first canonical acceptance."""

    candidate: ExternalChannelSessionTitleCandidate
    projection: ExternalChannelDiscordThreadTitleProjection | None


@dataclass
class ExternalChannelTitleArtifactService:
    """Create idempotent title artifacts at the exact root Session boundary."""

    title_repository: Annotated[
        ExternalChannelTitleRepository,
        Depends(ExternalChannelTitleRepository),
    ]

    async def create(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelTitleArtifactRequest,
    ) -> ExternalChannelTitleArtifacts:
        """Create or verify all title artifacts permitted by exact provenance."""
        provisional_title = _required_provisional_title(
            request.provisional_title_source
        )
        candidate = await self.title_repository.create_session_title_candidate(
            session,
            ExternalChannelSessionTitleCandidateCreate(
                agent_session_id=request.agent_session_id,
                binding_id=request.binding_id,
                trigger_provider_message_key=request.trigger_provider_message_key,
                admission_access_request_id=request.access_request_id,
                admission_provisional_title=provisional_title,
                status=ExternalChannelSessionTitleCandidateStatus.PENDING,
                consumed_event_id=None,
                relinquished_reason=None,
            ),
        )
        projection = await self._create_discord_projection(
            session,
            request=request,
            candidate=candidate,
        )
        return ExternalChannelTitleArtifacts(
            candidate=candidate,
            projection=projection,
        )

    async def create_projection_for_existing_candidate(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelTitleArtifactRequest,
    ) -> ExternalChannelTitleArtifacts | None:
        """Add only an eligible projection to a prior exact creation candidate."""
        candidate = await self.title_repository.get_candidate_by_identity(
            session,
            agent_session_id=request.agent_session_id,
            binding_id=request.binding_id,
            trigger_provider_message_key=request.trigger_provider_message_key,
        )
        if candidate is None:
            return None
        if candidate.admission_access_request_id != request.access_request_id:
            raise ValueError(
                "Session title candidate access provenance does not match."
            )
        projection = await self._create_discord_projection(
            session,
            request=request,
            candidate=candidate,
        )
        return ExternalChannelTitleArtifacts(
            candidate=candidate,
            projection=projection,
        )

    async def _create_discord_projection(
        self,
        session: AsyncSession,
        *,
        request: ExternalChannelTitleArtifactRequest,
        candidate: ExternalChannelSessionTitleCandidate,
    ) -> ExternalChannelDiscordThreadTitleProjection | None:
        """Create the one fail-closed Discord root projection when eligible."""
        observation = request.discord_root_thread_observation
        if candidate.admission_provisional_title is None:
            return None
        if (
            request.provider is not ExternalChannelProvider.DISCORD
            or observation is None
            or not self._qualifies_discord_root(request, observation=observation)
        ):
            return None
        existing = await self.title_repository.get_projection_by_resource_id(
            session,
            resource_id=request.resource.id,
        )
        if existing is not None:
            self._verify_existing_projection(
                existing,
                request=request,
                candidate=candidate,
                observation=observation,
            )
            return existing
        return await self.title_repository.create_discord_thread_title_projection(
            session,
            ExternalChannelDiscordThreadTitleProjectionCreate(
                resource_id=request.resource.id,
                binding_id=request.binding_id,
                agent_session_id=request.agent_session_id,
                session_title_candidate_id=candidate.id,
                provisioning_protocol_version=(
                    SUPPORTED_DISCORD_THREAD_TITLE_PROVISIONING_PROTOCOL_VERSION
                ),
                requested_provisional_title=candidate.admission_provisional_title,
                admission_connection_id=request.connection_id,
                admission_guild_id=observation.guild_id,
                admission_parent_channel_id=observation.parent_channel_id,
                admission_root_message_id=observation.root_message_id,
                admission_trigger_provider_message_key=(
                    observation.trigger_provider_message_key
                ),
                admission_observation_status=observation.status,
                admission_root_has_thread=observation.root_has_thread,
                admission_observed_thread_channel_id=(
                    None
                    if observation.thread is None
                    else observation.thread.channel_id
                ),
                admission_observed_at=observation.observed_at,
                provisioning_status=(
                    ExternalChannelDiscordThreadTitleProvisioningStatus.PENDING
                ),
                preflight_absent_at=None,
                thread_channel_id=None,
                expected_provisional_title=None,
                provisioning_proof_kind=None,
                provision_attempt_count=0,
                provision_next_attempt_at=None,
                provision_claimed_at=None,
                provision_failure_kind=None,
                provision_failure_summary=None,
                provision_completed_at=None,
                desired_title=None,
                title_generation_event_id=None,
                title_status=ExternalChannelDiscordThreadTitleStatus.WAITING,
                title_attempt_count=0,
                title_next_attempt_at=None,
                title_claimed_at=None,
                title_failure_kind=None,
                title_failure_summary=None,
                title_completed_at=None,
            ),
        )

    @staticmethod
    def _qualifies_discord_root(
        request: ExternalChannelTitleArtifactRequest,
        *,
        observation: DiscordRootThreadObservation,
    ) -> bool:
        """Require exact root provenance and no canonical delivery target."""
        labels = request.resource.labels or {}
        delivery_channel_id = labels.get("delivery_channel_id")
        return (
            request.resource.resource_type is ExternalChannelResourceType.THREAD
            and request.resource.connection_id == request.connection_id
            and labels.get("provider") == ExternalChannelProvider.DISCORD.value
            and labels.get("guild_id") == observation.guild_id
            and labels.get("parent_channel_id") == observation.parent_channel_id
            and labels.get("root_message_id") == observation.root_message_id
            and observation.trigger_provider_message_key
            == request.trigger_provider_message_key
            and delivery_channel_id is None
        )

    @staticmethod
    def _verify_existing_projection(
        projection: ExternalChannelDiscordThreadTitleProjection,
        *,
        request: ExternalChannelTitleArtifactRequest,
        candidate: ExternalChannelSessionTitleCandidate,
        observation: DiscordRootThreadObservation,
    ) -> None:
        """Verify a duplicate admission without comparing a fresh observation time."""
        if (
            projection.binding_id != request.binding_id
            or projection.agent_session_id != request.agent_session_id
            or projection.session_title_candidate_id != candidate.id
            or projection.requested_provisional_title
            != candidate.admission_provisional_title
            or projection.admission_connection_id != request.connection_id
            or projection.admission_guild_id != observation.guild_id
            or projection.admission_parent_channel_id != observation.parent_channel_id
            or projection.admission_root_message_id != observation.root_message_id
            or projection.admission_trigger_provider_message_key
            != observation.trigger_provider_message_key
            or projection.admission_observation_status is not observation.status
            or projection.admission_root_has_thread != observation.root_has_thread
            or projection.admission_observed_thread_channel_id
            != (None if observation.thread is None else observation.thread.channel_id)
        ):
            raise ValueError("Discord title projection identity does not match.")


def _required_provisional_title(source: str | None) -> str:
    """Normalize one admission-time Agent title or reject an ungrounded fallback."""
    if source is None or not source.strip():
        raise ValueError("Discord provisional title source must not be blank.")
    return normalize_discord_thread_name(source)
