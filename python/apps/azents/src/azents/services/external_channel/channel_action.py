"""Atomic Channel Action orchestration and one-attempt provider delivery."""

import asyncio
import datetime
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from dataclasses import replace as dataclass_replace
from pathlib import PurePosixPath
from typing import Annotated, NotRequired, TypedDict, assert_never
from urllib.parse import urlparse

import httpx
from fastapi import Depends
from pydantic import ValidationError

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.discord_external_channel_presentation import (
    render_discord_session_navigation_components,
    render_discord_session_presence,
    render_discord_setup_required,
)
from azents.core.enums import (
    ExternalChannelActionMode,
    ExternalChannelAppMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelProvider,
    ExternalChannelWorkStatus,
)
from azents.core.external_channel_effect_intent import ProviderEffectIntent
from azents.core.external_channel_file import (
    MAX_EXTERNAL_CHANNEL_FILES,
    ExternalChannelOutboundFileManifest,
    ExternalChannelOutboundFileSource,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelSetupPreparationBoundary,
)
from azents.core.external_channel_navigation import (
    ChannelNavigationAction,
    ChannelNavigationLink,
)
from azents.core.external_channel_progress import (
    ExternalChannelWorkTask as ChannelWorkTask,
)
from azents.core.external_channel_projection import is_external_channel_projection
from azents.core.external_channel_provider_effect import (
    ProviderEffectOutcome,
    ProviderEffectPlan,
    ProviderMutationOutcome,
    ProviderOperationKey,
    ProviderTarget,
)
from azents.core.external_channel_session_presence import (
    ExternalChannelSessionPresenceState,
    build_external_channel_scheduled_task_url,
    build_external_channel_session_url,
)
from azents.core.session_resource_authority import (
    SessionExecutionOwner,
    SessionResourceAuthority,
)
from azents.core.slack_external_channel_progress import (
    render_slack_session_actions,
    render_slack_session_presence,
    render_slack_setup_required,
)
from azents.repos.external_channel.action_operations import (
    ExternalChannelActionOperations,
)
from azents.repos.external_channel.work_data import (
    ChannelActionEffectPlan,
    ChannelActionResult,
    ChannelWorkSnapshot,
)
from azents.runtime.transfer.runtime_to_provider import (
    RuntimeToProviderBatch,
    RuntimeToProviderCleanupError,
    RuntimeToProviderDeliveryExecutor,
    RuntimeToProviderSource,
    RuntimeToProviderTransferError,
)
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.services.exchange_file import ExchangeFileService
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.discord_delivery import (
    DiscordDeliveryClient,
    DiscordDeliveryResult,
    DiscordFileMessageTransport,
    DiscordOutboundFile,
    DiscordOutboundFileContentError,
    _sdk_delivery_failure,
    _sdk_timeout_result,
)
from azents.services.external_channel.discord_sdk import (
    DiscordSDKClientFactory,
    DiscordSDKError,
    get_discord_sdk_client_factory,
)
from azents.services.external_channel.discord_settings_scope import (
    build_discord_binding_settings_open_custom_id,
    build_discord_settings_custom_id,
)
from azents.services.external_channel.file_transfer import (
    ExternalChannelFileTransferError,
    iter_external_channel_exchange_file_chunks,
    iter_external_channel_outbound_file_chunks,
)
from azents.services.external_channel.presentation import (
    SlackAgentPresentation,
    normalize_slack_agent_name,
    prepend_agent_blocks,
    prepend_agent_fallback,
    prepend_agent_markdown,
    resolve_slack_agent_name_presentation,
    resolve_slack_agent_presentation,
)
from azents.services.external_channel.slack_events import (
    SlackControlMessageResult,
    SlackConversationClient,
    SlackExternalUploadTransport,
    SlackOutboundFile,
    SlackOutboundFileContentError,
    SlackPrivateFileTransport,
)
from azents.services.external_channel.slack_http import SLACK_SETTINGS_OPEN_ACTION_ID
from azents.services.external_channel.slack_sdk_client import create_slack_web_client
from azents.services.external_channel.slack_settings import (
    build_slack_parent_settings_locator,
    build_slack_settings_locator,
)
from azents.services.file_storage import FileStorage, RangedFileStorage
from azents.services.runtime_storage_error import RuntimeStorageError
from azents.services.runtime_web.service_url import (
    RuntimeWebServiceUrlResolver,
    get_runtime_web_service_url_resolver,
)
from azents.services.scheduled_task.control import (
    render_scheduled_task_discord_controls,
)

logger = logging.getLogger(__name__)
RuntimeTargetResolver = Callable[[], Awaitable[ServerToRuntimeTarget]]


def _validate_provider_authority(
    target: ProviderTarget,
    *,
    authority: SessionResourceAuthority | None,
    agent_id: str | None,
    session_id: str | None,
) -> None:
    """Reject a provider effect whose execution identity changed."""
    if authority is None:
        return
    if (
        agent_id is not None
        and agent_id != authority.agent_id
        or session_id is not None
        and session_id != authority.session_id
        or target.agent_id is not None
        and target.agent_id != authority.agent_id
        or target.agent_session_id is not None
        and target.agent_session_id != authority.session_id
    ):
        raise ValueError(
            "External Channel execution authority does not match provider effect"
        )


async def get_slack_delivery_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide the bounded outbound Slack mutation transport."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


@dataclass(frozen=True)
class _SessionPresenceContext:
    """Validated Session presence navigation and copy identity."""

    agent_name: str
    session_url: str
    state: ExternalChannelSessionPresenceState


@dataclass(frozen=True)
class _SessionNavigationContext:
    """Validated Session navigation and current Agent identity."""

    agent_name: str
    session_url: str


def get_slack_delivery_client(
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_slack_delivery_http_client),
    ],
) -> SlackConversationClient:
    """Provide the Slack Channel Action adapter."""
    return SlackConversationClient(
        web_client=create_slack_web_client(),
        private_file_transport=SlackPrivateFileTransport(http_client),
        external_upload_transport=SlackExternalUploadTransport(http_client),
    )


