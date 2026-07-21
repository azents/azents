"""External Channel persistence repository."""

from collections.abc import Awaitable, Callable
from typing import TypeVar

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelBindingStatus,
    ExternalChannelRouteStatus,
    ExternalChannelWorkStatus,
)
from azents.rdb.models.base import RDBModel
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessGrant,
    RDBExternalChannelAccessRequest,
    RDBExternalChannelAction,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelBlock,
    RDBExternalChannelConnection,
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelEvent,
    RDBExternalChannelInvocationBatch,
    RDBExternalChannelInvocationBatchItem,
    RDBExternalChannelMessage,
    RDBExternalChannelMessageRevision,
    RDBExternalChannelPendingContext,
    RDBExternalChannelPrincipal,
    RDBExternalChannelResource,
    RDBExternalChannelWork,
)

from .data import (
    ExternalChannelAccessGrant,
    ExternalChannelAccessGrantCreate,
    ExternalChannelAccessRequest,
    ExternalChannelAccessRequestCreate,
    ExternalChannelAction,
    ExternalChannelActionCreate,
    ExternalChannelAgentRoute,
    ExternalChannelAgentRouteCreate,
    ExternalChannelBinding,
    ExternalChannelBindingCreate,
    ExternalChannelBlock,
    ExternalChannelBlockCreate,
    ExternalChannelConnection,
    ExternalChannelConnectionCreate,
    ExternalChannelDeliveryAttempt,
    ExternalChannelDeliveryAttemptCreate,
    ExternalChannelEvent,
    ExternalChannelEventAdmission,
    ExternalChannelEventCreate,
    ExternalChannelInvocationBatch,
    ExternalChannelInvocationBatchCreate,
    ExternalChannelInvocationBatchItem,
    ExternalChannelInvocationBatchItemCreate,
    ExternalChannelMessage,
    ExternalChannelMessageCreate,
    ExternalChannelMessageRevision,
    ExternalChannelMessageRevisionCreate,
    ExternalChannelPendingContext,
    ExternalChannelPendingContextCreate,
    ExternalChannelPrincipal,
    ExternalChannelPrincipalCreate,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
    ExternalChannelWork,
    ExternalChannelWorkCreate,
)

_RecordT = TypeVar("_RecordT", bound=BaseModel)


