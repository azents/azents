"""External Channel persistence operations for Session and Agent lifecycle work."""

import datetime
from collections.abc import Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    ExternalChannelAccessGrantScope,
    ExternalChannelAccessRequestStatus,
    ExternalChannelAppMode,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelSetupClaimStatus,
    ExternalChannelTransport,
    ExternalChannelWorkStatus,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.base import RDBModel
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessGrant,
    RDBExternalChannelAccessRequest,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelAppClaim,
    RDBExternalChannelBinding,
    RDBExternalChannelBlock,
    RDBExternalChannelChannelDefault,
    RDBExternalChannelConnection,
    RDBExternalChannelInteraction,
    RDBExternalChannelParticipationSetting,
    RDBExternalChannelResource,
    RDBExternalChannelSetupClaim,
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
    ExternalChannelPurgeVerification,
    ExternalChannelRestoreValidation,
)
from azents.repos.external_channel.work import terminate_binding_with_plans
from azents.repos.external_channel.work_state import ExternalChannelWorkStateStore
from azents.repos.scheduled_task.lifecycle import ScheduledTaskLifecycleRepository
from azents.services.external_channel.provider_effect import ProviderEffectPlan

_NONTERMINAL_SETUP_CLAIM_STATUSES = (
    ExternalChannelSetupClaimStatus.PENDING_AGENT,
    ExternalChannelSetupClaimStatus.PENDING_LOCATION,
    ExternalChannelSetupClaimStatus.SELECTED,
)
_LIVE_INTERACTION_STATUSES = (
    ExternalChannelInteractionStatus.ACCEPTED,
    ExternalChannelInteractionStatus.PROCESSING,
    ExternalChannelInteractionStatus.COMPLETED,
)


@dataclass(frozen=True)
class _LockedParticipationState:
    """Active settings and nonterminal claims locked for lifecycle mutation."""

    settings: tuple[RDBExternalChannelParticipationSetting, ...]
    claims: tuple[RDBExternalChannelSetupClaim, ...]


