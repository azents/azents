"""External Channel access decisions and binding activation setup."""

import datetime
from dataclasses import dataclass
from typing import Annotated, Literal, assert_never

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStartReason,
    ExternalChannelAccessGrantScope,
    ExternalChannelAccessRequestStatus,
    ExternalChannelResourceStatus,
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
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcomeKind,
)
from azents.services.external_channel.ingestion_replay import (
    ExternalChannelIngestionReplayService,
    external_channel_replay_deadline,
)
from azents.services.root_agent_session_creation import (
    RootAgentSessionCreationService,
)
from azents.services.root_agent_session_creation.data import (
    AgentDefaultRootWorkspaceIntent,
)


class ExternalChannelAccessDecisionError(ValueError):
    """An access decision cannot be applied to the current domain state."""


class ExternalChannelAccessRequestNotFound(LookupError):
    """The access request does not exist."""


@dataclass(frozen=True)
class ExternalChannelAllowedAccess:
    """Durable result of an idempotent Allow decision."""

    request: ExternalChannelAccessRequest
    binding: ExternalChannelBinding
    grant: ExternalChannelAccessGrant
    control_delete_delivery_id: str | None


@dataclass(frozen=True)
class ExternalChannelResolvedAccess:
    """Durable result of an idempotent Deny or Block decision."""

    request: ExternalChannelAccessRequest
    control_delete_delivery_id: str | None


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
        Depends(ExternalChannelRepository),
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
        """Allow one participant and create its Session binding atomically."""
        async with self.session_manager() as session:
            request_snapshot = await self.repository.get_access_request(
                session,
                access_request_id=access_request_id,
            )
            if request_snapshot is None:
                raise ExternalChannelAccessRequestNotFound(access_request_id)
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
                delete_intent = (
                    await self.repository.create_access_request_control_delete_intent(
                        session,
                        access_request_id=request.id,
                    )
                )
                await session.commit()
                await self._replay_allowed_request(
                    access_request_id=request.id,
                    now=now,
                )
                return ExternalChannelAllowedAccess(
                    request=request,
                    binding=binding,
                    grant=grant,
                    control_delete_delivery_id=(
                        None if delete_intent is None else delete_intent.id
                    ),
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
                            agent_id=agent.id,
                            title=None,
                            start_reason=AgentSessionStartReason.EXTERNAL_CHANNEL,
                        ),
                        workspace_intent=AgentDefaultRootWorkspaceIntent(),
                    )
                )
                agent_session_id = root_session.agent_session.id
            binding = await self.repository.create_binding_idempotent(
                session,
                ExternalChannelBindingCreate(
                    resource_id=request.resource_id,
                    route_id=request.route_id,
                    agent_session_id=agent_session_id,
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
            delete_intent = (
                await self.repository.create_access_request_control_delete_intent(
                    session,
                    access_request_id=request.id,
                )
            )
            await session.commit()
            await self._replay_allowed_request(
                access_request_id=decided.id,
                now=now,
            )
            return ExternalChannelAllowedAccess(
                request=decided,
                binding=binding,
                grant=grant,
                control_delete_delivery_id=(
                    None if delete_intent is None else delete_intent.id
                ),
            )

    async def _replay_allowed_request(
        self,
        *,
        access_request_id: str,
        now: datetime.datetime,
    ) -> None:
        """Resume one committed typed Allow without reverting its decision."""
        outcome = await self.ingestion_replay_service.replay_access_allow(
            access_request_id=access_request_id,
            deadline=external_channel_replay_deadline(now=now),
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
            if request_snapshot.status is expected_status:
                request = await self._locked_request(
                    session,
                    access_request_id=access_request_id,
                )
                if request.status is not expected_status:
                    raise ExternalChannelAccessDecisionError(
                        "The access request changed during decision retry."
                    )
                delete_intent = (
                    await self.repository.create_access_request_control_delete_intent(
                        session,
                        access_request_id=request.id,
                    )
                )
                await session.commit()
                return ExternalChannelResolvedAccess(
                    request=request,
                    control_delete_delivery_id=(
                        None if delete_intent is None else delete_intent.id
                    ),
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
                delete_intent = (
                    await self.repository.create_access_request_control_delete_intent(
                        session,
                        access_request_id=request.id,
                    )
                )
                await session.commit()
                return ExternalChannelResolvedAccess(
                    request=request,
                    control_delete_delivery_id=(
                        None if delete_intent is None else delete_intent.id
                    ),
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
            delete_intent = (
                await self.repository.create_access_request_control_delete_intent(
                    session,
                    access_request_id=request.id,
                )
            )
            await session.commit()
            return ExternalChannelResolvedAccess(
                request=decided,
                control_delete_delivery_id=(
                    None if delete_intent is None else delete_intent.id
                ),
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