class ExternalChannelRepository:
    """Provider-generic SQLAlchemy repository for External Channel state."""

    async def create_connection(
        self,
        session: AsyncSession,
        create: ExternalChannelConnectionCreate,
    ) -> ExternalChannelConnection:
        """Create a Workspace-owned provider connection."""
        return ExternalChannelConnection.model_validate(
            await self._create(session, RDBExternalChannelConnection, create)
        )

    async def get_connection(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnection | None:
        """Fetch a connection by its stable identity."""
        rdb = await session.get(RDBExternalChannelConnection, connection_id)
        return self._as(ExternalChannelConnection, rdb)

    async def get_connection_by_http_callback_selector_hash(
        self,
        session: AsyncSession,
        *,
        http_callback_selector_hash: str,
    ) -> ExternalChannelConnection | None:
        """Fetch the sole HTTP callback candidate before signature verification."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelConnection).where(
                RDBExternalChannelConnection.http_callback_selector_hash
                == http_callback_selector_hash
            )
        )
        return self._as(ExternalChannelConnection, rdb)

    async def lock_connection(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnection | None:
        """Lock one connection for a connection-state transition."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(RDBExternalChannelConnection.id == connection_id)
            .with_for_update()
        )
        return self._as(ExternalChannelConnection, rdb)

    async def create_agent_route(
        self,
        session: AsyncSession,
        create: ExternalChannelAgentRouteCreate,
    ) -> ExternalChannelAgentRoute:
        """Create a route from a connection to one Agent."""
        return ExternalChannelAgentRoute.model_validate(
            await self._create(session, RDBExternalChannelAgentRoute, create)
        )

    async def get_active_route_by_connection_id(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelAgentRoute | None:
        """Fetch the active route selected for a connection."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelAgentRoute).where(
                RDBExternalChannelAgentRoute.connection_id == connection_id,
                RDBExternalChannelAgentRoute.status
                == ExternalChannelRouteStatus.ACTIVE,
            )
        )
        return self._as(ExternalChannelAgentRoute, rdb)

    async def create_resource_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelResourceCreate,
    ) -> ExternalChannelResource:
        """Create or return one canonical provider resource."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelResource,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelResource).where(
                    RDBExternalChannelResource.connection_id == create.connection_id,
                    RDBExternalChannelResource.resource_type == create.resource_type,
                    RDBExternalChannelResource.provider_resource_key
                    == create.provider_resource_key,
                )
            ),
        )
        return ExternalChannelResource.model_validate(rdb)

    async def admit_event(
        self,
        session: AsyncSession,
        create: ExternalChannelEventCreate,
    ) -> ExternalChannelEventAdmission:
        """Atomically admit one provider event or return its prior admission."""
        result = await session.execute(
            pg_insert(RDBExternalChannelEvent)
            .values(**create.model_dump())
            .on_conflict_do_nothing(
                constraint="uq_external_channel_events_connection_provider_event"
            )
            .returning(RDBExternalChannelEvent)
        )
        rdb = result.scalar_one_or_none()
        if rdb is not None:
            await session.flush()
            return ExternalChannelEventAdmission(
                event=ExternalChannelEvent.model_validate(rdb),
                created=True,
            )
        existing = await self.get_event_by_provider_identity(
            session,
            connection_id=create.connection_id,
            provider_event_id=create.provider_event_id,
        )
        if existing is None:
            raise RuntimeError("External Channel event admission lookup failed")
        return ExternalChannelEventAdmission(event=existing, created=False)

    async def get_event_by_provider_identity(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        provider_event_id: str,
    ) -> ExternalChannelEvent | None:
        """Fetch a provider event by its durable connection-scoped identity."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelEvent).where(
                RDBExternalChannelEvent.connection_id == connection_id,
                RDBExternalChannelEvent.provider_event_id == provider_event_id,
            )
        )
        return self._as(ExternalChannelEvent, rdb)

    async def lock_event(
        self,
        session: AsyncSession,
        *,
        event_id: str,
    ) -> ExternalChannelEvent | None:
        """Lock one admitted event before a processor state transition."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelEvent)
            .where(RDBExternalChannelEvent.id == event_id)
            .with_for_update()
        )
        return self._as(ExternalChannelEvent, rdb)

    async def create_principal_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelPrincipalCreate,
    ) -> ExternalChannelPrincipal:
        """Create or return a canonical provider principal."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelPrincipal,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelPrincipal).where(
                    RDBExternalChannelPrincipal.provider == create.provider,
                    RDBExternalChannelPrincipal.provider_tenant_id
                    == create.provider_tenant_id,
                    RDBExternalChannelPrincipal.provider_user_id
                    == create.provider_user_id,
                )
            ),
        )
        return ExternalChannelPrincipal.model_validate(rdb)

    async def create_message_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelMessageCreate,
    ) -> ExternalChannelMessage:
        """Create or return a canonical external message."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelMessage,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelMessage).where(
                    RDBExternalChannelMessage.resource_id == create.resource_id,
                    RDBExternalChannelMessage.provider_message_key
                    == create.provider_message_key,
                )
            ),
        )
        return ExternalChannelMessage.model_validate(rdb)

    async def create_message_revision_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelMessageRevisionCreate,
    ) -> ExternalChannelMessageRevision:
        """Create or return an immutable message revision."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelMessageRevision,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelMessageRevision).where(
                    RDBExternalChannelMessageRevision.message_id == create.message_id,
                    RDBExternalChannelMessageRevision.revision_key
                    == create.revision_key,
                )
            ),
        )
        return ExternalChannelMessageRevision.model_validate(rdb)

    async def create_pending_context_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelPendingContextCreate,
    ) -> ExternalChannelPendingContext:
        """Create or return pending context for one message revision."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelPendingContext,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelPendingContext).where(
                    RDBExternalChannelPendingContext.resource_id == create.resource_id,
                    RDBExternalChannelPendingContext.message_revision_id
                    == create.message_revision_id,
                )
            ),
        )
        return ExternalChannelPendingContext.model_validate(rdb)

    async def create_binding_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelBindingCreate,
    ) -> ExternalChannelBinding:
        """Create or return the active binding for one resource and route."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelBinding,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelBinding).where(
                    RDBExternalChannelBinding.resource_id == create.resource_id,
                    RDBExternalChannelBinding.route_id == create.route_id,
                    RDBExternalChannelBinding.status
                    == ExternalChannelBindingStatus.ACTIVE,
                )
            ),
        )
        return ExternalChannelBinding.model_validate(rdb)

    async def lock_binding(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
    ) -> ExternalChannelBinding | None:
        """Lock one Session-bound binding for an atomic transition."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .where(RDBExternalChannelBinding.id == binding_id)
            .with_for_update()
        )
        return self._as(ExternalChannelBinding, rdb)

    async def create_invocation_batch_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelInvocationBatchCreate,
    ) -> ExternalChannelInvocationBatch:
        """Create or return a binding-scoped trigger invocation batch."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelInvocationBatch,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelInvocationBatch).where(
                    RDBExternalChannelInvocationBatch.binding_id == create.binding_id,
                    RDBExternalChannelInvocationBatch.trigger_message_id
                    == create.trigger_message_id,
                )
            ),
        )
        return ExternalChannelInvocationBatch.model_validate(rdb)

    async def create_invocation_batch_item_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelInvocationBatchItemCreate,
    ) -> ExternalChannelInvocationBatchItem:
        """Create or return an immutable batch revision membership item."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelInvocationBatchItem,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelInvocationBatchItem).where(
                    RDBExternalChannelInvocationBatchItem.batch_id == create.batch_id,
                    RDBExternalChannelInvocationBatchItem.message_revision_id
                    == create.message_revision_id,
                )
            ),
        )
        return ExternalChannelInvocationBatchItem.model_validate(rdb)

    async def create_access_request_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelAccessRequestCreate,
    ) -> ExternalChannelAccessRequest:
        """Create or return an access request for a source message."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelAccessRequest,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelAccessRequest).where(
                    RDBExternalChannelAccessRequest.route_id == create.route_id,
                    RDBExternalChannelAccessRequest.source_message_id
                    == create.source_message_id,
                )
            ),
        )
        return ExternalChannelAccessRequest.model_validate(rdb)

    async def create_access_grant(
        self,
        session: AsyncSession,
        create: ExternalChannelAccessGrantCreate,
    ) -> ExternalChannelAccessGrant:
        """Create one durable access grant."""
        return ExternalChannelAccessGrant.model_validate(
            await self._create(session, RDBExternalChannelAccessGrant, create)
        )

    async def create_block_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelBlockCreate,
    ) -> ExternalChannelBlock:
        """Create or return the unique Agent-and-principal block record."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelBlock,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelBlock).where(
                    RDBExternalChannelBlock.agent_id == create.agent_id,
                    RDBExternalChannelBlock.principal_id == create.principal_id,
                )
            ),
        )
        return ExternalChannelBlock.model_validate(rdb)

    async def create_work_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelWorkCreate,
    ) -> ExternalChannelWork:
        """Create or return active Channel Work for one binding."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelWork,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelWork).where(
                    RDBExternalChannelWork.binding_id == create.binding_id,
                    RDBExternalChannelWork.status == ExternalChannelWorkStatus.ACTIVE,
                )
            ),
        )
        return ExternalChannelWork.model_validate(rdb)

    async def lock_work_by_binding_id(
        self,
        session: AsyncSession,
        *,
        binding_id: str,
    ) -> ExternalChannelWork | None:
        """Lock the active Channel Work for one binding."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelWork)
            .where(
                RDBExternalChannelWork.binding_id == binding_id,
                RDBExternalChannelWork.status == ExternalChannelWorkStatus.ACTIVE,
            )
            .with_for_update()
        )
        return self._as(ExternalChannelWork, rdb)

    async def create_action_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelActionCreate,
    ) -> ExternalChannelAction:
        """Create or return the committed action for one durable tool call."""
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelAction,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelAction).where(
                    RDBExternalChannelAction.agent_session_id
                    == create.agent_session_id,
                    RDBExternalChannelAction.client_tool_call_id
                    == create.client_tool_call_id,
                )
            ),
        )
        return ExternalChannelAction.model_validate(rdb)

    async def create_delivery_attempt_idempotent(
        self,
        session: AsyncSession,
        create: ExternalChannelDeliveryAttemptCreate,
    ) -> ExternalChannelDeliveryAttempt:
        """Create or return a durable at-most-once provider operation intent."""
        predicate = [
            RDBExternalChannelDeliveryAttempt.origin_type == create.origin_type,
            RDBExternalChannelDeliveryAttempt.origin_id == create.origin_id,
            RDBExternalChannelDeliveryAttempt.operation == create.operation,
        ]
        if create.binding_id is None:
            predicate.append(RDBExternalChannelDeliveryAttempt.binding_id.is_(None))
        else:
            predicate.append(
                RDBExternalChannelDeliveryAttempt.binding_id == create.binding_id
            )
        rdb = await self._insert_or_lookup(
            session,
            RDBExternalChannelDeliveryAttempt,
            create,
            lambda: session.scalar(
                sa.select(RDBExternalChannelDeliveryAttempt).where(*predicate)
            ),
        )
        return ExternalChannelDeliveryAttempt.model_validate(rdb)

    async def lock_delivery_attempt(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
    ) -> ExternalChannelDeliveryAttempt | None:
        """Lock one delivery ledger row before its sole provider attempt."""
        rdb = await session.scalar(
            sa.select(RDBExternalChannelDeliveryAttempt)
            .where(RDBExternalChannelDeliveryAttempt.id == delivery_attempt_id)
            .with_for_update()
        )
        return self._as(ExternalChannelDeliveryAttempt, rdb)

    async def _create(
        self,
        session: AsyncSession,
        model: type[RDBModel],
        create: BaseModel,
    ) -> RDBModel:
        """Persist one new ORM record and flush generated fields."""
        rdb = model(**create.model_dump())
        session.add(rdb)
        await session.flush()
        return rdb

    async def _insert_or_lookup(
        self,
        session: AsyncSession,
        model: type[RDBModel],
        create: BaseModel,
        lookup: Callable[[], Awaitable[RDBModel | None]],
    ) -> RDBModel:
        """Insert idempotently, then load the unique conflicting record."""
        result = await session.execute(
            pg_insert(model)
            .values(**create.model_dump())
            .on_conflict_do_nothing()
            .returning(model)
        )
        rdb = result.scalar_one_or_none()
        if rdb is not None:
            await session.flush()
            return rdb
        existing = await lookup()
        if existing is None:
            raise RuntimeError("External Channel idempotent lookup failed")
        return existing

    @staticmethod
    def _as(model: type[_RecordT], rdb: object | None) -> _RecordT | None:
        """Build one immutable repository record when an ORM row exists."""
        if rdb is None:
            return None
        return model.model_validate(rdb)
