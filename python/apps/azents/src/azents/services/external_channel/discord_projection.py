"""GET-first Discord initial-title projection provisioning reconciliation."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelDiscordThreadObservationStatus,
    ExternalChannelDiscordThreadTitleProofKind,
    ExternalChannelDiscordThreadTitleProvisioningStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelSessionTitleCandidateStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelDiscordThreadTitleProjection,
    ExternalChannelResource,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.title import (
    SUPPORTED_DISCORD_THREAD_TITLE_PROVISIONING_PROTOCOL_VERSION,
    ExternalChannelTitleRepository,
)
from azents.services.external_channel.channel_action import (
    get_discord_delivery_client,
)
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import DiscordConnectionCredentials
from azents.services.external_channel.discord_delivery import (
    DiscordDeliveryClient,
    DiscordThreadProvisioningResult,
)

_DEFAULT_LIMIT = 20
_DEFAULT_STALE_THRESHOLD = datetime.timedelta(minutes=2)
_MAX_RETRY_SECONDS = 300


@dataclass(frozen=True)
class DiscordProjectionProvisioningAuthority:
    """Current credential and exact identity authority for one projection claim."""

    bot_token: str
    bot_user_id: str
    delivery_channel_id: str | None


@dataclass(frozen=True)
class DiscordProjectionProvisioningDrain:
    """Content-free bounded reconciliation outcome counts."""

    claimed: int
    ready: int
    unmanaged: int
    retried: int
    failed: int


@dataclass
class DiscordProjectionAuthorityLoader:
    """Revalidate projection ownership without using mutable delivery inference."""

    external_channel_repository: ExternalChannelRepository
    agent_repository: AgentRepository
    agent_session_repository: AgentSessionRepository
    title_repository: ExternalChannelTitleRepository
    credentials_codec: ExternalChannelCredentialsCodec

    async def load(
        self,
        session: AsyncSession,
        *,
        projection: ExternalChannelDiscordThreadTitleProjection,
    ) -> DiscordProjectionProvisioningAuthority | None:
        """Return current complete provider authority or fail closed."""
        if (
            projection.provisioning_protocol_version
            != SUPPORTED_DISCORD_THREAD_TITLE_PROVISIONING_PROTOCOL_VERSION
        ):
            return None
        connection = (
            await self.external_channel_repository.get_connection_configuration(
                session,
                connection_id=projection.admission_connection_id,
            )
        )
        resource = await self.external_channel_repository.get_resource(
            session,
            resource_id=projection.resource_id,
        )
        binding = await self.external_channel_repository.get_binding(
            session,
            binding_id=projection.binding_id,
        )
        candidate = await self.title_repository.get_candidate_by_identity(
            session,
            agent_session_id=projection.agent_session_id,
            binding_id=projection.binding_id,
            trigger_provider_message_key=projection.admission_trigger_provider_message_key,
        )
        if (
            connection is None
            or resource is None
            or not _connection_matches_projection(connection, projection)
            or not _resource_matches_projection(resource, projection)
            or binding is None
            or binding.resource_id != projection.resource_id
            or binding.agent_session_id != projection.agent_session_id
            or binding.disconnected_at is not None
            or candidate is None
            or candidate.id != projection.session_title_candidate_id
            or candidate.admission_provisional_title
            != projection.requested_provisional_title
            or candidate.status
            not in {
                ExternalChannelSessionTitleCandidateStatus.PENDING,
                ExternalChannelSessionTitleCandidateStatus.CONSUMED,
            }
        ):
            return None
        route = await self.external_channel_repository.get_agent_route(
            session,
            route_id=binding.route_id,
        )
        agent_session = await self.agent_session_repository.get_by_id(
            session,
            projection.agent_session_id,
        )
        if (
            route is None
            or agent_session is None
            or agent_session.status is not AgentSessionStatus.ACTIVE
            or agent_session.stop_requested_at is not None
            or agent_session.ended_at is not None
            or route.connection_id != connection.id
            or route.agent_id != agent_session.agent_id
            or route.connection_app_mode is not connection.app_mode
            or route.catalog_status is not ExternalChannelRouteCatalogStatus.AVAILABLE
        ):
            return None
        if (
            connection.encrypted_credentials is None
            or connection.provider_bot_user_id is None
        ):
            return None
        agent = await self.agent_repository.get_by_id(session, agent_session.agent_id)
        if agent is None or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE:
            return None
        try:
            credentials = self.credentials_codec.decrypt(
                connection.encrypted_credentials
            )
        except ValueError:
            return None
        if not isinstance(credentials, DiscordConnectionCredentials):
            return None
        return DiscordProjectionProvisioningAuthority(
            bot_token=credentials.bot_token,
            bot_user_id=connection.provider_bot_user_id,
            delivery_channel_id=_delivery_channel_id(resource),
        )


@dataclass
class DiscordProjectionReconciliationService:
    """Reconcile title-projection thread provisioning without gating delivery."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    title_repository: Annotated[
        ExternalChannelTitleRepository,
        Depends(ExternalChannelTitleRepository),
    ]
    authority_loader: DiscordProjectionAuthorityLoader
    discord_client: Annotated[
        DiscordDeliveryClient,
        Depends(get_discord_delivery_client),
    ]
    stale_threshold: datetime.timedelta = _DEFAULT_STALE_THRESHOLD
    limit: int = _DEFAULT_LIMIT

    async def drain_once(
        self,
        *,
        now: datetime.datetime | None = None,
    ) -> DiscordProjectionProvisioningDrain:
        """Claim and reconcile one bounded batch of due projection controls."""
        current = now or datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            claimed = await self.title_repository.claim_due_provisioning(
                session,
                now=current,
                stale_before=current - self.stale_threshold,
                limit=self.limit,
            )
            await session.commit()
        outcomes = [
            await self._reconcile(projection, now=current) for projection in claimed
        ]
        return DiscordProjectionProvisioningDrain(
            claimed=len(claimed),
            ready=sum(outcome == "ready" for outcome in outcomes),
            unmanaged=sum(outcome == "unmanaged" for outcome in outcomes),
            retried=sum(outcome == "retry" for outcome in outcomes),
            failed=sum(outcome == "failed" for outcome in outcomes),
        )

    async def _reconcile(
        self,
        projection: ExternalChannelDiscordThreadTitleProjection,
        *,
        now: datetime.datetime,
    ) -> str:
        """Perform one GET-first settlement for one exact projection claim."""
        if (
            projection.provisioning_protocol_version
            != SUPPORTED_DISCORD_THREAD_TITLE_PROVISIONING_PROTOCOL_VERSION
        ):
            # Current Workers must never mutate a projection protocol they do not own.
            # The durable claim query excludes these rows; this also guards stale
            # callers.
            return "skipped"
        authority = await self._load_authority(projection)
        if authority is None:
            return await self._fail(
                projection,
                now=now,
                failure_kind="authority_revoked",
                failure_summary="Discord projection authority is no longer current.",
            )
        read = await self.discord_client.read_root_thread(
            bot_token=authority.bot_token,
            guild_id=projection.admission_guild_id,
            parent_channel_id=projection.admission_parent_channel_id,
            root_message_id=projection.admission_root_message_id,
        )
        if read.status == "present":
            return await self._settle_existing(
                projection,
                authority=authority,
                result=read,
                now=now,
                # A prior durable absence preflight fences a crash/ambiguous POST.
                # On a later GET-first drain, exact Bot/name proof is direct recovery;
                # never POST again while that thread is already present.
                direct=projection.preflight_absent_at is not None,
            )
        if read.status == "failed":
            return await self._fail_result(projection, result=read, now=now)
        if read.status == "unknown":
            return await self._retry_result(projection, result=read, now=now)

        preflight = await self._persist_preflight(projection, now=now)
        if preflight != "persisted":
            return preflight
        authority = await self._load_authority(projection)
        if authority is None:
            return await self._fail(
                projection,
                now=now,
                failure_kind="authority_revoked",
                failure_summary="Discord projection authority is no longer current.",
            )
        created = await self.discord_client.create_root_thread(
            bot_token=authority.bot_token,
            guild_id=projection.admission_guild_id,
            parent_channel_id=projection.admission_parent_channel_id,
            root_message_id=projection.admission_root_message_id,
            requested_provisional_title=projection.requested_provisional_title,
        )
        if created.status == "present":
            return await self._settle_existing(
                projection,
                authority=authority,
                result=created,
                now=now,
                direct=True,
            )
        if created.status == "failed":
            return await self._fail_result(projection, result=created, now=now)

        reconciled = await self.discord_client.read_root_thread(
            bot_token=authority.bot_token,
            guild_id=projection.admission_guild_id,
            parent_channel_id=projection.admission_parent_channel_id,
            root_message_id=projection.admission_root_message_id,
        )
        if reconciled.status == "present":
            return await self._settle_existing(
                projection,
                authority=authority,
                result=reconciled,
                now=now,
                direct=True,
            )
        if reconciled.status == "failed":
            return await self._fail_result(projection, result=reconciled, now=now)
        return await self._retry_result(projection, result=reconciled, now=now)

    async def _settle_existing(
        self,
        projection: ExternalChannelDiscordThreadTitleProjection,
        *,
        authority: DiscordProjectionProvisioningAuthority,
        result: DiscordThreadProvisioningResult,
        now: datetime.datetime,
        direct: bool,
    ) -> str:
        """Settle owned proof or preserve a usable unmanaged provider thread."""
        thread_channel_id = result.thread_channel_id
        if thread_channel_id is None:
            return await self._retry_result(projection, result=result, now=now)
        proof_valid = _thread_proof_matches(
            result,
            projection=projection,
            authority=authority,
        )
        adopted = (
            projection.admission_observation_status
            is ExternalChannelDiscordThreadObservationStatus.THREAD_ABSENT
            and authority.delivery_channel_id in {None, thread_channel_id}
            and proof_valid
            and adoption_created_after_admission(projection, result=result)
        )
        if direct and proof_valid:
            proof_kind = ExternalChannelDiscordThreadTitleProofKind.DIRECT
        elif adopted:
            proof_kind = ExternalChannelDiscordThreadTitleProofKind.ADOPTED
        else:
            return await self._settle_unmanaged(
                projection,
                delivery_channel_id=thread_channel_id,
                now=now,
                reason="provider_thread_not_proven",
            )
        async with self.session_manager() as session:
            current_authority = await self.authority_loader.load(
                session,
                projection=projection,
            )
            if (
                current_authority is None
                or current_authority.bot_user_id != authority.bot_user_id
            ):
                failed = await (
                    self.title_repository.fail_provisioning_and_relinquish_title(
                        session,
                        projection_id=projection.id,
                        expected_provision_attempt_count=(
                            projection.provision_attempt_count
                        ),
                        expected_provision_claimed_at=_claimed_at(projection),
                        failure_kind="authority_revoked",
                        failure_summary=(
                            "Discord projection authority is no longer current."
                        ),
                        now=now,
                    )
                )
                await session.commit()
                return "failed" if failed is not None else "lost"
            settled = await self.title_repository.settle_provisioning_ready(
                session,
                projection_id=projection.id,
                expected_provision_attempt_count=projection.provision_attempt_count,
                expected_provision_claimed_at=_claimed_at(projection),
                delivery_channel_id=thread_channel_id,
                thread_channel_id=thread_channel_id,
                expected_provisional_title=projection.requested_provisional_title,
                proof_kind=proof_kind,
                now=now,
            )
            await session.commit()
        return _durable_settlement_outcome(settled)

    async def _persist_preflight(
        self,
        projection: ExternalChannelDiscordThreadTitleProjection,
        *,
        now: datetime.datetime,
    ) -> str:
        """Durably fence exact absence before one projection-owned POST."""
        async with self.session_manager() as session:
            authority = await self.authority_loader.load(
                session,
                projection=projection,
            )
            if authority is None:
                failed = await (
                    self.title_repository.fail_provisioning_and_relinquish_title(
                        session,
                        projection_id=projection.id,
                        expected_provision_attempt_count=(
                            projection.provision_attempt_count
                        ),
                        expected_provision_claimed_at=_claimed_at(projection),
                        failure_kind="authority_revoked",
                        failure_summary=(
                            "Discord projection authority is no longer current."
                        ),
                        now=now,
                    )
                )
                await session.commit()
                return "failed" if failed is not None else "lost"
            settled = await self.title_repository.persist_provisioning_preflight(
                session,
                projection_id=projection.id,
                expected_provision_attempt_count=projection.provision_attempt_count,
                expected_provision_claimed_at=_claimed_at(projection),
                observed_absent_at=now,
            )
            await session.commit()
        return "persisted" if settled is not None else "lost"

    async def _settle_unmanaged(
        self,
        projection: ExternalChannelDiscordThreadTitleProjection,
        *,
        delivery_channel_id: str,
        now: datetime.datetime,
        reason: str,
    ) -> str:
        """Record a usable but unowned thread without provider title authority."""
        async with self.session_manager() as session:
            settled = await self.title_repository.settle_provisioning_unmanaged(
                session,
                projection_id=projection.id,
                expected_provision_attempt_count=projection.provision_attempt_count,
                expected_provision_claimed_at=_claimed_at(projection),
                delivery_channel_id=delivery_channel_id,
                reason=reason,
                now=now,
            )
            await session.commit()
        return _durable_settlement_outcome(settled)

    async def _retry_result(
        self,
        projection: ExternalChannelDiscordThreadTitleProjection,
        *,
        result: DiscordThreadProvisioningResult,
        now: datetime.datetime,
    ) -> str:
        """Persist one ambiguous or transient result for a later GET-first retry."""
        return await self._retry(
            projection,
            now=now,
            failure_kind=result.error_kind or "provider_ambiguous",
            failure_summary=result.error_summary
            or "Discord provisioning result was not provable.",
        )

    async def _retry(
        self,
        projection: ExternalChannelDiscordThreadTitleProjection,
        *,
        now: datetime.datetime,
        failure_kind: str,
        failure_summary: str,
    ) -> str:
        """Release the exact claim with bounded exponential retry delay."""
        async with self.session_manager() as session:
            retried = await self.title_repository.retry_provisioning(
                session,
                projection_id=projection.id,
                expected_provision_attempt_count=projection.provision_attempt_count,
                expected_provision_claimed_at=_claimed_at(projection),
                next_attempt_at=now
                + datetime.timedelta(
                    seconds=min(
                        _MAX_RETRY_SECONDS,
                        2 ** min(projection.provision_attempt_count, 8),
                    )
                ),
                failure_kind=failure_kind,
                failure_summary=failure_summary,
            )
            await session.commit()
        return "retry" if retried is not None else "lost"

    async def _fail_result(
        self,
        projection: ExternalChannelDiscordThreadTitleProjection,
        *,
        result: DiscordThreadProvisioningResult,
        now: datetime.datetime,
    ) -> str:
        """Terminalize a confirmed permanent provider failure."""
        return await self._fail(
            projection,
            now=now,
            failure_kind=result.error_kind or "provider_rejected",
            failure_summary=result.error_summary
            or "Discord rejected thread provisioning.",
        )

    async def _fail(
        self,
        projection: ExternalChannelDiscordThreadTitleProjection,
        *,
        now: datetime.datetime,
        failure_kind: str,
        failure_summary: str,
    ) -> str:
        """Terminalize one exact claim before any additional provider mutation."""
        async with self.session_manager() as session:
            failed = await self.title_repository.fail_provisioning_and_relinquish_title(
                session,
                projection_id=projection.id,
                expected_provision_attempt_count=projection.provision_attempt_count,
                expected_provision_claimed_at=_claimed_at(projection),
                failure_kind=failure_kind,
                failure_summary=failure_summary,
                now=now,
            )
            await session.commit()
        return "failed" if failed is not None else "lost"

    async def _load_authority(
        self,
        projection: ExternalChannelDiscordThreadTitleProjection,
    ) -> DiscordProjectionProvisioningAuthority | None:
        """Load authority immediately before each provider operation."""
        async with self.session_manager() as session:
            return await self.authority_loader.load(session, projection=projection)