class ExternalChannelLifecycleRepository:
    """Own restrictive External Channel lifecycle mutations and verification."""

    @classmethod
    def create(cls) -> "ExternalChannelLifecycleRepository":
        """Create a lifecycle repository for application dependency injection."""
        return cls()

    def __init__(
        self,
        work_state_store: ExternalChannelWorkStateStore | None = None,
        scheduled_task_lifecycle_repository: ScheduledTaskLifecycleRepository
        | None = None,
    ) -> None:
        """Create the lifecycle repository."""
        self.work_state_store = work_state_store or ExternalChannelWorkStateStore()
        self.scheduled_task_lifecycle_repository = (
            scheduled_task_lifecycle_repository or ScheduledTaskLifecycleRepository()
        )

    async def terminate_session_tree(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
        now: datetime.datetime,
    ) -> ExternalChannelArchiveTermination:
        """Disconnect active bindings and capture one-shot cleanup plans."""
        bindings = await self._locked_bindings(
            session,
            session_ids=session_ids,
            connected_only=True,
        )
        resources = {
            resource.id: resource
            for resource in await session.scalars(
                sa.select(RDBExternalChannelResource)
                .where(
                    RDBExternalChannelResource.id.in_(
                        [binding.resource_id for binding in bindings]
                    )
                )
                .order_by(RDBExternalChannelResource.id)
                .with_for_update()
            )
        }
        plans: list[ProviderEffectPlan] = []
        finished_work_count = 0
        work_states = {
            state.binding_id: state
            for state in await self.work_state_store.list_for_sessions(
                session,
                session_ids=session_ids,
            )
        }
        for binding in bindings:
            resource = resources.get(binding.resource_id)
            if resource is None:
                continue
            state = work_states.get(binding.id)
            finished_work_count += int(
                state is not None and state.status is ExternalChannelWorkStatus.ACTIVE
            )
            plans.extend(
                await terminate_binding_with_plans(
                    session,
                    work_state_store=self.work_state_store,
                    scheduled_task_lifecycle_repository=(
                        self.scheduled_task_lifecycle_repository
                    ),
                    binding=binding,
                    resource=resource,
                    now=now,
                    reason="session_archived",
                    emit_leave_presence=False,
                )
            )
        return ExternalChannelArchiveTermination(
            disconnected_binding_count=len(bindings),
            finished_work_count=finished_work_count,
            direct_cleanup_count=len(plans),
            cleanup_plans=tuple(plans),
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
            connected_only=False,
        )
        if any(binding.disconnected_at is None for binding in bindings):
            raise RuntimeError("Restored External Channel binding was reactivated")
        works = await self.work_state_store.list_for_sessions(
            session,
            session_ids=session_ids,
        )
        if any(work.status is ExternalChannelWorkStatus.ACTIVE for work in works):
            raise RuntimeError("Restored External Channel work was reactivated")
        return ExternalChannelRestoreValidation(
            disconnected_binding_count=len(bindings),
            finished_work_count=len(works),
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
            connected_only=False,
        )
        binding_ids = [binding.id for binding in bindings]
        access_request_ids = await self._session_tree_access_request_ids(
            session,
            session_ids=session_ids,
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
        deleted_work_count = await self.work_state_store.delete_for_sessions(
            session,
            session_ids=session_ids,
        )
        deleted_binding_count = await self._delete(
            session,
            RDBExternalChannelBinding,
            RDBExternalChannelBinding.id.in_(binding_ids),
        )
        await session.flush()
        return ExternalChannelPurgeCleanup(
            deleted_session_grant_count=deleted_session_grant_count,
            preserved_agent_grant_reference_count=preserved_agent_grant_reference_count,
            deleted_access_request_count=deleted_access_request_count,
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
        remaining_work_count = len(
            await self.work_state_store.list_for_sessions(
                session,
                session_ids=session_ids,
            )
        )
        verification = ExternalChannelPurgeVerification(
            remaining_binding_count=await self._count(
                session,
                RDBExternalChannelBinding,
                RDBExternalChannelBinding.agent_session_id.in_(session_ids),
            ),
            remaining_work_count=remaining_work_count,
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
            active_participation_setting_count=await self._count(
                session,
                RDBExternalChannelParticipationSetting,
                sa.and_(
                    RDBExternalChannelParticipationSetting.connection_id
                    == connection.id,
                    RDBExternalChannelParticipationSetting.status
                    == ExternalChannelParticipationSettingStatus.ACTIVE,
                ),
            ),
            nonterminal_setup_claim_count=await self._count(
                session,
                RDBExternalChannelSetupClaim,
                sa.and_(
                    RDBExternalChannelSetupClaim.connection_id == connection.id,
                    RDBExternalChannelSetupClaim.status.in_(
                        _NONTERMINAL_SETUP_CLAIM_STATUSES
                    ),
                ),
            ),
            active_binding_count=len(affected_bindings),
            connected_parent_binding_count=await self._connected_parent_binding_count(
                session,
                route_ids=route_ids,
            ),
            bound_resource_count=len(
                {binding.resource_id for binding in affected_bindings}
            ),
            open_admission_count=await self._count(
                session,
                RDBExternalChannelInteraction,
                _open_selector_condition(
                    connection_id=connection.id,
                    route_id=None,
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
        defaults = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelChannelDefault)
                    .where(
                        RDBExternalChannelChannelDefault.route_id == route.id,
                        RDBExternalChannelChannelDefault.status
                        == ExternalChannelChannelDefaultStatus.ACTIVE,
                    )
                    .order_by(RDBExternalChannelChannelDefault.id)
                    .with_for_update()
                )
            ).all()
        )
        participation_state = await self._lock_participation_state(
            session,
            connection_id=connection.id,
            route_ids=(route.id,),
        )
        settings = participation_state.settings
        claims = participation_state.claims
        interaction_conditions = [
            _open_selector_condition(
                connection_id=connection.id,
                route_id=route.id,
            )
        ]
        if claims:
            interaction_conditions.append(
                RDBExternalChannelInteraction.setup_claim_id.in_(
                    [claim.id for claim in claims]
                )
            )
        if settings:
            interaction_conditions.append(
                RDBExternalChannelInteraction.projection["provider_parent_channel_id"]
                .as_string()
                .in_(
                    sorted({setting.provider_parent_channel_id for setting in settings})
                )
            )
        interactions = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelInteraction)
                    .where(
                        RDBExternalChannelInteraction.connection_id == connection.id,
                        RDBExternalChannelInteraction.status.in_(
                            _LIVE_INTERACTION_STATUSES
                        ),
                        sa.or_(*interaction_conditions),
                    )
                    .order_by(RDBExternalChannelInteraction.id)
                    .with_for_update()
                )
            ).all()
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
                        RDBExternalChannelBinding.disconnected_at.is_(None),
                    )
                    .order_by(RDBExternalChannelBinding.resource_id)
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
        cleanup_plans = await self._terminalize_bindings(
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
        self._terminalize_participation_state(
            settings=settings,
            claims=claims,
            interactions=interactions,
            now=now,
            reason="relationship_removed",
            claim_status=ExternalChannelSetupClaimStatus.INVALIDATED,
        )
        for channel_default in defaults:
            channel_default.status = ExternalChannelChannelDefaultStatus.INVALIDATED
            channel_default.invalidated_at = now
            channel_default.invalidation_reason = "relationship_removed"
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
            cleanup_plans=cleanup_plans,
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
        defaults = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelChannelDefault)
                    .where(
                        RDBExternalChannelChannelDefault.connection_id == connection.id,
                        RDBExternalChannelChannelDefault.status
                        == ExternalChannelChannelDefaultStatus.ACTIVE,
                    )
                    .order_by(RDBExternalChannelChannelDefault.id)
                    .with_for_update()
                )
            ).all()
        )
        participation_state = await self._lock_participation_state(
            session,
            connection_id=connection.id,
            route_ids=None,
        )
        settings = participation_state.settings
        claims = participation_state.claims
        interactions = list(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelInteraction)
                    .where(
                        RDBExternalChannelInteraction.connection_id == connection.id,
                        RDBExternalChannelInteraction.status.in_(
                            _LIVE_INTERACTION_STATUSES
                        ),
                    )
                    .order_by(RDBExternalChannelInteraction.id)
                    .with_for_update()
                )
            ).all()
        )
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
                        RDBExternalChannelBinding.disconnected_at.is_(None),
                    )
                    .order_by(RDBExternalChannelBinding.resource_id)
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
        cleanup_plans = await self._terminalize_bindings(
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
        self._terminalize_participation_state(
            settings=settings,
            claims=claims,
            interactions=interactions,
            now=now,
            reason=reason,
            claim_status=ExternalChannelSetupClaimStatus.INVALIDATED,
        )
        for channel_default in defaults:
            channel_default.status = ExternalChannelChannelDefaultStatus.INVALIDATED
            channel_default.invalidated_at = now
            channel_default.invalidation_reason = reason
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
            invalidated_default_count=len(defaults),
            invalidated_participation_setting_count=len(settings),
            terminated_setup_claim_count=len(claims),
            expired_admission_count=len(interactions),
            expired_access_request_count=len(access_requests),
            unavailable_resource_count=unavailable_resource_count,
            disconnected_binding_count=len(bindings),
            cleanup_plans=cleanup_plans,
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
        plans: list[ProviderEffectPlan] = []
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
                    plans.extend(disconnected.cleanup_plans)
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
                    plans.extend(removed.cleanup_plans)
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
            cleanup_plans=tuple(plans),
            provider_state_purge_connection_ids=tuple(
                provider_state_purge_connection_ids
            ),
            deleted_route_count=0,
            deleted_access_request_count=0,
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

    async def _lock_participation_state(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        route_ids: Sequence[str] | None,
    ) -> _LockedParticipationState:
        """Lock active settings then nonterminal claims for one lifecycle root."""
        setting_conditions = [
            RDBExternalChannelParticipationSetting.connection_id == connection_id,
            RDBExternalChannelParticipationSetting.status
            == ExternalChannelParticipationSettingStatus.ACTIVE,
        ]
        claim_conditions = [
            RDBExternalChannelSetupClaim.connection_id == connection_id,
            RDBExternalChannelSetupClaim.status.in_(_NONTERMINAL_SETUP_CLAIM_STATUSES),
        ]
        if route_ids is not None:
            setting_conditions.append(
                RDBExternalChannelParticipationSetting.route_id.in_(route_ids)
            )
            claim_conditions.append(
                RDBExternalChannelSetupClaim.route_id.in_(route_ids)
            )
        settings = tuple(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelParticipationSetting)
                    .where(*setting_conditions)
                    .order_by(RDBExternalChannelParticipationSetting.id)
                    .with_for_update()
                )
            ).all()
        )
        claims = tuple(
            (
                await session.scalars(
                    sa.select(RDBExternalChannelSetupClaim)
                    .where(*claim_conditions)
                    .order_by(RDBExternalChannelSetupClaim.id)
                    .with_for_update()
                )
            ).all()
        )
        return _LockedParticipationState(settings=settings, claims=claims)

    @staticmethod
    def _terminalize_participation_state(
        *,
        settings: Sequence[RDBExternalChannelParticipationSetting],
        claims: Sequence[RDBExternalChannelSetupClaim],
        interactions: Sequence[RDBExternalChannelInteraction],
        now: datetime.datetime,
        reason: str,
        claim_status: ExternalChannelSetupClaimStatus,
    ) -> None:
        """Invalidate selected participation state without reviving history."""
        for setting in settings:
            setting.status = ExternalChannelParticipationSettingStatus.INVALIDATED
            setting.settings_generation += 1
            setting.invalidated_at = now
            setting.invalidation_reason = reason
        for claim in claims:
            claim.status = claim_status
            claim.claim_generation += 1
        for interaction in interactions:
            interaction.status = ExternalChannelInteractionStatus.EXPIRED

    @staticmethod
    async def _connected_parent_binding_count(
        session: AsyncSession,
        *,
        route_ids: Sequence[str],
    ) -> int:
        """Count connected parent-channel Bindings for bounded impact previews."""
        if not route_ids:
            return 0
        return int(
            await session.scalar(
                sa.select(sa.func.count(RDBExternalChannelBinding.id))
                .join(
                    RDBExternalChannelResource,
                    RDBExternalChannelResource.id
                    == RDBExternalChannelBinding.resource_id,
                )
                .where(
                    RDBExternalChannelBinding.route_id.in_(route_ids),
                    RDBExternalChannelBinding.disconnected_at.is_(None),
                    RDBExternalChannelResource.resource_type
                    == ExternalChannelResourceType.PARENT_CHANNEL,
                )
            )
            or 0
        )

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
                RDBExternalChannelBinding.disconnected_at.is_(None),
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
            active_participation_setting_count=await self._count(
                session,
                RDBExternalChannelParticipationSetting,
                sa.and_(
                    RDBExternalChannelParticipationSetting.route_id == route_id,
                    RDBExternalChannelParticipationSetting.status
                    == ExternalChannelParticipationSettingStatus.ACTIVE,
                ),
            ),
            nonterminal_setup_claim_count=await self._count(
                session,
                RDBExternalChannelSetupClaim,
                sa.and_(
                    RDBExternalChannelSetupClaim.route_id == route_id,
                    RDBExternalChannelSetupClaim.status.in_(
                        _NONTERMINAL_SETUP_CLAIM_STATUSES
                    ),
                ),
            ),
            active_binding_count=active_binding_count,
            connected_parent_binding_count=await self._connected_parent_binding_count(
                session,
                route_ids=(route_id,),
            ),
            bound_resource_count=bound_resource_count,
            open_admission_count=await self._count(
                session,
                RDBExternalChannelInteraction,
                _open_selector_condition(
                    connection_id=None,
                    route_id=route_id,
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
                    RDBExternalChannelBinding.disconnected_at.is_(None),
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
    ) -> tuple[ProviderEffectPlan, ...]:
        """Disconnect bindings and capture bounded cleanup plans."""
        resources_by_id = {resource.id: resource for resource in resources}
        plans: list[ProviderEffectPlan] = []
        for binding in bindings:
            resource = resources_by_id.get(binding.resource_id)
            if resource is None:
                continue
            plans.extend(
                await terminate_binding_with_plans(
                    session,
                    work_state_store=self.work_state_store,
                    scheduled_task_lifecycle_repository=(
                        self.scheduled_task_lifecycle_repository
                    ),
                    binding=binding,
                    resource=resource,
                    now=now,
                    reason=reason,
                    emit_leave_presence=True,
                )
            )
        return tuple(plans)

    async def _locked_bindings(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
        connected_only: bool,
    ) -> list[RDBExternalChannelBinding]:
        """Lock bindings in stable order after the caller locks Session roots."""
        predicate: list[sa.ColumnElement[bool]] = [
            RDBExternalChannelBinding.agent_session_id.in_(session_ids)
        ]
        if connected_only:
            predicate.append(RDBExternalChannelBinding.disconnected_at.is_(None))
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


def _open_selector_condition(
    *,
    connection_id: str | None,
    route_id: str | None,
) -> sa.ColumnElement[bool]:
    """Match nonterminal interaction-owned selector state."""
    conditions: list[sa.ColumnElement[bool]] = [
        RDBExternalChannelInteraction.projection.op("?")("agent_selector"),
        RDBExternalChannelInteraction.status.in_(
            (
                ExternalChannelInteractionStatus.ACCEPTED,
                ExternalChannelInteractionStatus.PROCESSING,
                ExternalChannelInteractionStatus.COMPLETED,
            )
        ),
        RDBExternalChannelInteraction.expires_at > sa.func.now(),
    ]
    if connection_id is not None:
        conditions.append(RDBExternalChannelInteraction.connection_id == connection_id)
    if route_id is not None:
        conditions.append(
            RDBExternalChannelInteraction.projection["agent_selector"][
                "selected_route_id"
            ].as_string()
            == route_id
        )
    return sa.and_(*conditions)


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