async def get_discord_delivery_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide a bounded HTTP client for Discord message delivery."""
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
        yield client


def get_discord_file_message_transport(
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_discord_delivery_http_client),
    ],
) -> DiscordFileMessageTransport:
    """Provide approved G2 Discord multipart file-message transport."""
    return DiscordFileMessageTransport(http_client)


def get_discord_delivery_client(
    sdk_factory: Annotated[
        DiscordSDKClientFactory,
        Depends(get_discord_sdk_client_factory),
    ],
    file_transport: Annotated[
        DiscordFileMessageTransport,
        Depends(get_discord_file_message_transport),
    ],
) -> DiscordDeliveryClient:
    """Provide the public SDK Discord Channel Action adapter."""
    return DiscordDeliveryClient(sdk_factory, file_transport)


@dataclass(frozen=True)
class _SlackSelectorControlPresentation:
    """One bounded Slack selector control projection."""

    text: str
    blocks: list[dict[str, object]]


@dataclass
class ExternalChannelActionService:
    """Commit Channel Work before attempting provider operations once."""

    operations: Annotated[
        ExternalChannelActionOperations,
        Depends(ExternalChannelActionOperations.create),
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    slack_client: Annotated[
        SlackConversationClient,
        Depends(get_slack_delivery_client),
    ]
    discord_client: Annotated[
        DiscordDeliveryClient,
        Depends(get_discord_delivery_client),
    ]
    exchange_file_service: Annotated[
        ExchangeFileService,
        Depends(ExchangeFileService),
    ]
    config: Annotated[Config, Depends(get_config)]
    navigation_urls: Annotated[
        RuntimeWebServiceUrlResolver, Depends(get_runtime_web_service_url_resolver)
    ]
    binding_locks: dict[str, asyncio.Lock] = dataclass_field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    @classmethod
    def create(
        cls,
        operations: Annotated[
            ExternalChannelActionOperations,
            Depends(ExternalChannelActionOperations.create),
        ],
        credentials_codec: Annotated[
            ExternalChannelCredentialsCodec,
            Depends(get_external_channel_credentials_codec),
        ],
        slack_client: Annotated[
            SlackConversationClient, Depends(get_slack_delivery_client)
        ],
        discord_client: Annotated[
            DiscordDeliveryClient, Depends(get_discord_delivery_client)
        ],
        exchange_file_service: Annotated[
            ExchangeFileService, Depends(ExchangeFileService)
        ],
        config: Annotated[Config, Depends(get_config)],
        navigation_urls: Annotated[
            RuntimeWebServiceUrlResolver, Depends(get_runtime_web_service_url_resolver)
        ],
    ) -> "ExternalChannelActionService":
        """Construct the provider orchestrator from completed repository operations."""
        return cls(
            operations=operations,
            credentials_codec=credentials_codec,
            slack_client=slack_client,
            discord_client=discord_client,
            exchange_file_service=exchange_file_service,
            config=config,
            navigation_urls=navigation_urls,
        )

    def for_execution_owner(
        self,
        owner: SessionExecutionOwner,
    ) -> "ExternalChannelActionService":
        """Return a request-local service bound to one durable execution owner."""
        bound = dataclass_replace(
            self,
            operations=self.operations.for_execution(owner),
        )
        bound.binding_locks = self.binding_locks
        return bound

    def for_execution(
        self,
        authority: SessionResourceAuthority,
    ) -> "ExternalChannelActionService":
        """Bind direct Channel Work operations to complete execution authority."""
        return self.for_execution_owner(authority.execution_owner)

    def _operations_for_authority(
        self,
        authority: SessionResourceAuthority | None,
    ) -> ExternalChannelActionOperations:
        """Select completed persistence operations for the execution authority."""
        if authority is None:
            return self.operations
        return self.operations.for_execution(authority.execution_owner)

    async def has_active_binding(self, *, session_id: str, agent_id: str) -> bool:
        """Return whether the tool should be exposed for this root Session."""
        return await self.operations.has_active_binding(
            session_id=session_id,
            agent_id=agent_id,
        )

    async def snapshot(
        self,
        *,
        session_id: str,
        agent_id: str,
    ) -> list[ChannelWorkSnapshot]:
        """Load the canonical active-work snapshot."""
        return await self.operations.list_active_work(
            session_id=session_id,
            agent_id=agent_id,
        )

    async def prepare_navigation(
        self,
        *,
        actions: Sequence[ChannelNavigationAction],
        session_id: str,
        agent_id: str,
        binding_id: str,
    ) -> tuple[ChannelNavigationLink, ...]:
        """Resolve independent product destinations before publishing any Work."""
        context = await self.operations.navigation_context(
            session_id=session_id,
            agent_id=agent_id,
            binding_id=binding_id,
            service_ids=[
                action.service_id for action in actions if action.service_id is not None
            ],
        )
        links: list[ChannelNavigationLink] = []
        for action in actions:
            match action.type:
                case "browser":
                    base = build_external_channel_session_url(
                        self.config.web_url,
                        context.workspace_handle,
                        agent_id,
                        session_id,
                    )
                    url = None if base is None else f"{base}?page=browser"
                    label = action.label or "Open browser"
                case "web_service":
                    if action.service_id is None:
                        raise ValueError("Web service action requires service_id.")
                    base = self.navigation_urls.resolve(
                        context.service_hosts[action.service_id]
                    )
                    url = (
                        None
                        if base is None
                        else base.rstrip("/") + (action.path or "/")
                    )
                    label = action.label or "Open web service"
                case _ as unreachable:
                    assert_never(unreachable)
            if url is None or len(url) > 512:
                raise ValueError(
                    "Channel action URL is unavailable or exceeds the provider limit."
                )
            links.append(ChannelNavigationLink(label=label, url=url))
        return tuple(links)

    async def execute(
        self,
        *,
        links: Sequence[ChannelNavigationLink],
        session_id: str,
        agent_id: str,
        run_id: str,
        client_tool_call_id: str,
        binding_id: str,
        mode: ExternalChannelActionMode,
        message: str | None,
        title: str | None,
        tasks: Sequence[ChannelWorkTask] | None,
        files: Sequence[ExternalChannelOutboundFileManifest],
        file_storage: FileStorage | None,
        authority: SessionResourceAuthority | None = None,
        provider_delivery_service: RuntimeToProviderDeliveryExecutor | None = None,
        resolve_runtime_target: RuntimeTargetResolver | None = None,
    ) -> ChannelActionResult:
        """Serialize canonical Action and provider effects for one binding."""
        if authority is not None and (
            authority.session_id != session_id
            or authority.agent_id != agent_id
            or authority.run_id != run_id
        ):
            raise ValueError(
                "External Channel execution authority does not match action"
            )
        lock = self.binding_locks.setdefault(binding_id, asyncio.Lock())
        async with lock:
            return await self._execute_serialized(
                links=links,
                session_id=session_id,
                agent_id=agent_id,
                run_id=run_id,
                client_tool_call_id=client_tool_call_id,
                binding_id=binding_id,
                mode=mode,
                message=message,
                title=title,
                tasks=tasks,
                files=files,
                file_storage=file_storage,
                authority=authority,
                provider_delivery_service=provider_delivery_service,
                resolve_runtime_target=resolve_runtime_target,
            )

    async def _execute_serialized(
        self,
        *,
        links: Sequence[ChannelNavigationLink],
        session_id: str,
        agent_id: str,
        run_id: str,
        client_tool_call_id: str,
        binding_id: str,
        mode: ExternalChannelActionMode,
        message: str | None,
        title: str | None,
        tasks: Sequence[ChannelWorkTask] | None,
        files: Sequence[ExternalChannelOutboundFileManifest],
        file_storage: FileStorage | None,
        authority: SessionResourceAuthority | None = None,
        provider_delivery_service: RuntimeToProviderDeliveryExecutor | None = None,
        resolve_runtime_target: RuntimeTargetResolver | None = None,
    ) -> ChannelActionResult:
        """Commit canonical state, then execute ordered provider effects once."""
        operations = self._operations_for_authority(authority)
        transition = await operations.commit_direct_action(
            links=links,
            session_id=session_id,
            agent_id=agent_id,
            run_id=run_id,
            client_tool_call_id=client_tool_call_id,
            binding_id=binding_id,
            mode=mode,
            message=message,
            title=title,
            tasks=tasks,
            files=files,
            now=datetime.datetime.now(datetime.UTC),
        )
        reply_requested = any(
            effect.provider.target.operation is ExternalChannelDeliveryOperation.REPLY
            for effect in transition.effects
        )
        reply_delivered = (
            mode is not ExternalChannelActionMode.FINISH or reply_requested
        )
        outcomes: list[ProviderEffectOutcome] = []
        for effect_index, effect in enumerate(transition.effects):
            operation = effect.provider.target.operation
            skipped: ProviderEffectOutcome | None = None
            if (
                operation is ExternalChannelDeliveryOperation.PROGRESS_DELETE
                and transition.work_status is ExternalChannelWorkStatus.FINISHED
                and not reply_delivered
            ):
                skipped = ProviderEffectOutcome(
                    operation=operation,
                    part=effect.part,
                    status="not_attempted",
                    reason="final_reply_not_delivered",
                    detail=(
                        "Activity Tracker cleanup requires a delivered final reply."
                    ),
                )
            elif any(
                dependency >= effect_index or outcomes[dependency].status != "delivered"
                for dependency in effect.dependencies
            ):
                skipped = ProviderEffectOutcome(
                    operation=operation,
                    part=effect.part,
                    status="not_attempted",
                    reason="effect_dependency_not_delivered",
                    detail=(
                        "Activity Tracker relocation requires every earlier effect "
                        "to be delivered."
                    ),
                )
            if skipped is not None:
                outcome = skipped
            else:
                outcome = await self._execute_direct_effect(
                    effect,
                    file_storage=file_storage,
                    agent_id=agent_id,
                    session_id=session_id,
                    authority=authority,
                    provider_delivery_service=provider_delivery_service,
                    resolve_runtime_target=resolve_runtime_target,
                )
            outcomes.append(outcome)
            if operation is ExternalChannelDeliveryOperation.REPLY:
                reply_delivered = reply_delivered and outcome.status == "delivered"
        awaiting_input = False
        state_revision = transition.state_revision
        if (
            mode is ExternalChannelActionMode.REQUEST_INPUT
            and reply_requested
            and reply_delivered
        ):
            settlement = await operations.settle_awaiting_input(
                session_id=session_id,
                agent_id=agent_id,
                binding_id=binding_id,
                run_id=run_id,
                work_cycle_id=transition.work_id,
                expected_state_revision=transition.state_revision,
            )
            awaiting_input = settlement.established
            state_revision = settlement.state_revision
        return ChannelActionResult(
            binding_id=transition.binding_id,
            work_status=transition.work_status,
            state_revision=state_revision,
            awaiting_input=awaiting_input,
            outcomes=tuple(outcomes),
        )

    async def execute_direct_effect(
        self,
        effect: ChannelActionEffectPlan,
        *,
        file_storage: FileStorage | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        authority: SessionResourceAuthority | None = None,
        provider_delivery_service: RuntimeToProviderDeliveryExecutor | None = None,
        resolve_runtime_target: RuntimeTargetResolver | None = None,
    ) -> ProviderEffectOutcome:
        """Revalidate, execute, and apply one process-local provider effect."""
        return await self._execute_direct_effect(
            effect,
            file_storage=file_storage,
            agent_id=agent_id,
            session_id=session_id,
            authority=authority,
            provider_delivery_service=provider_delivery_service,
            resolve_runtime_target=resolve_runtime_target,
        )

    async def _execute_direct_effect(
        self,
        effect: ChannelActionEffectPlan,
        *,
        file_storage: FileStorage | None,
        agent_id: str | None,
        session_id: str | None,
        authority: SessionResourceAuthority | None,
        provider_delivery_service: RuntimeToProviderDeliveryExecutor | None,
        resolve_runtime_target: RuntimeTargetResolver | None,
    ) -> ProviderEffectOutcome:
        """Execute one effect and return its public outcome."""
        _validate_provider_authority(
            effect.provider.target,
            authority=authority,
            agent_id=agent_id,
            session_id=session_id,
        )
        operations = self._operations_for_authority(authority)
        current = await operations.revalidate_direct_effect(
            effect=effect,
        )
        if current is None:
            return ProviderEffectOutcome(
                operation=effect.provider.target.operation,
                part=effect.part,
                status="not_attempted",
                reason="provider_authority_unavailable",
                detail=("Current External Channel provider authority is unavailable."),
            )
        result = await self._deliver(
            current,
            file_storage=file_storage,
            agent_id=agent_id,
            session_id=session_id,
            authority=authority,
            provider_delivery_service=provider_delivery_service,
            resolve_runtime_target=resolve_runtime_target,
        )
        await operations.apply_direct_effect_outcome(
            effect=effect,
            outcome=result,
        )
        return ProviderEffectOutcome(
            operation=current.target.operation,
            part=effect.part,
            status=result.status,
            reason=result.error_kind,
            detail=result.error_summary,
        )

    async def execute_direct_control(
        self,
        plan: ProviderEffectPlan,
        *,
        preparation_boundary: ExternalChannelSetupPreparationBoundary | None,
    ) -> ProviderMutationOutcome | None:
        """Execute one post-commit provider control without durable work state."""
        current = await self.operations.revalidate_direct_control(
            plan=plan,
            preparation_boundary=preparation_boundary,
        )
        if current is None:
            return None
        outcome = await self._deliver(
            current,
            file_storage=None,
            agent_id=current.target.agent_id,
            session_id=None,
            authority=None,
            provider_delivery_service=None,
            resolve_runtime_target=None,
        )
        intent = current.target.decode_intent()
        work_id = intent.work_id
        desired_revision = intent.desired_progress_revision
        part = intent.part_ordinal
        if work_id is not None and desired_revision is not None and part is not None:
            await self.operations.apply_direct_effect_outcome(
                effect=ChannelActionEffectPlan(
                    provider=current,
                    part=part,
                    work_cycle_id=work_id,
                    expected_desired_progress_revision=desired_revision,
                    dependencies=(),
                    projection_host_kind=intent.tracker_host_kind,
                ),
                outcome=outcome,
            )
        elif intent.access_request_id is not None:
            await self.operations.apply_access_control_outcome(
                plan=current,
                outcome=outcome,
            )
        return outcome

    async def execute_binding_effect(
        self,
        plan: ProviderEffectPlan,
        *,
        file_storage: FileStorage | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        authority: SessionResourceAuthority | None = None,
        provider_delivery_service: RuntimeToProviderDeliveryExecutor | None = None,
        resolve_runtime_target: RuntimeTargetResolver | None = None,
    ) -> ProviderMutationOutcome | None:
        """Revalidate and execute one process-local exact-Binding effect."""
        _validate_provider_authority(
            plan.target,
            authority=authority,
            agent_id=agent_id,
            session_id=session_id,
        )
        operations = self._operations_for_authority(authority)
        current = await operations.revalidate_binding_effect(
            plan=plan,
        )
        if current is None:
            return None
        return await self._deliver(
            current,
            file_storage=file_storage,
            agent_id=agent_id,
            session_id=session_id,
            authority=authority,
            provider_delivery_service=provider_delivery_service,
            resolve_runtime_target=resolve_runtime_target,
        )

    async def execute_terminal_control(
        self,
        plan: ProviderEffectPlan,
    ) -> ProviderMutationOutcome | None:
        """Execute one captured cleanup after canonical terminal commit."""
        current = await self.operations.revalidate_terminal_control(
            plan=plan,
        )
        if current is None:
            return None
        outcome = await self._deliver(
            current,
            file_storage=None,
            agent_id=current.target.agent_id,
            session_id=None,
            authority=None,
            provider_delivery_service=None,
            resolve_runtime_target=None,
        )
        intent = current.target.decode_intent()
        work_id = intent.work_id
        desired_revision = intent.desired_progress_revision
        part = intent.part_ordinal
        if work_id is not None and desired_revision is not None and part is not None:
            await self.operations.apply_direct_effect_outcome(
                effect=ChannelActionEffectPlan(
                    provider=current,
                    part=part,
                    work_cycle_id=work_id,
                    expected_desired_progress_revision=desired_revision,
                    dependencies=(),
                    projection_host_kind=intent.tracker_host_kind,
                ),
                outcome=outcome,
            )
        return outcome

    async def _deliver(
        self,
        plan: ProviderEffectPlan,
        *,
        file_storage: FileStorage | None,
        agent_id: str | None,
        session_id: str | None,
        authority: SessionResourceAuthority | None,
        provider_delivery_service: RuntimeToProviderDeliveryExecutor | None,
        resolve_runtime_target: RuntimeTargetResolver | None,
    ) -> ProviderMutationOutcome:
        target = plan.target
        if target.encrypted_credentials is None:
            return ProviderMutationOutcome(
                status="failed",
                provider_message_key=None,
                error_kind="credentials_missing",
                error_summary="External Channel credentials are unavailable.",
            )
        credentials = self.credentials_codec.decrypt(target.encrypted_credentials)
        match target.provider:
            case ExternalChannelProvider.SLACK:
                return _provider_mutation_outcome(
                    await self._deliver_slack(
                        target,
                        operation_key=plan.operation_key,
                        bot_token=credentials.bot_token,
                        file_storage=file_storage,
                        agent_id=agent_id,
                        session_id=session_id,
                        authority=authority,
                        provider_delivery_service=provider_delivery_service,
                        resolve_runtime_target=resolve_runtime_target,
                    )
                )
            case ExternalChannelProvider.DISCORD:
                return _provider_mutation_outcome(
                    await self._deliver_discord(
                        target,
                        operation_key=plan.operation_key,
                        bot_token=credentials.bot_token,
                        file_storage=file_storage,
                        agent_id=agent_id,
                        authority=authority,
                    )
                )
            case _ as unreachable:
                assert_never(unreachable)

    async def _deliver_discord(
        self,
        target: ProviderTarget,
        *,
        operation_key: ProviderOperationKey,
        bot_token: str,
        file_storage: FileStorage | None,
        agent_id: str | None,
        authority: SessionResourceAuthority | None,
    ) -> DiscordDeliveryResult:
        """Deliver one Discord effect and reuse a session only when needed."""
        return await ExternalChannelActionService._deliver_discord_with_client(
            self,
            target,
            operation_key=operation_key,
            bot_token=bot_token,
            file_storage=file_storage,
            agent_id=agent_id,
            authority=authority,
            discord_client=self.discord_client,
            workflow_session_open=False,
        )

    async def _deliver_discord_with_client(
        self,
        target: ProviderTarget,
        *,
        operation_key: ProviderOperationKey,
        bot_token: str,
        file_storage: FileStorage | None,
        agent_id: str | None,
        authority: SessionResourceAuthority | None,
        discord_client: DiscordDeliveryClient,
        workflow_session_open: bool,
    ) -> DiscordDeliveryResult:
        """Deliver one Discord text, multipart file, or control mutation."""
        payload = target.request_payload
        intent = target.decode_intent()
        reply = None
        if target.operation is ExternalChannelDeliveryOperation.REPLY:
            reply = _decode_discord_reply(target)
            if reply is None:
                return _discord_invalid_payload()
        configuration = target.provider_configuration
        destination = (
            reply.destination
            if reply is not None
            else _decode_discord_destination(target)
        )
        if destination is None or configuration is None:
            return _discord_invalid_payload()
        guild_id = destination.guild_id
        channel_id = destination.channel_id
        files = (
            reply.files if reply is not None else _outbound_files(payload.get("files"))
        )
        if files is None:
            return _discord_invalid_payload()
        delivery_channel_id = channel_id
        thread_parent = destination.thread_parent_channel_id
        if thread_parent is not None:
            if not workflow_session_open:
                try:
                    async with discord_client.open(
                        bot_token=bot_token
                    ) as workflow_client:
                        return await (
                            ExternalChannelActionService._deliver_discord_with_client(
                                self,
                                target,
                                operation_key=operation_key,
                                bot_token=bot_token,
                                file_storage=file_storage,
                                agent_id=agent_id,
                                authority=authority,
                                discord_client=workflow_client,
                                workflow_session_open=True,
                            )
                        )
                except DiscordSDKError as error:
                    return _sdk_delivery_failure(error)
                except TimeoutError:
                    return _sdk_timeout_result()
            thread = await discord_client.ensure_thread(
                bot_token=bot_token,
                guild_id=guild_id,
                parent_channel_id=thread_parent,
                root_message_id=channel_id,
                name=target.agent_name,
                auto_archive_duration=(
                    configuration.thread_auto_archive_duration_minutes
                ),
            )
            if thread.status != "delivered":
                return thread
            resolved_thread_id = _discord_thread_channel_id(thread.provider_message_key)
            if resolved_thread_id is None:
                return _discord_invalid_payload()
            delivery_channel_id = resolved_thread_id
            if target.resource_id is not None:
                await self._record_discord_delivery_channel(
                    resource_id=target.resource_id,
                    delivery_channel_id=resolved_thread_id,
                    initial_thread_title=thread.created_thread_name,
                    authority=authority,
                )
        match target.operation:
            case (
                ExternalChannelDeliveryOperation.REPLY
                | ExternalChannelDeliveryOperation.PROGRESS_CREATE
                | ExternalChannelDeliveryOperation.CONTROL_MESSAGE
            ):
                if (
                    target.operation is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
                    and intent.control_kind == "session_presence"
                ):
                    presence = _session_presence_context(
                        target,
                        intent=intent,
                        web_url=self.config.web_url,
                    )
                    if presence is None or files:
                        return _discord_invalid_payload()
                    control = render_discord_session_presence(
                        agent_name=presence.agent_name,
                        session_url=presence.session_url,
                        state=presence.state,
                        settings_custom_id=(
                            build_discord_binding_settings_open_custom_id(
                                secret=self.config.auth.jwt.secret_key,
                                binding_id=target.binding_id,
                            )
                            if presence.state == "joined"
                            and isinstance(target.binding_id, str)
                            and target.binding_id
                            else None
                        ),
                    )
                    return await discord_client.create_message(
                        bot_token=bot_token,
                        guild_id=guild_id,
                        channel_id=delivery_channel_id,
                        content=control.text,
                        operation_key=operation_key,
                        suppress_notifications=False,
                        suppress_embeds=False,
                        components=control.components,
                        embeds=control.embeds,
                    )
                if (
                    target.operation is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
                    and intent.control_kind == "setup_required"
                ):
                    setup = _decode_discord_setup(target, files=files)
                    if setup is None:
                        return _discord_invalid_payload()
                    control = render_discord_setup_required(
                        agent_name=setup.agent_name,
                        channel_custom_id=build_discord_settings_custom_id(
                            secret=self.config.auth.jwt.secret_key,
                            action="setup_channel",
                            origin_interaction_id=setup.claim_id,
                            setup_claim_id=setup.claim_id,
                            claim_generation=setup.claim_generation,
                            source_revision=setup.source_revision,
                        ),
                        threads_custom_id=build_discord_settings_custom_id(
                            secret=self.config.auth.jwt.secret_key,
                            action="setup_threads",
                            origin_interaction_id=setup.claim_id,
                            setup_claim_id=setup.claim_id,
                            claim_generation=setup.claim_generation,
                            source_revision=setup.source_revision,
                        ),
                    )
                    return await discord_client.create_message(
                        bot_token=bot_token,
                        guild_id=guild_id,
                        channel_id=delivery_channel_id,
                        content=control.text,
                        operation_key=operation_key,
                        suppress_notifications=False,
                        suppress_embeds=False,
                        components=control.components,
                        embeds=control.embeds,
                    )
                if (
                    target.operation is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
                    and intent.control_kind == "scheduled_task_registration"
                ):
                    text = payload.get("text")
                    embeds = _discord_embeds(payload.get("embeds"))
                    task_id = payload.get("task_id")
                    delete_locator = payload.get("delete_locator")
                    edit_url = (
                        None
                        if not isinstance(task_id, str)
                        else _scheduled_task_edit_url(
                            target,
                            web_url=self.config.web_url,
                            task_id=task_id,
                        )
                    )
                    if (
                        files
                        or text != ""
                        or embeds is None
                        or not isinstance(delete_locator, str)
                        or edit_url is None
                    ):
                        return _discord_invalid_payload()
                    return await discord_client.create_message(
                        bot_token=bot_token,
                        guild_id=guild_id,
                        channel_id=delivery_channel_id,
                        content=_discord_agent_content(target, text),
                        operation_key=operation_key,
                        suppress_notifications=False,
                        suppress_embeds=False,
                        components=render_scheduled_task_discord_controls(
                            edit_url=edit_url,
                            delete_locator=delete_locator,
                        ),
                        embeds=embeds,
                    )
                if (
                    target.operation is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
                    and intent.control_kind == "scheduled_task_deletion"
                ):
                    text = payload.get("text")
                    embeds = _discord_embeds(payload.get("embeds"))
                    if files or text != "" or embeds is None:
                        return _discord_invalid_payload()
                    return await discord_client.create_message(
                        bot_token=bot_token,
                        guild_id=guild_id,
                        channel_id=delivery_channel_id,
                        content=_discord_agent_content(target, text),
                        operation_key=operation_key,
                        suppress_notifications=False,
                        suppress_embeds=False,
                        embeds=embeds,
                    )
                text = reply.text if reply is not None else payload.get("text")
                if not isinstance(text, str):
                    return _discord_invalid_payload()
                forward_to_parent = (
                    reply.forward_to_parent
                    if reply is not None
                    else payload.get("forward_to_parent", False)
                )
                forward_parent_channel_id = (
                    reply.parent_channel_id
                    if reply is not None
                    else payload.get("parent_channel_id")
                )
                if (
                    not isinstance(forward_to_parent, bool)
                    or forward_to_parent
                    and (
                        target.operation is not ExternalChannelDeliveryOperation.REPLY
                        or not isinstance(forward_parent_channel_id, str)
                        or not forward_parent_channel_id.isdigit()
                    )
                ):
                    return _discord_invalid_payload()
                components = (
                    (
                        [row.to_wire() for row in reply.components]
                        if reply.components is not None
                        else None
                    )
                    if reply is not None
                    else _discord_components(payload.get("components"))
                )
                if (
                    reply is None
                    and payload.get("components") is not None
                    and components is None
                ):
                    return _discord_invalid_payload()
                embeds = (
                    (
                        [embed.to_wire() for embed in reply.embeds]
                        if reply.embeds is not None
                        else None
                    )
                    if reply is not None
                    else _discord_embeds(payload.get("embeds"))
                )
                if (
                    reply is None
                    and payload.get("embeds") is not None
                    and embeds is None
                ):
                    return _discord_invalid_payload()
                if target.operation is ExternalChannelDeliveryOperation.PROGRESS_CREATE:
                    context = _session_navigation_context(
                        target,
                        web_url=self.config.web_url,
                    )
                    if context is None or components is not None:
                        return _discord_invalid_payload()
                    components = _discord_tracker_components(
                        target,
                        intent=intent,
                        session_url=context.session_url,
                        secret=self.config.auth.jwt.secret_key,
                    )
                    if components is None:
                        return _discord_invalid_payload()
                if files:
                    if components is not None or embeds is not None:
                        return _discord_invalid_payload()
                    runtime_files = [
                        file
                        for file in files
                        if file.source is ExternalChannelOutboundFileSource.RUNTIME
                    ]
                    exchange_files = [
                        file
                        for file in files
                        if file.source is ExternalChannelOutboundFileSource.EXCHANGE
                    ]
                    if runtime_files and (
                        not isinstance(file_storage, RangedFileStorage)
                        or agent_id is None
                    ):
                        return DiscordDeliveryResult(
                            status="failed",
                            provider_message_key=None,
                            error_kind="runtime_file_source_unavailable",
                            error_summary=(
                                "The original Runtime file source is unavailable."
                            ),
                        )
                    if exchange_files and authority is None:
                        return DiscordDeliveryResult(
                            status="failed",
                            provider_message_key=None,
                            error_kind="exchange_file_source_unavailable",
                            error_summary=(
                                "The original Exchange file source is unavailable."
                            ),
                        )
                    ranged_storage = (
                        file_storage
                        if isinstance(file_storage, RangedFileStorage)
                        else None
                    )
                    return await discord_client.create_file_message(
                        bot_token=bot_token,
                        guild_id=guild_id,
                        channel_id=delivery_channel_id,
                        content=_discord_agent_content(target, text),
                        files=tuple(
                            DiscordOutboundFile(
                                filename=file.filename,
                                media_type=file.media_type,
                                length=file.expected_size,
                                content=lambda file=file: _discord_outbound_content(
                                    manifest=file,
                                    file_storage=ranged_storage,
                                    agent_id=agent_id,
                                    exchange_file_service=self.exchange_file_service,
                                    authority=authority,
                                ),
                            )
                            for file in files
                        ),
                        operation_key=operation_key,
                        suppress_embeds=configuration.suppress_url_previews,
                        forward_to_parent=forward_to_parent,
                        parent_channel_id=(
                            forward_parent_channel_id
                            if isinstance(forward_parent_channel_id, str)
                            else None
                        ),
                    )
                if components is None and embeds is None:
                    return await discord_client.create_message(
                        bot_token=bot_token,
                        guild_id=guild_id,
                        channel_id=delivery_channel_id,
                        content=_discord_agent_content(target, text),
                        operation_key=operation_key,
                        suppress_notifications=False,
                        suppress_embeds=configuration.suppress_url_previews,
                        forward_to_parent=forward_to_parent,
                        parent_channel_id=(
                            forward_parent_channel_id
                            if isinstance(forward_parent_channel_id, str)
                            else None
                        ),
                    )
                return await discord_client.create_message(
                    bot_token=bot_token,
                    guild_id=guild_id,
                    channel_id=delivery_channel_id,
                    content=_discord_agent_content(target, text),
                    operation_key=operation_key,
                    suppress_notifications=(
                        target.operation
                        is ExternalChannelDeliveryOperation.PROGRESS_CREATE
                    ),
                    suppress_embeds=(
                        configuration.suppress_url_previews and not embeds
                    ),
                    components=components,
                    embeds=embeds,
                    forward_to_parent=forward_to_parent,
                    parent_channel_id=(
                        forward_parent_channel_id
                        if isinstance(forward_parent_channel_id, str)
                        else None
                    ),
                )
            case ExternalChannelDeliveryOperation.PROGRESS_UPDATE:
                update = _decode_discord_progress_update(
                    target, guild_id=guild_id, web_url=self.config.web_url
                )
                if update is None:
                    return _discord_invalid_payload()
                components = _discord_tracker_components(
                    target,
                    intent=intent,
                    session_url=update.context.session_url,
                    secret=self.config.auth.jwt.secret_key,
                )
                if components is None:
                    return _discord_invalid_payload()
                embeds = [embed.to_wire() for embed in update.embeds]
                return await discord_client.update_message(
                    bot_token=bot_token,
                    guild_id=guild_id,
                    channel_id=delivery_channel_id,
                    message_id=update.message_id,
                    content=(
                        None
                        if intent.tracker_host_kind == "reply"
                        else _discord_agent_content(target, update.text)
                    ),
                    suppress_embeds=(
                        configuration.suppress_url_previews and not embeds
                    ),
                    components=components,
                    embeds=embeds,
                )
            case ExternalChannelDeliveryOperation.PROGRESS_DELETE:
                deletion = _decode_discord_progress_delete(target, guild_id=guild_id)
                if deletion is None:
                    return _discord_invalid_payload()
                if intent.tracker_host_kind == "reply":
                    return await discord_client.update_message(
                        bot_token=bot_token,
                        guild_id=guild_id,
                        channel_id=delivery_channel_id,
                        message_id=deletion.message_id,
                        content=None,
                        suppress_embeds=configuration.suppress_url_previews,
                        components=[],
                        embeds=[],
                    )
                return await discord_client.delete_message(
                    bot_token=bot_token,
                    guild_id=guild_id,
                    channel_id=delivery_channel_id,
                    message_id=deletion.message_id,
                )
            case _ as unreachable:
                assert_never(unreachable)

    async def _record_discord_delivery_channel(
        self,
        *,
        resource_id: str,
        delivery_channel_id: str,
        initial_thread_title: str | None,
        authority: SessionResourceAuthority | None,
    ) -> None:
        """Persist a provisioned Discord thread outside the provider mutation."""
        operations = self._operations_for_authority(authority)
        await operations.record_discord_delivery_channel(
            resource_id=resource_id,
            delivery_channel_id=delivery_channel_id,
            initial_thread_title=initial_thread_title,
        )

    async def _deliver_slack(
        self,
        target: ProviderTarget,
        *,
        operation_key: ProviderOperationKey,
        bot_token: str,
        file_storage: FileStorage | None,
        agent_id: str | None,
        session_id: str | None,
        authority: SessionResourceAuthority | None,
        provider_delivery_service: RuntimeToProviderDeliveryExecutor | None,
        resolve_runtime_target: RuntimeTargetResolver | None,
    ) -> SlackControlMessageResult:
        intent = target.decode_intent()
        presentation = resolve_slack_agent_presentation(
            target,
            avatar_cdn_base_url=self.config.avatar_cdn_base_url,
        )
        destination = _decode_slack_destination(target)
        if destination is None:
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="provider_target_invalid",
                error_summary="Slack delivery target is incomplete.",
            )
        tenant_id = destination.tenant_id
        channel_id = destination.channel_id
        thread_ts = destination.thread_ts
        match target.operation:
            case ExternalChannelDeliveryOperation.REPLY:
                reply = _decode_slack_reply(target, destination)
                if reply is None:
                    return _invalid_payload()
                if reply.files:
                    del file_storage
                    return await self._deliver_slack_files(
                        bot_token=bot_token,
                        tenant_id=tenant_id,
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        markdown_text=prepend_agent_markdown(presentation, reply.text),
                        files=reply.files,
                        operation_key=operation_key,
                        agent_id=agent_id,
                        session_id=session_id,
                        authority=authority,
                        provider_delivery_service=provider_delivery_service,
                        resolve_runtime_target=resolve_runtime_target,
                    )
                return await self.slack_client.post_message(
                    blocks=(
                        None
                        if reply.blocks is None
                        else prepend_agent_blocks(presentation, list(reply.blocks))
                    ),
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    markdown_text=prepend_agent_markdown(presentation, reply.text),
                    icon_url=(None if presentation is None else presentation.icon_url),
                    reply_broadcast=reply.broadcast,
                )
            case ExternalChannelDeliveryOperation.PROGRESS_CREATE:
                progress = _decode_slack_progress(target, web_url=self.config.web_url)
                if progress is None:
                    return _invalid_payload()
                blocks = list(progress.blocks)
                blocks.append(
                    _slack_progress_actions(
                        intent=intent,
                        target=target,
                        channel_id=channel_id,
                        session_url=progress.context.session_url,
                        jwt_secret=self.config.auth.jwt.secret_key,
                    )
                )
                return await self.slack_client.post_blocks(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    text=prepend_agent_fallback(presentation, progress.text),
                    blocks=prepend_agent_blocks(presentation, blocks),
                    icon_url=(None if presentation is None else presentation.icon_url),
                )
            case ExternalChannelDeliveryOperation.PROGRESS_UPDATE:
                update = _decode_slack_progress_update(
                    target, web_url=self.config.web_url
                )
                if update is None:
                    return _invalid_payload()
                progress = update.content
                blocks = list(progress.blocks)
                blocks.append(
                    _slack_progress_actions(
                        intent=intent,
                        target=target,
                        channel_id=channel_id,
                        session_url=progress.context.session_url,
                        jwt_secret=self.config.auth.jwt.secret_key,
                    )
                )
                return await self.slack_client.update_message(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    message_ts=update.message_ts,
                    text=prepend_agent_fallback(presentation, progress.text),
                    blocks=prepend_agent_blocks(presentation, blocks),
                )
            case ExternalChannelDeliveryOperation.PROGRESS_DELETE:
                deletion = _decode_slack_progress_delete(target)
                if deletion is None:
                    return _invalid_payload()
                return await self.slack_client.delete_message(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    message_ts=deletion.message_ts,
                )
            case ExternalChannelDeliveryOperation.CONTROL_MESSAGE:
                return await self._deliver_slack_control(
                    target,
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    presentation=presentation,
                )
            case _ as unreachable:
                assert_never(unreachable)

    async def _deliver_slack_control(
        self,
        target: ProviderTarget,
        *,
        bot_token: str,
        tenant_id: str,
        channel_id: str,
        thread_ts: str | None,
        presentation: SlackAgentPresentation | None,
    ) -> SlackControlMessageResult:
        """Deliver one validated selector, notice, or approval control."""
        intent = target.decode_intent()
        if not _slack_control_tenant_matches(target, tenant_id):
            return _invalid_payload()
        control_kind = intent.control_kind
        if control_kind in {
            "scheduled_task_registration",
            "scheduled_task_deletion",
        }:
            notice = _decode_slack_control_notice(target)
            if notice is None:
                return _invalid_payload()
            return await self.slack_client.post_blocks(
                bot_token=bot_token,
                tenant_id=tenant_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                text=prepend_agent_fallback(presentation, notice.text),
                blocks=prepend_agent_blocks(presentation, list(notice.blocks)),
                icon_url=(None if presentation is None else presentation.icon_url),
            )
        if control_kind == "agent_selector":
            selector_interaction_id = _decode_slack_selector(target)
            if selector_interaction_id is None:
                return _invalid_payload()
            selector = _render_agent_selector_control(selector_interaction_id)
            return await self.slack_client.post_blocks(
                bot_token=bot_token,
                tenant_id=tenant_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                text=selector.text,
                blocks=selector.blocks,
                icon_url=None,
            )
        if control_kind == "setup_required":
            if not isinstance(target.agent_name, str) or not target.agent_name:
                return _invalid_payload()
            control = render_slack_setup_required(
                agent_name=target.agent_name,
                settings_action_id=SLACK_SETTINGS_OPEN_ACTION_ID,
                settings_action_value=build_slack_parent_settings_locator(
                    secret=self.config.auth.jwt.secret_key,
                    connection_id=target.connection_id,
                    provider_parent_channel_id=channel_id,
                ),
            )
            return await self.slack_client.post_blocks(
                bot_token=bot_token,
                tenant_id=tenant_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                text=control.text,
                blocks=control.blocks,
                icon_url=None,
            )
        if control_kind == "session_presence":
            context = _session_presence_context(
                target,
                intent=intent,
                web_url=self.config.web_url,
            )
            if context is None:
                return _invalid_payload()
            control = render_slack_session_presence(
                agent_name=context.agent_name,
                session_url=context.session_url,
                state=context.state,
                settings_action_id=SLACK_SETTINGS_OPEN_ACTION_ID,
                settings_action_value=(
                    build_slack_settings_locator(
                        secret=self.config.auth.jwt.secret_key,
                        connection_id=target.connection_id,
                        provider_parent_channel_id=channel_id,
                        resource_id=target.resource_id,
                        binding_id=target.binding_id,
                    )
                    if (
                        context.state == "joined"
                        and target.resource_id is not None
                        and target.binding_id is not None
                    )
                    else None
                ),
            )
            return await self.slack_client.post_blocks(
                bot_token=bot_token,
                tenant_id=tenant_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                text=control.text,
                blocks=control.blocks,
                icon_url=None,
            )
        if control_kind == "shortcut_already_bound":
            recorded_presentation = resolve_slack_agent_name_presentation(
                _decode_slack_recorded_agent_name(target)
            )
            bound_presentation = presentation or recorded_presentation
            if bound_presentation is None:
                return _invalid_payload()
            text = (
                "This conversation is already linked to the recorded Agent. "
                "Start a separate top-level conversation to use another Agent."
            )
            return await self.slack_client.post_blocks(
                bot_token=bot_token,
                tenant_id=tenant_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                text=prepend_agent_fallback(bound_presentation, text),
                blocks=prepend_agent_blocks(
                    bound_presentation,
                    [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": text},
                        }
                    ],
                ),
                icon_url=bound_presentation.icon_url,
            )
        approval = _decode_slack_approval(target)
        if approval is None or thread_ts is None:
            return _invalid_payload()
        return await self.slack_client.post_approval_control_message(
            bot_token=bot_token,
            tenant_id=tenant_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            approval_url=approval.url,
            participant_label=approval.participant_label,
            participant_provider_user_id=approval.participant_provider_user_id,
            agent_name=(
                None
                if presentation is None or not presentation.show_name
                else presentation.name
            ),
            agent_markdown_line=(
                None
                if presentation is None or not presentation.show_name
                else presentation.markdown_line
            ),
            icon_url=None if presentation is None else presentation.icon_url,
        )

    async def _deliver_slack_files(
        self,
        *,
        bot_token: str,
        tenant_id: str,
        channel_id: str,
        thread_ts: str | None,
        markdown_text: str,
        files: tuple[ExternalChannelOutboundFileManifest, ...],
        operation_key: ProviderOperationKey,
        agent_id: str | None,
        session_id: str | None,
        authority: SessionResourceAuthority | None,
        provider_delivery_service: RuntimeToProviderDeliveryExecutor | None,
        resolve_runtime_target: RuntimeTargetResolver | None,
    ) -> SlackControlMessageResult:
        """Stream Runtime and Exchange files inside one direct provider call."""
        runtime_sources = tuple(
            RuntimeToProviderSource(
                runtime_path=file.path,
                filename=file.filename,
                media_type=file.media_type,
                expected_size=file.expected_size,
            )
            for file in files
            if file.source is ExternalChannelOutboundFileSource.RUNTIME
        )
        batch: RuntimeToProviderBatch | None = None
        if runtime_sources:
            if (
                provider_delivery_service is None
                or resolve_runtime_target is None
                or agent_id is None
                or session_id is None
            ):
                return SlackControlMessageResult(
                    status="failed",
                    provider_message_key=None,
                    error_kind="runtime_file_source_unavailable",
                    error_summary="The original Runtime file source is unavailable.",
                )
            try:

                async def before_source_admission() -> None:
                    return None

                target = await resolve_runtime_target()
                prepared_batch = await provider_delivery_service.prepare(
                    target=target,
                    agent_id=agent_id,
                    session_id=session_id,
                    operation_id=f"external-channel:{operation_key.value}",
                    batch_id=operation_key.value,
                    sources=runtime_sources,
                    before_source_admission=before_source_admission,
                )
                await prepared_batch.ensure_active()
                batch = prepared_batch
            except RuntimeStorageError:
                return SlackControlMessageResult(
                    status="failed",
                    provider_message_key=None,
                    error_kind="runtime_file_source_unavailable",
                    error_summary="The original Runtime file source is unavailable.",
                )
            except asyncio.CancelledError:
                if batch is not None:
                    await asyncio.shield(batch.close())
                    await asyncio.shield(batch.abandon_or_cancel())
                raise
            except RuntimeToProviderCleanupError:
                return SlackControlMessageResult(
                    status="unknown",
                    provider_message_key=None,
                    error_kind="runtime_transfer_cleanup_unknown",
                    error_summary="Runtime file delivery cleanup is not confirmed.",
                )
            except RuntimeToProviderTransferError:
                if batch is not None:
                    try:
                        await batch.abandon_or_cancel()
                    except RuntimeToProviderTransferError:
                        return SlackControlMessageResult(
                            status="unknown",
                            provider_message_key=None,
                            error_kind="runtime_transfer_cleanup_unknown",
                            error_summary=(
                                "Runtime file delivery cleanup is not confirmed."
                            ),
                        )
                return SlackControlMessageResult(
                    status="failed",
                    provider_message_key=None,
                    error_kind="runtime_file_source_unavailable",
                    error_summary="The original Runtime file source is unavailable.",
                )
        if (
            any(
                file.source is ExternalChannelOutboundFileSource.EXCHANGE
                for file in files
            )
            and authority is None
        ):
            if batch is not None:
                try:
                    await batch.abandon_or_cancel()
                except RuntimeToProviderCleanupError:
                    return SlackControlMessageResult(
                        status="unknown",
                        provider_message_key=None,
                        error_kind="runtime_transfer_cleanup_unknown",
                        error_summary=(
                            "Runtime file delivery cleanup is not confirmed."
                        ),
                    )
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="exchange_file_source_unavailable",
                error_summary="The original Exchange file source is unavailable.",
            )

        async def before_provider_request() -> None:
            if batch is not None:
                await batch.ensure_active()

        runtime_index = 0
        outbound_files: list[SlackOutboundFile] = []
        for file in files:
            if file.source is ExternalChannelOutboundFileSource.RUNTIME:
                source_index = runtime_index
                runtime_index += 1
                assert batch is not None
                outbound_files.append(
                    SlackOutboundFile(
                        filename=file.filename,
                        length=file.expected_size,
                        content=lambda source_index=source_index: (
                            _slack_runtime_provider_content(
                                batch=batch,
                                source_index=source_index,
                            )
                        ),
                    )
                )
            else:
                outbound_files.append(
                    SlackOutboundFile(
                        filename=file.filename,
                        length=file.expected_size,
                        content=lambda file=file: _slack_exchange_outbound_content(
                            manifest=file,
                            exchange_file_service=self.exchange_file_service,
                            authority=authority,
                        ),
                    )
                )
        try:
            result = await self.slack_client.post_file_message(
                bot_token=bot_token,
                tenant_id=tenant_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                markdown_text=markdown_text,
                files=outbound_files,
                before_provider_request=before_provider_request,
                deadline_at=batch.deadline_at if batch is not None else None,
            )
        except asyncio.CancelledError:
            if batch is not None:
                await asyncio.shield(batch.close())
            raise
        except RuntimeToProviderTransferError:
            if batch is not None:
                await batch.close()
            return SlackControlMessageResult(
                status="unknown",
                provider_message_key=None,
                error_kind="runtime_transfer_ambiguous",
                error_summary="Runtime file delivery outcome is unknown.",
            )
        if batch is None:
            return result
        if result.status == "delivered":
            try:
                await batch.provider_completed()
                await batch.acknowledge_and_settle()
            except asyncio.CancelledError:
                await asyncio.shield(batch.close())
                raise
            except RuntimeToProviderTransferError:
                logger.exception(
                    "Runtime claim cleanup failed after provider delivery",
                    extra={"provider": "slack", "operation": "reply"},
                )
                await batch.close()
            return result
        if result.status == "failed":
            try:
                await batch.close()
                await batch.abandon_or_cancel()
            except asyncio.CancelledError:
                raise
            except RuntimeToProviderTransferError:
                return SlackControlMessageResult(
                    status="unknown",
                    provider_message_key=None,
                    error_kind="runtime_transfer_cleanup_unknown",
                    error_summary="Runtime file delivery cleanup is not confirmed.",
                )
            return result
        await batch.close()
        return result


def _provider_mutation_outcome(
    result: SlackControlMessageResult | DiscordDeliveryResult,
) -> ProviderMutationOutcome:
    """Normalize provider-specific results before durable settlement."""
    return ProviderMutationOutcome(
        status=result.status,
        provider_message_key=result.provider_message_key,
        error_kind=result.error_kind,
        error_summary=result.error_summary,
    )


def _provider_message_ts(value: object) -> str | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    message_ts = value.rsplit(":", 1)[-1]
    return message_ts or None


def _discord_thread_channel_id(value: object) -> str | None:
    """Extract one validated Discord thread channel from a transient result."""
    if not isinstance(value, str):
        return None
    prefix = "discord-thread:"
    thread_id = value.removeprefix(prefix)
    if thread_id == value or not thread_id.isdigit():
        return None
    return thread_id


def _discord_provider_message_id(
    value: object,
    *,
    guild_id: str,
) -> str | None:
    """Extract an exact message snowflake from one canonical Discord key."""
    if not isinstance(value, str):
        return None
    provider, separator, remainder = value.partition(":")
    if provider != "discord" or not separator:
        return None
    message_guild_id, separator, message_id = remainder.partition(":")
    if not separator or message_guild_id != guild_id or not message_id.isdigit():
        return None
    return message_id


def _discord_agent_content(target: ProviderTarget, text: str) -> str:
    """Prefix visible Discord text with a safely rendered current Agent name."""
    if target.app_mode is not ExternalChannelAppMode.MULTI:
        return text
    name = normalize_slack_agent_name(target.agent_name)
    if name is None:
        return text
    escaped_name = name.replace("\\", "\\\\").replace("*", "\\*")
    if not text:
        return f"**{escaped_name}**"
    return f"**{escaped_name}**\n{text}"


def _session_presence_context(
    target: ProviderTarget,
    *,
    intent: ProviderEffectIntent,
    web_url: str | None,
) -> _SessionPresenceContext | None:
    """Resolve one presence control without trusting persisted display content."""
    state = intent.presence_state
    if state is None:
        return None
    context = _session_navigation_context(target, web_url=web_url)
    if context is None:
        return None
    return _SessionPresenceContext(
        agent_name=context.agent_name,
        session_url=context.session_url,
        state=state,
    )


def _session_navigation_context(
    target: ProviderTarget,
    *,
    web_url: str | None,
) -> _SessionNavigationContext | None:
    """Resolve one current Session URL without trusting persisted display content."""
    if (
        not isinstance(target.agent_name, str)
        or not target.agent_name
        or not isinstance(target.workspace_handle, str)
        or not target.workspace_handle
        or not isinstance(target.agent_id, str)
        or not target.agent_id
        or not isinstance(target.agent_session_id, str)
        or not target.agent_session_id
    ):
        return None
    session_url = build_external_channel_session_url(
        web_url,
        target.workspace_handle,
        target.agent_id,
        target.agent_session_id,
    )
    if session_url is None:
        return None
    return _SessionNavigationContext(
        agent_name=target.agent_name,
        session_url=session_url,
    )


def _slack_progress_actions(
    *,
    target: ProviderTarget,
    channel_id: str,
    intent: ProviderEffectIntent,
    session_url: str,
    jwt_secret: str,
) -> dict[str, object]:
    """Render Slack Tracker controls from exact current target authority."""
    if intent.scheduled_tracker:
        return render_slack_session_actions(
            session_url=session_url,
            settings_action_id=None,
            settings_action_value=None,
        )
    if target.resource_id is None or target.binding_id is None:
        raise ValueError("Conversational Slack Tracker authority is incomplete.")
    return render_slack_session_actions(
        session_url=session_url,
        settings_action_id=SLACK_SETTINGS_OPEN_ACTION_ID,
        settings_action_value=build_slack_settings_locator(
            secret=jwt_secret,
            connection_id=target.connection_id,
            provider_parent_channel_id=channel_id,
            resource_id=target.resource_id,
            binding_id=target.binding_id,
        ),
    )


def _discord_tracker_components(
    target: ProviderTarget,
    *,
    intent: ProviderEffectIntent,
    session_url: str,
    secret: str,
) -> list[dict[str, object]] | None:
    """Render current Discord Tracker controls from exact target authority."""
    if intent.scheduled_tracker:
        return render_discord_session_navigation_components(
            session_url,
            settings_custom_id=None,
        )
    if not isinstance(target.binding_id, str) or not target.binding_id:
        return None
    return render_discord_session_navigation_components(
        session_url,
        settings_custom_id=build_discord_binding_settings_open_custom_id(
            secret=secret,
            binding_id=target.binding_id,
        ),
    )


def _scheduled_task_edit_url(
    target: ProviderTarget,
    *,
    web_url: str | None,
    task_id: str,
) -> str | None:
    """Resolve one exact Scheduled Task Web editor from current target authority."""
    if (
        not isinstance(target.workspace_handle, str)
        or not target.workspace_handle
        or not isinstance(target.agent_id, str)
        or not target.agent_id
        or not isinstance(target.agent_session_id, str)
        or not target.agent_session_id
    ):
        return None
    return build_external_channel_scheduled_task_url(
        web_url,
        target.workspace_handle,
        target.agent_id,
        target.agent_session_id,
        task_id,
    )


def _invalid_payload() -> SlackControlMessageResult:
    return SlackControlMessageResult(
        status="failed",
        provider_message_key=None,
        error_kind="provider_payload_invalid",
        error_summary="The committed provider request is incomplete.",
    )


def _render_agent_selector_control(
    selector_interaction_id: str,
) -> _SlackSelectorControlPresentation:
    """Render the generic control for one interaction-owned selector."""
    text = "Select an Agent to continue this conversation."
    return _SlackSelectorControlPresentation(
        text=text,
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Select Agent"},
                        "action_id": "azents_agent_selector_open",
                        "value": selector_interaction_id,
                    }
                ],
            },
        ],
    )


def _discord_invalid_payload() -> DiscordDeliveryResult:
    return DiscordDeliveryResult(
        status="failed",
        provider_message_key=None,
        error_kind="provider_payload_invalid",
        error_summary="The committed Discord provider request is incomplete.",
    )


@dataclass(frozen=True)
class _SlackDestination:
    """Validated Slack target and explicit thread-scope predicate."""

    tenant_id: str
    channel_id: str
    thread_ts: str | None
    thread_scope: bool


def _decode_slack_destination(target: ProviderTarget) -> _SlackDestination | None:
    """Preserve the provider target's historical scope and null semantics."""
    payload = target.request_payload
    tenant = target.provider_tenant_id
    channel = payload.get("channel_id")
    thread = payload.get("thread_ts")
    scope = payload.get("conversation_scope")
    if (
        not isinstance(tenant, str)
        or not tenant
        or not isinstance(channel, str)
        or scope == "parent_channel"
        and thread is not None
        or scope != "parent_channel"
        and not isinstance(thread, str)
    ):
        return None
    return _SlackDestination(
        tenant_id=tenant,
        channel_id=channel,
        thread_ts=thread if isinstance(thread, str) else None,
        thread_scope=scope == "thread",
    )


