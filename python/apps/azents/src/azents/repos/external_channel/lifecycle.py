"""External Channel persistence operations for Session and Agent lifecycle work."""

import datetime
from collections.abc import Sequence

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAccessGrantScope,
    ExternalChannelBindingStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
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
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelInvocationBatch,
    RDBExternalChannelInvocationBatchItem,
    RDBExternalChannelPendingContext,
    RDBExternalChannelWork,
)
from azents.repos.external_channel.data import (
    ExternalChannelAgentDecommissionCleanup,
    ExternalChannelArchiveTermination,
    ExternalChannelPurgeCleanup,
    ExternalChannelPurgePreparation,
    ExternalChannelPurgeVerification,
    ExternalChannelRestoreValidation,
)


class ExternalChannelLifecycleRepository:
    """Own restrictive External Channel lifecycle mutations and verification."""

    async def terminate_session_tree(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
        now: datetime.datetime,
    ) -> ExternalChannelArchiveTermination:
        """Disconnect active bindings and finish their work without provider calls.

        The caller must lock the Session tree first. Bindings are then locked in
        identifier order to establish the External Channel half of the lock order.
        """
        bindings = await self._locked_bindings(
            session,
            session_ids=session_ids,
            active_only=True,
        )
        if not bindings:
            return ExternalChannelArchiveTermination(
                disconnected_binding_count=0,
                finished_work_count=0,
                deleted_pending_context_count=0,
                created_progress_delete_intent_count=0,
            )
        binding_ids = [binding.id for binding in bindings]
        resource_ids = [binding.resource_id for binding in bindings]
        works = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelWork)
                    .where(
                        RDBExternalChannelWork.binding_id.in_(binding_ids),
                        RDBExternalChannelWork.status
                        == ExternalChannelWorkStatus.ACTIVE,
                    )
                    .order_by(RDBExternalChannelWork.id)
                    .with_for_update()
                )
            ).all()
        )
        for binding in bindings:
            binding.status = ExternalChannelBindingStatus.DISCONNECTED
            binding.disconnected_at = now
            binding.disconnect_reason = "session_archived"

        finished_work_count = 0
        created_progress_delete_intent_count = 0
        for work in works:
            work.status = ExternalChannelWorkStatus.FINISHED
            work.finished_at = now
            work.desired_progress_payload = None
            work.desired_progress_revision += 1
            finished_work_count += 1
            if work.progress_provider_message_key is not None:
                result = await session.execute(
                    pg_insert(RDBExternalChannelDeliveryAttempt)
                    .values(
                        id=uuid7().hex,
                        origin_type=ExternalChannelDeliveryOriginType.BINDING_DISCONNECT,
                        origin_id=work.binding_id,
                        channel_action_id=None,
                        binding_id=work.binding_id,
                        operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                        request_payload={
                            "provider_message_key": work.progress_provider_message_key,
                        },
                        status=ExternalChannelDeliveryStatus.PENDING,
                        provider_message_key=work.progress_provider_message_key,
                        error_kind=None,
                        error_summary=None,
                        attempted_at=None,
                        completed_at=None,
                    )
                    .on_conflict_do_nothing()
                    .returning(RDBExternalChannelDeliveryAttempt.id)
                )
                created_progress_delete_intent_count += int(
                    result.scalar_one_or_none() is not None
                )
        deleted_pending_context_count = await self._delete(
            session,
            RDBExternalChannelPendingContext,
            RDBExternalChannelPendingContext.resource_id.in_(resource_ids),
        )
        await session.flush()
        return ExternalChannelArchiveTermination(
            disconnected_binding_count=len(bindings),
            finished_work_count=finished_work_count,
            deleted_pending_context_count=deleted_pending_context_count,
            created_progress_delete_intent_count=created_progress_delete_intent_count,
        )

    async def validate_restore_session_tree(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> ExternalChannelRestoreValidation:
        """Assert restore cannot reactivate prior External Channel state."""
        bindings = await self._locked_bindings(
            session,
            session_ids=session_ids,
            active_only=False,
        )
        if any(
            binding.status is ExternalChannelBindingStatus.ACTIVE
            for binding in bindings
        ):
            raise RuntimeError("Restored External Channel binding was reactivated")
        binding_ids = [binding.id for binding in bindings]
        works = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelWork)
                    .where(RDBExternalChannelWork.binding_id.in_(binding_ids))
                    .order_by(RDBExternalChannelWork.id)
                    .with_for_update()
                )
            ).all()
        )
        if any(work.status is ExternalChannelWorkStatus.ACTIVE for work in works):
            raise RuntimeError("Restored External Channel work was reactivated")
        return ExternalChannelRestoreValidation(
            disconnected_binding_count=len(bindings),
            finished_work_count=len(works),
        )

    async def prepare_session_tree_purge(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
        now: datetime.datetime,
    ) -> ExternalChannelPurgePreparation:
        """Make delivery attempts terminal without performing provider work."""
        binding_ids = [
            binding.id
            for binding in await self._locked_bindings(
                session,
                session_ids=session_ids,
                active_only=False,
            )
        ]
        access_request_ids = await self._session_tree_access_request_ids(
            session,
            session_ids=session_ids,
        )
        action_ids = await self._session_tree_action_ids(
            session,
            session_ids=session_ids,
            binding_ids=binding_ids,
        )
        attempts = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelDeliveryAttempt)
                    .where(
                        sa.or_(
                            RDBExternalChannelDeliveryAttempt.binding_id.in_(
                                binding_ids
                            ),
                            RDBExternalChannelDeliveryAttempt.channel_action_id.in_(
                                action_ids
                            ),
                            sa.and_(
                                RDBExternalChannelDeliveryAttempt.origin_type
                                == ExternalChannelDeliveryOriginType.ACCESS_REQUEST,
                                RDBExternalChannelDeliveryAttempt.origin_id.in_(
                                    access_request_ids
                                ),
                            ),
                        )
                    )
                    .order_by(RDBExternalChannelDeliveryAttempt.id)
                    .with_for_update()
                )
            ).all()
        )
        not_attempted_delivery_count = 0
        unknown_delivery_count = 0
        for attempt in attempts:
            if attempt.status is ExternalChannelDeliveryStatus.PENDING:
                attempt.status = ExternalChannelDeliveryStatus.NOT_ATTEMPTED
                attempt.completed_at = now
                attempt.error_kind = "PurgeNotAttempted"
                attempt.error_summary = "Purge completed without provider execution."
                not_attempted_delivery_count += 1
            elif attempt.status is ExternalChannelDeliveryStatus.ATTEMPTING:
                attempt.status = ExternalChannelDeliveryStatus.UNKNOWN
                attempt.completed_at = now
                attempt.error_kind = "PurgeOutcomeUnknown"
                attempt.error_summary = "Purge interrupted a provider delivery attempt."
                unknown_delivery_count += 1
        await session.flush()
        return ExternalChannelPurgePreparation(
            not_attempted_delivery_count=not_attempted_delivery_count,
            unknown_delivery_count=unknown_delivery_count,
        )

    async def purge_session_tree(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> ExternalChannelPurgeCleanup:
        """Delete Session-owned records in foreign-key restrictive order."""
        bindings = await self._locked_bindings(
            session,
            session_ids=session_ids,
            active_only=False,
        )
        binding_ids = [binding.id for binding in bindings]
        access_request_ids = await self._session_tree_access_request_ids(
            session,
            session_ids=session_ids,
        )
        action_ids = await self._session_tree_action_ids(
            session,
            session_ids=session_ids,
            binding_ids=binding_ids,
        )
        batch_ids = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelInvocationBatch.id)
                    .where(
                        RDBExternalChannelInvocationBatch.binding_id.in_(binding_ids)
                    )
                    .order_by(RDBExternalChannelInvocationBatch.id)
                    .with_for_update()
                )
            ).all()
        )
        deleted_delivery_attempt_count = await self._delete(
            session,
            RDBExternalChannelDeliveryAttempt,
            sa.or_(
                RDBExternalChannelDeliveryAttempt.binding_id.in_(binding_ids),
                RDBExternalChannelDeliveryAttempt.channel_action_id.in_(action_ids),
                sa.and_(
                    RDBExternalChannelDeliveryAttempt.origin_type
                    == ExternalChannelDeliveryOriginType.ACCESS_REQUEST,
                    RDBExternalChannelDeliveryAttempt.origin_id.in_(access_request_ids),
                ),
            ),
        )
        deleted_action_count = await self._delete(
            session,
            RDBExternalChannelAction,
            RDBExternalChannelAction.id.in_(action_ids),
        )
        deleted_session_grant_count = await self._delete(
            session,
            RDBExternalChannelAccessGrant,
            sa.and_(
                RDBExternalChannelAccessGrant.scope
                == ExternalChannelAccessGrantScope.SESSION,
                RDBExternalChannelAccessGrant.agent_session_id.in_(session_ids),
            ),
        )
        preserved_agent_grant_reference_count = await self._detach_agent_grants(
            session,
            access_request_ids=access_request_ids,
        )
        deleted_access_request_count = await self._delete(
            session,
            RDBExternalChannelAccessRequest,
            RDBExternalChannelAccessRequest.id.in_(access_request_ids),
        )
        deleted_invocation_batch_item_count = await self._delete(
            session,
            RDBExternalChannelInvocationBatchItem,
            RDBExternalChannelInvocationBatchItem.batch_id.in_(batch_ids),
        )
        deleted_invocation_batch_count = await self._delete(
            session,
            RDBExternalChannelInvocationBatch,
            RDBExternalChannelInvocationBatch.id.in_(batch_ids),
        )
        deleted_work_count = await self._delete(
            session,
            RDBExternalChannelWork,
            RDBExternalChannelWork.binding_id.in_(binding_ids),
        )
        deleted_binding_count = await self._delete(
            session,
            RDBExternalChannelBinding,
            RDBExternalChannelBinding.id.in_(binding_ids),
        )
        await session.flush()
        return ExternalChannelPurgeCleanup(
            deleted_delivery_attempt_count=deleted_delivery_attempt_count,
            deleted_action_count=deleted_action_count,
            deleted_session_grant_count=deleted_session_grant_count,
            preserved_agent_grant_reference_count=preserved_agent_grant_reference_count,
            deleted_access_request_count=deleted_access_request_count,
            deleted_invocation_batch_item_count=deleted_invocation_batch_item_count,
            deleted_invocation_batch_count=deleted_invocation_batch_count,
            deleted_work_count=deleted_work_count,
            deleted_binding_count=deleted_binding_count,
        )

    async def verify_session_tree_purged(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> ExternalChannelPurgeVerification:
        """Require direct Session-owned External Channel roots to be absent."""
        binding_ids = sa.select(RDBExternalChannelBinding.id).where(
            RDBExternalChannelBinding.agent_session_id.in_(session_ids)
        )
        action_ids = sa.select(RDBExternalChannelAction.id).where(
            sa.or_(
                RDBExternalChannelAction.agent_session_id.in_(session_ids),
                RDBExternalChannelAction.binding_id.in_(binding_ids),
            )
        )
        verification = ExternalChannelPurgeVerification(
            remaining_binding_count=await self._count(
                session,
                RDBExternalChannelBinding,
                RDBExternalChannelBinding.agent_session_id.in_(session_ids),
            ),
            remaining_work_count=await self._count(
                session,
                RDBExternalChannelWork,
                RDBExternalChannelWork.binding_id.in_(binding_ids),
            ),
            remaining_action_count=await self._count(
                session,
                RDBExternalChannelAction,
                RDBExternalChannelAction.agent_session_id.in_(session_ids),
            ),
            remaining_delivery_attempt_count=await self._count(
                session,
                RDBExternalChannelDeliveryAttempt,
                sa.or_(
                    RDBExternalChannelDeliveryAttempt.binding_id.in_(binding_ids),
                    RDBExternalChannelDeliveryAttempt.channel_action_id.in_(action_ids),
                ),
            ),
            remaining_access_request_count=await self._count(
                session,
                RDBExternalChannelAccessRequest,
                RDBExternalChannelAccessRequest.agent_session_id.in_(session_ids),
            ),
            remaining_session_grant_count=await self._count(
                session,
                RDBExternalChannelAccessGrant,
                sa.and_(
                    RDBExternalChannelAccessGrant.scope
                    == ExternalChannelAccessGrantScope.SESSION,
                    RDBExternalChannelAccessGrant.agent_session_id.in_(session_ids),
                ),
            ),
            remaining_invocation_batch_count=await self._count(
                session,
                RDBExternalChannelInvocationBatch,
                RDBExternalChannelInvocationBatch.binding_id.in_(binding_ids),
            ),
        )
        if any(verification.model_dump().values()):
            raise RuntimeError(
                "Session-owned External Channel state remains after purge"
            )
        return verification

    async def cleanup_decommissioned_agent(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelAgentDecommissionCleanup:
        """Remove direct Agent state while retaining Workspace provider canon."""
        routes = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelAgentRoute)
                    .where(RDBExternalChannelAgentRoute.agent_id == agent_id)
                    .order_by(RDBExternalChannelAgentRoute.id)
                    .with_for_update()
                )
            ).all()
        )
        route_ids = [route.id for route in routes]
        for route in routes:
            route.status = ExternalChannelRouteStatus.INACTIVE
            route.deactivated_at = now
        access_request_ids = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelAccessRequest.id)
                    .where(RDBExternalChannelAccessRequest.route_id.in_(route_ids))
                    .order_by(RDBExternalChannelAccessRequest.id)
                    .with_for_update()
                )
            ).all()
        )
        deleted_control_attempt_count = await self._delete(
            session,
            RDBExternalChannelDeliveryAttempt,
            sa.and_(
                RDBExternalChannelDeliveryAttempt.origin_type
                == ExternalChannelDeliveryOriginType.ACCESS_REQUEST,
                RDBExternalChannelDeliveryAttempt.origin_id.in_(access_request_ids),
                RDBExternalChannelDeliveryAttempt.operation
                == ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            ),
        )
        deleted_agent_grant_count = await self._delete(
            session,
            RDBExternalChannelAccessGrant,
            RDBExternalChannelAccessGrant.agent_id == agent_id,
        )
        deleted_block_count = await self._delete(
            session,
            RDBExternalChannelBlock,
            RDBExternalChannelBlock.agent_id == agent_id,
        )
        deleted_access_request_count = await self._delete(
            session,
            RDBExternalChannelAccessRequest,
            RDBExternalChannelAccessRequest.id.in_(access_request_ids),
        )
        deleted_route_count = await self._delete(
            session,
            RDBExternalChannelAgentRoute,
            RDBExternalChannelAgentRoute.id.in_(route_ids),
        )
        await session.flush()
        return ExternalChannelAgentDecommissionCleanup(
            deleted_route_count=deleted_route_count,
            deleted_access_request_count=deleted_access_request_count,
            deleted_control_attempt_count=deleted_control_attempt_count,
            deleted_agent_grant_count=deleted_agent_grant_count,
            deleted_block_count=deleted_block_count,
        )

    async def _locked_bindings(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
        active_only: bool,
    ) -> list[RDBExternalChannelBinding]:
        """Lock bindings in stable order after the caller locks Session roots."""
        predicate: list[sa.ColumnElement[bool]] = [
            RDBExternalChannelBinding.agent_session_id.in_(session_ids)
        ]
        if active_only:
            predicate.append(
                RDBExternalChannelBinding.status == ExternalChannelBindingStatus.ACTIVE
            )
        return list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelBinding)
                    .where(*predicate)
                    .order_by(RDBExternalChannelBinding.id)
                    .with_for_update()
                )
            ).all()
        )

    async def _session_tree_access_request_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> list[str]:
        """Lock requests directly or binding-pair-owned by the Session tree."""
        binding_pairs = sa.select(
            RDBExternalChannelBinding.route_id,
            RDBExternalChannelBinding.resource_id,
        ).where(RDBExternalChannelBinding.agent_session_id.in_(session_ids))
        return list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelAccessRequest.id)
                    .where(
                        sa.or_(
                            RDBExternalChannelAccessRequest.agent_session_id.in_(
                                session_ids
                            ),
                            sa.tuple_(
                                RDBExternalChannelAccessRequest.route_id,
                                RDBExternalChannelAccessRequest.resource_id,
                            ).in_(binding_pairs),
                        )
                    )
                    .order_by(RDBExternalChannelAccessRequest.id)
                    .with_for_update()
                )
            ).all()
        )

    async def _session_tree_action_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
        binding_ids: Sequence[str],
    ) -> list[str]:
        """Lock Session-owned actions before their delivery attempts are removed."""
        return list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelAction.id)
                    .where(
                        sa.or_(
                            RDBExternalChannelAction.agent_session_id.in_(session_ids),
                            RDBExternalChannelAction.binding_id.in_(binding_ids),
                        )
                    )
                    .order_by(RDBExternalChannelAction.id)
                    .with_for_update()
                )
            ).all()
        )

    async def _detach_agent_grants(
        self,
        session: AsyncSession,
        *,
        access_request_ids: Sequence[str],
    ) -> int:
        """Preserve Agent grants while releasing their Session request reference."""
        result = await session.execute(
            sa.update(RDBExternalChannelAccessGrant)
            .where(
                RDBExternalChannelAccessGrant.scope
                == ExternalChannelAccessGrantScope.AGENT,
                RDBExternalChannelAccessGrant.source_access_request_id.in_(
                    access_request_ids
                ),
            )
            .values(source_access_request_id=None)
            .returning(RDBExternalChannelAccessGrant.id)
        )
        return len(result.scalars().all())

    async def _delete(
        self,
        session: AsyncSession,
        model: type[RDBModel],
        predicate: sa.ColumnElement[bool],
    ) -> int:
        """Delete matching ORM rows and return the exact count."""
        result = await session.execute(
            sa.delete(model).where(predicate).returning(sa.literal(1))
        )
        return len(result.scalars().all())

    async def _count(
        self,
        session: AsyncSession,
        model: type[RDBModel],
        predicate: sa.ColumnElement[bool],
    ) -> int:
        """Count ORM rows matching one lifecycle ownership predicate."""
        count = await session.scalar(
            sa.select(sa.func.count()).select_from(model).where(predicate)
        )
        return count or 0
