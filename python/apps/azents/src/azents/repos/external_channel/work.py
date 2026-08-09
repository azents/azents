"""External Channel Work persistence and direct provider-effect planning."""

import datetime
from collections.abc import Sequence
from typing import Literal, assert_never

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStatus,
    ExternalChannelAccessRequestStatus,
    ExternalChannelActionMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelWorkProjectionStatus,
    ExternalChannelWorkStatus,
    ExternalChannelWorkTaskStatus,
)
from azents.core.external_channel_file import ExternalChannelOutboundFileManifest
from azents.core.external_channel_progress import ExternalChannelDesiredProgress
from azents.core.external_channel_session_presence import session_presence_payload
from azents.core.external_channel_title import DISCORD_INITIAL_THREAD_TITLE_LABEL
from azents.core.slack_external_channel_progress import (
    render_slack_persisted_progress,
    render_slack_progress,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessRequest,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelResource,
    RDBExternalChannelSetupClaim,
)
from azents.rdb.models.workspace import RDBWorkspace
from azents.repos.external_channel.work_data import (
    ChannelActionEffectPlan,
    ChannelActionTransition,
    ChannelWorkSnapshot,
    ChannelWorkTask,
    ExternalChannelFileAccessTarget,
)
from azents.repos.external_channel.work_state import (
    ChannelWorkProjectionPartState,
    ChannelWorkState,
    ChannelWorkStateMutation,
    ExternalChannelWorkStateStore,
)
from azents.services.external_channel.discord_delivery import (
    DISCORD_CREATE_MESSAGE_MAX_REQUEST_BYTES,
    DISCORD_DEFAULT_MAX_FILE_BYTES,
)
from azents.services.external_channel.discord_presentation import (
    render_discord_persisted_progress,
    split_discord_markdown,
)
from azents.services.external_channel.provider_effect import (
    ProviderEffectPlan,
    ProviderMutationOutcome,
    ProviderOperationKey,
    ProviderTarget,
)
from azents.services.external_channel.slack_events import (
    SLACK_MARKDOWN_TEXT_MAX_LENGTH,
)