@dataclass(frozen=True)
class _SlackReply:
    """Validated reply fields; provider blocks remain opaque egress data."""

    destination: _SlackDestination
    text: str
    broadcast: bool
    files: tuple[ExternalChannelOutboundFileManifest, ...]
    blocks: tuple[dict[str, object], ...] | None


@dataclass(frozen=True)
class _SlackProgress:
    """Validated progress content with opaque provider blocks."""

    text: str
    blocks: tuple[dict[str, object], ...]
    context: _SessionNavigationContext


@dataclass(frozen=True)
class _SlackControlNotice:
    """Validated notice text and opaque provider blocks."""

    text: str
    blocks: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class _SlackApproval:
    """Validated approval control fields."""

    url: str
    participant_provider_user_id: str
    participant_label: str


def _slack_control_tenant_matches(target: ProviderTarget, tenant_id: str) -> bool:
    value = target.request_payload.get("tenant_id")
    return value is None or value == tenant_id


def _decode_slack_control_notice(target: ProviderTarget) -> _SlackControlNotice | None:
    payload = target.request_payload
    text = payload.get("text")
    blocks = _blocks(payload.get("blocks"))
    if not isinstance(text, str) or blocks is None:
        return None
    return _SlackControlNotice(text=text, blocks=tuple(blocks))


