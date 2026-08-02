"""External Channel automatic Session-title persistence."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelDiscordThreadTitleProofKind,
    ExternalChannelDiscordThreadTitleProvisioningStatus,
    ExternalChannelDiscordThreadTitleStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelSessionTitleCandidateStatus,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelDiscordThreadTitleProjection,
    RDBExternalChannelResource,
    RDBExternalChannelSessionTitleCandidate,
)

from .data import (
    ExternalChannelDiscordThreadTitleProjection,
    ExternalChannelDiscordThreadTitleProjectionCreate,
    ExternalChannelSessionTitleCandidate,
    ExternalChannelSessionTitleCandidateCreate,
)

SUPPORTED_DISCORD_THREAD_TITLE_PROVISIONING_PROTOCOL_VERSION = 1


class ExternalChannelTitleRepository:
    """Persist exact External Channel title eligibility and projection state."""

    @staticmethod
    def _validate_relinquished_reason(reason: str) -> None:
        """Reject empty or oversized terminal reason codes."""
        if not reason.strip() or len(reason) > 120:
            raise ValueError("Candidate relinquishment reason is invalid.")

    @staticmethod
    def _validate_failure(
        *,
        failure_kind: str,
        failure_summary: str,
    ) -> None:
        """Reject malformed bounded projection failure diagnostics."""
        if (
            not failure_kind.strip()
            or len(failure_kind) > 120
            or not failure_summary.strip()
            or len(failure_summary) > 255
        ):
            raise ValueError("Projection failure diagnostics are invalid.")

    @staticmethod
    def _candidate(
        row: RDBExternalChannelSessionTitleCandidate,
    ) -> ExternalChannelSessionTitleCandidate:
        """Build an immutable candidate repository record."""
        return ExternalChannelSessionTitleCandidate.model_validate(row)

    @staticmethod
    def _projection(
        row: RDBExternalChannelDiscordThreadTitleProjection,
    ) -> ExternalChannelDiscordThreadTitleProjection:
        """Build an immutable projection repository record."""
        return ExternalChannelDiscordThreadTitleProjection.model_validate(row)

    @staticmethod
    async def _refresh_projections(
        session: AsyncSession,
        rows: list[RDBExternalChannelDiscordThreadTitleProjection],
    ) -> None:
        """Refresh server-managed timestamps before immutable DTO conversion."""
        for row in rows:
            await session.refresh(row)

    @staticmethod
    async def _lock_attempting_provisioning(
        session: AsyncSession,
        *,
        projection_id: str,
        expected_provision_attempt_count: int,
        expected_provision_claimed_at: datetime.datetime,
    ) -> RDBExternalChannelDiscordThreadTitleProjection | None:
        """Lock only the exact current provisioning claim fence."""
        return await session.scalar(
            sa.select(RDBExternalChannelDiscordThreadTitleProjection)
            .where(
                RDBExternalChannelDiscordThreadTitleProjection.id == projection_id,
                RDBExternalChannelDiscordThreadTitleProjection.provisioning_status
                == ExternalChannelDiscordThreadTitleProvisioningStatus.ATTEMPTING,
                RDBExternalChannelDiscordThreadTitleProjection.provision_attempt_count
                == expected_provision_attempt_count,
                RDBExternalChannelDiscordThreadTitleProjection.provision_claimed_at
                == expected_provision_claimed_at,
            )
            .with_for_update()
        )

    @staticmethod
    async def _lock_projection_resource(
        session: AsyncSession,
        *,
        projection: RDBExternalChannelDiscordThreadTitleProjection,
    ) -> RDBExternalChannelResource | None:
        """Lock the projection's one canonical Resource delivery target."""
        return await session.scalar(
            sa.select(RDBExternalChannelResource)
            .where(RDBExternalChannelResource.id == projection.resource_id)
            .with_for_update()
        )

    @staticmethod
    async def _lock_current_settlement_resource(
        session: AsyncSession,
        *,
        projection: RDBExternalChannelDiscordThreadTitleProjection,
    ) -> RDBExternalChannelResource | None:
        """Lock and revalidate every durable owner before provider settlement."""
        resource = await ExternalChannelTitleRepository._lock_projection_resource(
            session,
            projection=projection,
        )
        if (
            resource is None
            or resource.connection_id != projection.admission_connection_id
            or resource.status is not ExternalChannelResourceStatus.ACTIVE
        ):
            return None
        binding = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .where(
                RDBExternalChannelBinding.id == projection.binding_id,
                RDBExternalChannelBinding.resource_id == resource.id,
                RDBExternalChannelBinding.agent_session_id
                == projection.agent_session_id,
                RDBExternalChannelBinding.disconnected_at.is_(None),
            )
            .with_for_update()
        )
        candidate = await session.scalar(
            sa.select(RDBExternalChannelSessionTitleCandidate)
            .where(
                RDBExternalChannelSessionTitleCandidate.id
                == projection.session_title_candidate_id,
                RDBExternalChannelSessionTitleCandidate.agent_session_id
                == projection.agent_session_id,
                RDBExternalChannelSessionTitleCandidate.binding_id
                == projection.binding_id,
                RDBExternalChannelSessionTitleCandidate.trigger_provider_message_key
                == projection.admission_trigger_provider_message_key,
                RDBExternalChannelSessionTitleCandidate.admission_provisional_title
                == projection.requested_provisional_title,
                RDBExternalChannelSessionTitleCandidate.status.in_(
                    (
                        ExternalChannelSessionTitleCandidateStatus.PENDING,
                        ExternalChannelSessionTitleCandidateStatus.CONSUMED,
                    )
                ),
            )
            .with_for_update()
        )
        agent_session = await session.scalar(
            sa.select(RDBAgentSession)
            .where(
                RDBAgentSession.id == projection.agent_session_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgentSession.stop_requested_at.is_(None),
                RDBAgentSession.ended_at.is_(None),
            )
            .with_for_update()
        )
        if binding is None or candidate is None or agent_session is None:
            return None
        route = await session.scalar(
            sa.select(RDBExternalChannelAgentRoute)
            .where(
                RDBExternalChannelAgentRoute.id == binding.route_id,
                RDBExternalChannelAgentRoute.connection_id
                == projection.admission_connection_id,
                RDBExternalChannelAgentRoute.agent_id == agent_session.agent_id,
                RDBExternalChannelAgentRoute.catalog_status
                == ExternalChannelRouteCatalogStatus.AVAILABLE,
            )
            .with_for_update()
        )
        if route is None:
            return None
        agent = await session.scalar(
            sa.select(RDBAgent)
            .where(
                RDBAgent.id == agent_session.agent_id,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            )
            .with_for_update()
        )
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == projection.admission_connection_id,
                RDBExternalChannelConnection.provider
                == ExternalChannelProvider.DISCORD,
                RDBExternalChannelConnection.status.in_(
                    (
                        ExternalChannelConnectionStatus.ACTIVE,
                        ExternalChannelConnectionStatus.DEGRADED,
                    )
                ),
                RDBExternalChannelConnection.disconnected_at.is_(None),
                RDBExternalChannelConnection.provider_tenant_id
                == projection.admission_guild_id,
                RDBExternalChannelConnection.provider_bot_user_id.is_not(None),
                RDBExternalChannelConnection.encrypted_credentials.is_not(None),
                RDBExternalChannelConnection.app_mode == route.connection_app_mode,
            )
            .with_for_update()
        )
        return resource if agent is not None and connection is not None else None

    @staticmethod
    def _terminalize_provisioning(
        projection: RDBExternalChannelDiscordThreadTitleProjection,
        *,
        provisioning_status: ExternalChannelDiscordThreadTitleProvisioningStatus,
        reason: str,
        now: datetime.datetime,
    ) -> None:
        """Terminalize one projection without reopening title authority."""
        projection.provisioning_status = provisioning_status
        projection.provision_next_attempt_at = None
        projection.provision_claimed_at = None
        projection.provision_failure_kind = reason
        projection.provision_failure_summary = reason
        projection.provision_completed_at = now
        projection.title_status = ExternalChannelDiscordThreadTitleStatus.RELINQUISHED
        projection.title_next_attempt_at = None
        projection.title_claimed_at = None
        projection.title_failure_kind = reason
        projection.title_failure_summary = reason
        projection.title_completed_at = now

    @staticmethod
    def _set_delivery_channel_if_compatible(
        resource: RDBExternalChannelResource,
        *,
        delivery_channel_id: str,
    ) -> bool:
        """Set one canonical delivery target or reject a conflicting target."""
        if not delivery_channel_id.strip():
            raise ValueError("Discord delivery channel identity is invalid.")
        labels = dict(resource.labels or {})
        existing = labels.get("delivery_channel_id")
        if existing is not None and (
            not isinstance(existing, str) or existing != delivery_channel_id
        ):
            return False
        labels["delivery_channel_id"] = delivery_channel_id
        labels["thread_channel_id"] = delivery_channel_id
        labels["thread_id"] = delivery_channel_id
        resource.labels = labels
        return True

    async def create_session_title_candidate(
        self,
        session: AsyncSession,
        create: ExternalChannelSessionTitleCandidateCreate,
    ) -> ExternalChannelSessionTitleCandidate:
        """Create or verify the one exact title candidate for a new Session."""
        result = await session.execute(
            pg_insert(RDBExternalChannelSessionTitleCandidate)
            .values(
                id=uuid7().hex,
                agent_session_id=create.agent_session_id,
                binding_id=create.binding_id,
                trigger_provider_message_key=create.trigger_provider_message_key,
                admission_access_request_id=create.admission_access_request_id,
                admission_provisional_title=create.admission_provisional_title,
                status=create.status,
                consumed_event_id=create.consumed_event_id,
                relinquished_reason=create.relinquished_reason,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    RDBExternalChannelSessionTitleCandidate.agent_session_id
                ]
            )
            .returning(RDBExternalChannelSessionTitleCandidate)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            await session.flush()
            return self._candidate(row)

        existing = await session.scalar(
            sa.select(RDBExternalChannelSessionTitleCandidate)
            .where(
                RDBExternalChannelSessionTitleCandidate.agent_session_id
                == create.agent_session_id
            )
            .with_for_update()
        )
        if existing is None:
            raise RuntimeError("Session title candidate idempotent creation failed.")
        if (
            existing.binding_id != create.binding_id
            or existing.trigger_provider_message_key
            != create.trigger_provider_message_key
            or existing.admission_access_request_id
            != create.admission_access_request_id
            or existing.admission_provisional_title
            != create.admission_provisional_title
        ):
            raise ValueError("Session title candidate identity does not match.")
        return self._candidate(existing)

    async def create_discord_thread_title_projection(
        self,
        session: AsyncSession,
        create: ExternalChannelDiscordThreadTitleProjectionCreate,
    ) -> ExternalChannelDiscordThreadTitleProjection:
        """Create or verify the one initial-title projection for a Resource."""
        values = create.model_dump()
        result = await session.execute(
            pg_insert(RDBExternalChannelDiscordThreadTitleProjection)
            .values(id=uuid7().hex, **values)
            .on_conflict_do_nothing(
                index_elements=[
                    RDBExternalChannelDiscordThreadTitleProjection.resource_id
                ]
            )
            .returning(RDBExternalChannelDiscordThreadTitleProjection)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            await session.flush()
            return self._projection(row)

        existing = await session.scalar(
            sa.select(RDBExternalChannelDiscordThreadTitleProjection)
            .where(
                RDBExternalChannelDiscordThreadTitleProjection.resource_id
                == create.resource_id
            )
            .with_for_update()
        )
        if existing is None:
            raise RuntimeError("Discord title projection idempotent creation failed.")
        immutable_fields = (
            "binding_id",
            "agent_session_id",
            "session_title_candidate_id",
            "provisioning_protocol_version",
            "requested_provisional_title",
            "admission_connection_id",
            "admission_guild_id",
            "admission_parent_channel_id",
            "admission_root_message_id",
            "admission_trigger_provider_message_key",
            "admission_observation_status",
            "admission_root_has_thread",
            "admission_observed_thread_channel_id",
            "admission_observed_at",
        )
        if any(getattr(existing, field) != values[field] for field in immutable_fields):
            raise ValueError("Discord title projection identity does not match.")
        return self._projection(existing)

    async def get_projection_by_resource_id(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelDiscordThreadTitleProjection | None:
        """Read one Resource-owned projection without affecting legacy delivery."""
        row = await session.scalar(
            sa.select(RDBExternalChannelDiscordThreadTitleProjection).where(
                RDBExternalChannelDiscordThreadTitleProjection.resource_id
                == resource_id
            )
        )
        return None if row is None else self._projection(row)

    async def get_candidate_by_identity(
        self,
        session: AsyncSession,
        *,
        agent_session_id: str,
        binding_id: str,
        trigger_provider_message_key: str,
    ) -> ExternalChannelSessionTitleCandidate | None:
        """Read one exact title candidate without changing its terminal state."""
        row = await session.scalar(
            sa.select(RDBExternalChannelSessionTitleCandidate).where(
                RDBExternalChannelSessionTitleCandidate.agent_session_id
                == agent_session_id,
                RDBExternalChannelSessionTitleCandidate.binding_id == binding_id,
                RDBExternalChannelSessionTitleCandidate.trigger_provider_message_key
                == trigger_provider_message_key,
            )
        )
        return None if row is None else self._candidate(row)

    async def get_pending_candidate_for_event(
        self,
        session: AsyncSession,
        *,
        agent_session_id: str,
        binding_id: str,
        trigger_provider_message_key: str,
        for_update: bool,
    ) -> ExternalChannelSessionTitleCandidate | None:
        """Load the exact pending candidate eligible for one promoted Event."""
        statement = sa.select(RDBExternalChannelSessionTitleCandidate).where(
            RDBExternalChannelSessionTitleCandidate.agent_session_id
            == agent_session_id,
            RDBExternalChannelSessionTitleCandidate.binding_id == binding_id,
            RDBExternalChannelSessionTitleCandidate.trigger_provider_message_key
            == trigger_provider_message_key,
            RDBExternalChannelSessionTitleCandidate.status
            == ExternalChannelSessionTitleCandidateStatus.PENDING,
        )
        if for_update:
            statement = statement.with_for_update()
        row = await session.scalar(statement)
        return None if row is None else self._candidate(row)

    async def consume_pending_candidate(
        self,
        session: AsyncSession,
        *,
        candidate_id: str,
        agent_session_id: str,
        binding_id: str,
        trigger_provider_message_key: str,
        consumed_event_id: str,
    ) -> ExternalChannelSessionTitleCandidate | None:
        """Consume only the exact pending candidate after initial title assignment."""
        result = await session.execute(
            sa.update(RDBExternalChannelSessionTitleCandidate)
            .where(
                RDBExternalChannelSessionTitleCandidate.id == candidate_id,
                RDBExternalChannelSessionTitleCandidate.agent_session_id
                == agent_session_id,
                RDBExternalChannelSessionTitleCandidate.binding_id == binding_id,
                RDBExternalChannelSessionTitleCandidate.trigger_provider_message_key
                == trigger_provider_message_key,
                RDBExternalChannelSessionTitleCandidate.status
                == ExternalChannelSessionTitleCandidateStatus.PENDING,
            )
            .values(
                status=ExternalChannelSessionTitleCandidateStatus.CONSUMED,
                consumed_event_id=consumed_event_id,
            )
            .returning(RDBExternalChannelSessionTitleCandidate)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        await session.flush()
        return self._candidate(row)

    async def relinquish_pending_candidate(
        self,
        session: AsyncSession,
        *,
        candidate_id: str,
        agent_session_id: str,
        binding_id: str,
        trigger_provider_message_key: str,
        reason: str,
    ) -> ExternalChannelSessionTitleCandidate | None:
        """Terminalize one exact unused candidate without granting later eligibility."""
        self._validate_relinquished_reason(reason)
        result = await session.execute(
            sa.update(RDBExternalChannelSessionTitleCandidate)
            .where(
                RDBExternalChannelSessionTitleCandidate.id == candidate_id,
                RDBExternalChannelSessionTitleCandidate.agent_session_id
                == agent_session_id,
                RDBExternalChannelSessionTitleCandidate.binding_id == binding_id,
                RDBExternalChannelSessionTitleCandidate.trigger_provider_message_key
                == trigger_provider_message_key,
                RDBExternalChannelSessionTitleCandidate.status
                == ExternalChannelSessionTitleCandidateStatus.PENDING,
            )
            .values(
                status=ExternalChannelSessionTitleCandidateStatus.RELINQUISHED,
                relinquished_reason=reason,
            )
            .returning(RDBExternalChannelSessionTitleCandidate)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        await session.flush()
        return self._candidate(row)

    async def arm_title_projections_for_generated_title(
        self,
        session: AsyncSession,
        *,
        agent_session_id: str,
        generation_event_id: str,
        desired_title: str,
        now: datetime.datetime,
    ) -> tuple[ExternalChannelDiscordThreadTitleProjection, ...]:
        """Atomically snapshot a winning final title into eligible projections."""
        rows = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelDiscordThreadTitleProjection)
                    .join(
                        RDBExternalChannelSessionTitleCandidate,
                        RDBExternalChannelSessionTitleCandidate.id
                        == (
                            RDBExternalChannelDiscordThreadTitleProjection.session_title_candidate_id
                        ),
                    )
                    .where(
                        RDBExternalChannelDiscordThreadTitleProjection.agent_session_id
                        == agent_session_id,
                        RDBExternalChannelDiscordThreadTitleProjection.title_status
                        == ExternalChannelDiscordThreadTitleStatus.WAITING,
                        RDBExternalChannelSessionTitleCandidate.status
                        == ExternalChannelSessionTitleCandidateStatus.CONSUMED,
                        RDBExternalChannelSessionTitleCandidate.consumed_event_id
                        == generation_event_id,
                    )
                    .order_by(RDBExternalChannelDiscordThreadTitleProjection.id)
                    .with_for_update()
                )
            ).all()
        )
        for row in rows:
            row.desired_title = desired_title
            row.title_generation_event_id = generation_event_id
            if (
                row.provisioning_status
                is ExternalChannelDiscordThreadTitleProvisioningStatus.READY
            ):
                row.title_status = ExternalChannelDiscordThreadTitleStatus.PENDING
                row.title_next_attempt_at = now
            else:
                row.title_status = ExternalChannelDiscordThreadTitleStatus.WAITING
        await session.flush()
        for row in rows:
            await session.refresh(row)
        return tuple(self._projection(row) for row in rows)

    async def claim_due_provisioning(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        stale_before: datetime.datetime,
        limit: int,
    ) -> tuple[ExternalChannelDiscordThreadTitleProjection, ...]:
        """Claim bounded due or stale provisioning projections for current Workers."""
        candidate_status = RDBExternalChannelSessionTitleCandidate.status
        candidate_provisional_title = (
            RDBExternalChannelSessionTitleCandidate.admission_provisional_title
        )
        projection_provisional_title = (
            RDBExternalChannelDiscordThreadTitleProjection.requested_provisional_title
        )
        rows = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelDiscordThreadTitleProjection)
                    .join(
                        RDBExternalChannelSessionTitleCandidate,
                        RDBExternalChannelSessionTitleCandidate.id
                        == (
                            RDBExternalChannelDiscordThreadTitleProjection.session_title_candidate_id
                        ),
                    )
                    .where(
                        RDBExternalChannelDiscordThreadTitleProjection.provisioning_protocol_version
                        == SUPPORTED_DISCORD_THREAD_TITLE_PROVISIONING_PROTOCOL_VERSION,
                        candidate_provisional_title == projection_provisional_title,
                        candidate_status.in_(
                            (
                                ExternalChannelSessionTitleCandidateStatus.PENDING,
                                ExternalChannelSessionTitleCandidateStatus.CONSUMED,
                            )
                        ),
                        sa.or_(
                            sa.and_(
                                RDBExternalChannelDiscordThreadTitleProjection.provisioning_status
                                == (
                                    ExternalChannelDiscordThreadTitleProvisioningStatus.PENDING
                                ),
                                RDBExternalChannelDiscordThreadTitleProjection.provision_next_attempt_at.is_(
                                    None
                                ),
                            ),
                            sa.and_(
                                RDBExternalChannelDiscordThreadTitleProjection.provisioning_status
                                == (
                                    ExternalChannelDiscordThreadTitleProvisioningStatus.RETRY_WAIT
                                ),
                                RDBExternalChannelDiscordThreadTitleProjection.provision_next_attempt_at
                                <= now,
                            ),
                            sa.and_(
                                RDBExternalChannelDiscordThreadTitleProjection.provisioning_status
                                == (
                                    ExternalChannelDiscordThreadTitleProvisioningStatus.ATTEMPTING
                                ),
                                RDBExternalChannelDiscordThreadTitleProjection.provision_claimed_at
                                < stale_before,
                            ),
                        ),
                    )
                    .order_by(RDBExternalChannelDiscordThreadTitleProjection.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for row in rows:
            row.provisioning_status = (
                ExternalChannelDiscordThreadTitleProvisioningStatus.ATTEMPTING
            )
            row.provision_attempt_count += 1
            row.provision_claimed_at = now
            row.provision_next_attempt_at = None
        await session.flush()
        for row in rows:
            await session.refresh(row)
        return tuple(self._projection(row) for row in rows)

    async def claim_due_titles(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        stale_before: datetime.datetime,
        limit: int,
    ) -> tuple[ExternalChannelDiscordThreadTitleProjection, ...]:
        """Claim bounded due or stale final-title projections for current Workers."""
        rows = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelDiscordThreadTitleProjection)
                    .where(
                        RDBExternalChannelDiscordThreadTitleProjection.provisioning_status
                        == ExternalChannelDiscordThreadTitleProvisioningStatus.READY,
                        sa.or_(
                            sa.and_(
                                RDBExternalChannelDiscordThreadTitleProjection.title_status
                                == ExternalChannelDiscordThreadTitleStatus.PENDING,
                                RDBExternalChannelDiscordThreadTitleProjection.title_next_attempt_at
                                <= now,
                            ),
                            sa.and_(
                                RDBExternalChannelDiscordThreadTitleProjection.title_status
                                == ExternalChannelDiscordThreadTitleStatus.RETRY_WAIT,
                                RDBExternalChannelDiscordThreadTitleProjection.title_next_attempt_at
                                <= now,
                            ),
                            sa.and_(
                                RDBExternalChannelDiscordThreadTitleProjection.title_status
                                == ExternalChannelDiscordThreadTitleStatus.ATTEMPTING,
                                RDBExternalChannelDiscordThreadTitleProjection.title_claimed_at
                                < stale_before,
                            ),
                        ),
                    )
                    .order_by(RDBExternalChannelDiscordThreadTitleProjection.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for row in rows:
            row.title_status = ExternalChannelDiscordThreadTitleStatus.ATTEMPTING
            row.title_attempt_count += 1
            row.title_claimed_at = now
            row.title_next_attempt_at = None
        await session.flush()
        for row in rows:
            await session.refresh(row)
        return tuple(self._projection(row) for row in rows)

    async def persist_provisioning_preflight(
        self,
        session: AsyncSession,
        *,
        projection_id: str,
        expected_provision_attempt_count: int,
        expected_provision_claimed_at: datetime.datetime,
        observed_absent_at: datetime.datetime,
    ) -> ExternalChannelDiscordThreadTitleProjection | None:
        """Persist exact absence evidence before one projection-owned POST."""
        projection = await self._lock_attempting_provisioning(
            session,
            projection_id=projection_id,
            expected_provision_attempt_count=expected_provision_attempt_count,
            expected_provision_claimed_at=expected_provision_claimed_at,
        )
        if projection is None:
            return None
        projection.preflight_absent_at = observed_absent_at
        await session.flush()
        await self._refresh_projections(session, [projection])
        return self._projection(projection)

    async def settle_provisioning_ready(
        self,
        session: AsyncSession,
        *,
        projection_id: str,
        expected_provision_attempt_count: int,
        expected_provision_claimed_at: datetime.datetime,
        delivery_channel_id: str,
        thread_channel_id: str,
        expected_provisional_title: str,
        proof_kind: ExternalChannelDiscordThreadTitleProofKind,
        now: datetime.datetime,
    ) -> ExternalChannelDiscordThreadTitleProjection | None:
        """Atomically record exact owned thread proof and canonical delivery target."""
        if (
            not thread_channel_id.strip()
            or delivery_channel_id != thread_channel_id
            or not expected_provisional_title.strip()
        ):
            raise ValueError("Discord thread proof identity is invalid.")
        projection = await self._lock_attempting_provisioning(
            session,
            projection_id=projection_id,
            expected_provision_attempt_count=expected_provision_attempt_count,
            expected_provision_claimed_at=expected_provision_claimed_at,
        )
        if projection is None or (
            projection.requested_provisional_title != expected_provisional_title
        ):
            return None
        resource = await self._lock_current_settlement_resource(
            session,
            projection=projection,
        )
        if resource is None:
            self._terminalize_provisioning(
                projection,
                provisioning_status=(
                    ExternalChannelDiscordThreadTitleProvisioningStatus.FAILED
                ),
                reason="authority_revoked",
                now=now,
            )
            await session.flush()
            await self._refresh_projections(session, [projection])
            return self._projection(projection)
        if not self._set_delivery_channel_if_compatible(
            resource,
            delivery_channel_id=delivery_channel_id,
        ):
            self._terminalize_provisioning(
                projection,
                provisioning_status=(
                    ExternalChannelDiscordThreadTitleProvisioningStatus.UNMANAGED
                ),
                reason="delivery_channel_conflict",
                now=now,
            )
            await session.flush()
            await self._refresh_projections(session, [projection])
            return self._projection(projection)
        projection.provisioning_status = (
            ExternalChannelDiscordThreadTitleProvisioningStatus.READY
        )
        projection.thread_channel_id = thread_channel_id
        projection.expected_provisional_title = expected_provisional_title
        projection.provisioning_proof_kind = proof_kind
        projection.provision_next_attempt_at = None
        projection.provision_claimed_at = None
        projection.provision_failure_kind = None
        projection.provision_failure_summary = None
        projection.provision_completed_at = now
        if (
            projection.title_status is ExternalChannelDiscordThreadTitleStatus.WAITING
            and projection.desired_title is not None
            and projection.title_generation_event_id is not None
        ):
            projection.title_status = ExternalChannelDiscordThreadTitleStatus.PENDING
            projection.title_next_attempt_at = now
        await session.flush()
        await self._refresh_projections(session, [projection])
        return self._projection(projection)

    async def settle_provisioning_unmanaged(
        self,
        session: AsyncSession,
        *,
        projection_id: str,
        expected_provision_attempt_count: int,
        expected_provision_claimed_at: datetime.datetime,
        delivery_channel_id: str,
        reason: str,
        now: datetime.datetime,
    ) -> ExternalChannelDiscordThreadTitleProjection | None:
        """Preserve a usable non-owned thread while terminally relinquishing title."""
        self._validate_relinquished_reason(reason)
        projection = await self._lock_attempting_provisioning(
            session,
            projection_id=projection_id,
            expected_provision_attempt_count=expected_provision_attempt_count,
            expected_provision_claimed_at=expected_provision_claimed_at,
        )
        if projection is None:
            return None
        resource = await self._lock_current_settlement_resource(
            session,
            projection=projection,
        )
        if resource is None:
            self._terminalize_provisioning(
                projection,
                provisioning_status=(
                    ExternalChannelDiscordThreadTitleProvisioningStatus.FAILED
                ),
                reason="authority_revoked",
                now=now,
            )
        elif not self._set_delivery_channel_if_compatible(
            resource,
            delivery_channel_id=delivery_channel_id,
        ):
            self._terminalize_provisioning(
                projection,
                provisioning_status=(
                    ExternalChannelDiscordThreadTitleProvisioningStatus.UNMANAGED
                ),
                reason="delivery_channel_conflict",
                now=now,
            )
        else:
            self._terminalize_provisioning(
                projection,
                provisioning_status=(
                    ExternalChannelDiscordThreadTitleProvisioningStatus.UNMANAGED
                ),
                reason=reason,
                now=now,
            )
        await session.flush()
        await self._refresh_projections(session, [projection])
        return self._projection(projection)

    async def retry_provisioning(
        self,
        session: AsyncSession,
        *,
        projection_id: str,
        expected_provision_attempt_count: int,
        expected_provision_claimed_at: datetime.datetime,
        next_attempt_at: datetime.datetime,
        failure_kind: str,
        failure_summary: str,
    ) -> ExternalChannelDiscordThreadTitleProjection | None:
        """Release one exact transient provisioning claim for GET-first retry."""
        self._validate_failure(
            failure_kind=failure_kind,
            failure_summary=failure_summary,
        )
        projection = await self._lock_attempting_provisioning(
            session,
            projection_id=projection_id,
            expected_provision_attempt_count=expected_provision_attempt_count,
            expected_provision_claimed_at=expected_provision_claimed_at,
        )
        if projection is None:
            return None
        projection.provisioning_status = (
            ExternalChannelDiscordThreadTitleProvisioningStatus.RETRY_WAIT
        )
        projection.provision_next_attempt_at = next_attempt_at
        projection.provision_claimed_at = None
        projection.provision_failure_kind = failure_kind
        projection.provision_failure_summary = failure_summary
        await session.flush()
        await self._refresh_projections(session, [projection])
        return self._projection(projection)

    async def fail_provisioning_and_relinquish_title(
        self,
        session: AsyncSession,
        *,
        projection_id: str,
        expected_provision_attempt_count: int,
        expected_provision_claimed_at: datetime.datetime,
        failure_kind: str,
        failure_summary: str,
        now: datetime.datetime,
    ) -> ExternalChannelDiscordThreadTitleProjection | None:
        """Terminalize permanent provisioning failure without affecting execution."""
        self._validate_failure(
            failure_kind=failure_kind,
            failure_summary=failure_summary,
        )
        projection = await self._lock_attempting_provisioning(
            session,
            projection_id=projection_id,
            expected_provision_attempt_count=expected_provision_attempt_count,
            expected_provision_claimed_at=expected_provision_claimed_at,
        )
        if projection is None:
            return None
        projection.provisioning_status = (
            ExternalChannelDiscordThreadTitleProvisioningStatus.FAILED
        )
        projection.provision_next_attempt_at = None
        projection.provision_claimed_at = None
        projection.provision_failure_kind = failure_kind
        projection.provision_failure_summary = failure_summary
        projection.provision_completed_at = now
        projection.title_status = ExternalChannelDiscordThreadTitleStatus.RELINQUISHED
        projection.title_next_attempt_at = None
        projection.title_claimed_at = None
        projection.title_failure_kind = failure_kind
        projection.title_failure_summary = failure_summary
        projection.title_completed_at = now
        await session.flush()
        await self._refresh_projections(session, [projection])
        return self._projection(projection)
