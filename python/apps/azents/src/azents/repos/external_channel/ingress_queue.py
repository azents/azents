"""Persistence primitives for active External Channel ingress queues."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelIngressItemState
from azents.rdb.models.external_channel_ingress import (
    RDBExternalChannelIngressItem,
    RDBExternalChannelIngressOwner,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressAdmission,
    ExternalChannelIngressBatch,
    ExternalChannelIngressCorrelation,
    ExternalChannelIngressDiagnosticCounts,
    ExternalChannelIngressDiagnosticItem,
    ExternalChannelIngressDiagnosticSnapshot,
    ExternalChannelIngressItem,
    ExternalChannelIngressItemCreate,
    ExternalChannelIngressLeaseClaim,
    ExternalChannelIngressOwner,
    ExternalChannelIngressOwnerCreate,
)


class ExternalChannelIngressQueueRepository:
    """Own active queue admission, lease, claim, retry, and recovery state."""

    async def admit(
        self,
        session: AsyncSession,
        *,
        owner_create: ExternalChannelIngressOwnerCreate,
        item_create: ExternalChannelIngressItemCreate,
    ) -> ExternalChannelIngressAdmission:
        """Insert or reuse one compatible owner and active item."""
        await session.execute(
            pg_insert(RDBExternalChannelIngressOwner)
            .values(id=uuid7().hex, **owner_create.model_dump())
            .on_conflict_do_nothing(index_elements=["target_resource_id"])
        )
        owner = await session.scalar(
            sa.select(RDBExternalChannelIngressOwner)
            .where(
                RDBExternalChannelIngressOwner.target_resource_id
                == owner_create.target_resource_id
            )
            .with_for_update()
        )
        if owner is None:
            raise RuntimeError("External Channel ingress owner could not be created.")
        replaced_stale_owner = False
        if not self._reconcile_owner(owner, expected=owner_create):
            await session.delete(owner)
            await session.flush()
            owner = RDBExternalChannelIngressOwner(
                **owner_create.model_dump(),
            )
            session.add(owner)
            await session.flush()
            replaced_stale_owner = True
        existing = await session.scalar(
            sa.select(RDBExternalChannelIngressItem).where(
                RDBExternalChannelIngressItem.owner_id == owner.id,
                RDBExternalChannelIngressItem.deduplication_key
                == item_create.deduplication_key,
            )
        )
        created = existing is None
        if existing is None:
            existing = RDBExternalChannelIngressItem(
                **item_create.model_dump(),
                owner_id=owner.id,
                queue_key=uuid7().hex,
            )
            session.add(existing)
            await session.flush()
        return ExternalChannelIngressAdmission(
            owner=ExternalChannelIngressOwner.model_validate(owner),
            item=ExternalChannelIngressItem.model_validate(existing),
            created=created,
            replaced_stale_owner=replaced_stale_owner,
        )

    def _reconcile_owner(
        self,
        owner: RDBExternalChannelIngressOwner,
        *,
        expected: ExternalChannelIngressOwnerCreate,
    ) -> bool:
        """Reuse, adopt, or reject one active effective-conversation owner."""
        base_matches = (
            owner.connection_id == expected.connection_id
            and owner.target_resource_id == expected.target_resource_id
            and owner.route_id == expected.route_id
        )
        if not base_matches:
            return False
        owner_ready = owner.binding_id is not None and owner.session_id is not None
        expected_ready = (
            expected.binding_id is not None and expected.session_id is not None
        )
        if owner_ready:
            return expected_ready and (
                owner.binding_id == expected.binding_id
                and owner.session_id == expected.session_id
            )
        if expected_ready:
            owner.binding_id = expected.binding_id
            owner.session_id = expected.session_id
            owner.participation_setting_id = expected.participation_setting_id
            owner.participation_settings_generation = (
                expected.participation_settings_generation
            )
            owner.response_mode = expected.response_mode
            owner.preparation_next_attempt_at = None
            return True
        preparation_matches = (
            owner.participation_setting_id == expected.participation_setting_id
            and owner.participation_settings_generation
            == expected.participation_settings_generation
            and owner.response_mode is expected.response_mode
        )
        if not preparation_matches:
            return False
        return True

    async def get_active_owner(
        self,
        session: AsyncSession,
        *,
        owner_id: str,
    ) -> ExternalChannelIngressOwner | None:
        """Return one active owner lifecycle without acquiring ownership."""
        owner = await session.get(RDBExternalChannelIngressOwner, owner_id)
        return (
            ExternalChannelIngressOwner.model_validate(owner)
            if owner is not None
            else None
        )

    async def claim_lease(
        self,
        session: AsyncSession,
        *,
        owner_id: str,
        lease_owner: str,
        now: datetime.datetime,
        lease_expires_at: datetime.datetime,
    ) -> ExternalChannelIngressLeaseClaim | None:
        """Acquire or reclaim one conversation-owner drain lease."""
        owner = await session.scalar(
            sa.select(RDBExternalChannelIngressOwner)
            .where(
                RDBExternalChannelIngressOwner.id == owner_id,
                sa.or_(
                    RDBExternalChannelIngressOwner.session_id.is_not(None),
                    RDBExternalChannelIngressOwner.preparation_next_attempt_at.is_(
                        None
                    ),
                    RDBExternalChannelIngressOwner.preparation_next_attempt_at <= now,
                ),
                sa.or_(
                    RDBExternalChannelIngressOwner.lease_owner == lease_owner,
                    RDBExternalChannelIngressOwner.lease_owner.is_(None),
                    RDBExternalChannelIngressOwner.lease_expires_at < now,
                ),
            )
            .with_for_update()
        )
        if owner is None:
            return None
        owner.lease_owner = lease_owner
        owner.lease_generation += 1
        owner.lease_acquired_at = now
        owner.lease_expires_at = lease_expires_at
        owner.current_batch_id = None
        owner.current_batch_started_at = None
        await session.execute(
            sa.update(RDBExternalChannelIngressItem)
            .where(
                RDBExternalChannelIngressItem.owner_id == owner_id,
                RDBExternalChannelIngressItem.state
                == ExternalChannelIngressItemState.PROCESSING,
            )
            .values(
                state=ExternalChannelIngressItemState.PENDING,
                processing_owner=None,
                processing_generation=None,
                batch_id=None,
            )
        )
        await session.flush()
        await session.refresh(owner, attribute_names=["updated_at"])
        return ExternalChannelIngressLeaseClaim(
            owner=ExternalChannelIngressOwner.model_validate(owner)
        )

    async def lock_leased_owner(
        self,
        session: AsyncSession,
        *,
        owner_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
    ) -> RDBExternalChannelIngressOwner | None:
        """Lock one current owner under its unexpired lease fence."""
        return await session.scalar(
            sa.select(RDBExternalChannelIngressOwner)
            .where(
                RDBExternalChannelIngressOwner.id == owner_id,
                RDBExternalChannelIngressOwner.lease_owner == lease_owner,
                RDBExternalChannelIngressOwner.lease_generation == lease_generation,
                RDBExternalChannelIngressOwner.lease_expires_at >= now,
            )
            .with_for_update()
        )

    async def lock_first_authoritative_item(
        self,
        session: AsyncSession,
        *,
        owner_id: str,
    ) -> ExternalChannelIngressItem | None:
        """Lock the oldest retained trigger while the caller owns the owner lease."""
        item = await session.scalar(
            sa.select(RDBExternalChannelIngressItem)
            .where(RDBExternalChannelIngressItem.owner_id == owner_id)
            .order_by(RDBExternalChannelIngressItem.queue_key)
            .limit(1)
            .with_for_update()
        )
        return (
            ExternalChannelIngressItem.model_validate(item)
            if item is not None
            else None
        )

    async def mark_owner_ready(
        self,
        session: AsyncSession,
        *,
        owner: RDBExternalChannelIngressOwner,
        binding_id: str,
        session_id: str,
        initial_title_eligible: bool,
    ) -> None:
        """Record the immutable Binding and Session after provider preparation."""
        owner.binding_id = binding_id
        owner.session_id = session_id
        owner.preparation_next_attempt_at = None
        if initial_title_eligible:
            first_invocation = await session.scalar(
                sa.select(RDBExternalChannelIngressItem)
                .where(
                    RDBExternalChannelIngressItem.owner_id == owner.id,
                    RDBExternalChannelIngressItem.invocation.is_(True),
                )
                .order_by(RDBExternalChannelIngressItem.queue_key)
                .limit(1)
                .with_for_update()
            )
            if first_invocation is not None:
                first_invocation.initial_title_eligible = True
        await session.flush()

    async def schedule_preparation_retry(
        self,
        session: AsyncSession,
        *,
        owner: RDBExternalChannelIngressOwner,
        next_attempt_at: datetime.datetime,
    ) -> None:
        """Retain all items while releasing a failed owner preparation attempt."""
        owner.preparation_attempt_count += 1
        owner.preparation_next_attempt_at = next_attempt_at
        owner.lease_owner = None
        owner.lease_acquired_at = None
        owner.lease_expires_at = None
        owner.current_batch_id = None
        owner.current_batch_started_at = None
        await session.flush()

    async def delete_owner(
        self,
        session: AsyncSession,
        *,
        owner: RDBExternalChannelIngressOwner,
    ) -> None:
        """Delete one terminal active owner and all retained items."""
        await session.delete(owner)
        await session.flush()

    async def claim_due_batch(
        self,
        session: AsyncSession,
        *,
        owner_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
    ) -> ExternalChannelIngressBatch | None:
        """Claim the first single item or a later batch of at most ten."""
        owner = await self.lock_leased_owner(
            session,
            owner_id=owner_id,
            lease_owner=lease_owner,
            lease_generation=lease_generation,
            now=now,
        )
        if owner is None or owner.session_id is None or owner.binding_id is None:
            return None
        limit = 1 if owner.first_batch_pending else 10
        items = list(
            await session.scalars(
                sa.select(RDBExternalChannelIngressItem)
                .where(
                    RDBExternalChannelIngressItem.owner_id == owner_id,
                    sa.or_(
                        RDBExternalChannelIngressItem.state
                        == ExternalChannelIngressItemState.PENDING,
                        sa.and_(
                            RDBExternalChannelIngressItem.state
                            == ExternalChannelIngressItemState.RETRY_WAITING,
                            RDBExternalChannelIngressItem.next_attempt_at <= now,
                        ),
                    ),
                )
                .order_by(RDBExternalChannelIngressItem.queue_key)
                .limit(limit)
                .with_for_update()
            )
        )
        if not items:
            return None
        batch_id = uuid7().hex
        for item in items:
            item.state = ExternalChannelIngressItemState.PROCESSING
            item.attempt_count += 1
            item.next_attempt_at = None
            item.processing_owner = lease_owner
            item.processing_generation = lease_generation
            item.batch_id = batch_id
        owner.first_batch_pending = False
        owner.current_batch_id = batch_id
        owner.current_batch_started_at = now
        await session.flush()
        for item in items:
            await session.refresh(item, attribute_names=["updated_at"])
        return ExternalChannelIngressBatch(
            owner_id=owner_id,
            target_resource_id=owner.target_resource_id,
            binding_id=owner.binding_id,
            session_id=owner.session_id,
            batch_id=batch_id,
            lease_owner=lease_owner,
            lease_generation=lease_generation,
            items=tuple(
                ExternalChannelIngressItem.model_validate(item) for item in items
            ),
        )

    async def lock_claimed_batch(
        self,
        session: AsyncSession,
        *,
        claim: ExternalChannelIngressBatch,
        now: datetime.datetime,
    ) -> (
        tuple[
            RDBExternalChannelIngressOwner,
            list[RDBExternalChannelIngressItem],
        ]
        | None
    ):
        """Lock and validate one current processing batch."""
        owner = await session.scalar(
            sa.select(RDBExternalChannelIngressOwner)
            .where(
                RDBExternalChannelIngressOwner.id == claim.owner_id,
                RDBExternalChannelIngressOwner.session_id == claim.session_id,
                RDBExternalChannelIngressOwner.lease_owner == claim.lease_owner,
                RDBExternalChannelIngressOwner.lease_generation
                == claim.lease_generation,
                RDBExternalChannelIngressOwner.lease_expires_at >= now,
                RDBExternalChannelIngressOwner.current_batch_id == claim.batch_id,
            )
            .with_for_update()
        )
        if owner is None:
            return None
        item_ids = [item.id for item in claim.items]
        items = list(
            await session.scalars(
                sa.select(RDBExternalChannelIngressItem)
                .where(
                    RDBExternalChannelIngressItem.id.in_(item_ids),
                    RDBExternalChannelIngressItem.owner_id == claim.owner_id,
                    RDBExternalChannelIngressItem.state
                    == ExternalChannelIngressItemState.PROCESSING,
                    RDBExternalChannelIngressItem.processing_owner == claim.lease_owner,
                    RDBExternalChannelIngressItem.processing_generation
                    == claim.lease_generation,
                    RDBExternalChannelIngressItem.batch_id == claim.batch_id,
                )
                .order_by(RDBExternalChannelIngressItem.queue_key)
                .with_for_update()
            )
        )
        if len(items) != len(item_ids):
            return None
        return owner, items

    async def list_active_correlations(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        conversation_position_id: str,
    ) -> dict[str, ExternalChannelIngressCorrelation]:
        """Map active provider message identities to invocation identities."""
        rows = await session.execute(
            sa.select(
                RDBExternalChannelIngressItem.trigger_provider_message_key,
                RDBExternalChannelIngressItem.invocation_id,
                RDBExternalChannelIngressItem.principal_id,
            ).where(
                RDBExternalChannelIngressItem.connection_id == connection_id,
                RDBExternalChannelIngressItem.conversation_position_id
                == conversation_position_id,
            )
        )
        return {
            provider_message_key: ExternalChannelIngressCorrelation(
                invocation_id=invocation_id,
                principal_id=principal_id,
            )
            for provider_message_key, invocation_id, principal_id in rows.tuples()
        }

    async def reset_batch_for_coordination(
        self,
        session: AsyncSession,
        *,
        owner: RDBExternalChannelIngressOwner,
        items: list[RDBExternalChannelIngressItem],
    ) -> None:
        """Return a stale preparation to pending without consuming provider attempts."""
        for item in items:
            item.state = ExternalChannelIngressItemState.PENDING
            item.attempt_count -= 1
            item.processing_owner = None
            item.processing_generation = None
            item.batch_id = None
        owner.current_batch_id = None
        owner.current_batch_started_at = None
        await session.flush()

    async def move_to_retry_tail(
        self,
        session: AsyncSession,
        *,
        item: RDBExternalChannelIngressItem,
        next_attempt_at: datetime.datetime,
    ) -> None:
        """Preserve item identity and age while moving retryable work to the tail."""
        item.queue_key = uuid7().hex
        item.state = ExternalChannelIngressItemState.RETRY_WAITING
        item.next_attempt_at = next_attempt_at
        item.processing_owner = None
        item.processing_generation = None
        item.batch_id = None
        await session.flush()

    async def finish_batch(
        self,
        session: AsyncSession,
        *,
        owner: RDBExternalChannelIngressOwner,
        deleted_items: list[RDBExternalChannelIngressItem],
    ) -> None:
        """Delete completed active rows and retain or delete their owner."""
        for item in deleted_items:
            await session.delete(item)
        await session.flush()
        remaining = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBExternalChannelIngressItem)
            .where(RDBExternalChannelIngressItem.owner_id == owner.id)
        )
        if remaining == 0:
            await session.delete(owner)
            return
        owner.current_batch_id = None
        owner.current_batch_started_at = None
        await session.flush()

    async def release_lease(
        self,
        session: AsyncSession,
        *,
        owner_id: str,
        lease_owner: str,
        lease_generation: int,
    ) -> bool:
        """Release one current owner lease while retaining active queue state."""
        result = await session.execute(
            sa.update(RDBExternalChannelIngressOwner)
            .where(
                RDBExternalChannelIngressOwner.id == owner_id,
                RDBExternalChannelIngressOwner.lease_owner == lease_owner,
                RDBExternalChannelIngressOwner.lease_generation == lease_generation,
            )
            .values(
                lease_owner=None,
                lease_acquired_at=None,
                lease_expires_at=None,
                current_batch_id=None,
                current_batch_started_at=None,
            )
            .returning(RDBExternalChannelIngressOwner.id)
        )
        return result.scalar_one_or_none() is not None

    async def list_recoverable_owners(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        limit: int,
    ) -> list[ExternalChannelIngressOwner]:
        """List bounded active owners whose preparation or item work is due."""
        due_item = sa.and_(
            RDBExternalChannelIngressOwner.session_id.is_not(None),
            sa.exists(
                sa.select(RDBExternalChannelIngressItem.id).where(
                    RDBExternalChannelIngressItem.owner_id
                    == RDBExternalChannelIngressOwner.id,
                    sa.or_(
                        RDBExternalChannelIngressItem.state
                        == ExternalChannelIngressItemState.PENDING,
                        sa.and_(
                            RDBExternalChannelIngressItem.state
                            == ExternalChannelIngressItemState.RETRY_WAITING,
                            RDBExternalChannelIngressItem.next_attempt_at <= now,
                        ),
                        sa.and_(
                            RDBExternalChannelIngressItem.state
                            == ExternalChannelIngressItemState.PROCESSING,
                            sa.or_(
                                RDBExternalChannelIngressOwner.lease_owner.is_(None),
                                RDBExternalChannelIngressOwner.lease_expires_at < now,
                            ),
                        ),
                    ),
                )
            ),
        )
        preparation_due = sa.and_(
            RDBExternalChannelIngressOwner.session_id.is_(None),
            sa.or_(
                RDBExternalChannelIngressOwner.preparation_next_attempt_at.is_(None),
                RDBExternalChannelIngressOwner.preparation_next_attempt_at <= now,
            ),
        )
        result = await session.scalars(
            sa.select(RDBExternalChannelIngressOwner)
            .where(
                sa.or_(
                    RDBExternalChannelIngressOwner.lease_owner.is_(None),
                    RDBExternalChannelIngressOwner.lease_expires_at < now,
                ),
                sa.or_(preparation_due, due_item),
            )
            .order_by(RDBExternalChannelIngressOwner.updated_at)
            .limit(limit)
        )
        return [ExternalChannelIngressOwner.model_validate(owner) for owner in result]

    async def inspect_active(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        limit: int,
    ) -> ExternalChannelIngressDiagnosticSnapshot:
        """Return bounded content-free diagnostics for active ingress state."""
        if limit < 1 or limit > 1000:
            raise ValueError("Active ingress diagnostic limit must be from 1 to 1000.")
        summary = (
            await session.execute(
                sa.select(
                    sa.func.count(sa.distinct(RDBExternalChannelIngressItem.owner_id)),
                    sa.func.count().filter(
                        RDBExternalChannelIngressItem.state
                        == ExternalChannelIngressItemState.PENDING
                    ),
                    sa.func.count().filter(
                        RDBExternalChannelIngressItem.state
                        == ExternalChannelIngressItemState.PROCESSING
                    ),
                    sa.func.count().filter(
                        RDBExternalChannelIngressItem.state
                        == ExternalChannelIngressItemState.RETRY_WAITING
                    ),
                    sa.func.min(RDBExternalChannelIngressItem.created_at),
                    sa.func.count(),
                )
            )
        ).one()
        owner_count, pending, processing, retry_waiting, oldest_created_at, total = (
            summary
        )
        rows = (
            await session.execute(
                sa.select(
                    RDBExternalChannelIngressItem,
                    RDBExternalChannelIngressOwner,
                )
                .join(
                    RDBExternalChannelIngressOwner,
                    RDBExternalChannelIngressOwner.id
                    == RDBExternalChannelIngressItem.owner_id,
                )
                .order_by(RDBExternalChannelIngressItem.queue_key)
                .limit(limit)
            )
        ).tuples()
        return ExternalChannelIngressDiagnosticSnapshot(
            observed_at=now,
            owner_count=int(owner_count or 0),
            counts=ExternalChannelIngressDiagnosticCounts(
                pending=int(pending or 0),
                processing=int(processing or 0),
                retry_waiting=int(retry_waiting or 0),
            ),
            oldest_queue_age_seconds=(
                None
                if oldest_created_at is None
                else max(0, int((now - oldest_created_at).total_seconds()))
            ),
            items=tuple(
                ExternalChannelIngressDiagnosticItem(
                    id=item.id,
                    owner_id=owner.id,
                    session_id=owner.session_id,
                    provider=item.provider,
                    connection_id=item.connection_id,
                    owner_ready=owner.session_id is not None,
                    preparation_attempt_count=owner.preparation_attempt_count,
                    preparation_next_attempt_at=owner.preparation_next_attempt_at,
                    state=item.state,
                    attempt_count=item.attempt_count,
                    batch_id=item.batch_id,
                    next_attempt_at=item.next_attempt_at,
                    processing_owner=item.processing_owner,
                    processing_generation=item.processing_generation,
                    item_age_seconds=max(
                        0,
                        int((now - item.created_at).total_seconds()),
                    ),
                    owner_age_seconds=max(
                        0,
                        int((now - owner.created_at).total_seconds()),
                    ),
                    lease_owner=owner.lease_owner,
                    lease_generation=owner.lease_generation,
                    lease_expires_at=owner.lease_expires_at,
                    current_batch_id=owner.current_batch_id,
                    current_batch_started_at=owner.current_batch_started_at,
                )
                for item, owner in rows
            ),
            truncated=int(total or 0) > limit,
        )