def _decode_slack_selector(target: ProviderTarget) -> str | None:
    value = target.request_payload.get("selector_interaction_id")
    return value if isinstance(value, str) and value else None


def _decode_slack_recorded_agent_name(target: ProviderTarget) -> str | None:
    value = target.request_payload.get("recorded_agent_name")
    return value if isinstance(value, str) else None


def _decode_slack_approval(target: ProviderTarget) -> _SlackApproval | None:
    payload = target.request_payload
    url = payload.get("approval_url")
    user = payload.get("participant_provider_user_id")
    label = payload.get("participant_label")
    if not isinstance(url, str) or not url:
        return None
    if not isinstance(user, str) or not user:
        return None
    if not isinstance(label, str) or not label:
        return None
    return _SlackApproval(
        url=url, participant_provider_user_id=user, participant_label=label
    )


def _decode_slack_progress(
    target: ProviderTarget, *, web_url: str | None
) -> _SlackProgress | None:
    payload = target.request_payload
    text = payload.get("text")
    blocks = _blocks(payload.get("blocks"))
    context = _session_navigation_context(target, web_url=web_url)
    if not isinstance(text, str) or blocks is None or context is None:
        return None
    return _SlackProgress(text=text, blocks=tuple(blocks), context=context)


@dataclass(frozen=True)
class _SlackProgressUpdate:
    """Complete validated update payload."""

    content: _SlackProgress
    message_ts: str


