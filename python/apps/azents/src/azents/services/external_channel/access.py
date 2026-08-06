"""External Channel access decisions and binding setup."""

import datetime
import logging
from dataclasses import dataclass
from typing import Annotated, Literal, assert_never

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionProductMode,
    AgentSessionStartReason,
    ExternalChannelAccessGrantScope,
    ExternalChannelAccessRequestStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelSetupClaimStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.external_channel.data import (
    ExternalChannelAccessGrant,
    ExternalChannelAccessGrantCreate,
    ExternalChannelAccessRequest,
    ExternalChannelBinding,
    ExternalChannelBindingCreate,
    ExternalChannelBlock,
    ExternalChannelBlockCreate,
    ExternalChannelSetupClaim,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcomeKind,
)
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
    external_channel_replay_deadline,
)
from azents.services.external_channel.provider_effect import ProviderEffectPlan
from azents.services.root_agent_session_creation import (
    RootAgentSessionCreationService,
)
from azents.services.root_agent_session_creation.data import (
    AgentDefaultRootWorkspaceIntent,
)

logger = logging.getLogger(__name__)


class ExternalChannelAccessDecisionError(ValueError):
    """An access decision cannot be applied to the current domain state."""


class ExternalChannelAccessRequestNotFound(LookupError):
    """The access request does not exist."""


@dataclass(frozen=True)
class ExternalChannelSetupContinuation:
    """Provider-neutral location setup state after an Allow decision."""

    setup_claim_id: str
    claim_generation: int
    source_revision: int
    route_id: str


@dataclass(frozen=True)
class ExternalChannelAllowedAccess:
    """Durable result of an idempotent Allow decision."""

    request: ExternalChannelAccessRequest
    binding: ExternalChannelBinding | None
    grant: ExternalChannelAccessGrant
    control_delete_plan: ProviderEffectPlan | None
    setup_continuation: ExternalChannelSetupContinuation | None


@dataclass(frozen=True)
class ExternalChannelResolvedAccess:
    """Durable result of an idempotent Deny or Block decision."""

    request: ExternalChannelAccessRequest
    control_delete_plan: ProviderEffectPlan | None


@dataclass(frozen=True)
class ExternalChannelRevokedAccess:
    """Durable access-policy revocation result."""

    grant: ExternalChannelAccessGrant


@dataclass(frozen=True)
class ExternalChannelRemovedBlock:
    """Durable block-removal result."""

    block: ExternalChannelBlock