def _connection_matches_projection(
    connection: ExternalChannelConnectionConfiguration | None,
    projection: ExternalChannelDiscordThreadTitleProjection,
) -> bool:
    """Validate the active Discord credential and exact admission connection."""
    return bool(
        connection is not None
        and connection.id == projection.admission_connection_id
        and connection.provider is ExternalChannelProvider.DISCORD
        and connection.status
        in {
            ExternalChannelConnectionStatus.ACTIVE,
            ExternalChannelConnectionStatus.DEGRADED,
        }
        and connection.disconnected_at is None
        and connection.provider_tenant_id == projection.admission_guild_id
        and connection.provider_bot_user_id
        and connection.encrypted_credentials
    )


def _resource_matches_projection(
    resource: ExternalChannelResource | None,
    projection: ExternalChannelDiscordThreadTitleProjection,
) -> bool:
    """Validate the active canonical Resource without using labels as proof."""
    return bool(
        resource is not None
        and resource.id == projection.resource_id
        and resource.connection_id == projection.admission_connection_id
        and resource.status is ExternalChannelResourceStatus.ACTIVE
    )


def _delivery_channel_id(resource: ExternalChannelResource) -> str | None:
    """Read only the canonical target for adoption consistency, never ownership."""
    value = (resource.labels or {}).get("delivery_channel_id")
    return value if isinstance(value, str) and value else None