@dataclass(frozen=True)
class _SlackProgressDelete:
    """Complete validated deletion payload."""

    message_ts: str


def _decode_slack_progress_update(
    target: ProviderTarget, *, web_url: str | None
) -> _SlackProgressUpdate | None:
    content = _decode_slack_progress(target, web_url=web_url)
    message_ts = _provider_message_ts(
        target.request_payload.get("provider_message_key")
    )
    if content is None or message_ts is None:
        return None
    return _SlackProgressUpdate(content=content, message_ts=message_ts)


def _decode_slack_progress_delete(
    target: ProviderTarget,
) -> _SlackProgressDelete | None:
    message_ts = _provider_message_ts(
        target.request_payload.get("provider_message_key")
    )
    if message_ts is None:
        return None
    return _SlackProgressDelete(message_ts=message_ts)


def _decode_slack_reply(
    target: ProviderTarget, destination: _SlackDestination
) -> _SlackReply | None:
    """Validate consumed reply fields, retaining file-reply block behavior."""
    payload = target.request_payload
    text = payload.get("text")
    broadcast = payload.get("reply_broadcast", False)
    files = _outbound_files(payload.get("files"))
    if (
        not isinstance(text, str)
        or not isinstance(broadcast, bool)
        or broadcast
        and not destination.thread_scope
        or files is None
    ):
        return None
    raw_blocks = payload.get("blocks")
    blocks = None if files else _blocks(raw_blocks)
    if not files and raw_blocks is not None and blocks is None:
        return None
    return _SlackReply(
        destination=destination,
        text=text,
        broadcast=broadcast,
        files=files,
        blocks=None if blocks is None else tuple(blocks),
    )