@dataclass
class ExternalChannelAccessService:
    """Apply authenticated approver decisions without provider network calls."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]
    work_repository: Annotated[
        ExternalChannelWorkRepository,
        Depends(ExternalChannelWorkRepository.create),
    ]
    agent_repository: Annotated[
        AgentRepository,
        Depends(AgentRepository),
    ]
    root_agent_session_creation_service: Annotated[
        RootAgentSessionCreationService,
        Depends(RootAgentSessionCreationService),
    ]
    ingestion_replay_service: Annotated[
        ExternalChannelIngestionReplayService,
        Depends(ExternalChannelIngestionReplayService),
    ]

    async def allow(
        self,
        *,
        access_request_id: str,
        scope: ExternalChannelAccessGrantScope,
        decided_by_user_id: str,
        decision_summary: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelAllowedAccess:
        """Allow one participant and commit the applicable authorization state."""
        async with self.session_manager() as session:
            created_provider_event_type: str | None = None
            request_snapshot = await self.repository.get_access_request(
                session,
                access_request_id=access_request_id,
            )
            if request_snapshot is None:
                raise ExternalChannelAccessRequestNotFound(access_request_id)
            if request_snapshot.setup_claim_id is not None:
                return await self._allow_setup_request(
                    session,
                    request_snapshot=request_snapshot,
                    scope=scope,
                    decided_by_user_id=decided_by_user_id,
                    decision_summary=decision_summary,
                    now=now,
                )
            route_snapshot = await self.repository.get_agent_route(
                session,
                route_id=request_snapshot.route_id,
            )
            if route_snapshot is None:
                raise ExternalChannelAccessDecisionError(
                    "The External Channel route is unavailable."
                )
            connection = await self.repository.lock_connection_for_routing(
                session,
                connection_id=route_snapshot.connection_id,
            )
            if connection is None:
                raise ExternalChannelAccessDecisionError(
                    "The External Channel route is unavailable."
                )
            route = await self.repository.get_routable_route_by_id(
                session,
                route_id=request_snapshot.route_id,
            )
            if route is None or route.connection_id != connection.id:
                raise ExternalChannelAccessDecisionError(
                    "The External Channel route is unavailable."
                )
            active_agent_id = route.require_active_agent_id()
            resource = await self.repository.lock_resource(
                session,
                resource_id=request_snapshot.resource_id,
            )
            binding = await self.repository.lock_connected_binding_by_resource(
                session,
                resource_id=request_snapshot.resource_id,
            )
            if binding is not None and binding.route_id != route.id:
                raise ExternalChannelAccessDecisionError(
                    "The external conversation is already bound to another route."
                )
            request = await self._locked_request(
                session,
                access_request_id=access_request_id,
            )
            if request.status is ExternalChannelAccessRequestStatus.ALLOWED:
                grant = await self.repository.get_active_access_grant(
                    session,
                    agent_id=active_agent_id,
                    principal_id=request.principal_id,
                    agent_session_id=request.agent_session_id,
                )
                if binding is None or grant is None or grant.scope is not scope:
                    raise ExternalChannelAccessDecisionError(
                        "The prior Allow decision no longer has its active state."
                    )
                delete_plan = await self.work_repository.prepare_access_control_delete(
                    session,
                    access_request_id=request.id,
                )
                await session.commit()
                await self._replay_allowed_request(
                    access_request_id=request.id,
                    now=now,
                    initial_title_eligible=False,
                )
                return ExternalChannelAllowedAccess(
                    request=request,
                    binding=binding,
                    grant=grant,
                    control_delete_plan=delete_plan,
                    setup_continuation=None,
                )
            self._require_pending(request, now=now)
            if (
                resource is None
                or resource.status is not ExternalChannelResourceStatus.ACTIVE
            ):
                raise ExternalChannelAccessDecisionError(
                    "The external conversation is not active."
                )
            agent = await self.agent_repository.get_by_id(session, active_agent_id)
            if (
                agent is None
                or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            ):
                raise ExternalChannelAccessDecisionError("The Agent is not active.")
            if (
                await self.repository.get_active_block(
                    session,
                    agent_id=agent.id,
                    principal_id=request.principal_id,
                )
                is not None
            ):
                raise ExternalChannelAccessDecisionError(
                    "The external participant is blocked."
                )

            if binding is not None:
                agent_session_id = binding.agent_session_id
            elif request.agent_session_id is not None:
                raise ExternalChannelAccessDecisionError(
                    "The linked External Channel binding is no longer active."
                )
            else:
                root_session = (
                    await self.root_agent_session_creation_service.create_root_session(
                        session,
                        create=AgentSessionCreate(
                            workspace_id=agent.workspace_id,
                            product_mode=AgentSessionProductMode.TEAM,
                            associated_user_id=None,
                            agent_id=agent.id,
                            title=None,
                            start_reason=AgentSessionStartReason.EXTERNAL_CHANNEL,
                        ),
                        workspace_intent=AgentDefaultRootWorkspaceIntent(),
                    )
                )
                agent_session_id = root_session.agent_session.id
                if root_session.created:
                    created_provider_event_type = _provider_event_type(
                        provider=connection.provider,
                        labels=resource.labels,
                    )
            binding = await self.repository.create_binding_idempotent(
                session,
                ExternalChannelBindingCreate(
                    resource_id=request.resource_id,
                    route_id=request.route_id,
                    agent_session_id=agent_session_id,
                    response_mode=agent.external_channel_default_response_mode,
                    disconnected_at=None,
                    disconnect_reason=None,
                ),
                expected_access_request_id=request.id,
            )
            grant = await self.repository.ensure_access_grant(
                session,
                ExternalChannelAccessGrantCreate(
                    agent_id=agent.id,
                    principal_id=request.principal_id,
                    scope=scope,
                    agent_session_id=(
                        agent_session_id
                        if scope is ExternalChannelAccessGrantScope.SESSION
                        else None
                    ),
                    granted_by_user_id=decided_by_user_id,
                    source_access_request_id=request.id,
                    revoked_by_user_id=None,
                    revoked_at=None,
                ),
            )
            decided = await self.repository.decide_access_request(
                session,
                access_request_id=request.id,
                status=ExternalChannelAccessRequestStatus.ALLOWED,
                agent_session_id=agent_session_id,
                decided_by_user_id=decided_by_user_id,
                decision_summary=decision_summary,
                decided_at=now,
            )
            if decided is None:
                raise ExternalChannelAccessRequestNotFound(access_request_id)
            delete_plan = await self.work_repository.prepare_access_control_delete(
                session,
                access_request_id=request.id,
            )
            await session.commit()
            if created_provider_event_type is not None:
                logger.info(
                    "Created External Channel AgentSession",
                    extra={
                        "external_channel_provider": connection.provider.value,
                        "provider_event_type": created_provider_event_type,
                    },
                )
            await self._replay_allowed_request(
                access_request_id=decided.id,
                now=now,
                initial_title_eligible=created_provider_event_type is not None,
            )
            return ExternalChannelAllowedAccess(
                request=decided,
                binding=binding,
                grant=grant,
                control_delete_plan=delete_plan,
                setup_continuation=None,
            )

    async def _allow_setup_request(
        self,
        session: AsyncSession,
        *,
        request_snapshot: ExternalChannelAccessRequest,
        scope: ExternalChannelAccessGrantScope,
        decided_by_user_id: str,
        decision_summary: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelAllowedAccess:
        """Grant setup access without creating or replaying a Binding."""
        if scope is not ExternalChannelAccessGrantScope.AGENT:
            raise ExternalChannelAccessDecisionError(
                "Initial channel setup requires an Agent-scoped access grant."
            )
        setup_claim_id = request_snapshot.setup_claim_id
        assert setup_claim_id is not None
        route_snapshot = await self.repository.get_agent_route(
            session,
            route_id=request_snapshot.route_id,
        )
        if route_snapshot is None:
            raise ExternalChannelAccessDecisionError(
                "The External Channel route is unavailable."
            )
        connection = await self.repository.lock_connection_for_routing(
            session,
            connection_id=route_snapshot.connection_id,
        )
        route = await self.repository.get_routable_route_by_id(
            session,
            route_id=request_snapshot.route_id,
        )
        resource = await self.repository.lock_resource(
            session,
            resource_id=request_snapshot.resource_id,
        )
        claim = await self.repository.lock_setup_claim(
            session,
            claim_id=setup_claim_id,
        )
        request = await self._locked_request(
            session,
            access_request_id=request_snapshot.id,
        )
        if (
            connection is None
            or route is None
            or route.connection_id != connection.id
            or resource is None
            or resource.connection_id != connection.id
            or resource.status is not ExternalChannelResourceStatus.ACTIVE
            or claim is None
            or claim.connection_id != connection.id
            or claim.route_id != route.id
            or claim.source_resource_id != resource.id
            or claim.principal_id != request.principal_id
            or claim.status
            not in {
                ExternalChannelSetupClaimStatus.PENDING_LOCATION,
                ExternalChannelSetupClaimStatus.SELECTED,
                ExternalChannelSetupClaimStatus.COMPLETED,
            }
            or request.setup_claim_id != claim.id
        ):
            raise ExternalChannelAccessDecisionError(
                "The External Channel setup request is unavailable."
            )
        active_agent_id = route.require_active_agent_id()
        if (
            await self.repository.get_active_block(
                session,
                agent_id=active_agent_id,
                principal_id=request.principal_id,
            )
            is not None
        ):
            raise ExternalChannelAccessDecisionError(
                "The external participant is blocked."
            )
        if request.status is ExternalChannelAccessRequestStatus.ALLOWED:
            grant = await self.repository.get_active_access_grant(
                session,
                agent_id=active_agent_id,
                principal_id=request.principal_id,
                agent_session_id=None,
            )
            if (
                grant is None
                or grant.scope is not ExternalChannelAccessGrantScope.AGENT
            ):
                raise ExternalChannelAccessDecisionError(
                    "The prior setup Allow decision no longer has its active grant."
                )
            delete_plan = await self.work_repository.prepare_access_control_delete(
                session,
                access_request_id=request.id,
            )
            await session.commit()
            return ExternalChannelAllowedAccess(
                request=request,
                binding=None,
                grant=grant,
                control_delete_plan=delete_plan,
                setup_continuation=_setup_continuation(claim),
            )
        self._require_pending(request, now=now)
        grant = await self.repository.ensure_access_grant(
            session,
            ExternalChannelAccessGrantCreate(
                agent_id=active_agent_id,
                principal_id=request.principal_id,
                scope=ExternalChannelAccessGrantScope.AGENT,
                agent_session_id=None,
                granted_by_user_id=decided_by_user_id,
                source_access_request_id=request.id,
                revoked_by_user_id=None,
                revoked_at=None,
            ),
        )
        decided = await self.repository.decide_access_request(
            session,
            access_request_id=request.id,
            status=ExternalChannelAccessRequestStatus.ALLOWED,
            agent_session_id=None,
            decided_by_user_id=decided_by_user_id,
            decision_summary=decision_summary,
            decided_at=now,
        )
        if decided is None:
            raise ExternalChannelAccessRequestNotFound(request.id)
        delete_plan = await self.work_repository.prepare_access_control_delete(
            session,
            access_request_id=request.id,
        )
        await session.commit()
        return ExternalChannelAllowedAccess(
            request=decided,
            binding=None,
            grant=grant,
            control_delete_plan=delete_plan,
            setup_continuation=_setup_continuation(claim),
        )

    async def _replay_allowed_request(
        self,
        *,
        access_request_id: str,
        now: datetime.datetime,
        initial_title_eligible: bool,
    ) -> None:
        """Resume one committed typed Allow without reverting its decision."""
        outcome = await self.ingestion_replay_service.replay_access_allow(
            access_request_id=access_request_id,
            deadline=external_channel_replay_deadline(now=now),
            initial_title_eligible=initial_title_eligible,
        )
        match outcome.kind:
            case (
                ExternalChannelIngestionOutcomeKind.ACCEPTED
                | ExternalChannelIngestionOutcomeKind.DUPLICATE
            ):
                return
            case (
                ExternalChannelIngestionOutcomeKind.AWAITING_SELECTION
                | ExternalChannelIngestionOutcomeKind.AWAITING_ACCESS
                | ExternalChannelIngestionOutcomeKind.IGNORED
                | ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
                | ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION
            ):
                raise ExternalChannelAccessDecisionError(
                    "The allowed External Channel invocation could not be resumed."
                )
            case _ as unreachable:
                assert_never(unreachable)

    async def deny(
        self,
        *,
        access_request_id: str,
        decided_by_user_id: str,
        decision_summary: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelResolvedAccess:
        """Resolve only the source access request as denied."""
        return await self._resolve(
            access_request_id=access_request_id,
            action="deny",
            decided_by_user_id=decided_by_user_id,
            decision_summary=decision_summary,
            now=now,
        )

    async def block(
        self,
        *,
        access_request_id: str,
        decided_by_user_id: str,
        decision_summary: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelResolvedAccess:
        """Create the Agent-level block and resolve the source request."""
        return await self._resolve(
            access_request_id=access_request_id,
            action="block",
            decided_by_user_id=decided_by_user_id,
            decision_summary=decision_summary,
            now=now,
        )

    async def revoke_grant(
        self,
        *,
        grant_id: str,
    ) -> ExternalChannelRevokedAccess:
        """Revoke one Session- or Agent-scoped participant grant."""
        async with self.session_manager() as session:
            grant = await self.repository.delete_access_grant(
                session,
                grant_id=grant_id,
            )
            if grant is None:
                raise ExternalChannelAccessDecisionError(
                    "The access grant does not exist."
                )
            await session.commit()
            return ExternalChannelRevokedAccess(grant=grant)

    async def remove_block(
        self,
        *,
        block_id: str,
        removed_by_user_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelRemovedBlock:
        """Remove one Agent-level participant block."""
        async with self.session_manager() as session:
            block = await self.repository.remove_block(
                session,
                block_id=block_id,
                removed_by_user_id=removed_by_user_id,
                removed_at=now,
            )
            if block is None:
                raise ExternalChannelAccessDecisionError(
                    "The access block does not exist."
                )
            await session.commit()
            return ExternalChannelRemovedBlock(block=block)

    async def _resolve(
        self,
        *,
        access_request_id: str,
        action: Literal["deny", "block"],
        decided_by_user_id: str,
        decision_summary: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelResolvedAccess:
        async with self.session_manager() as session:
            request_snapshot = await self.repository.get_access_request(
                session,
                access_request_id=access_request_id,
            )
            if request_snapshot is None:
                raise ExternalChannelAccessRequestNotFound(access_request_id)
            expected_status = (
                ExternalChannelAccessRequestStatus.BLOCKED
                if action == "block"
                else ExternalChannelAccessRequestStatus.DENIED
            )
            if request_snapshot.setup_claim_id is not None:
                return await self._resolve_setup_request(
                    session,
                    request_snapshot=request_snapshot,
                    action=action,
                    expected_status=expected_status,
                    decided_by_user_id=decided_by_user_id,
                    decision_summary=decision_summary,
                    now=now,
                )
            if request_snapshot.status is expected_status:
                request = await self._locked_request(
                    session,
                    access_request_id=access_request_id,
                )
                if request.status is not expected_status:
                    raise ExternalChannelAccessDecisionError(
                        "The access request changed during decision retry."
                    )
                delete_plan = await self.work_repository.prepare_access_control_delete(
                    session,
                    access_request_id=request.id,
                )
                await session.commit()
                return ExternalChannelResolvedAccess(
                    request=request,
                    control_delete_plan=delete_plan,
                )
            route_snapshot = await self.repository.get_agent_route(
                session,
                route_id=request_snapshot.route_id,
            )
            if route_snapshot is None:
                raise ExternalChannelAccessDecisionError(
                    "The External Channel route does not exist."
                )
            connection = await self.repository.lock_connection_for_routing(
                session,
                connection_id=route_snapshot.connection_id,
            )
            if connection is None:
                raise ExternalChannelAccessDecisionError(
                    "The External Channel route is unavailable."
                )
            route = await self.repository.get_routable_route_by_id(
                session,
                route_id=request_snapshot.route_id,
            )
            if route is None or route.connection_id != connection.id:
                raise ExternalChannelAccessDecisionError(
                    "The External Channel route is unavailable."
                )
            resource = await self.repository.lock_resource(
                session,
                resource_id=request_snapshot.resource_id,
            )
            if resource is None or resource.connection_id != connection.id:
                raise ExternalChannelAccessDecisionError(
                    "The external conversation is unavailable."
                )
            binding = await self.repository.lock_connected_binding_by_resource(
                session,
                resource_id=resource.id,
            )
            if binding is not None and binding.route_id != route.id:
                raise ExternalChannelAccessDecisionError(
                    "The external conversation is already bound to another route."
                )
            request = await self._locked_request(
                session,
                access_request_id=access_request_id,
            )
            if request.status is expected_status:
                delete_plan = await self.work_repository.prepare_access_control_delete(
                    session,
                    access_request_id=request.id,
                )
                await session.commit()
                return ExternalChannelResolvedAccess(
                    request=request,
                    control_delete_plan=delete_plan,
                )
            self._require_pending(request, now=now)
            if action == "block":
                active_agent_id = route.require_active_agent_id()
                await self.repository.create_block_idempotent(
                    session,
                    ExternalChannelBlockCreate(
                        agent_id=active_agent_id,
                        principal_id=request.principal_id,
                        blocked_by_user_id=decided_by_user_id,
                        reason=decision_summary,
                        removed_by_user_id=None,
                        removed_at=None,
                    ),
                )
            decided = await self.repository.decide_access_request(
                session,
                access_request_id=request.id,
                status=expected_status,
                agent_session_id=request.agent_session_id,
                decided_by_user_id=decided_by_user_id,
                decision_summary=decision_summary,
                decided_at=now,
            )
            if decided is None:
                raise ExternalChannelAccessRequestNotFound(access_request_id)
            delete_plan = await self.work_repository.prepare_access_control_delete(
                session,
                access_request_id=request.id,
            )
            await session.commit()
            return ExternalChannelResolvedAccess(
                request=decided,
                control_delete_plan=delete_plan,
            )

    async def _resolve_setup_request(
        self,
        session: AsyncSession,
        *,
        request_snapshot: ExternalChannelAccessRequest,
        action: Literal["deny", "block"],
        expected_status: ExternalChannelAccessRequestStatus,
        decided_by_user_id: str,
        decision_summary: str | None,
        now: datetime.datetime,
    ) -> ExternalChannelResolvedAccess:
        """Resolve setup access and terminate its pre-Session continuation."""
        setup_claim_id = request_snapshot.setup_claim_id
        assert setup_claim_id is not None
        route_snapshot = await self.repository.get_agent_route(
            session,
            route_id=request_snapshot.route_id,
        )
        if route_snapshot is None:
            raise ExternalChannelAccessDecisionError(
                "The External Channel route does not exist."
            )
        connection = await self.repository.lock_connection_for_routing(
            session,
            connection_id=route_snapshot.connection_id,
        )
        route = await self.repository.get_routable_route_by_id(
            session,
            route_id=request_snapshot.route_id,
        )
        resource = await self.repository.lock_resource(
            session,
            resource_id=request_snapshot.resource_id,
        )
        claim = await self.repository.lock_setup_claim(
            session,
            claim_id=setup_claim_id,
        )
        request = await self._locked_request(
            session,
            access_request_id=request_snapshot.id,
        )
        if (
            connection is None
            or route is None
            or route.connection_id != connection.id
            or resource is None
            or resource.connection_id != connection.id
            or claim is None
            or claim.connection_id != connection.id
            or claim.route_id != route.id
            or claim.source_resource_id != resource.id
            or claim.principal_id != request.principal_id
            or request.setup_claim_id != claim.id
        ):
            raise ExternalChannelAccessDecisionError(
                "The External Channel setup request is unavailable."
            )
        if request.status is expected_status:
            delete_plan = await self.work_repository.prepare_access_control_delete(
                session,
                access_request_id=request.id,
            )
            await session.commit()
            return ExternalChannelResolvedAccess(
                request=request,
                control_delete_plan=delete_plan,
            )
        self._require_pending(request, now=now)
        if action == "block":
            await self.repository.create_block_idempotent(
                session,
                ExternalChannelBlockCreate(
                    agent_id=route.require_active_agent_id(),
                    principal_id=request.principal_id,
                    blocked_by_user_id=decided_by_user_id,
                    reason=decision_summary,
                    removed_by_user_id=None,
                    removed_at=None,
                ),
            )
        decided = await self.repository.decide_access_request(
            session,
            access_request_id=request.id,
            status=expected_status,
            agent_session_id=None,
            decided_by_user_id=decided_by_user_id,
            decision_summary=decision_summary,
            decided_at=now,
        )
        if decided is None:
            raise ExternalChannelAccessRequestNotFound(request.id)
        if claim.status in {
            ExternalChannelSetupClaimStatus.PENDING_AGENT,
            ExternalChannelSetupClaimStatus.PENDING_LOCATION,
            ExternalChannelSetupClaimStatus.SELECTED,
        }:
            terminated = await self.repository.terminate_setup_claim(
                session,
                claim_id=claim.id,
                expected_claim_generation=claim.claim_generation,
                status=(
                    ExternalChannelSetupClaimStatus.INVALIDATED
                    if action == "block"
                    else ExternalChannelSetupClaimStatus.EXPIRED
                ),
            )
            if terminated is None:
                raise ExternalChannelAccessDecisionError(
                    "The External Channel setup changed during access resolution."
                )
        delete_plan = await self.work_repository.prepare_access_control_delete(
            session,
            access_request_id=request.id,
        )
        await session.commit()
        return ExternalChannelResolvedAccess(
            request=decided,
            control_delete_plan=delete_plan,
        )

    async def _locked_request(
        self,
        session: AsyncSession,
        *,
        access_request_id: str,
    ) -> ExternalChannelAccessRequest:
        request = await self.repository.lock_access_request(
            session,
            access_request_id=access_request_id,
        )
        if request is None:
            raise ExternalChannelAccessRequestNotFound(access_request_id)
        return request

    @staticmethod
    def _require_pending(
        request: ExternalChannelAccessRequest,
        *,
        now: datetime.datetime,
    ) -> None:
        if request.status is not ExternalChannelAccessRequestStatus.PENDING:
            raise ExternalChannelAccessDecisionError(
                "The access request has already been resolved."
            )
        if request.expires_at <= now:
            raise ExternalChannelAccessDecisionError("The access request has expired.")


def _provider_event_type(
    *,
    provider: ExternalChannelProvider,
    labels: dict[str, object] | None,
) -> str:
    """Return the sanitized provider event kind retained with the resource."""
    value = None if labels is None else labels.get("provider_event_type")
    expected = {
        ExternalChannelProvider.SLACK: {"app_mention", "message"},
        ExternalChannelProvider.DISCORD: {"discord_message_create"},
    }
    return (
        value if isinstance(value, str) and value in expected[provider] else "unknown"
    )


def _setup_continuation(
    claim: ExternalChannelSetupClaim,
) -> ExternalChannelSetupContinuation | None:
    """Project a pending location claim for provider-control continuation."""
    route_id = claim.route_id
    if (
        claim.status is not ExternalChannelSetupClaimStatus.PENDING_LOCATION
        or route_id is None
    ):
        return None
    return ExternalChannelSetupContinuation(
        setup_claim_id=claim.id,
        claim_generation=claim.claim_generation,
        source_revision=claim.source_revision,
        route_id=route_id,
    )
