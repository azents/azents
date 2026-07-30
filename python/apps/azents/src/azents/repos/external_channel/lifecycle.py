"""External Channel persistence operations for Session and Agent lifecycle work."""

import datetime
from collections.abc import Sequence

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    ExternalChannelAccessGrantScope,
    ExternalChannelAccessRequestStatus,
    ExternalChannelAppMode,
    ExternalChannelBindingStatus,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationAdmissionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelTransport,
    ExternalChannelWorkProjectionStatus,
    ExternalChannelWorkStatus,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.base import RDBModel
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessGrant,
    RDBExternalChannelAccessRequest,
    RDBExternalChannelAction,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelAppClaim,
    RDBExternalChannelBinding,
    RDBExternalChannelBlock,
    RDBExternalChannelChannelDefault,
    RDBExternalChannelConnection,
    RDBExternalChannelConversationAdmission,
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelInvocationBatch,
    RDBExternalChannelInvocationBatchItem,
    RDBExternalChannelResource,
    RDBExternalChannelWork,
    RDBExternalChannelWorkProjectionPart,
)
from azents.repos.external_channel.data import (
    ExternalChannelAgentDecommissionCleanup,
    ExternalChannelArchiveTermination,
    ExternalChannelMultiConnectionDisconnect,
    ExternalChannelMultiConnectionImpact,
    ExternalChannelMultiImpactBinding,
    ExternalChannelMultiImpactDefault,
    ExternalChannelMultiRouteImpact,
    ExternalChannelMultiRouteRemoval,
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
                created_progress_delete_intent_count=0,
                progress_delete_intent_ids=(),
            )
        binding_ids = [binding.id for binding in bindings]
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
        progress_delete_intent_ids: list[str] = []
        for work in works:
            work.status = ExternalChannelWorkStatus.FINISHED
            work.finished_at = now
            work.state_revision += 1
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
                created_id = result.scalar_one_or_none()
                if created_id is not None:
                    created_progress_delete_intent_count += 1
                    progress_delete_intent_ids.append(created_id)
        discord_cleanup_ids = await self._create_discord_projection_delete_intents(
            session,
            binding_ids=binding_ids,
            origin_type=ExternalChannelDeliveryOriginType.BINDING_DISCONNECT,
            now=now,
        )
        progress_delete_intent_ids.extend(discord_cleanup_ids)
        created_progress_delete_intent_count += len(discord_cleanup_ids)
        await session.flush()
        return ExternalChannelArchiveTermination(
            disconnected_binding_count=len(bindings),
            finished_work_count=finished_work_count,
            created_progress_delete_intent_count=created_progress_delete_intent_count,
            progress_delete_intent_ids=tuple(progress_delete_intent_ids),
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

    async def project_multi_route_impact(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        route_id: str,
    ) -> ExternalChannelMultiRouteImpact | None:
        """Project a sanitized deterministic Multi route removal impact."""
        route = await self._lock_multi_route(
            session,
            connection_id=connection_id,
            route_id=route_id,
        )
        if route is None:
            return None
        connection = await session.get(
            RDBExternalChannelConnection,
            route.connection_id,
        )
        if connection is None:
            return None
        return await self._project_route_impact(
            session,
            route_id=route.id,
            generation=connection.updated_at,
        )

    async def project_multi_connection_impact(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelMultiConnectionImpact | None:
        """Project a sanitized deterministic whole-Multi-App disconnect impact."""
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.app_mode == ExternalChannelAppMode.MULTI,
                RDBExternalChannelConnection.status
                != ExternalChannelConnectionStatus.DISCONNECTED,
            )
            .with_for_update()
        )
        if connection is None:
            return None
        routes = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelAgentRoute)
                    .where(
                        RDBExternalChannelAgentRoute.connection_id == connection.id,
                        RDBExternalChannelAgentRoute.connection_app_mode
                        == ExternalChannelAppMode.MULTI,
                    )
                    .order_by(RDBExternalChannelAgentRoute.id)
                    .with_for_update()
                )
            ).all()
        )
        route_ids = tuple(route.id for route in routes)
        affected_defaults, affected_bindings = await self._impact_details(
            session,
            route_ids=route_ids,
        )
        return ExternalChannelMultiConnectionImpact(
            connection_id=connection.id,
            generation=connection.updated_at,
            active_route_count=sum(
                route.catalog_status is ExternalChannelRouteCatalogStatus.AVAILABLE
                and route.agent_id is not None
                for route in routes
            ),
            active_default_count=len(affected_defaults),
            active_binding_count=len(affected_bindings),
            bound_resource_count=len(
                {binding.resource_id for binding in affected_bindings}
            ),
            open_admission_count=await self._count(
                session,
                RDBExternalChannelConversationAdmission,
                sa.and_(
                    RDBExternalChannelConversationAdmission.connection_id
                    == connection.id,
                    RDBExternalChannelConversationAdmission.status.in_(
                        (
                            ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
                            ExternalChannelConversationAdmissionStatus.SELECTED,
                            ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS,
                        )
                    ),
                ),
            ),
            pending_access_request_count=await self._count(
                session,
                RDBExternalChannelAccessRequest,
                sa.and_(
                    RDBExternalChannelAccessRequest.route_id.in_(route_ids),
                    RDBExternalChannelAccessRequest.status
                    == ExternalChannelAccessRequestStatus.PENDING,
                ),
            ),
            affected_defaults=affected_defaults,
            affected_bindings=affected_bindings,
        )

    async def remove_multi_route(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        route_id: str,
        removed_by_user_id: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelMultiRouteRemoval | None:
        """Remove one Multi association while preserving route history."""
        route = await self._lock_multi_route(
            session,
            connection_id=connection_id,
            route_id=route_id,
        )
        if route is None:
            return None
        connection = await session.get(
            RDBExternalChannelConnection,
            route.connection_id,
        )
        if connection is None:
            return None
        impact = await self._project_route_impact(
            session,
            route_id=route.id,
            generation=connection.updated_at,
        )
        already_removed = (
            route.catalog_status is ExternalChannelRouteCatalogStatus.REMOVED
        )
        historically_bound_resource_ids = sa.select(
            RDBExternalChannelBinding.resource_id
        ).where(RDBExternalChannelBinding.route_id == route.id)
        resources = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelResource)
                    .where(
                        RDBExternalChannelResource.id.in_(
                            historically_bound_resource_ids
                        )
                    )
                    .order_by(RDBExternalChannelResource.id)
                    .with_for_update()
                )
            ).all()
        )
        bindings = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelBinding)
                    .where(
                        RDBExternalChannelBinding.route_id == route.id,
                        RDBExternalChannelBinding.status
                        == ExternalChannelBindingStatus.ACTIVE,
                    )
                    .order_by(RDBExternalChannelBinding.resource_id)
                    .with_for_update()
                )
            ).all()
        )
        admissions = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelConversationAdmission)
                    .where(
                        RDBExternalChannelConversationAdmission.selected_route_id
                        == route.id,
                        RDBExternalChannelConversationAdmission.status.in_(
                            (
                                ExternalChannelConversationAdmissionStatus.SELECTED,
                                ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS,
                            )
                        ),
                    )
                    .order_by(RDBExternalChannelConversationAdmission.id)
                    .with_for_update()
                )
            ).all()
        )
        access_requests = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelAccessRequest)
                    .where(
                        RDBExternalChannelAccessRequest.route_id == route.id,
                        RDBExternalChannelAccessRequest.status
                        == ExternalChannelAccessRequestStatus.PENDING,
                    )
                    .order_by(RDBExternalChannelAccessRequest.id)
                    .with_for_update()
                )
            ).all()
        )
        progress_delete_intent_ids = await self._terminalize_bindings(
            session,
            bindings=bindings,
            resources=resources,
            now=now,
            reason="relationship_removed",
        )
        for resource in resources:
            if resource.status is ExternalChannelResourceStatus.ACTIVE:
                resource.status = ExternalChannelResourceStatus.UNAVAILABLE
                resource.unavailable_at = now
        await session.execute(
            sa.update(RDBExternalChannelChannelDefault)
            .where(
                RDBExternalChannelChannelDefault.route_id == route.id,
                RDBExternalChannelChannelDefault.status
                == ExternalChannelChannelDefaultStatus.ACTIVE,
            )
            .values(
                status=ExternalChannelChannelDefaultStatus.INVALIDATED,
                invalidated_at=now,
                invalidation_reason="relationship_removed",
            )
        )
        for admission in admissions:
            admission.status = ExternalChannelConversationAdmissionStatus.EXPIRED
        for request in access_requests:
            request.status = ExternalChannelAccessRequestStatus.EXPIRED
            request.decision_summary = "The External Channel relationship was removed."
            request.decided_at = now
        if not already_removed:
            route.catalog_status = ExternalChannelRouteCatalogStatus.REMOVED
            route.catalog_removed_at = now
            route.catalog_removed_by_user_id = removed_by_user_id
        route.agent_id = None
        await session.flush()
        return ExternalChannelMultiRouteRemoval(
            impact=impact,
            progress_delete_intent_ids=progress_delete_intent_ids,
        )

    async def reenable_multi_route(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        route_id: str,
    ) -> bool:
        """Re-enable a preserved Multi association without reviving old state."""
        route = await self._lock_multi_route(
            session,
            connection_id=connection_id,
            route_id=route_id,
        )
        if route is None:
            return False
        agent = await session.scalar(
            sa.select(RDBAgent)
            .where(
                RDBAgent.id == route.agent_id_snapshot,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            )
            .with_for_update()
        )
        connection = await session.get(RDBExternalChannelConnection, connection_id)
        if (
            agent is None
            or connection is None
            or connection.status
            in (
                ExternalChannelConnectionStatus.DISCONNECTING,
                ExternalChannelConnectionStatus.DISCONNECTED,
            )
            or agent.workspace_id != connection.workspace_id
        ):
            return False
        if route.catalog_status is ExternalChannelRouteCatalogStatus.AVAILABLE:
            return route.agent_id == route.agent_id_snapshot
        route.agent_id = route.agent_id_snapshot
        route.catalog_status = ExternalChannelRouteCatalogStatus.AVAILABLE
        route.catalog_removed_at = None
        route.catalog_removed_by_user_id = None
        await session.flush()
        return True

    async def disconnect_multi_connection(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        now: datetime.datetime,
        reason: str,
        defer_provider_state_purge: bool = False,
    ) -> ExternalChannelMultiConnectionDisconnect | None:
        """Terminalize all live Multi-App routing state and credentials."""
        return await self._disconnect_connection(
            session,
            connection_id=connection_id,
            expected_app_mode=ExternalChannelAppMode.MULTI,
            now=now,
            reason=reason,
            defer_provider_state_purge=defer_provider_state_purge,
        )

    async def disconnect_single_connection(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        now: datetime.datetime,
        reason: str,
        defer_provider_state_purge: bool = False,
    ) -> ExternalChannelMultiConnectionDisconnect | None:
        """Terminalize the whole Single App when its relationship is removed."""
        return await self._disconnect_connection(
            session,
            connection_id=connection_id,
            expected_app_mode=ExternalChannelAppMode.SINGLE,
            now=now,
            reason=reason,
            defer_provider_state_purge=defer_provider_state_purge,
        )

    async def _disconnect_connection(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        expected_app_mode: ExternalChannelAppMode,
        now: datetime.datetime,
        reason: str,
        defer_provider_state_purge: bool,
    ) -> ExternalChannelMultiConnectionDisconnect | None:
        """Terminalize every live routing root for one immutable App mode."""
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(RDBExternalChannelConnection.id == connection_id)
            .with_for_update()
        )
        if connection is None or connection.app_mode is not expected_app_mode:
            return None
        routes = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelAgentRoute)
                    .where(RDBExternalChannelAgentRoute.connection_id == connection.id)
                    .order_by(RDBExternalChannelAgentRoute.id)
                    .with_for_update()
                )
            ).all()
        )
        route_ids = [route.id for route in routes]
        resources = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelResource)
                    .where(RDBExternalChannelResource.connection_id == connection.id)
                    .order_by(RDBExternalChannelResource.id)
                    .with_for_update()
                )
            ).all()
        )
        bindings = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelBinding)
                    .where(
                        RDBExternalChannelBinding.route_id.in_(route_ids),
                        RDBExternalChannelBinding.status
                        == ExternalChannelBindingStatus.ACTIVE,
                    )
                    .order_by(RDBExternalChannelBinding.resource_id)
                    .with_for_update()
                )
            ).all()
        )
        admissions = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelConversationAdmission)
                    .where(
                        RDBExternalChannelConversationAdmission.connection_id
                        == connection.id,
                        RDBExternalChannelConversationAdmission.status.in_(
                            (
                                ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
                                ExternalChannelConversationAdmissionStatus.SELECTED,
                                ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS,
                            )
                        ),
                    )
                    .order_by(RDBExternalChannelConversationAdmission.id)
                    .with_for_update()
                )
            ).all()
        )
        access_requests = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelAccessRequest)
                    .where(
                        RDBExternalChannelAccessRequest.route_id.in_(route_ids),
                        RDBExternalChannelAccessRequest.status
                        == ExternalChannelAccessRequestStatus.PENDING,
                    )
                    .order_by(RDBExternalChannelAccessRequest.id)
                    .with_for_update()
                )
            ).all()
        )
        progress_delete_intent_ids = await self._terminalize_bindings(
            session,
            bindings=bindings,
            resources=resources,
            now=now,
            reason=reason,
        )
        unavailable_resource_count = 0
        for resource in resources:
            if resource.status is ExternalChannelResourceStatus.ACTIVE:
                resource.status = ExternalChannelResourceStatus.UNAVAILABLE
                resource.unavailable_at = now
                unavailable_resource_count += 1
        invalidated_default_count = await self._update_count(
            session,
            sa.update(RDBExternalChannelChannelDefault)
            .where(
                RDBExternalChannelChannelDefault.connection_id == connection.id,
                RDBExternalChannelChannelDefault.status
                == ExternalChannelChannelDefaultStatus.ACTIVE,
            )
            .values(
                status=ExternalChannelChannelDefaultStatus.INVALIDATED,
                invalidated_at=now,
                invalidation_reason=reason,
            ),
        )
        for admission in admissions:
            admission.status = ExternalChannelConversationAdmissionStatus.EXPIRED
        for request in access_requests:
            request.status = ExternalChannelAccessRequestStatus.EXPIRED
            request.decision_summary = (
                "The External Channel connection was disconnected."
            )
            request.decided_at = now
        disconnected_route_count = 0
        for route in routes:
            if (
                route.catalog_status is not ExternalChannelRouteCatalogStatus.REMOVED
                or route.agent_id is not None
            ):
                disconnected_route_count += 1
            if route.catalog_status is not ExternalChannelRouteCatalogStatus.REMOVED:
                route.catalog_status = ExternalChannelRouteCatalogStatus.REMOVED
                route.catalog_removed_at = now
                route.catalog_removed_by_user_id = None
            route.agent_id = None
        connection.status = ExternalChannelConnectionStatus.DISCONNECTED
        await self._delete(
            session,
            RDBExternalChannelAppClaim,
            RDBExternalChannelAppClaim.connection_id == connection.id,
        )
        if not defer_provider_state_purge:
            self._purge_connection_provider_state(connection)
        connection.disconnected_at = now
        connection.socket_lease_owner = None
        connection.socket_lease_until = None
        if connection.transport is ExternalChannelTransport.SOCKET:
            connection.socket_heartbeat_at = now
            connection.socket_gap_detected_at = now
            connection.socket_gap_reason = reason
        else:
            connection.socket_heartbeat_at = None
            connection.socket_gap_detected_at = None
            connection.socket_gap_reason = None
        await session.flush()
        return ExternalChannelMultiConnectionDisconnect(
            disconnected_route_count=disconnected_route_count,
            invalidated_default_count=invalidated_default_count,
            expired_admission_count=len(admissions),
            expired_access_request_count=len(access_requests),
            unavailable_resource_count=unavailable_resource_count,
            disconnected_binding_count=len(bindings),
            progress_delete_intent_ids=progress_delete_intent_ids,
        )

    async def purge_disconnected_connection_provider_state(
        self,
        session: AsyncSession,
        *,
        connection_ids: Sequence[str],
    ) -> int:
        """Clear deferred provider state after delivery targets are captured."""
        unique_ids = tuple(sorted(set(connection_ids)))
        if not unique_ids:
            return 0
        connections = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelConnection)
                    .where(
                        RDBExternalChannelConnection.id.in_(unique_ids),
                        RDBExternalChannelConnection.status
                        == ExternalChannelConnectionStatus.DISCONNECTED,
                    )
                    .order_by(RDBExternalChannelConnection.id)
                    .with_for_update()
                )
            ).all()
        )
        if len(connections) != len(unique_ids):
            raise RuntimeError(
                "Disconnected External Channel provider state disappeared."
            )
        for connection in connections:
            self._purge_connection_provider_state(connection)
        await session.flush()
        return len(connections)

    async def cleanup_decommissioned_agent(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelAgentDecommissionCleanup:
        """Terminalize relationships without erasing shared App provenance."""
        route_rows = (
            await session.execute(
                sa.select(
                    RDBExternalChannelAgentRoute.id,
                    RDBExternalChannelAgentRoute.connection_id,
                    RDBExternalChannelConnection.app_mode,
                )
                .join(
                    RDBExternalChannelConnection,
                    RDBExternalChannelConnection.id
                    == RDBExternalChannelAgentRoute.connection_id,
                )
                .where(RDBExternalChannelAgentRoute.agent_id == agent_id)
                .order_by(
                    RDBExternalChannelAgentRoute.connection_id,
                    RDBExternalChannelAgentRoute.id,
                )
            )
        ).all()
        progress_delete_intent_ids: list[str] = []
        provider_state_purge_connection_ids: list[str] = []
        for route_id, connection_id, app_mode in route_rows:
            if app_mode is ExternalChannelAppMode.SINGLE:
                disconnected = await self.disconnect_single_connection(
                    session,
                    connection_id=connection_id,
                    now=now,
                    reason="agent_decommissioned",
                    defer_provider_state_purge=True,
                )
                if disconnected is not None:
                    progress_delete_intent_ids.extend(
                        disconnected.progress_delete_intent_ids
                    )
                    provider_state_purge_connection_ids.append(connection_id)
            else:
                removed = await self.remove_multi_route(
                    session,
                    connection_id=connection_id,
                    route_id=route_id,
                    removed_by_user_id=None,
                    now=now,
                )
                if removed is not None:
                    progress_delete_intent_ids.extend(
                        removed.progress_delete_intent_ids
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
        await session.flush()
        return ExternalChannelAgentDecommissionCleanup(
            progress_delete_intent_ids=tuple(progress_delete_intent_ids),
            provider_state_purge_connection_ids=tuple(
                provider_state_purge_connection_ids
            ),
            deleted_route_count=0,
            deleted_access_request_count=0,
            deleted_control_attempt_count=0,
            deleted_agent_grant_count=deleted_agent_grant_count,
            deleted_block_count=deleted_block_count,
        )

    @staticmethod
    def _purge_connection_provider_state(
        connection: RDBExternalChannelConnection,
    ) -> None:
        """Remove provider identity and credentials from a terminal connection."""
        connection.encrypted_credentials = None
        connection.provider_tenant_id = None
        connection.provider_bot_user_id = None
        connection.capabilities = None

    async def _lock_multi_route(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        route_id: str,
    ) -> RDBExternalChannelAgentRoute | None:
        """Lock connection then route for one Multi relationship transition."""
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(RDBExternalChannelConnection.id == connection_id)
            .with_for_update()
        )
        if (
            connection is None
            or connection.app_mode is not ExternalChannelAppMode.MULTI
        ):
            return None
        route = await session.scalar(
            sa.select(RDBExternalChannelAgentRoute)
            .where(
                RDBExternalChannelAgentRoute.id == route_id,
                RDBExternalChannelAgentRoute.connection_id == connection.id,
                RDBExternalChannelAgentRoute.connection_app_mode
                == ExternalChannelAppMode.MULTI,
            )
            .with_for_update()
        )
        return route

    async def _project_route_impact(
        self,
        session: AsyncSession,
        *,
        route_id: str,
        generation: datetime.datetime,
    ) -> ExternalChannelMultiRouteImpact:
        """Return deterministic route impact without provider message content."""
        affected_defaults, affected_bindings = await self._impact_details(
            session,
            route_ids=(route_id,),
        )
        active_binding_count = await self._count(
            session,
            RDBExternalChannelBinding,
            sa.and_(
                RDBExternalChannelBinding.route_id == route_id,
                RDBExternalChannelBinding.status == ExternalChannelBindingStatus.ACTIVE,
            ),
        )
        bound_resource_count = int(
            await session.scalar(
                sa.select(
                    sa.func.count(sa.distinct(RDBExternalChannelBinding.resource_id))
                ).where(RDBExternalChannelBinding.route_id == route_id)
            )
            or 0
        )
        return ExternalChannelMultiRouteImpact(
            route_id=route_id,
            generation=generation,
            active_default_count=len(affected_defaults),
            active_binding_count=active_binding_count,
            bound_resource_count=bound_resource_count,
            open_admission_count=await self._count(
                session,
                RDBExternalChannelConversationAdmission,
                sa.and_(
                    RDBExternalChannelConversationAdmission.selected_route_id
                    == route_id,
                    RDBExternalChannelConversationAdmission.status.in_(
                        (
                            ExternalChannelConversationAdmissionStatus.SELECTED,
                            ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS,
                        )
                    ),
                ),
            ),
            pending_access_request_count=await self._count(
                session,
                RDBExternalChannelAccessRequest,
                sa.and_(
                    RDBExternalChannelAccessRequest.route_id == route_id,
                    RDBExternalChannelAccessRequest.status
                    == ExternalChannelAccessRequestStatus.PENDING,
                ),
            ),
            affected_defaults=affected_defaults,
            affected_bindings=affected_bindings,
        )

    async def _impact_details(
        self,
        session: AsyncSession,
        *,
        route_ids: Sequence[str],
    ) -> tuple[
        tuple[ExternalChannelMultiImpactDefault, ...],
        tuple[ExternalChannelMultiImpactBinding, ...],
    ]:
        """Load bounded, sanitized default and binding identities for confirmation."""
        if not route_ids:
            return (), ()
        default_rows = (
            await session.execute(
                sa.select(
                    RDBExternalChannelChannelDefault,
                    RDBExternalChannelAgentRoute,
                    RDBAgent.name,
                )
                .join(
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelAgentRoute.id
                    == RDBExternalChannelChannelDefault.route_id,
                )
                .outerjoin(
                    RDBAgent,
                    RDBAgent.id == RDBExternalChannelAgentRoute.agent_id,
                )
                .where(
                    RDBExternalChannelChannelDefault.route_id.in_(route_ids),
                    RDBExternalChannelChannelDefault.status
                    == ExternalChannelChannelDefaultStatus.ACTIVE,
                )
                .order_by(
                    RDBExternalChannelChannelDefault.provider_channel_id,
                    RDBExternalChannelChannelDefault.id,
                )
            )
        ).all()
        binding_rows = (
            await session.execute(
                sa.select(
                    RDBExternalChannelBinding,
                    RDBExternalChannelResource,
                )
                .join(
                    RDBExternalChannelResource,
                    RDBExternalChannelResource.id
                    == RDBExternalChannelBinding.resource_id,
                )
                .where(
                    RDBExternalChannelBinding.route_id.in_(route_ids),
                    RDBExternalChannelBinding.status
                    == ExternalChannelBindingStatus.ACTIVE,
                )
                .order_by(
                    RDBExternalChannelBinding.agent_session_id,
                    RDBExternalChannelBinding.id,
                )
            )
        ).all()
        defaults = tuple(
            ExternalChannelMultiImpactDefault(
                id=channel_default.id,
                provider_channel_id=channel_default.provider_channel_id,
                route_id=route.id,
                agent_id=route.agent_id,
                agent_name=agent_name,
            )
            for channel_default, route, agent_name in default_rows
        )
        bindings = tuple(
            ExternalChannelMultiImpactBinding(
                id=binding.id,
                route_id=binding.route_id,
                agent_session_id=binding.agent_session_id,
                resource_id=resource.id,
                channel_label=_impact_label(
                    resource.labels,
                    preferred=("channel_name", "channel_id"),
                    fallback=resource.id,
                ),
                thread_label=_impact_optional_label(
                    resource.labels,
                    preferred=("thread_label", "thread_ts"),
                ),
            )
            for binding, resource in binding_rows
        )
        return defaults, bindings

    async def _terminalize_bindings(
        self,
        session: AsyncSession,
        *,
        bindings: Sequence[RDBExternalChannelBinding],
        resources: Sequence[RDBExternalChannelResource],
        now: datetime.datetime,
        reason: str,
    ) -> tuple[str, ...]:
        """Disconnect bindings and finish work with one-attempt cleanup intents."""
        if not bindings:
            return ()
        binding_ids = [binding.id for binding in bindings]
        resource_labels = {resource.id: resource.labels for resource in resources}
        binding_resource_ids = {binding.id: binding.resource_id for binding in bindings}
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
            binding.disconnect_reason = reason
        progress_delete_intent_ids: list[str] = []
        for work in works:
            work.status = ExternalChannelWorkStatus.FINISHED
            work.finished_at = now
            work.state_revision += 1
            work.desired_progress_payload = None
            work.desired_progress_revision += 1
            if work.progress_provider_message_key is None:
                continue
            result = await session.execute(
                pg_insert(RDBExternalChannelDeliveryAttempt)
                .values(
                    id=uuid7().hex,
                    origin_type=ExternalChannelDeliveryOriginType.BINDING_DISCONNECT,
                    origin_id=work.binding_id,
                    channel_action_id=None,
                    binding_id=work.binding_id,
                    operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                    request_payload=_provider_payload(
                        resource_labels.get(binding_resource_ids[work.binding_id]),
                        work.progress_provider_message_key,
                    ),
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
            created_id = result.scalar_one_or_none()
            if created_id is not None:
                progress_delete_intent_ids.append(created_id)
        progress_delete_intent_ids.extend(
            await self._create_discord_projection_delete_intents(
                session,
                binding_ids=binding_ids,
                origin_type=ExternalChannelDeliveryOriginType.BINDING_DISCONNECT,
                now=now,
            )
        )
        await session.flush()
        return tuple(progress_delete_intent_ids)

    async def _create_discord_projection_delete_intents(
        self,
        session: AsyncSession,
        *,
        binding_ids: Sequence[str],
        origin_type: ExternalChannelDeliveryOriginType,
        now: datetime.datetime,
    ) -> tuple[str, ...]:
        """Create ordered deletes for current Discord projection parts."""
        rows = (
            await session.execute(
                sa.select(
                    RDBExternalChannelWorkProjectionPart,
                    RDBExternalChannelWork,
                    RDBExternalChannelResource,
                )
                .join(
                    RDBExternalChannelWork,
                    RDBExternalChannelWork.id
                    == RDBExternalChannelWorkProjectionPart.work_id,
                )
                .join(
                    RDBExternalChannelBinding,
                    RDBExternalChannelBinding.id == RDBExternalChannelWork.binding_id,
                )
                .join(
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelAgentRoute.id
                    == RDBExternalChannelBinding.route_id,
                )
                .join(
                    RDBExternalChannelConnection,
                    RDBExternalChannelConnection.id
                    == RDBExternalChannelAgentRoute.connection_id,
                )
                .join(
                    RDBExternalChannelResource,
                    RDBExternalChannelResource.id
                    == RDBExternalChannelBinding.resource_id,
                )
                .where(
                    RDBExternalChannelWork.binding_id.in_(binding_ids),
                    RDBExternalChannelConnection.provider
                    == ExternalChannelProvider.DISCORD,
                    RDBExternalChannelWorkProjectionPart.status
                    == ExternalChannelWorkProjectionStatus.PRESENT,
                    RDBExternalChannelWorkProjectionPart.provider_message_key.is_not(
                        None
                    ),
                )
                .order_by(
                    RDBExternalChannelWork.binding_id,
                    RDBExternalChannelWorkProjectionPart.part_ordinal,
                )
                .with_for_update()
            )
        ).all()
        created_ids: list[str] = []
        for part, work, resource in rows:
            labels = resource.labels or {}
            guild_id = labels.get("guild_id")
            channel_id = labels.get("delivery_channel_id") or labels.get("thread_id")
            message_key = part.provider_message_key
            if (
                not isinstance(guild_id, str)
                or not guild_id
                or not isinstance(channel_id, str)
                or not channel_id
                or not isinstance(message_key, str)
                or not message_key
            ):
                continue
            payload: dict[str, object] = {
                "provider": "discord",
                "guild_id": guild_id,
                "channel_id": channel_id,
                "provider_message_key": message_key,
                "work_id": work.id,
            }
            if labels.get("delivery_channel_id") is None:
                parent_channel_id = labels.get("parent_channel_id")
                root_message_id = labels.get("root_message_id")
                if (
                    isinstance(parent_channel_id, str)
                    and isinstance(root_message_id, str)
                    and root_message_id == channel_id
                ):
                    payload["thread_parent_channel_id"] = parent_channel_id
                    payload["thread_root_message_id"] = root_message_id
            attempt = RDBExternalChannelDeliveryAttempt(
                origin_type=origin_type,
                origin_id=work.binding_id,
                channel_action_id=None,
                binding_id=work.binding_id,
                operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                request_payload=payload,
                status=ExternalChannelDeliveryStatus.PENDING,
                provider_message_key=message_key,
                error_kind=None,
                error_summary=None,
                attempted_at=None,
                completed_at=None,
                part_ordinal=part.part_ordinal,
            )
            session.add(attempt)
            await session.flush()
            part.status = ExternalChannelWorkProjectionStatus.PENDING
            part.latest_delivery_attempt_id = attempt.id
            created_ids.append(attempt.id)
        return tuple(created_ids)

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
        """Lock access requests directly owned by the Session tree."""
        return list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelAccessRequest.id)
                    .where(
                        RDBExternalChannelAccessRequest.agent_session_id.in_(
                            session_ids
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

    async def _update_count(
        self,
        session: AsyncSession,
        statement: sa.Update,
    ) -> int:
        """Apply one terminal transition and return its affected row count."""
        result = await session.execute(statement.returning(sa.literal(1)))
        return len(result.scalars().all())


def _provider_payload(
    labels: dict[str, object] | None,
    provider_message_key: str,
) -> dict[str, object]:
    """Build the provider target retained for one progress deletion."""
    labels = labels or {}
    channel_id = labels.get("channel_id")
    thread_ts = labels.get("thread_ts")
    if not isinstance(channel_id, str) or not isinstance(thread_ts, str):
        raise ValueError("External Channel resource has no provider target.")
    return {
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "provider_message_key": provider_message_key,
    }


def _impact_label(
    labels: dict[str, object] | None,
    *,
    preferred: Sequence[str],
    fallback: str,
) -> str:
    """Return one bounded non-secret provider label for management confirmation."""
    value = _impact_optional_label(labels, preferred=preferred)
    return fallback if value is None else value


def _impact_optional_label(
    labels: dict[str, object] | None,
    *,
    preferred: Sequence[str],
) -> str | None:
    """Return the first bounded visible label without provider payload content."""
    labels = labels or {}
    for key in preferred:
        value = labels.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:255]
    return None