@dataclass(frozen=True)
class _DiscordSetup:
    """Validated setup claim and display identity."""

    agent_name: str
    claim_id: str
    claim_generation: int
    source_revision: int


def _decode_discord_setup(
    target: ProviderTarget, *, files: tuple[ExternalChannelOutboundFileManifest, ...]
) -> _DiscordSetup | None:
    payload = target.request_payload
    name = target.agent_name
    claim = payload.get("setup_claim_id")
    generation = payload.get("claim_generation")
    revision = payload.get("source_revision")
    if (
        files
        or not isinstance(name, str)
        or not name
        or not isinstance(claim, str)
        or not claim
        or not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation <= 0
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision <= 0
    ):
        return None
    return _DiscordSetup(
        agent_name=name,
        claim_id=claim,
        claim_generation=generation,
        source_revision=revision,
    )


@dataclass(frozen=True)
class _DiscordDestination:
    """Validated provider identity and optional root-message thread target."""

    guild_id: str
    channel_id: str
    thread_parent_channel_id: str | None


def _decode_discord_destination(target: ProviderTarget) -> _DiscordDestination | None:
    """Validate the current target without interpreting provider extensions."""
    payload = target.request_payload
    guild_id = payload.get("guild_id")
    channel_id = payload.get("channel_id")
    scope = payload.get("conversation_scope")
    parent = payload.get("thread_parent_channel_id")
    root = payload.get("thread_root_message_id")
    configuration = target.provider_configuration
    if (
        not isinstance(guild_id, str)
        or not guild_id.isdigit()
        or target.provider_tenant_id != guild_id
        or configuration is None
        or configuration.target_guild_id != guild_id
        or not isinstance(channel_id, str)
        or not channel_id.isdigit()
    ):
        return None
    if scope == "parent_channel":
        if parent is not None or root is not None:
            return None
    elif scope is None or scope == "thread":
        if parent is not None or root is not None:
            if (
                not isinstance(parent, str)
                or not parent.isdigit()
                or not isinstance(root, str)
                or root != channel_id
            ):
                return None
    else:
        return None
    return _DiscordDestination(
        guild_id=guild_id,
        channel_id=channel_id,
        thread_parent_channel_id=parent if isinstance(parent, str) else None,
    )


