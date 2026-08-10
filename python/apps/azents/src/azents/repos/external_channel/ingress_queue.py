"""Persistence primitives for active External Channel ingress queues."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelIngressItemState
from azents.rdb.models.external_channel_ingress import (
    RDBExternalChannelIngressItem,
    RDBExternalChannelIngressSession,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressAdmission,
    ExternalChannelIngressBatch,
    ExternalChannelIngressCorrelation,
    ExternalChannelIngressItem,
    ExternalChannelIngressItemCreate,
    ExternalChannelIngressLeaseClaim,
    ExternalChannelIngressSession,
)


class ExternalChannelIngressQueueRepository:
    """Own active queue admission, lease, claim, retry, and recovery state."""

    async def admit(
        self,
        session: AsyncSession,
        *,
        create: ExternalChannelIngressItemCreate,
    ) -> ExternalChannelIngressAdmission:
        """Insert or reuse one active item while serializing drain deletion."""
        await session.execute(
            pg_insert(RDBExternalChannelIngressSession)
            .values(session_id=create.session_id)
            .on_conflict_do_nothing(index_elements=["session_id"])
        )
        drain = await session.scalar(
            sa.select(RDBExternalChannelIngressSession)
            .where(RDBExternalChannelIngressSession.session_id == create.session_id)
            .with_for_update()
        )
        if drain is None:
            raise RuntimeError("External Channel ingress Session could not be created.")
        existing = await session.scalar(
            sa.select(RDBExternalChannelIngressItem).where(
                RDBExternalChannelIngressItem.session_id == create.session_id,
                RDBExternalChannelIngressItem.deduplication_key
                == create.deduplication_key,
            )
        )
        created = existing is None
        if existing is None:
            values = create.model_dump()
            existing = RDBExternalChannelIngressItem(
                **values,
                queue_key=uuid7().hex,
            )
            session.add(existing)
            await session.flush()
        return ExternalChannelIngressAdmission(
            session=ExternalChannelIngressSession.model_validate(drain),
            item=ExternalChannelIngressItem.model_validate(existing),
            created=created,
        )

    async def get_active_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> ExternalChannelIngressSession | None:
        """Return one active drain lifecycle without acquiring ownership."""
        drain = await session.scalar(
            sa.select(RDBExternalChannelIngressSession).where(
                RDBExternalChannelIngressSession.session_id == session_id
            )
        )
        return (
            ExternalChannelIngressSession.model_validate(drain)
            if drain is not None
            else None
        )

    async def claim_lease(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        lease_owner: str,
        now: datetime.datetime,
        lease_expires_at: datetime.datetime,
    ) -> ExternalChannelIngressLeaseClaim | None:
        """Acquire or reclaim one Session drain lease."""
        drain = await session.scalar(
            sa.select(RDBExternalChannelIngressSession)
            .where(
                RDBExternalChannelIngressSession.session_id == session_id,
                sa.or_(
                    RDBExternalChannelIngressSession.lease_owner == lease_owner,
                    RDBExternalChannelIngressSession.lease_owner.is_(None),
                    RDBExternalChannelIngressSession.lease_expires_at < now,
                ),
            )
            .with_for_update()
        )
        if drain is None:
            return None
        drain.lease_owner = lease_owner
        drain.lease_generation += 1
        drain.lease_acquired_at = now
        drain.lease_expires_at = lease_expires_at
        drain.current_batch_id = None
        drain.current_batch_started_at = None
        await session.execute(
            sa.update(RDBExternalChannelIngressItem)
            .where(
                RDBExternalChannelIngressItem.session_id == session_id,
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
        await session.refresh(drain, attribute_names=["updated_at"])
        return ExternalChannelIngressLeaseClaim(
            session=ExternalChannelIngressSession.model_validate(drain)
        )

    async def claim_due_batch(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
    ) -> ExternalChannelIngressBatch | None:
        """Claim the first single item or a later batch of at most ten."""
        drain = await session.scalar(
            sa.select(RDBExternalChannelIngressSession)
            .where(
                RDBExternalChannelIngressSession.session_id == session_id,
                RDBExternalChannelIngressSession.lease_owner == lease_owner,
                RDBExternalChannelIngressSession.lease_generation == lease_generation,
                RDBExternalChannelIngressSession.lease_expires_at >= now,
            )
            .with_for_update()
        )
        if drain is None:
            return None
        limit = 1 if drain.first_batch_pending else 10
        items = list(
            await session.scalars(
                sa.select(RDBExternalChannelIngressItem)
                .where(
                    RDBExternalChannelIngressItem.session_id == session_id,
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
        drain.first_batch_pending = False
        drain.current_batch_id = batch_id
        drain.current_batch_started_at = now
        await session.flush()
        for item in items:
            await session.refresh(item, attribute_names=["updated_at"])
        return ExternalChannelIngressBatch(
            session_id=session_id,
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
            RDBExternalChannelIngressSession,
            list[RDBExternalChannelIngressItem],
        ]
        | None
    ):
        """Lock and validate one current processing batch."""
        drain = await session.scalar(
            sa.select(RDBExternalChannelIngressSession)
            .where(
                RDBExternalChannelIngressSession.session_id == claim.session_id,
                RDBExternalChannelIngressSession.lease_owner == claim.lease_owner,
                RDBExternalChannelIngressSession.lease_generation
                == claim.lease_generation,
                RDBExternalChannelIngressSession.lease_expires_at >= now,
                RDBExternalChannelIngressSession.current_batch_id == claim.batch_id,
            )
            .with_for_update()
        )
        if drain is None:
            return None
        item_ids = [item.id for item in claim.items]
        items = list(
            await session.scalars(
                sa.select(RDBExternalChannelIngressItem)
                .where(
                    RDBExternalChannelIngressItem.id.in_(item_ids),
                    RDBExternalChannelIngressItem.session_id == claim.session_id,
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
        return drain, items

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
                RDBExternalChannelIngressItem.invocation.is_(True),
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
        drain: RDBExternalChannelIngressSession,
        items: list[RDBExternalChannelIngressItem],
    ) -> None:
        """Return a stale preparation to pending without consuming provider attempts."""
        for item in items:
            item.state = ExternalChannelIngressItemState.PENDING
            item.attempt_count -= 1
            item.processing_owner = None
            item.processing_generation = None
            item.batch_id = None
        drain.current_batch_id = None
        drain.current_batch_started_at = None
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
        drain: RDBExternalChannelIngressSession,
        deleted_items: list[RDBExternalChannelIngressItem],
    ) -> None:
        """Delete completed active rows and retain or delete their drain owner."""
        for item in deleted_items:
            await session.delete(item)
        await session.flush()
        remaining = await session.scalar(
            sa.select(sa.func.count())
            .select_from(RDBExternalChannelIngressItem)
            .where(RDBExternalChannelIngressItem.session_id == drain.session_id)
        )
        if remaining == 0:
            await session.delete(drain)
            return
        drain.current_batch_id = None
        drain.current_batch_started_at = None
        await session.flush()

    async def release_lease(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        lease_owner: str,
        lease_generation: int,
    ) -> bool:
        """Release one current drain lease while retaining active queue state."""
        result = await session.execute(
            sa.update(RDBExternalChannelIngressSession)
            .where(
                RDBExternalChannelIngressSession.session_id == session_id,
                RDBExternalChannelIngressSession.lease_owner == lease_owner,
                RDBExternalChannelIngressSession.lease_generation == lease_generation,
            )
            .values(
                lease_owner=None,
                lease_acquired_at=None,
                lease_expires_at=None,
                current_batch_id=None,
                current_batch_started_at=None,
            )
            .returning(RDBExternalChannelIngressSession.session_id)
        )
        return result.scalar_one_or_none() is not None

    async def list_recoverable_sessions(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        limit: int,
    ) -> list[ExternalChannelIngressSession]:
        """List bounded active Session domain state whose work is due."""
        due_item = sa.exists(
            sa.select(RDBExternalChannelIngressItem.id).where(
                RDBExternalChannelIngressItem.session_id
                == RDBExternalChannelIngressSession.session_id,
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
                            RDBExternalChannelIngressSession.lease_owner.is_(None),
                            RDBExternalChannelIngressSession.lease_expires_at < now,
                        ),
                    ),
                ),
            )
        )
        result = await session.scalars(
            sa.select(RDBExternalChannelIngressSession)
            .where(
                sa.or_(
                    RDBExternalChannelIngressSession.lease_owner.is_(None),
                    RDBExternalChannelIngressSession.lease_expires_at < now,
                ),
                due_item,
            )
            .order_by(RDBExternalChannelIngressSession.updated_at)
            .limit(limit)
        )
        return [ExternalChannelIngressSession.model_validate(drain) for drain in result]