def _thread_proof_matches(
    result: DiscordThreadProvisioningResult,
    *,
    projection: ExternalChannelDiscordThreadTitleProjection,
    authority: DiscordProjectionProvisioningAuthority,
) -> bool:
    """Require exact current Bot and stored provisional-name provider evidence."""
    thread = result.observed_thread
    return bool(
        thread is not None
        and result.thread_channel_id == thread.channel_id
        and thread.guild_id == projection.admission_guild_id
        and thread.parent_channel_id == projection.admission_parent_channel_id
        and thread.root_message_id == projection.admission_root_message_id
        and thread.owner_id == authority.bot_user_id
        and thread.name == projection.requested_provisional_title
    )


def adoption_created_after_admission(
    projection: ExternalChannelDiscordThreadTitleProjection,
    *,
    result: DiscordThreadProvisioningResult,
) -> bool:
    """Require adoption evidence to originate after exact admission absence."""
    thread = result.observed_thread
    return bool(
        thread is not None and thread.created_at >= projection.admission_observed_at
    )


def _claimed_at(
    projection: ExternalChannelDiscordThreadTitleProjection,
) -> datetime.datetime:
    """Return the required repository claim fence timestamp."""
    if projection.provision_claimed_at is None:
        raise RuntimeError("Claimed projection is missing its provisioning timestamp.")
    return projection.provision_claimed_at