@dataclass(frozen=True)
class _DiscordReplyButton:
    """Validated button retaining its exact provider-wire numeric values."""

    button_type: int | float
    style: int
    label: str
    destination_key: str
    destination: str

    def to_wire(self) -> dict[str, object]:
        """Lower the validated button to the Discord SDK shape."""
        return {
            "type": self.button_type,
            "style": self.style,
            "label": self.label,
            self.destination_key: self.destination,
        }


@dataclass(frozen=True)
class _DiscordReplyRow:
    """One validated row of Discord buttons."""

    row_type: int | float
    buttons: tuple[_DiscordReplyButton, ...]

    def to_wire(self) -> dict[str, object]:
        """Lower the validated row at the provider boundary."""
        return {
            "type": self.row_type,
            "components": [button.to_wire() for button in self.buttons],
        }


def _decode_discord_reply_rows(value: object) -> tuple[_DiscordReplyRow, ...] | None:
    """Validate and type the supported reply component subset."""
    rows = _discord_components(value)
    if rows is None:
        return None
    result: list[_DiscordReplyRow] = []
    for row in rows:
        row_type = row["type"]
        buttons = row["components"]
        if not isinstance(row_type, int | float) or not isinstance(buttons, list):
            return None
        typed_buttons: list[_DiscordReplyButton] = []
        for button in buttons:
            if not is_external_channel_projection(button):
                return None
            button_type = button.get("type")
            style = button.get("style")
            label = button.get("label")
            key = "url" if style == 5 else "custom_id"
            destination = button.get(key)
            if (
                not isinstance(button_type, int | float)
                or not isinstance(style, int)
                or not isinstance(label, str)
                or not isinstance(destination, str)
            ):
                return None
            typed_buttons.append(
                _DiscordReplyButton(button_type, style, label, key, destination)
            )
        result.append(_DiscordReplyRow(row_type, tuple(typed_buttons)))
    return tuple(result)


@dataclass(frozen=True)
class _DiscordReplyEmbedField:
    """Validated embed field preserving whether inline was present."""

    name: str
    value: str
    inline: bool | None
    inline_present: bool

    def to_wire(self) -> dict[str, object]:
        """Lower the field without collapsing omitted and null values."""
        result: dict[str, object] = {"name": self.name, "value": self.value}
        if self.inline_present:
            result["inline"] = self.inline
        return result


@dataclass(frozen=True)
class _DiscordReplyEmbed:
    """Validated embed and optional-key presence for lossless SDK lowering."""

    color: int
    title: str | None
    description: str | None
    fields: tuple[_DiscordReplyEmbedField, ...] | None
    present: frozenset[str]

    def to_wire(self) -> dict[str, object]:
        """Lower the embed preserving explicit nulls."""
        result: dict[str, object] = {"color": self.color}
        if "title" in self.present:
            result["title"] = self.title
        if "description" in self.present:
            result["description"] = self.description
        if "fields" in self.present:
            result["fields"] = (
                None
                if self.fields is None
                else [field.to_wire() for field in self.fields]
            )
        return result