class ExternalChannelWorkRepository:
    """Own canonical Channel Work and current provider projection state."""

    @classmethod
    def create(cls) -> "ExternalChannelWorkRepository":
        """Create a Work repository for application dependency injection."""
        return cls()

    def __init__(
        self,
        work_state_store: ExternalChannelWorkStateStore | None = None,
    ) -> None:
        """Create the Work repository."""
        self.work_state_store = work_state_store or ExternalChannelWorkStateStore()

    async def prepare_access_control_create(
        self,
        session: AsyncSession,
        *,
        access_request_id: str,
        connection_id: str,
        resource_id: str | None,
        route_id: str | None,
        binding_id: str | None,
        request_payload: dict[str, object],
        operation_seed: str,
    ) -> ProviderEffectPlan | None:
        """Claim one access-control create as conservatively unknown before I/O."""
        request = await session.scalar(
            sa.select(RDBExternalChannelAccessRequest)
            .where(
                RDBExternalChannelAccessRequest.id == access_request_id,
                RDBExternalChannelAccessRequest.status
                == ExternalChannelAccessRequestStatus.PENDING,
            )
            .with_for_update()
        )
        if (
            request is None
            or request.control_provider_message_key is not None
            or request.control_projection_status is not None
        ):
            return None
        request.control_projection_status = ExternalChannelWorkProjectionStatus.UNKNOWN
        await session.flush()
        return await self.prepare_direct_control(
            session,
            connection_id=connection_id,
            resource_id=resource_id,
            route_id=route_id,
            binding_id=binding_id,
            operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            request_payload=request_payload,
            operation_seed=operation_seed,
        )

    async def prepare_direct_control(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        resource_id: str | None,
        route_id: str | None,
        binding_id: str | None,
        operation: ExternalChannelDeliveryOperation,
        request_payload: dict[str, object],
        operation_seed: str,
    ) -> ProviderEffectPlan | None:
        """Capture one process-local provider control from current domain state."""
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection).where(
                RDBExternalChannelConnection.id == connection_id,
                RDBExternalChannelConnection.disconnected_at.is_(None),
            )
        )
        if connection is None:
            return None
        resource = (
            None
            if resource_id is None
            else await session.scalar(
                sa.select(RDBExternalChannelResource).where(
                    RDBExternalChannelResource.id == resource_id,
                    RDBExternalChannelResource.connection_id == connection.id,
                    RDBExternalChannelResource.status
                    == ExternalChannelResourceStatus.ACTIVE,
                )
            )
        )
        if resource_id is not None and resource is None:
            return None
        route = (
            None
            if route_id is None
            else await session.scalar(
                sa.select(RDBExternalChannelAgentRoute).where(
                    RDBExternalChannelAgentRoute.id == route_id,
                    RDBExternalChannelAgentRoute.connection_id == connection.id,
                )
            )
        )
        if route_id is not None and route is None:
            return None
        binding = (
            None
            if binding_id is None
            else await session.scalar(
                sa.select(RDBExternalChannelBinding).where(
                    RDBExternalChannelBinding.id == binding_id,
                    RDBExternalChannelBinding.resource_id == resource_id,
                    RDBExternalChannelBinding.disconnected_at.is_(None),
                )
            )
        )
        if binding_id is not None and binding is None:
            return None
        if binding is not None:
            if route is None:
                route = await session.get(
                    RDBExternalChannelAgentRoute,
                    binding.route_id,
                )
            if route is None or route.connection_id != connection.id:
                return None
        agent = (
            None
            if route is None or route.agent_id is None
            else await session.scalar(
                sa.select(RDBAgent).where(
                    RDBAgent.id == route.agent_id,
                    RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                )
            )
        )
        workspace = (
            None
            if agent is None
            else await session.get(RDBWorkspace, agent.workspace_id)
        )
        agent_session = (
            None
            if binding is None
            else await session.get(RDBAgentSession, binding.agent_session_id)
        )
        return ProviderEffectPlan(
            target=ProviderTarget(
                operation=operation,
                binding_id=None if binding is None else binding.id,
                resource_id=None if resource is None else resource.id,
                connection_id=connection.id,
                provider=connection.provider,
                app_mode=connection.app_mode,
                encrypted_credentials=connection.encrypted_credentials,
                provider_tenant_id=connection.provider_tenant_id,
                capabilities=connection.capabilities,
                workspace_handle=None if workspace is None else workspace.handle,
                agent_id=None if agent is None else agent.id,
                agent_session_id=(None if agent_session is None else agent_session.id),
                agent_name=None if agent is None else agent.name,
                agent_avatar=None if agent is None else agent.avatar,
                request_payload=request_payload,
            ),
            operation_key=ProviderOperationKey.from_seed(operation_seed),
        )

    async def revalidate_direct_control(
        self,
        session: AsyncSession,
        *,
        plan: ProviderEffectPlan,
    ) -> ProviderEffectPlan | None:
        """Refresh one process-local control against current provider authority."""
        target = plan.target
        route_id: str | None = None
        if (
            target.operation is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
            and target.request_payload.get("control_kind") == "setup_required"
        ):
            setup_claim_id = target.request_payload.get("setup_claim_id")
            if not isinstance(setup_claim_id, str):
                return None
            claim = await session.get(
                RDBExternalChannelSetupClaim,
                setup_claim_id,
            )
            if claim is None or claim.route_id is None:
                return None
            route_id = claim.route_id
        access_request_id = target.request_payload.get("access_request_id")
        if (
            target.operation is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
            and isinstance(access_request_id, str)
        ):
            request = await session.scalar(
                sa.select(RDBExternalChannelAccessRequest).where(
                    RDBExternalChannelAccessRequest.id == access_request_id,
                    RDBExternalChannelAccessRequest.status
                    == ExternalChannelAccessRequestStatus.PENDING,
                    RDBExternalChannelAccessRequest.control_provider_message_key.is_(
                        None
                    ),
                    RDBExternalChannelAccessRequest.control_projection_status
                    == ExternalChannelWorkProjectionStatus.UNKNOWN,
                )
            )
            if request is None:
                return None
        return await self.prepare_direct_control(
            session,
            connection_id=target.connection_id,
            resource_id=target.resource_id,
            route_id=route_id,
            binding_id=target.binding_id,
            operation=target.operation,
            request_payload=target.request_payload,
            operation_seed=plan.operation_key.value,
        )

    async def revalidate_terminal_control(
        self,
        session: AsyncSession,
        *,
        plan: ProviderEffectPlan,
    ) -> ProviderEffectPlan | None:
        """Verify a captured cleanup plan against committed terminal state."""
        target = plan.target
        if target.binding_id is None or target.resource_id is None:
            return None
        row = (
            await session.execute(
                sa.select(
                    RDBExternalChannelBinding,
                    RDBExternalChannelResource,
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelConnection,
                )
                .join(
                    RDBExternalChannelResource,
                    RDBExternalChannelResource.id
                    == RDBExternalChannelBinding.resource_id,
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
                .where(
                    RDBExternalChannelBinding.id == target.binding_id,
                    RDBExternalChannelBinding.resource_id == target.resource_id,
                    RDBExternalChannelBinding.disconnected_at.is_not(None),
                    RDBExternalChannelResource.connection_id
                    == RDBExternalChannelConnection.id,
                    RDBExternalChannelConnection.id == target.connection_id,
                    RDBExternalChannelConnection.provider == target.provider,
                    RDBExternalChannelConnection.app_mode == target.app_mode,
                )
            )
        ).one_or_none()
        if row is None or target.encrypted_credentials is None:
            return None
        return plan

    async def prepare_initial_progress(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
        work_cycle_id: str,
    ) -> ProviderEffectPlan | None:
        """Plan the first current progress projection after canonical admission."""
        row = (
            await session.execute(
                sa.select(
                    RDBExternalChannelBinding,
                    RDBExternalChannelResource,
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelConnection,
                )
                .join(
                    RDBExternalChannelResource,
                    RDBExternalChannelResource.id
                    == RDBExternalChannelBinding.resource_id,
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
                .where(
                    RDBExternalChannelBinding.id == binding_id,
                    RDBExternalChannelBinding.agent_session_id == session_id,
                    RDBExternalChannelBinding.disconnected_at.is_(None),
                    RDBExternalChannelAgentRoute.agent_id == agent_id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        binding, resource, route, connection = row
        work = await self.work_state_store.load(
            session,
            agent_id=agent_id,
            session_id=session_id,
            binding_id=binding_id,
        )
        if (
            work is None
            or work.status is not ExternalChannelWorkStatus.ACTIVE
            or work.work_cycle_id != work_cycle_id
            or work.desired_progress is None
            or any(part.part_ordinal == 0 for part in work.projection_parts)
        ):
            return None
        if connection.provider is ExternalChannelProvider.SLACK:
            rendered = render_slack_persisted_progress(
                work.desired_progress,
                work_id=work.work_cycle_id,
                desired_progress_revision=work.desired_progress_revision,
            )
            payload = _provider_payload(
                connection.provider,
                resource.labels,
                text=rendered.text,
                blocks=rendered.blocks,
                desired_progress_revision=work.desired_progress_revision,
            )
        else:
            rendered_discord = render_discord_persisted_progress(
                work.desired_progress,
                work_id=work.work_cycle_id,
                desired_progress_revision=work.desired_progress_revision,
            )
            if not rendered_discord.pages:
                return None
            page = rendered_discord.pages[0]
            payload = _provider_payload(
                connection.provider,
                resource.labels,
                text=page.text,
                desired_progress_revision=work.desired_progress_revision,
            )
            payload["embeds"] = page.embeds
        payload["work_id"] = work.work_cycle_id
        payload["part_ordinal"] = 0
        plan = await self.prepare_direct_control(
            session,
            connection_id=connection.id,
            resource_id=resource.id,
            route_id=route.id,
            binding_id=binding.id,
            operation=ExternalChannelDeliveryOperation.PROGRESS_CREATE,
            request_payload=payload,
            operation_seed=(
                f"initial-progress:{work.work_cycle_id}:"
                f"{work.desired_progress_revision}"
            ),
        )
        if plan is None:
            return None
        assert work is not None
        expected_work_cycle_id = work.work_cycle_id
        expected_progress_revision = work.desired_progress_revision

        def claim(
            current: ChannelWorkState,
        ) -> ChannelWorkStateMutation[bool]:
            if (
                current.status is not ExternalChannelWorkStatus.ACTIVE
                or current.work_cycle_id != expected_work_cycle_id
                or current.desired_progress_revision != expected_progress_revision
                or current.desired_progress is None
                or any(part.part_ordinal == 0 for part in current.projection_parts)
            ):
                return ChannelWorkStateMutation(
                    state=current,
                    result=False,
                    changed=False,
                )
            updated = current.model_copy(deep=True)
            updated.projection_parts.append(
                ChannelWorkProjectionPartState(
                    part_ordinal=0,
                    desired_progress_revision=current.desired_progress_revision,
                    status=ExternalChannelWorkProjectionStatus.UNKNOWN,
                    provider_message_key=None,
                )
            )
            return ChannelWorkStateMutation(state=updated, result=True)

        claimed = await self.work_state_store.update_existing(
            session,
            agent_id=agent_id,
            session_id=session_id,
            binding_id=binding_id,
            mutator=claim,
        )
        return plan if claimed is not None and claimed.result else None

    async def prepare_access_control_delete(
        self,
        session: AsyncSession,
        *,
        access_request_id: str,
    ) -> ProviderEffectPlan | None:
        """Capture the current access-control message for one direct delete."""
        request = await session.scalar(
            sa.select(RDBExternalChannelAccessRequest)
            .where(
                RDBExternalChannelAccessRequest.id == access_request_id,
                RDBExternalChannelAccessRequest.status
                != ExternalChannelAccessRequestStatus.PENDING,
            )
            .with_for_update()
        )
        if (
            request is None
            or request.control_provider_message_key is None
            or request.control_projection_status
            is not ExternalChannelWorkProjectionStatus.PRESENT
        ):
            return None
        route = await session.get(RDBExternalChannelAgentRoute, request.route_id)
        resource = await session.get(RDBExternalChannelResource, request.resource_id)
        if (
            route is None
            or resource is None
            or resource.connection_id != route.connection_id
        ):
            return None
        connection = await session.get(
            RDBExternalChannelConnection, route.connection_id
        )
        if connection is None:
            return None
        binding = await session.scalar(
            sa.select(RDBExternalChannelBinding).where(
                RDBExternalChannelBinding.resource_id == resource.id,
                RDBExternalChannelBinding.route_id == route.id,
                RDBExternalChannelBinding.disconnected_at.is_(None),
            )
        )
        payload = _provider_payload(
            connection.provider,
            resource.labels,
            provider_message_key=request.control_provider_message_key,
        )
        payload["access_request_id"] = request.id
        return await self.prepare_direct_control(
            session,
            connection_id=connection.id,
            resource_id=resource.id,
            route_id=route.id,
            binding_id=None if binding is None else binding.id,
            operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
            request_payload=payload,
            operation_seed=f"access-delete:{request.id}:{request.updated_at.isoformat()}",
        )

    async def apply_access_control_outcome(
        self,
        session: AsyncSession,
        *,
        plan: ProviderEffectPlan,
        outcome: ProviderMutationOutcome,
    ) -> bool:
        """Compare-and-set current access-control provider projection state."""
        access_request_id = plan.target.request_payload.get("access_request_id")
        if not isinstance(access_request_id, str):
            return False
        request = await session.scalar(
            sa.select(RDBExternalChannelAccessRequest)
            .where(RDBExternalChannelAccessRequest.id == access_request_id)
            .with_for_update()
        )
        if request is None:
            return False
        if plan.target.operation is ExternalChannelDeliveryOperation.PROGRESS_DELETE:
            expected_key = plan.target.request_payload.get("provider_message_key")
            if (
                not isinstance(expected_key, str)
                or request.control_provider_message_key != expected_key
            ):
                return False
            if outcome.status == "delivered":
                request.control_provider_message_key = None
                request.control_projection_status = (
                    ExternalChannelWorkProjectionStatus.DELETED
                )
            elif outcome.status == "failed":
                request.control_projection_status = (
                    ExternalChannelWorkProjectionStatus.FAILED
                )
            else:
                request.control_projection_status = (
                    ExternalChannelWorkProjectionStatus.UNKNOWN
                )
        elif plan.target.operation is ExternalChannelDeliveryOperation.CONTROL_MESSAGE:
            if outcome.status == "delivered":
                if outcome.provider_message_key is None:
                    request.control_projection_status = (
                        ExternalChannelWorkProjectionStatus.UNKNOWN
                    )
                else:
                    request.control_provider_message_key = outcome.provider_message_key
                    request.control_projection_status = (
                        ExternalChannelWorkProjectionStatus.PRESENT
                    )
            elif outcome.status == "failed":
                request.control_projection_status = (
                    ExternalChannelWorkProjectionStatus.FAILED
                )
            else:
                request.control_projection_status = (
                    ExternalChannelWorkProjectionStatus.UNKNOWN
                )
        else:
            return False
        await session.flush()
        return True

    async def ensure_active_work(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        binding_id: str,
        desired_progress: ExternalChannelDesiredProgress,
    ) -> ChannelWorkState:
        """Create or reuse the one active Work cycle for an invoked binding."""

        def new_state() -> ChannelWorkState:
            return ChannelWorkState(
                binding_id=binding_id,
                work_cycle_id=uuid7().hex,
                status=ExternalChannelWorkStatus.ACTIVE,
                title=desired_progress.title,
                tasks=list(desired_progress.tasks),
                state_revision=1,
                desired_progress_revision=1,
                desired_progress=desired_progress,
                finished_at=None,
                projection_parts=[],
            )

        def activate(
            current: ChannelWorkState,
        ) -> ChannelWorkStateMutation[ChannelWorkState]:
            if current.status is ExternalChannelWorkStatus.ACTIVE:
                return ChannelWorkStateMutation(
                    state=current,
                    result=current,
                    changed=False,
                )
            replacement = new_state()
            return ChannelWorkStateMutation(
                state=replacement,
                result=replacement,
            )

        mutation = await self.work_state_store.update(
            session,
            agent_id=agent_id,
            session_id=session_id,
            binding_id=binding_id,
            default_factory=new_state,
            mutator=activate,
        )
        return mutation.result

    async def has_active_binding(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        agent_id: str,
    ) -> bool:
        """Return whether the root Session can receive Channel Actions."""
        exists = await session.scalar(
            sa.select(
                sa.exists().where(
                    RDBExternalChannelBinding.agent_session_id == session_id,
                    RDBExternalChannelBinding.disconnected_at.is_(None),
                    RDBExternalChannelBinding.agent_session_id == RDBAgentSession.id,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgentSession.agent_id == agent_id,
                    RDBAgent.id == agent_id,
                    RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                    RDBExternalChannelBinding.route_id
                    == RDBExternalChannelAgentRoute.id,
                    RDBExternalChannelAgentRoute.agent_id == agent_id,
                    RDBExternalChannelAgentRoute.connection_id
                    == RDBExternalChannelConnection.id,
                )
            )
        )
        return bool(exists)

    async def get_active_file_access_target(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        agent_id: str,
        binding_id: str,
    ) -> ExternalChannelFileAccessTarget | None:
        """Resolve one active binding and its current provider credential boundary."""
        row = (
            await session.execute(
                sa.select(
                    RDBExternalChannelBinding,
                    RDBExternalChannelConnection,
                    RDBExternalChannelResource,
                )
                .join(
                    RDBAgentSession,
                    RDBAgentSession.id == RDBExternalChannelBinding.agent_session_id,
                )
                .join(
                    RDBAgent,
                    RDBAgent.id == RDBAgentSession.agent_id,
                )
                .join(
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelAgentRoute.id
                    == RDBExternalChannelBinding.route_id,
                )
                .join(
                    RDBExternalChannelResource,
                    RDBExternalChannelResource.id
                    == RDBExternalChannelBinding.resource_id,
                )
                .join(
                    RDBExternalChannelConnection,
                    RDBExternalChannelConnection.id
                    == RDBExternalChannelAgentRoute.connection_id,
                )
                .where(
                    RDBExternalChannelBinding.id == binding_id,
                    RDBExternalChannelBinding.agent_session_id == session_id,
                    RDBExternalChannelBinding.disconnected_at.is_(None),
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgentSession.agent_id == agent_id,
                    RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                    RDBExternalChannelAgentRoute.agent_id == agent_id,
                    RDBExternalChannelResource.status
                    == ExternalChannelResourceStatus.ACTIVE,
                    RDBExternalChannelResource.connection_id
                    == RDBExternalChannelConnection.id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        binding, connection, resource = row
        return ExternalChannelFileAccessTarget(
            binding_id=binding.id,
            connection_id=connection.id,
            resource_id=resource.id,
            provider=connection.provider,
            encrypted_credentials=connection.encrypted_credentials,
            provider_tenant_id=connection.provider_tenant_id,
            capabilities=connection.capabilities,
            resource_labels=resource.labels,
        )

    async def list_active_work(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        agent_id: str,
    ) -> list[ChannelWorkSnapshot]:
        """List active binding work in stable binding order."""
        rows = (
            await session.execute(
                sa.select(
                    RDBExternalChannelBinding,
                    RDBExternalChannelResource,
                    RDBExternalChannelConnection,
                )
                .join(
                    RDBAgentSession,
                    RDBAgentSession.id == RDBExternalChannelBinding.agent_session_id,
                )
                .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
                .join(
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelAgentRoute.id
                    == RDBExternalChannelBinding.route_id,
                )
                .join(
                    RDBExternalChannelResource,
                    RDBExternalChannelResource.id
                    == RDBExternalChannelBinding.resource_id,
                )
                .join(
                    RDBExternalChannelConnection,
                    RDBExternalChannelConnection.id
                    == RDBExternalChannelAgentRoute.connection_id,
                )
                .where(
                    RDBExternalChannelBinding.agent_session_id == session_id,
                    RDBExternalChannelBinding.disconnected_at.is_(None),
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgentSession.agent_id == agent_id,
                    RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                    RDBExternalChannelAgentRoute.agent_id == agent_id,
                )
                .order_by(RDBExternalChannelBinding.id)
            )
        ).all()
        work_by_binding = await self.work_state_store.list_for_session(
            session,
            agent_id=agent_id,
            session_id=session_id,
        )
        return [
            ChannelWorkSnapshot(
                binding_id=binding.id,
                provider=connection.provider,
                resource_label=_resource_label(resource.labels, binding.id),
                title=work.title,
                tasks=list(work.tasks),
            )
            for binding, resource, connection in rows
            if (
                (work := work_by_binding.get(binding.id)) is not None
                and work.status is ExternalChannelWorkStatus.ACTIVE
            )
        ]

    async def commit_direct_action(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        agent_id: str,
        run_id: str | None,
        client_tool_call_id: str,
        binding_id: str,
        mode: ExternalChannelActionMode,
        message: str | None,
        title: str | None,
        tasks: Sequence[ChannelWorkTask] | None,
        files: Sequence[ExternalChannelOutboundFileManifest],
        now: datetime.datetime,
    ) -> ChannelActionTransition:
        """Commit canonical Work and return process-local provider effects."""
        del run_id
        requested_tasks = list(tasks) if tasks is not None else None
        if mode is ExternalChannelActionMode.FINISH and message is None:
            raise ValueError("Finish requires a final External Channel reply.")
        if mode is ExternalChannelActionMode.IGNORE and (
            message is not None
            or title is not None
            or requested_tasks is not None
            or bool(files)
        ):
            raise ValueError(
                "Ignore does not accept a message, title, task update, or files."
            )
        if files and message is None:
            raise ValueError("Channel file publication requires a message.")

        session_row = await session.scalar(
            sa.select(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.agent_id == agent_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .with_for_update()
        )
        if session_row is None:
            raise ValueError("AgentSession is not active.")
        agent = await session.scalar(
            sa.select(RDBAgent).where(
                RDBAgent.id == agent_id,
                RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            )
        )
        if agent is None:
            raise ValueError("Agent is not active.")
        binding = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .where(
                RDBExternalChannelBinding.id == binding_id,
                RDBExternalChannelBinding.agent_session_id == session_id,
                RDBExternalChannelBinding.disconnected_at.is_(None),
            )
            .with_for_update()
        )
        if binding is None:
            raise ValueError("External Channel binding is not active.")
        route = await session.scalar(
            sa.select(RDBExternalChannelAgentRoute).where(
                RDBExternalChannelAgentRoute.id == binding.route_id,
                RDBExternalChannelAgentRoute.agent_id == agent_id,
            )
        )
        if route is None:
            raise ValueError("External Channel route is not active.")
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection).where(
                RDBExternalChannelConnection.id == route.connection_id,
            )
        )
        if connection is None:
            raise ValueError("External Channel connection is unavailable.")
        _validate_message_length(connection.provider, message)
        resource = await session.scalar(
            sa.select(RDBExternalChannelResource).where(
                RDBExternalChannelResource.id == binding.resource_id,
                RDBExternalChannelResource.connection_id == connection.id,
                RDBExternalChannelResource.status
                == ExternalChannelResourceStatus.ACTIVE,
            )
        )
        if resource is None:
            raise ValueError("External Channel resource is unavailable.")
        workspace = await session.get(RDBWorkspace, agent.workspace_id)

        def default_work() -> ChannelWorkState:
            if mode is ExternalChannelActionMode.IGNORE:
                raise ValueError("Ignore requires active Channel Work.")
            return ChannelWorkState(
                binding_id=binding.id,
                work_cycle_id=uuid7().hex,
                status=ExternalChannelWorkStatus.ACTIVE,
                title=None,
                tasks=[],
                state_revision=1,
                desired_progress_revision=0,
                desired_progress=None,
                finished_at=None,
                projection_parts=[],
            )

        def transition(
            current: ChannelWorkState,
        ) -> ChannelWorkStateMutation[ChannelActionTransition]:
            if mode is ExternalChannelActionMode.IGNORE:
                if current.status is not ExternalChannelWorkStatus.ACTIVE:
                    raise ValueError("Ignore requires active Channel Work.")
                work = current.model_copy(deep=True)
                work.status = ExternalChannelWorkStatus.FINISHED
                work.state_revision += 1
                work.finished_at = now
                work.desired_progress_revision += 1
                work.desired_progress = None
                return ChannelWorkStateMutation(
                    state=work,
                    result=ChannelActionTransition(
                        binding_id=binding.id,
                        work_id=work.work_cycle_id,
                        work_status=work.status,
                        state_revision=work.state_revision,
                        effects=(),
                    ),
                )
            work = (
                default_work()
                if current.status is ExternalChannelWorkStatus.FINISHED
                else current.model_copy(deep=True)
            )
            effects: list[ChannelActionEffectPlan] = []

            def append_effect(
                operation: ExternalChannelDeliveryOperation,
                payload: dict[str, object],
                *,
                part: int,
                expected_desired_progress_revision: int | None,
            ) -> None:
                target = ProviderTarget(
                    operation=operation,
                    binding_id=binding.id,
                    resource_id=resource.id,
                    connection_id=connection.id,
                    provider=connection.provider,
                    app_mode=connection.app_mode,
                    encrypted_credentials=connection.encrypted_credentials,
                    provider_tenant_id=connection.provider_tenant_id,
                    capabilities=connection.capabilities,
                    workspace_handle=None if workspace is None else workspace.handle,
                    agent_id=agent.id,
                    agent_session_id=session_id,
                    agent_name=agent.name,
                    agent_avatar=agent.avatar,
                    request_payload=payload,
                )
                effects.append(
                    ChannelActionEffectPlan(
                        provider=ProviderEffectPlan(
                            target=target,
                            operation_key=ProviderOperationKey.from_seed(
                                f"{client_tool_call_id}:{len(effects)}:"
                                f"{operation.value}:{part}"
                            ),
                        ),
                        part=part,
                        work_cycle_id=work.work_cycle_id,
                        expected_desired_progress_revision=(
                            expected_desired_progress_revision
                        ),
                    )
                )

            if message is not None:
                for part, payload in enumerate(
                    _reply_parts(
                        provider=connection.provider,
                        labels=resource.labels,
                        text=message,
                        files=files,
                    )
                ):
                    append_effect(
                        ExternalChannelDeliveryOperation.REPLY,
                        payload,
                        part=part,
                        expected_desired_progress_revision=None,
                    )

            projection_parts = {
                part.part_ordinal: part for part in work.projection_parts
            }
            if mode is ExternalChannelActionMode.CONTINUE:
                progress_changed = title is not None or requested_tasks is not None
                if requested_tasks is not None and title is None:
                    raise ValueError(
                        "A Channel Work task update requires a work title."
                    )
                if title is not None and not title.endswith(("…", "...")):
                    raise ValueError("Channel Work titles must end with an ellipsis.")
                if title is not None and requested_tasks is None and not work.tasks:
                    raise ValueError(
                        "A title-only update requires existing Channel Work."
                    )
                if progress_changed:
                    next_tasks = (
                        requested_tasks
                        if requested_tasks is not None
                        else list(work.tasks)
                    )
                    if not next_tasks:
                        raise ValueError(
                            "Working Channel Work requires at least one task."
                        )
                    if not any(
                        task.status
                        not in {
                            ExternalChannelWorkTaskStatus.COMPLETED,
                            ExternalChannelWorkTaskStatus.FAILED,
                        }
                        for task in next_tasks
                    ):
                        raise ValueError(
                            "Continue must leave at least one unfinished "
                            "Channel Work task."
                        )
                    next_title = title if title is not None else work.title
                    if next_title is None:
                        raise ValueError("Working Channel Work requires a title.")
                    progress = ExternalChannelDesiredProgress(
                        schema_version=2,
                        state="working",
                        title=next_title,
                        tasks=next_tasks,
                    )
                    work.title = next_title
                    work.tasks = next_tasks
                    work.state_revision += 1
                    work.desired_progress_revision += 1
                    work.desired_progress = progress
                    if connection.provider is ExternalChannelProvider.SLACK:
                        rendered = render_slack_progress(
                            progress,
                            work_id=work.work_cycle_id,
                            desired_progress_revision=(work.desired_progress_revision),
                        )
                        desired_pages = ((rendered.text, rendered.blocks),)
                    else:
                        rendered_discord = render_discord_persisted_progress(
                            progress,
                            work_id=work.work_cycle_id,
                            desired_progress_revision=(work.desired_progress_revision),
                        )
                        desired_pages = tuple(
                            (page.text, page.embeds) for page in rendered_discord.pages
                        )
                    for part_ordinal, (text, presentation) in enumerate(desired_pages):
                        part = projection_parts.pop(part_ordinal, None)
                        operation: ExternalChannelDeliveryOperation | None = None
                        if (
                            part is None
                            or part.status
                            is ExternalChannelWorkProjectionStatus.DELETED
                        ):
                            operation = ExternalChannelDeliveryOperation.PROGRESS_CREATE
                        elif part.status is ExternalChannelWorkProjectionStatus.FAILED:
                            operation = (
                                ExternalChannelDeliveryOperation.PROGRESS_UPDATE
                                if part.provider_message_key is not None
                                else ExternalChannelDeliveryOperation.PROGRESS_CREATE
                            )
                        elif (
                            part.status is ExternalChannelWorkProjectionStatus.PRESENT
                            and part.provider_message_key is not None
                            and part.desired_progress_revision
                            < work.desired_progress_revision
                        ):
                            operation = ExternalChannelDeliveryOperation.PROGRESS_UPDATE
                        elif (
                            part.status is ExternalChannelWorkProjectionStatus.UNKNOWN
                            and part.desired_progress_revision
                            < work.desired_progress_revision
                        ):
                            operation = (
                                ExternalChannelDeliveryOperation.PROGRESS_UPDATE
                                if part.provider_message_key is not None
                                else ExternalChannelDeliveryOperation.PROGRESS_CREATE
                            )
                        if operation is None:
                            continue
                        payload = _provider_payload(
                            connection.provider,
                            resource.labels,
                            text=text,
                            blocks=(
                                presentation
                                if connection.provider is ExternalChannelProvider.SLACK
                                else None
                            ),
                            provider_message_key=(
                                None if part is None else part.provider_message_key
                            ),
                            desired_progress_revision=(work.desired_progress_revision),
                        )
                        if connection.provider is ExternalChannelProvider.DISCORD:
                            payload["embeds"] = presentation
                        append_effect(
                            operation,
                            payload,
                            part=part_ordinal,
                            expected_desired_progress_revision=(
                                work.desired_progress_revision
                            ),
                        )
                    for part_ordinal, part in sorted(projection_parts.items()):
                        if (
                            part.status is ExternalChannelWorkProjectionStatus.PRESENT
                            and part.provider_message_key is not None
                        ):
                            append_effect(
                                ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                                _provider_payload(
                                    connection.provider,
                                    resource.labels,
                                    provider_message_key=(part.provider_message_key),
                                    desired_progress_revision=(
                                        work.desired_progress_revision
                                    ),
                                ),
                                part=part_ordinal,
                                expected_desired_progress_revision=(
                                    work.desired_progress_revision
                                ),
                            )
            else:
                work.status = ExternalChannelWorkStatus.FINISHED
                work.state_revision += 1
                work.finished_at = now
                work.desired_progress_revision += 1
                work.desired_progress = None
                for part_ordinal, part in sorted(projection_parts.items()):
                    if (
                        part.status is ExternalChannelWorkProjectionStatus.PRESENT
                        and part.provider_message_key is not None
                    ):
                        append_effect(
                            ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                            _provider_payload(
                                connection.provider,
                                resource.labels,
                                provider_message_key=part.provider_message_key,
                                desired_progress_revision=(
                                    work.desired_progress_revision
                                ),
                            ),
                            part=part_ordinal,
                            expected_desired_progress_revision=(
                                work.desired_progress_revision
                            ),
                        )
            result = ChannelActionTransition(
                binding_id=binding.id,
                work_id=work.work_cycle_id,
                work_status=work.status,
                state_revision=work.state_revision,
                effects=tuple(effects),
            )
            return ChannelWorkStateMutation(state=work, result=result)

        mutation = await self.work_state_store.update(
            session,
            agent_id=agent_id,
            session_id=session_id,
            binding_id=binding.id,
            default_factory=default_work,
            mutator=transition,
        )
        return mutation.result

    async def revalidate_direct_effect(
        self,
        session: AsyncSession,
        *,
        effect: ChannelActionEffectPlan,
    ) -> ProviderEffectPlan | None:
        """Resolve current provider authority for one process-local effect."""
        target = effect.provider.target
        if target.binding_id is None or target.resource_id is None:
            return None
        row = (
            await session.execute(
                sa.select(
                    RDBExternalChannelBinding,
                    RDBExternalChannelResource,
                    RDBExternalChannelAgentRoute,
                    RDBExternalChannelConnection,
                    RDBAgentSession,
                    RDBAgent,
                    RDBWorkspace,
                )
                .join(
                    RDBExternalChannelResource,
                    RDBExternalChannelResource.id
                    == RDBExternalChannelBinding.resource_id,
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
                    RDBAgentSession,
                    RDBAgentSession.id == RDBExternalChannelBinding.agent_session_id,
                )
                .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
                .join(RDBWorkspace, RDBWorkspace.id == RDBAgent.workspace_id)
                .where(
                    RDBExternalChannelBinding.id == target.binding_id,
                    RDBExternalChannelBinding.resource_id == target.resource_id,
                    RDBExternalChannelBinding.disconnected_at.is_(None),
                    RDBExternalChannelResource.status
                    == ExternalChannelResourceStatus.ACTIVE,
                    RDBExternalChannelResource.connection_id
                    == RDBExternalChannelConnection.id,
                    RDBExternalChannelConnection.id == target.connection_id,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        binding, resource, _route, connection, agent_session, agent, workspace = row
        work = await self.work_state_store.load(
            session,
            agent_id=agent.id,
            session_id=agent_session.id,
            binding_id=binding.id,
        )
        if work is None or work.work_cycle_id != effect.work_cycle_id:
            return None
        return ProviderEffectPlan(
            target=ProviderTarget(
                operation=target.operation,
                binding_id=binding.id,
                resource_id=resource.id,
                connection_id=connection.id,
                provider=connection.provider,
                app_mode=connection.app_mode,
                encrypted_credentials=connection.encrypted_credentials,
                provider_tenant_id=connection.provider_tenant_id,
                capabilities=connection.capabilities,
                workspace_handle=workspace.handle,
                agent_id=agent.id,
                agent_session_id=agent_session.id,
                agent_name=agent.name,
                agent_avatar=agent.avatar,
                request_payload=target.request_payload,
            ),
            operation_key=effect.provider.operation_key,
        )

    async def apply_direct_effect_outcome(
        self,
        session: AsyncSession,
        *,
        effect: ChannelActionEffectPlan,
        outcome: ProviderMutationOutcome,
    ) -> bool:
        """Compare-and-set one current Work projection outcome."""
        expected_revision = effect.expected_desired_progress_revision
        if expected_revision is None:
            return True
        target = effect.provider.target
        if (
            target.agent_id is None
            or target.agent_session_id is None
            or target.binding_id is None
        ):
            return False

        def settle(
            current: ChannelWorkState,
        ) -> ChannelWorkStateMutation[bool]:
            if (
                current.work_cycle_id != effect.work_cycle_id
                or current.desired_progress_revision != expected_revision
            ):
                return ChannelWorkStateMutation(
                    state=current,
                    result=False,
                    changed=False,
                )
            updated = current.model_copy(deep=True)
            part = next(
                (
                    item
                    for item in updated.projection_parts
                    if item.part_ordinal == effect.part
                ),
                None,
            )
            if part is None:
                part = ChannelWorkProjectionPartState(
                    part_ordinal=effect.part,
                    desired_progress_revision=expected_revision,
                    status=ExternalChannelWorkProjectionStatus.UNKNOWN,
                    provider_message_key=None,
                )
                updated.projection_parts.append(part)
                updated.projection_parts.sort(key=lambda item: item.part_ordinal)
            elif part.desired_progress_revision > expected_revision:
                return ChannelWorkStateMutation(
                    state=current,
                    result=False,
                    changed=False,
                )
            part.desired_progress_revision = expected_revision
            match outcome.status:
                case "delivered":
                    if (
                        effect.provider.target.operation
                        is ExternalChannelDeliveryOperation.PROGRESS_DELETE
                    ):
                        part.status = ExternalChannelWorkProjectionStatus.DELETED
                        part.provider_message_key = None
                    elif outcome.provider_message_key is None:
                        part.status = ExternalChannelWorkProjectionStatus.UNKNOWN
                    else:
                        part.status = ExternalChannelWorkProjectionStatus.PRESENT
                        part.provider_message_key = outcome.provider_message_key
                case "failed":
                    part.status = ExternalChannelWorkProjectionStatus.FAILED
                case "unknown":
                    part.status = ExternalChannelWorkProjectionStatus.UNKNOWN
                case _ as unreachable:
                    assert_never(unreachable)
            return ChannelWorkStateMutation(state=updated, result=True)

        mutation = await self.work_state_store.update_existing(
            session,
            agent_id=target.agent_id,
            session_id=target.agent_session_id,
            binding_id=target.binding_id,
            mutator=settle,
        )
        return mutation is not None and mutation.result

    async def record_discord_delivery_channel(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
        delivery_channel_id: str,
        initial_thread_title: str | None,
    ) -> str | None:
        """Retain one provisioned Discord thread for all later provider effects."""
        resource = await session.get(
            RDBExternalChannelResource,
            resource_id,
            with_for_update=True,
        )
        if resource is None:
            return None
        labels = dict(resource.labels or {})
        if labels.get("provider") != ExternalChannelProvider.DISCORD.value:
            return None
        existing = labels.get("delivery_channel_id")
        if isinstance(existing, str) and existing:
            return existing
        labels["thread_channel_id"] = delivery_channel_id
        labels["delivery_channel_id"] = delivery_channel_id
        labels["thread_id"] = delivery_channel_id
        if initial_thread_title is not None:
            labels[DISCORD_INITIAL_THREAD_TITLE_LABEL] = initial_thread_title
        resource.labels = labels
        await session.flush()
        return delivery_channel_id


def _provider_payload(
    provider: ExternalChannelProvider,
    labels: dict[str, object] | None,
    *,
    text: str | None = None,
    blocks: list[dict[str, object]] | None = None,
    provider_message_key: str | None = None,
    desired_progress_revision: int | None = None,
    files: Sequence[ExternalChannelOutboundFileManifest] = (),
) -> dict[str, object]:
    """Build one persisted provider request intent without credentials."""
    labels = labels or {}
    payload: dict[str, object]
    match provider:
        case ExternalChannelProvider.SLACK:
            channel_id = labels.get("channel_id")
            thread_ts = labels.get("thread_ts")
            conversation_scope = labels.get("conversation_scope")
            if not isinstance(channel_id, str) or not channel_id:
                raise ValueError("External Channel resource has no provider channel.")
            if conversation_scope == "parent_channel":
                payload = {
                    "channel_id": channel_id,
                    "conversation_scope": "parent_channel",
                }
            elif not isinstance(thread_ts, str) or not thread_ts:
                raise ValueError("External Channel resource has no provider thread.")
            else:
                payload = {
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "conversation_scope": "thread",
                }
        case ExternalChannelProvider.DISCORD:
            guild_id = labels.get("guild_id")
            conversation_scope = labels.get("conversation_scope")
            parent_channel_id = labels.get("parent_channel_id")
            if not isinstance(guild_id, str) or not guild_id:
                raise ValueError("Discord resource has no provider Guild.")
            if conversation_scope == "parent_channel":
                if not isinstance(parent_channel_id, str) or not parent_channel_id:
                    raise ValueError("Discord parent Resource has no provider channel.")
                payload = {
                    "guild_id": guild_id,
                    "channel_id": parent_channel_id,
                    "conversation_scope": "parent_channel",
                }
            else:
                delivery_channel_id = labels.get("delivery_channel_id")
                thread_id = (
                    delivery_channel_id
                    if isinstance(delivery_channel_id, str) and delivery_channel_id
                    else labels.get("thread_id")
                )
                if not isinstance(thread_id, str) or not thread_id:
                    raise ValueError("Discord resource has no provider thread.")
                payload = {
                    "guild_id": guild_id,
                    "channel_id": thread_id,
                    "conversation_scope": "thread",
                }
                root_message_id = labels.get("root_message_id")
                if delivery_channel_id is None and (
                    isinstance(parent_channel_id, str)
                    and parent_channel_id
                    and isinstance(root_message_id, str)
                    and root_message_id == thread_id
                ):
                    payload["thread_parent_channel_id"] = parent_channel_id
                    payload["thread_root_message_id"] = root_message_id
        case _ as unreachable:
            assert_never(unreachable)
    if text is not None:
        payload["text"] = text
    if files:
        payload["files"] = [item.model_dump(mode="json") for item in files]
    if blocks is not None:
        payload["blocks"] = blocks
    if provider_message_key is not None:
        payload["provider_message_key"] = provider_message_key
    if desired_progress_revision is not None:
        payload["desired_progress_revision"] = desired_progress_revision
    return payload


def _reply_parts(
    *,
    provider: ExternalChannelProvider,
    labels: dict[str, object] | None,
    text: str,
    files: Sequence[ExternalChannelOutboundFileManifest],
) -> tuple[dict[str, object], ...]:
    """Lower one canonical reply into ordered provider-bound message parts."""
    match provider:
        case ExternalChannelProvider.SLACK:
            return (
                _provider_payload(
                    provider,
                    labels,
                    text=text,
                    files=files,
                ),
            )
        case ExternalChannelProvider.DISCORD:
            parts = split_discord_markdown(text)
            text_parts = tuple(
                _provider_payload(
                    provider,
                    labels,
                    text=part,
                )
                for part in parts
            )
            if not files:
                return text_parts
            batches = _discord_file_batches(files)
            if len(text_parts) == 1:
                return tuple(
                    _provider_payload(
                        provider,
                        labels,
                        text=text if ordinal == 0 else "Attachments (continued)",
                        files=batch,
                    )
                    for ordinal, batch in enumerate(batches)
                )
            return (
                *text_parts,
                *(
                    _provider_payload(
                        provider,
                        labels,
                        text=(
                            "Attachments" if ordinal == 0 else "Attachments (continued)"
                        ),
                        files=batch,
                    )
                    for ordinal, batch in enumerate(batches)
                ),
            )
        case _ as unreachable:
            assert_never(unreachable)


def _discord_file_batches(
    files: Sequence[ExternalChannelOutboundFileManifest],
) -> tuple[tuple[ExternalChannelOutboundFileManifest, ...], ...]:
    """Plan bounded ordered multipart batches before any provider call."""
    payload_budget = DISCORD_CREATE_MESSAGE_MAX_REQUEST_BYTES - (64 * 1024)
    batches: list[tuple[ExternalChannelOutboundFileManifest, ...]] = []
    current: list[ExternalChannelOutboundFileManifest] = []
    current_bytes = 0
    for file in files:
        if file.expected_size > DISCORD_DEFAULT_MAX_FILE_BYTES:
            raise ValueError(
                "Discord outbound file exceeds the current provider file limit."
            )
        if current and current_bytes + file.expected_size > payload_budget:
            batches.append(tuple(current))
            current = []
            current_bytes = 0
        if file.expected_size > payload_budget:
            raise ValueError("Discord outbound file exceeds the request limit.")
        current.append(file)
        current_bytes += file.expected_size
    if current:
        batches.append(tuple(current))
    return tuple(batches)


def _validate_message_length(
    provider: ExternalChannelProvider,
    message: str | None,
) -> None:
    """Validate one provider-bound conversational message before commit."""
    if message is None:
        return
    match provider:
        case ExternalChannelProvider.SLACK:
            maximum = SLACK_MARKDOWN_TEXT_MAX_LENGTH
        case ExternalChannelProvider.DISCORD:
            maximum = 64 * 1024
        case _ as unreachable:
            assert_never(unreachable)
    if len(message) > maximum:
        raise ValueError(
            f"External Channel message exceeds the {maximum}-character provider limit."
        )


def _resource_label(labels: dict[str, object] | None, fallback: str) -> str:
    """Return a safe resource label for model context."""
    labels = labels or {}
    for key in ("display_name", "channel_name", "label", "channel_id"):
        value = labels.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def projection_state(
    work: ChannelWorkState,
) -> Literal[
    "synchronized",
    "missing",
    "stale",
    "delete_failed",
    "unknown",
    "none",
]:
    """Derive current Work projection state only from owner-local parts."""
    projection_parts = work.projection_parts
    if any(
        part.status is ExternalChannelWorkProjectionStatus.UNKNOWN
        for part in projection_parts
    ):
        return "unknown"
    if work.desired_progress is None:
        if any(
            part.status is ExternalChannelWorkProjectionStatus.FAILED
            and part.provider_message_key is not None
            for part in projection_parts
        ):
            return "delete_failed"
        if any(
            part.status is ExternalChannelWorkProjectionStatus.PRESENT
            and part.provider_message_key is not None
            for part in projection_parts
        ):
            return "stale"
        return "none"
    if not projection_parts:
        return "missing"
    if any(
        part.status is not ExternalChannelWorkProjectionStatus.PRESENT
        or part.provider_message_key is None
        or part.desired_progress_revision != work.desired_progress_revision
        for part in projection_parts
    ):
        return "stale"
    return "synchronized"


async def terminate_binding_with_plans(
    session: AsyncSession,
    *,
    binding: RDBExternalChannelBinding,
    resource: RDBExternalChannelResource,
    work_state_store: ExternalChannelWorkStateStore,
    now: datetime.datetime,
    reason: str,
    emit_leave_presence: bool,
) -> tuple[ProviderEffectPlan, ...]:
    """Commit one binding termination and capture bounded cleanup plans."""
    if binding.disconnected_at is not None:
        return ()
    route = await session.get(RDBExternalChannelAgentRoute, binding.route_id)
    if route is None:
        raise RuntimeError("External Channel binding route disappeared.")
    connection = await session.get(RDBExternalChannelConnection, route.connection_id)
    agent_session = await session.get(RDBAgentSession, binding.agent_session_id)
    agent = (
        None
        if agent_session is None
        else await session.get(RDBAgent, agent_session.agent_id)
    )
    workspace = (
        None if agent is None else await session.get(RDBWorkspace, agent.workspace_id)
    )
    if connection is None or agent_session is None or agent is None:
        raise RuntimeError("External Channel binding authority disappeared.")

    plans: list[ProviderEffectPlan] = []

    def append_plan(
        operation: ExternalChannelDeliveryOperation,
        payload: dict[str, object],
    ) -> None:
        plans.append(
            ProviderEffectPlan(
                target=ProviderTarget(
                    operation=operation,
                    binding_id=binding.id,
                    resource_id=resource.id,
                    connection_id=connection.id,
                    provider=connection.provider,
                    app_mode=connection.app_mode,
                    encrypted_credentials=connection.encrypted_credentials,
                    provider_tenant_id=connection.provider_tenant_id,
                    capabilities=connection.capabilities,
                    workspace_handle=None if workspace is None else workspace.handle,
                    agent_id=agent.id,
                    agent_session_id=agent_session.id,
                    agent_name=agent.name,
                    agent_avatar=agent.avatar,
                    request_payload=payload,
                ),
                operation_key=ProviderOperationKey.from_seed(
                    f"binding-terminal:{binding.id}:{len(plans)}:{operation.value}"
                ),
            )
        )

    if emit_leave_presence:
        append_plan(
            ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            session_presence_payload(resource.labels, state="left"),
        )

    def finish(
        current: ChannelWorkState,
    ) -> ChannelWorkStateMutation[tuple[ProviderEffectPlan, ...]]:
        if current.status is not ExternalChannelWorkStatus.ACTIVE:
            return ChannelWorkStateMutation(
                state=current,
                result=(),
                changed=False,
            )
        work = current.model_copy(deep=True)
        work.status = ExternalChannelWorkStatus.FINISHED
        work.finished_at = now
        work.state_revision += 1
        work.desired_progress_revision += 1
        work.desired_progress = None
        progress_plans: list[ProviderEffectPlan] = []
        for part in work.projection_parts:
            if (
                part.status is not ExternalChannelWorkProjectionStatus.PRESENT
                or part.provider_message_key is None
            ):
                continue
            payload = _provider_payload(
                connection.provider,
                resource.labels,
                provider_message_key=part.provider_message_key,
                desired_progress_revision=work.desired_progress_revision,
            )
            payload["work_id"] = work.work_cycle_id
            payload["part_ordinal"] = part.part_ordinal
            operation = ExternalChannelDeliveryOperation.PROGRESS_DELETE
            progress_plans.append(
                ProviderEffectPlan(
                    target=ProviderTarget(
                        operation=operation,
                        binding_id=binding.id,
                        resource_id=resource.id,
                        connection_id=connection.id,
                        provider=connection.provider,
                        app_mode=connection.app_mode,
                        encrypted_credentials=connection.encrypted_credentials,
                        provider_tenant_id=connection.provider_tenant_id,
                        capabilities=connection.capabilities,
                        workspace_handle=(
                            None if workspace is None else workspace.handle
                        ),
                        agent_id=agent.id,
                        agent_session_id=agent_session.id,
                        agent_name=agent.name,
                        agent_avatar=agent.avatar,
                        request_payload=payload,
                    ),
                    operation_key=ProviderOperationKey.from_seed(
                        f"binding-terminal:{binding.id}:"
                        f"{len(plans) + len(progress_plans)}:{operation.value}"
                    ),
                )
            )
        return ChannelWorkStateMutation(
            state=work,
            result=tuple(progress_plans),
        )

    mutation = await work_state_store.update_existing(
        session,
        agent_id=agent.id,
        session_id=agent_session.id,
        binding_id=binding.id,
        mutator=finish,
    )
    if mutation is not None:
        plans.extend(mutation.result)
    binding.disconnected_at = now
    binding.disconnect_reason = reason
    await session.flush()
    return tuple(plans)
