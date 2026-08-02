"""External Channel automatic Session-title persistence."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelDiscordThreadTitleProvisioningStatus,
    ExternalChannelDiscordThreadTitleStatus,
    ExternalChannelSessionTitleCandidateStatus,
)
from azents.rdb.models.external_channel import (
    RDBExternalChannelDiscordThreadTitleProjection,
    RDBExternalChannelSessionTitleCandidate,
)

from .data import (
    ExternalChannelDiscordThreadTitleProjection,
    ExternalChannelDiscordThreadTitleProjectionCreate,
    ExternalChannelSessionTitleCandidate,
    ExternalChannelSessionTitleCandidateCreate,
)


class ExternalChannelTitleRepository:
    """Persist exact External Channel title eligibility and projection state."""

    @staticmethod
    def _validate_relinquished_reason(reason: str) -> None:
        """Reject empty or oversized terminal reason codes."""
        if not reason.strip() or len(reason) > 120:
            raise ValueError("Candidate relinquishment reason is invalid.")

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
        rows = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelDiscordThreadTitleProjection)
                    .where(
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
                        )
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
