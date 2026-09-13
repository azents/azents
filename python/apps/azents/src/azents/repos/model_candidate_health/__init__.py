"""Completed PostgreSQL operations for physical model candidate health."""

import dataclasses
import datetime
from typing import Annotated

import sqlalchemy as sa
from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ModelCandidateClaimKind
from azents.rdb.deps import get_session_manager
from azents.rdb.models.model_candidate_health import RDBModelCandidateHealth
from azents.rdb.session import SessionManager

from .data import (
    CandidateClaimTransfer,
    CandidateHealthSettlement,
    ForegroundProbeOutcome,
    ForegroundProbeResult,
    ModelCandidateHealthObservation,
    ModelCandidateHealthSnapshot,
    ModelCandidateHealthStatus,
    ModelCandidateIdentity,
    ReservationClaimOutcome,
    ReservationClaimResult,
)

MODEL_CANDIDATE_COOLDOWN = datetime.timedelta(minutes=5)
MODEL_CANDIDATE_CLAIM_LEASE = datetime.timedelta(minutes=5)


@dataclasses.dataclass
class ModelCandidateHealthRepository:
    """Own short database-only candidate health transactions."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def snapshot(
        self,
        identity: ModelCandidateIdentity,
    ) -> ModelCandidateHealthObservation:
        """Read candidate health without taking a row lock."""
        async with self.session_manager() as session:
            return await self.snapshot_in_session(session, identity)

    async def snapshot_in_session(
        self,
        session: AsyncSession,
        identity: ModelCandidateIdentity,
    ) -> ModelCandidateHealthObservation:
        """Read candidate health inside one caller-owned transaction."""
        row = await session.get(
            RDBModelCandidateHealth,
            self._primary_key(identity),
        )
        server_time = await self._database_time(session)
        return self._observe(row, server_time=server_time)

    async def snapshot_for_background(
        self,
        identity: ModelCandidateIdentity,
    ) -> ModelCandidateHealthObservation:
        """Read background eligibility without acquiring half-open authority."""
        return await self.snapshot(identity)

    async def snapshot_for_background_in_session(
        self,
        session: AsyncSession,
        identity: ModelCandidateIdentity,
    ) -> ModelCandidateHealthObservation:
        """Read background eligibility inside one caller-owned transaction."""
        return await self.snapshot_in_session(session, identity)

    async def renew_quota(
        self,
        identity: ModelCandidateIdentity,
    ) -> ModelCandidateHealthObservation:
        """Record an unclaimed quota observation and revoke every older claim."""
        async with self.session_manager() as session:
            return await self.renew_quota_in_session(session, identity)

    async def renew_quota_in_session(
        self,
        session: AsyncSession,
        identity: ModelCandidateIdentity,
    ) -> ModelCandidateHealthObservation:
        """Record quota inside the caller's transaction."""
        server_time = await self._database_time(session)
        statement = insert(RDBModelCandidateHealth).values(
            workspace_id=identity.workspace_id,
            llm_provider_integration_id=identity.llm_provider_integration_id,
            model_identifier=identity.model_identifier,
            generation=1,
            cooldown_until=server_time + MODEL_CANDIDATE_COOLDOWN,
            claim_kind=None,
            claim_owner_id=None,
            claim_token=None,
            claim_until=None,
            updated_at=server_time,
        )
        row = (
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        RDBModelCandidateHealth.workspace_id,
                        RDBModelCandidateHealth.llm_provider_integration_id,
                        RDBModelCandidateHealth.model_identifier,
                    ],
                    set_={
                        "generation": RDBModelCandidateHealth.generation + 1,
                        "cooldown_until": (server_time + MODEL_CANDIDATE_COOLDOWN),
                        "claim_kind": None,
                        "claim_owner_id": None,
                        "claim_token": None,
                        "claim_until": None,
                        "updated_at": server_time,
                    },
                ).returning(RDBModelCandidateHealth)
            )
        ).scalar_one()
        return self._observe(row, server_time=server_time)

    async def renew_claimed_quota(
        self,
        identity: ModelCandidateIdentity,
        *,
        expected_generation: int,
        expected_claim_kind: ModelCandidateClaimKind,
        expected_owner_id: str,
        expected_claim_token: str,
    ) -> tuple[CandidateHealthSettlement, ModelCandidateHealthObservation]:
        """Renew cooldown only for the exact current claim authority."""
        async with self.session_manager() as session:
            return await self.renew_claimed_quota_in_session(
                session,
                identity,
                expected_generation=expected_generation,
                expected_claim_kind=expected_claim_kind,
                expected_owner_id=expected_owner_id,
                expected_claim_token=expected_claim_token,
            )

    async def renew_claimed_quota_in_session(
        self,
        session: AsyncSession,
        identity: ModelCandidateIdentity,
        *,
        expected_generation: int,
        expected_claim_kind: ModelCandidateClaimKind,
        expected_owner_id: str,
        expected_claim_token: str,
    ) -> tuple[CandidateHealthSettlement, ModelCandidateHealthObservation]:
        """Renew an exact claimed quota result inside the caller's transaction."""
        server_time = await self._database_time(session)
        row = (
            await session.execute(
                sa.update(RDBModelCandidateHealth)
                .where(
                    *self._identity_predicates(identity),
                    RDBModelCandidateHealth.generation == expected_generation,
                    RDBModelCandidateHealth.claim_kind == expected_claim_kind,
                    RDBModelCandidateHealth.claim_owner_id == expected_owner_id,
                    RDBModelCandidateHealth.claim_token == expected_claim_token,
                )
                .values(
                    generation=RDBModelCandidateHealth.generation + 1,
                    cooldown_until=server_time + MODEL_CANDIDATE_COOLDOWN,
                    claim_kind=None,
                    claim_owner_id=None,
                    claim_token=None,
                    claim_until=None,
                    updated_at=server_time,
                )
                .returning(RDBModelCandidateHealth)
            )
        ).scalar_one_or_none()
        if row is None:
            current = await session.get(
                RDBModelCandidateHealth,
                self._primary_key(identity),
            )
            return (
                CandidateHealthSettlement.STALE,
                self._observe(current, server_time=server_time),
            )
        return (
            CandidateHealthSettlement.APPLIED,
            self._observe(row, server_time=server_time),
        )

    async def claim_foreground_probe(
        self,
        identity: ModelCandidateIdentity,
        *,
        owner_id: str,
    ) -> ForegroundProbeResult:
        """Claim the expired candidate for one foreground half-open probe."""
        async with self.session_manager() as session:
            return await self.claim_foreground_probe_in_session(
                session,
                identity,
                owner_id=owner_id,
            )

    async def claim_foreground_probe_in_session(
        self,
        session: AsyncSession,
        identity: ModelCandidateIdentity,
        *,
        owner_id: str,
    ) -> ForegroundProbeResult:
        """Claim a foreground probe inside the caller's transaction."""
        row = await self._lock(session, identity)
        server_time = await self._database_time(session)
        if row is None:
            return ForegroundProbeResult(
                outcome=ForegroundProbeOutcome.HEALTHY,
                observation=self._observe(None, server_time=server_time),
            )
        if row.cooldown_until > server_time:
            return ForegroundProbeResult(
                outcome=ForegroundProbeOutcome.COOLDOWN,
                observation=self._observe(row, server_time=server_time),
            )
        if self._has_active_claim(row, server_time=server_time):
            return ForegroundProbeResult(
                outcome=ForegroundProbeOutcome.BUSY,
                observation=self._observe(row, server_time=server_time),
            )
        self._replace_claim(
            row,
            claim_kind=ModelCandidateClaimKind.PROBE,
            owner_id=owner_id,
            server_time=server_time,
        )
        await session.flush()
        return ForegroundProbeResult(
            outcome=ForegroundProbeOutcome.CLAIMED,
            observation=self._observe(row, server_time=server_time),
        )

    async def claim_reservation(
        self,
        identity: ModelCandidateIdentity,
        *,
        session_id: str,
    ) -> ReservationClaimResult:
        """Claim one Session-owned recovery opportunity for an unhealthy candidate."""
        async with self.session_manager() as session:
            return await self.claim_reservation_in_session(
                session,
                identity,
                session_id=session_id,
            )

    async def claim_reservation_in_session(
        self,
        session: AsyncSession,
        identity: ModelCandidateIdentity,
        *,
        session_id: str,
    ) -> ReservationClaimResult:
        """Claim a Session reservation inside the caller's transaction."""
        row = await self._lock(session, identity)
        server_time = await self._database_time(session)
        if row is None:
            return ReservationClaimResult(
                outcome=ReservationClaimOutcome.HEALTHY,
                observation=self._observe(None, server_time=server_time),
            )
        if self._has_active_claim(row, server_time=server_time):
            if (
                row.claim_kind is ModelCandidateClaimKind.RESERVATION
                and row.claim_owner_id == session_id
            ):
                return ReservationClaimResult(
                    outcome=ReservationClaimOutcome.IDEMPOTENT,
                    observation=self._observe(row, server_time=server_time),
                )
            return ReservationClaimResult(
                outcome=ReservationClaimOutcome.BUSY,
                observation=self._observe(row, server_time=server_time),
            )
        self._replace_claim(
            row,
            claim_kind=ModelCandidateClaimKind.RESERVATION,
            owner_id=session_id,
            server_time=server_time,
        )
        await session.flush()
        return ReservationClaimResult(
            outcome=ReservationClaimOutcome.CLAIMED,
            observation=self._observe(row, server_time=server_time),
        )

    async def transfer_reservation(
        self,
        identity: ModelCandidateIdentity,
        *,
        expected_generation: int,
        expected_session_id: str,
        expected_claim_token: str,
        operation_id: str,
    ) -> CandidateClaimTransfer | None:
        """Transfer an exact Session reservation to foreground probe ownership."""
        async with self.session_manager() as session:
            return await self.transfer_reservation_in_session(
                session,
                identity,
                expected_generation=expected_generation,
                expected_session_id=expected_session_id,
                expected_claim_token=expected_claim_token,
                operation_id=operation_id,
            )

    async def transfer_reservation_in_session(
        self,
        session: AsyncSession,
        identity: ModelCandidateIdentity,
        *,
        expected_generation: int,
        expected_session_id: str,
        expected_claim_token: str,
        operation_id: str,
    ) -> CandidateClaimTransfer | None:
        """Transfer a reservation inside the caller's transaction."""
        server_time = await self._database_time(session)
        claim_token = uuid7().hex
        row = (
            await session.execute(
                sa.update(RDBModelCandidateHealth)
                .where(
                    *self._identity_predicates(identity),
                    RDBModelCandidateHealth.generation == expected_generation,
                    RDBModelCandidateHealth.claim_kind
                    == ModelCandidateClaimKind.RESERVATION,
                    RDBModelCandidateHealth.claim_owner_id == expected_session_id,
                    RDBModelCandidateHealth.claim_token == expected_claim_token,
                    RDBModelCandidateHealth.claim_until > server_time,
                )
                .values(
                    claim_kind=ModelCandidateClaimKind.PROBE,
                    claim_owner_id=operation_id,
                    claim_token=claim_token,
                    claim_until=server_time + MODEL_CANDIDATE_CLAIM_LEASE,
                    updated_at=server_time,
                )
                .returning(RDBModelCandidateHealth)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return CandidateClaimTransfer(
            server_time=server_time,
            health=self._build(row),
        )

    async def cancel_reservation(
        self,
        identity: ModelCandidateIdentity,
        *,
        expected_generation: int,
        expected_session_id: str,
        expected_claim_token: str,
    ) -> CandidateHealthSettlement:
        """Clear only the exact current Session reservation."""
        async with self.session_manager() as session:
            return await self.cancel_reservation_in_session(
                session,
                identity,
                expected_generation=expected_generation,
                expected_session_id=expected_session_id,
                expected_claim_token=expected_claim_token,
            )

    async def cancel_reservation_in_session(
        self,
        session: AsyncSession,
        identity: ModelCandidateIdentity,
        *,
        expected_generation: int,
        expected_session_id: str,
        expected_claim_token: str,
    ) -> CandidateHealthSettlement:
        """Clear a reservation inside the caller's transaction."""
        return await self._clear_claim_in_session(
            session,
            identity,
            expected_generation=expected_generation,
            expected_claim_kind=ModelCandidateClaimKind.RESERVATION,
            expected_owner_id=expected_session_id,
            expected_claim_token=expected_claim_token,
            require_expired=False,
        )

    async def expire_claim(
        self,
        identity: ModelCandidateIdentity,
        *,
        expected_generation: int,
        expected_claim_kind: ModelCandidateClaimKind,
        expected_owner_id: str,
        expected_claim_token: str,
    ) -> CandidateHealthSettlement:
        """Clear an exact claim only after its database deadline."""
        async with self.session_manager() as session:
            return await self.expire_claim_in_session(
                session,
                identity,
                expected_generation=expected_generation,
                expected_claim_kind=expected_claim_kind,
                expected_owner_id=expected_owner_id,
                expected_claim_token=expected_claim_token,
            )

    async def expire_claim_in_session(
        self,
        session: AsyncSession,
        identity: ModelCandidateIdentity,
        *,
        expected_generation: int,
        expected_claim_kind: ModelCandidateClaimKind,
        expected_owner_id: str,
        expected_claim_token: str,
    ) -> CandidateHealthSettlement:
        """Expire a claim inside the caller's transaction."""
        return await self._clear_claim_in_session(
            session,
            identity,
            expected_generation=expected_generation,
            expected_claim_kind=expected_claim_kind,
            expected_owner_id=expected_owner_id,
            expected_claim_token=expected_claim_token,
            require_expired=True,
        )

    async def complete_probe_success(
        self,
        identity: ModelCandidateIdentity,
        *,
        expected_generation: int,
        expected_owner_id: str,
        expected_claim_token: str,
    ) -> CandidateHealthSettlement:
        """Delete health state only for the exact successful foreground probe."""
        async with self.session_manager() as session:
            return await self.complete_probe_success_in_session(
                session,
                identity,
                expected_generation=expected_generation,
                expected_owner_id=expected_owner_id,
                expected_claim_token=expected_claim_token,
            )

    async def complete_probe_success_in_session(
        self,
        session: AsyncSession,
        identity: ModelCandidateIdentity,
        *,
        expected_generation: int,
        expected_owner_id: str,
        expected_claim_token: str,
    ) -> CandidateHealthSettlement:
        """Delete successful probe health inside the caller's transaction."""
        deleted = await session.scalar(
            sa.delete(RDBModelCandidateHealth)
            .where(
                *self._identity_predicates(identity),
                RDBModelCandidateHealth.generation == expected_generation,
                RDBModelCandidateHealth.claim_kind == ModelCandidateClaimKind.PROBE,
                RDBModelCandidateHealth.claim_owner_id == expected_owner_id,
                RDBModelCandidateHealth.claim_token == expected_claim_token,
            )
            .returning(RDBModelCandidateHealth.generation)
        )
        if deleted is None:
            return CandidateHealthSettlement.STALE
        return CandidateHealthSettlement.APPLIED

    async def _clear_claim_in_session(
        self,
        session: AsyncSession,
        identity: ModelCandidateIdentity,
        *,
        expected_generation: int,
        expected_claim_kind: ModelCandidateClaimKind,
        expected_owner_id: str,
        expected_claim_token: str,
        require_expired: bool,
    ) -> CandidateHealthSettlement:
        server_time = await self._database_time(session)
        predicates: list[sa.ColumnElement[bool]] = [
            *self._identity_predicates(identity),
            RDBModelCandidateHealth.generation == expected_generation,
            RDBModelCandidateHealth.claim_kind == expected_claim_kind,
            RDBModelCandidateHealth.claim_owner_id == expected_owner_id,
            RDBModelCandidateHealth.claim_token == expected_claim_token,
        ]
        if require_expired:
            predicates.append(RDBModelCandidateHealth.claim_until <= server_time)
        cleared = await session.scalar(
            sa.update(RDBModelCandidateHealth)
            .where(*predicates)
            .values(
                claim_kind=None,
                claim_owner_id=None,
                claim_token=None,
                claim_until=None,
                updated_at=server_time,
            )
            .returning(RDBModelCandidateHealth.generation)
        )
        if cleared is None:
            return CandidateHealthSettlement.STALE
        return CandidateHealthSettlement.APPLIED

    async def _lock(
        self,
        session: AsyncSession,
        identity: ModelCandidateIdentity,
    ) -> RDBModelCandidateHealth | None:
        return (
            await session.execute(
                sa.select(RDBModelCandidateHealth)
                .where(*self._identity_predicates(identity))
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def _database_time(self, session: AsyncSession) -> datetime.datetime:
        server_time = await session.scalar(sa.select(sa.func.clock_timestamp()))
        if server_time is None:
            raise RuntimeError("PostgreSQL did not return candidate-health time")
        return server_time

    def _replace_claim(
        self,
        row: RDBModelCandidateHealth,
        *,
        claim_kind: ModelCandidateClaimKind,
        owner_id: str,
        server_time: datetime.datetime,
    ) -> None:
        row.generation += 1
        row.claim_kind = claim_kind
        row.claim_owner_id = owner_id
        row.claim_token = uuid7().hex
        row.claim_until = server_time + MODEL_CANDIDATE_CLAIM_LEASE
        row.updated_at = server_time

    def _has_active_claim(
        self,
        row: RDBModelCandidateHealth,
        *,
        server_time: datetime.datetime,
    ) -> bool:
        return row.claim_until is not None and row.claim_until > server_time

    def _observe(
        self,
        row: RDBModelCandidateHealth | None,
        *,
        server_time: datetime.datetime,
    ) -> ModelCandidateHealthObservation:
        if row is None:
            return ModelCandidateHealthObservation(
                server_time=server_time,
                status=ModelCandidateHealthStatus.AVAILABLE,
                health=None,
            )
        if row.cooldown_until > server_time:
            status = ModelCandidateHealthStatus.COOLDOWN
        elif self._has_active_claim(row, server_time=server_time):
            status = ModelCandidateHealthStatus.CLAIMED
        else:
            status = ModelCandidateHealthStatus.RECOVERY_PENDING
        return ModelCandidateHealthObservation(
            server_time=server_time,
            status=status,
            health=self._build(row),
        )

    def _build(
        self,
        row: RDBModelCandidateHealth,
    ) -> ModelCandidateHealthSnapshot:
        return ModelCandidateHealthSnapshot(
            identity=ModelCandidateIdentity(
                workspace_id=row.workspace_id,
                llm_provider_integration_id=row.llm_provider_integration_id,
                model_identifier=row.model_identifier,
            ),
            generation=row.generation,
            cooldown_until=row.cooldown_until,
            claim_kind=row.claim_kind,
            claim_owner_id=row.claim_owner_id,
            claim_token=row.claim_token,
            claim_until=row.claim_until,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _identity_predicates(
        self,
        identity: ModelCandidateIdentity,
    ) -> tuple[sa.ColumnElement[bool], ...]:
        return (
            RDBModelCandidateHealth.workspace_id == identity.workspace_id,
            RDBModelCandidateHealth.llm_provider_integration_id
            == identity.llm_provider_integration_id,
            RDBModelCandidateHealth.model_identifier == identity.model_identifier,
        )

    def _primary_key(
        self,
        identity: ModelCandidateIdentity,
    ) -> dict[str, str]:
        return {
            "workspace_id": identity.workspace_id,
            "llm_provider_integration_id": identity.llm_provider_integration_id,
            "model_identifier": identity.model_identifier,
        }