def _decode_discord_reply_embeds(
    value: object,
) -> tuple[_DiscordReplyEmbed, ...] | None:
    """Validate and type embeds while retaining their original wire shape."""
    embeds = _discord_embeds(value)
    if embeds is None:
        return None
    result: list[_DiscordReplyEmbed] = []
    for embed in embeds:
        color, title, description = (
            embed.get("color"),
            embed.get("title"),
            embed.get("description"),
        )
        raw_fields = embed.get("fields")
        if (
            not isinstance(color, int)
            or title is not None
            and not isinstance(title, str)
            or description is not None
            and not isinstance(description, str)
            or raw_fields is not None
            and not isinstance(raw_fields, list)
        ):
            return None
        fields: list[_DiscordReplyEmbedField] = []
        for field in raw_fields or []:
            if not is_external_channel_projection(field):
                return None
            name, field_value, inline = (
                field.get("name"),
                field.get("value"),
                field.get("inline"),
            )
            if (
                not isinstance(name, str)
                or not isinstance(field_value, str)
                or inline is not None
                and not isinstance(inline, bool)
            ):
                return None
            fields.append(
                _DiscordReplyEmbedField(name, field_value, inline, "inline" in field)
            )
        result.append(
            _DiscordReplyEmbed(
                color,
                title,
                description,
                None if raw_fields is None else tuple(fields),
                frozenset(embed),
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class _DiscordProgressUpdate:
    """Validated progress update content and message identity."""

    text: str
    embeds: tuple[_DiscordReplyEmbed, ...]
    context: _SessionNavigationContext
    message_id: str


@dataclass(frozen=True)
class _DiscordProgressDelete:
    """Validated progress deletion message identity."""

    message_id: str


def _decode_discord_progress_update(
    target: ProviderTarget, *, guild_id: str, web_url: str | None
) -> _DiscordProgressUpdate | None:
    payload = target.request_payload
    text = payload.get("text")
    embeds = _decode_discord_reply_embeds(payload.get("embeds"))
    context = _session_navigation_context(target, web_url=web_url)
    message_id = _discord_provider_message_id(
        payload.get("provider_message_key"), guild_id=guild_id
    )
    if (
        not isinstance(text, str)
        or embeds is None
        or context is None
        or message_id is None
    ):
        return None
    return _DiscordProgressUpdate(
        text=text, embeds=embeds, context=context, message_id=message_id
    )


def _decode_discord_progress_delete(
    target: ProviderTarget, *, guild_id: str
) -> _DiscordProgressDelete | None:
    message_id = _discord_provider_message_id(
        target.request_payload.get("provider_message_key"), guild_id=guild_id
    )
    return None if message_id is None else _DiscordProgressDelete(message_id=message_id)


@dataclass(frozen=True)
class _DiscordReplyPayload:
    """Validated fields consumed by a Discord reply operation."""

    destination: _DiscordDestination
    text: str
    forward_to_parent: bool
    parent_channel_id: str | None
    files: tuple[ExternalChannelOutboundFileManifest, ...]
    components: tuple[_DiscordReplyRow, ...] | None
    embeds: tuple[_DiscordReplyEmbed, ...] | None


def _decode_discord_reply(target: ProviderTarget) -> _DiscordReplyPayload | None:
    """Validate reply destination and content before any provider mutation."""
    payload = target.request_payload
    destination = _decode_discord_destination(target)
    text = payload.get("text")
    forward = payload.get("forward_to_parent", False)
    parent = payload.get("parent_channel_id")
    raw_components = payload.get("components")
    raw_embeds = payload.get("embeds")
    files = _outbound_files(payload.get("files"))
    components = _decode_discord_reply_rows(raw_components)
    embeds = _decode_discord_reply_embeds(raw_embeds)
    if (
        destination is None
        or not isinstance(text, str)
        or not isinstance(forward, bool)
        or forward
        and (not isinstance(parent, str) or not parent.isdigit())
        or raw_components is not None
        and components is None
        or raw_embeds is not None
        and embeds is None
        or files is None
        or files
        and (components is not None or embeds is not None)
    ):
        return None
    return _DiscordReplyPayload(
        destination=destination,
        text=text,
        forward_to_parent=forward,
        parent_channel_id=parent if isinstance(parent, str) else None,
        files=files,
        components=components,
        embeds=embeds,
    )


def _outbound_files(
    value: object,
) -> tuple[ExternalChannelOutboundFileManifest, ...] | None:
    if value is None:
        return ()
    if (
        not isinstance(value, list)
        or not value
        or len(value) > MAX_EXTERNAL_CHANNEL_FILES
    ):
        return None
    try:
        files = tuple(
            ExternalChannelOutboundFileManifest.model_validate(item) for item in value
        )
    except ValidationError:
        return None
    if any(PurePosixPath(file.filename).name != file.filename for file in files):
        return None
    return files


async def _slack_runtime_provider_content(
    *,
    batch: RuntimeToProviderBatch,
    source_index: int,
) -> AsyncIterator[bytes]:
    """Map one trusted Runtime batch stream to Slack's content error boundary."""
    try:
        async for chunk in batch.iter_source_chunks(source_index):
            yield chunk
    except RuntimeToProviderTransferError as error:
        raise SlackOutboundFileContentError from error


async def _slack_exchange_outbound_content(
    *,
    manifest: ExternalChannelOutboundFileManifest,
    exchange_file_service: ExchangeFileService,
    authority: SessionResourceAuthority | None,
) -> AsyncIterator[bytes]:
    """Map one authorized Exchange stream to Slack's content error boundary."""
    try:
        if authority is None:
            raise ExternalChannelFileTransferError(
                "Exchange file source is unavailable."
            )
        async for chunk in iter_external_channel_exchange_file_chunks(
            exchange_file_service=exchange_file_service,
            manifest=manifest,
            authority=authority,
        ):
            yield chunk
    except ExternalChannelFileTransferError as error:
        raise SlackOutboundFileContentError from error


async def _discord_outbound_content(
    *,
    manifest: ExternalChannelOutboundFileManifest,
    file_storage: RangedFileStorage | None,
    agent_id: str | None,
    exchange_file_service: ExchangeFileService,
    authority: SessionResourceAuthority | None,
) -> AsyncIterator[bytes]:
    """Yield one current source once for a Discord multipart request."""
    try:
        match manifest.source:
            case ExternalChannelOutboundFileSource.RUNTIME:
                if file_storage is None or agent_id is None:
                    raise ExternalChannelFileTransferError(
                        "Runtime file source is unavailable."
                    )
                async for chunk in iter_external_channel_outbound_file_chunks(
                    file_storage=file_storage,
                    manifest=manifest,
                    agent_id=agent_id,
                ):
                    yield chunk
            case ExternalChannelOutboundFileSource.EXCHANGE:
                if authority is None:
                    raise ExternalChannelFileTransferError(
                        "Exchange file source is unavailable."
                    )
                async for chunk in iter_external_channel_exchange_file_chunks(
                    exchange_file_service=exchange_file_service,
                    manifest=manifest,
                    authority=authority,
                ):
                    yield chunk
            case _ as unreachable:
                assert_never(unreachable)
    except ExternalChannelFileTransferError as error:
        raise DiscordOutboundFileContentError from error


def _blocks(value: object) -> list[dict[str, object]] | None:
    """Validate one persisted Slack Block Kit list."""
    if not isinstance(value, list) or not all(
        is_external_channel_projection(block) for block in value
    ):
        return None
    return [block for block in value if is_external_channel_projection(block)]


def _discord_components(value: object) -> list[dict[str, object]] | None:
    """Validate one bounded Discord component payload."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 5:
        return None
    rows: list[dict[str, object]] = []
    for row in value:
        if (
            not is_external_channel_projection(row)
            or row.get("type") != 1
            or set(row) != {"type", "components"}
        ):
            return None
        components = row.get("components")
        if not isinstance(components, list) or not components or len(components) > 5:
            return None
        if not all(_discord_button(component) for component in components):
            return None
        rows.append(row)
    return rows


def _discord_button(value: object) -> bool:
    """Permit the generated Button forms without accepting raw provider JSON."""
    if not is_external_channel_projection(value) or value.get("type") != 2:
        return False
    label = value.get("label")
    style = value.get("style")
    if (
        not isinstance(label, str)
        or not label
        or len(label) > 80
        or not isinstance(style, int)
        or style not in {1, 2, 3, 4, 5}
    ):
        return False
    if style == 5:
        url = value.get("url")
        parsed = urlparse(url) if isinstance(url, str) else None
        return (
            set(value) == {"type", "style", "label", "url"}
            and parsed is not None
            and parsed.scheme in {"http", "https"}
            and bool(parsed.netloc)
        )
    custom_id = value.get("custom_id")
    return (
        set(value) == {"type", "style", "label", "custom_id"}
        and isinstance(custom_id, str)
        and bool(custom_id)
        and len(custom_id) <= 100
    )


def _discord_embeds(value: object) -> list[dict[str, object]] | None:
    """Validate the generated bounded Embed subset persisted for delivery."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > 10:
        return None
    embeds: list[dict[str, object]] = []
    for embed in value:
        if not is_external_channel_projection(embed) or set(embed) - {
            "title",
            "description",
            "color",
            "fields",
        }:
            return None
        title = embed.get("title")
        description = embed.get("description")
        color = embed.get("color")
        fields = _discord_embed_fields(embed.get("fields"))
        if (
            (title is not None and not isinstance(title, str))
            or isinstance(title, str)
            and (not title or len(title) > 256)
            or (description is not None and not isinstance(description, str))
            or isinstance(description, str)
            and (not description or len(description) > 4_096)
            or (embed.get("fields") is not None and fields is None)
            or title is None
            and description is None
            and not fields
            or not isinstance(color, int)
            or not 0 <= color <= 0xFFFFFF
            or sum(
                (
                    len(title) if isinstance(title, str) else 0,
                    len(description) if isinstance(description, str) else 0,
                    *(
                        len(field["name"]) + len(field["value"])
                        for field in fields or []
                    ),
                )
            )
            > 6_000
        ):
            return None
        embeds.append(embed)
    return embeds


class _DiscordEmbedField(TypedDict):
    """One validated Discord Embed field."""

    name: str
    value: str
    inline: NotRequired[bool]


def _discord_embed_fields(value: object) -> list[_DiscordEmbedField] | None:
    """Validate the generated bounded Discord Embed field subset."""
    if value is None:
        return []
    if not isinstance(value, list) or not value or len(value) > 25:
        return None
    fields: list[_DiscordEmbedField] = []
    for field in value:
        if not is_external_channel_projection(field) or set(field) not in (
            {"name", "value"},
            {"name", "value", "inline"},
        ):
            return None
        name = field.get("name")
        field_value = field.get("value")
        inline = field.get("inline")
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 256
            or not isinstance(field_value, str)
            or not field_value
            or len(field_value) > 1_024
            or inline is not None
            and not isinstance(inline, bool)
        ):
            return None
        fields.append(
            {
                "name": name,
                "value": field_value,
                **({"inline": inline} if isinstance(inline, bool) else {}),
            }
        )
    return fields