def _durable_settlement_outcome(
    projection: ExternalChannelDiscordThreadTitleProjection | None,
) -> str:
    """Report only a durable terminal provisioning settlement as successful."""
    if projection is None:
        return "lost"
    match projection.provisioning_status:
        case ExternalChannelDiscordThreadTitleProvisioningStatus.READY:
            return "ready"
        case ExternalChannelDiscordThreadTitleProvisioningStatus.UNMANAGED:
            return "unmanaged"
        case ExternalChannelDiscordThreadTitleProvisioningStatus.FAILED:
            return "failed"
        case _:
            return "lost"


def get_discord_projection_reconciliation_service(
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ],
    title_repository: Annotated[
        ExternalChannelTitleRepository,
        Depends(ExternalChannelTitleRepository),
    ],
    external_channel_repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ],
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)],
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ],
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ],
    discord_client: Annotated[
        DiscordDeliveryClient,
        Depends(get_discord_delivery_client),
    ],
) -> DiscordProjectionReconciliationService:
    """Compose bounded projection reconciliation into the existing Worker process."""
    return DiscordProjectionReconciliationService(
        session_manager=session_manager,
        title_repository=title_repository,
        authority_loader=DiscordProjectionAuthorityLoader(
            external_channel_repository=external_channel_repository,
            agent_repository=agent_repository,
            agent_session_repository=agent_session_repository,
            title_repository=title_repository,
            credentials_codec=credentials_codec,
        ),
        discord_client=discord_client,
    )
