"""Atomic Channel Action orchestration and one-attempt provider delivery."""

import asyncio
import datetime
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, NotRequired, TypedDict, assert_never, cast
from urllib.parse import urlparse

import httpx
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    ExternalChannelActionMode,
    ExternalChannelAppMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelProvider,
    ExternalChannelWorkStatus,
)
from azents.core.external_channel_file import (
    MAX_EXTERNAL_CHANNEL_FILES,
    ExternalChannelOutboundFileManifest,
    ExternalChannelOutboundFileSource,
)
from azents.core.external_channel_projection import is_external_channel_projection
from azents.core.external_channel_session_presence import (
    ExternalChannelSessionPresenceState,
    build_external_channel_scheduled_task_url,
    build_external_channel_session_url,
)
from azents.core.slack_external_channel_progress import (
    render_slack_binding_settings_on_demand,
    render_slack_session_navigation_actions,
    render_slack_session_presence,
    render_slack_setup_required,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import (
    ChannelActionEffectPlan,
    ChannelActionResult,
    ChannelWorkSnapshot,
    ChannelWorkTask,
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
from azents.services.external_channel.discord_presentation import (
    render_discord_session_navigation_components,
    render_discord_session_presence,
    render_discord_setup_required,
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
from azents.services.external_channel.provider_effect import (
    ProviderEffectOutcome,
    ProviderEffectPlan,
    ProviderMutationOutcome,
    ProviderOperationKey,
    ProviderTarget,
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
from azents.services.scheduled_task.control import (
    render_scheduled_task_discord_controls,
)
from azents.services.session_resource_authority import SessionResourceAuthority

logger = logging.getLogger(__name__)
RuntimeTargetResolver = Callable[[], Awaitable[ServerToRuntimeTarget]]


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

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelWorkRepository,
        Depends(ExternalChannelWorkRepository.create),
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

    async def has_active_binding(self, *, session_id: str, agent_id: str) -> bool:
        """Return whether the tool should be exposed for this root Session."""
        async with self.session_manager() as session:
            return await self.repository.has_active_binding(
                session,
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
        async with self.session_manager() as session:
            return await self.repository.list_active_work(
                session,
                session_id=session_id,
                agent_id=agent_id,
            )

    async def execute(
        self,
        *,
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
        async with self.session_manager() as session:
            transition = await self.repository.commit_direct_action(
                session,
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
            await session.commit()
        reply_delivered = mode is not ExternalChannelActionMode.FINISH or any(
            effect.provider.target.operation is ExternalChannelDeliveryOperation.REPLY
            for effect in transition.effects
        )
        outcomes: list[ProviderEffectOutcome] = []
        for effect in transition.effects:
            operation = effect.provider.target.operation
            if (
                operation is ExternalChannelDeliveryOperation.PROGRESS_DELETE
                and transition.work_status is ExternalChannelWorkStatus.FINISHED
                and not reply_delivered
            ):
                outcomes.append(
                    ProviderEffectOutcome(
                        operation=operation,
                        part=effect.part,
                        status="not_attempted",
                        reason="final_reply_not_delivered",
                        detail=(
                            "Activity Tracker cleanup requires a delivered final reply."
                        ),
                    )
                )
                continue
            outcome = await self.execute_direct_effect(
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
        return ChannelActionResult(
            binding_id=transition.binding_id,
            work_status=transition.work_status,
            state_revision=transition.state_revision,
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
        async with self.session_manager() as session:
            current = await self.repository.revalidate_direct_effect(
                session,
                effect=effect,
            )
        if current is None:
            return ProviderEffectOutcome(
                operation=effect.provider.target.operation,
                part=effect.part,
                status="not_attempted",
                reason="provider_authority_unavailable",
                detail="Current External Channel provider authority is unavailable.",
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
        async with self.session_manager() as session:
            await self.repository.apply_direct_effect_outcome(
                session,
                effect=effect,
                outcome=result,
            )
            await session.commit()
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
    ) -> ProviderMutationOutcome | None:
        """Execute one post-commit provider control without durable work state."""
        async with self.session_manager() as session:
            current = await self.repository.revalidate_direct_control(
                session,
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
        work_id = current.target.request_payload.get("work_id")
        desired_revision = current.target.request_payload.get(
            "desired_progress_revision"
        )
        part = current.target.request_payload.get("part_ordinal", 0)
        if (
            isinstance(work_id, str)
            and isinstance(desired_revision, int)
            and isinstance(part, int)
        ):
            async with self.session_manager() as session:
                await self.repository.apply_direct_effect_outcome(
                    session,
                    effect=ChannelActionEffectPlan(
                        provider=current,
                        part=part,
                        work_cycle_id=work_id,
                        expected_desired_progress_revision=desired_revision,
                    ),
                    outcome=outcome,
                )
                await session.commit()
        elif isinstance(
            current.target.request_payload.get("access_request_id"),
            str,
        ):
            async with self.session_manager() as session:
                await self.repository.apply_access_control_outcome(
                    session,
                    plan=current,
                    outcome=outcome,
                )
                await session.commit()
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
        async with self.session_manager() as session:
            current = await self.repository.revalidate_binding_effect(
                session,
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
        async with self.session_manager() as session:
            current = await self.repository.revalidate_terminal_control(
                session,
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
        work_id = current.target.request_payload.get("work_id")
        desired_revision = current.target.request_payload.get(
            "desired_progress_revision"
        )
        part = current.target.request_payload.get("part_ordinal", 0)
        if (
            isinstance(work_id, str)
            and isinstance(desired_revision, int)
            and isinstance(part, int)
        ):
            async with self.session_manager() as session:
                await self.repository.apply_direct_effect_outcome(
                    session,
                    effect=ChannelActionEffectPlan(
                        provider=current,
                        part=part,
                        work_cycle_id=work_id,
                        expected_desired_progress_revision=desired_revision,
                    ),
                    outcome=outcome,
                )
                await session.commit()
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
        guild_id = payload.get("guild_id")
        channel_id = payload.get("channel_id")
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
            return _discord_invalid_payload()
        files = _outbound_files(payload.get("files"))
        if files is None:
            return _discord_invalid_payload()
        delivery_channel_id = channel_id
        conversation_scope = payload.get("conversation_scope")
        parent_channel_id = payload.get("thread_parent_channel_id")
        root_message_id = payload.get("thread_root_message_id")
        if conversation_scope == "parent_channel":
            if parent_channel_id is not None or root_message_id is not None:
                return _discord_invalid_payload()
        elif conversation_scope in {None, "thread"} and (
            parent_channel_id is not None or root_message_id is not None
        ):
            if (
                not isinstance(parent_channel_id, str)
                or not parent_channel_id.isdigit()
                or not isinstance(root_message_id, str)
                or root_message_id != channel_id
            ):
                return _discord_invalid_payload()
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
                parent_channel_id=parent_channel_id,
                root_message_id=root_message_id,
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
                )
        elif conversation_scope not in {None, "thread"}:
            return _discord_invalid_payload()
        match target.operation:
            case (
                ExternalChannelDeliveryOperation.REPLY
                | ExternalChannelDeliveryOperation.PROGRESS_CREATE
                | ExternalChannelDeliveryOperation.CONTROL_MESSAGE
            ):
                if (
                    target.operation is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
                    and payload.get("control_kind") == "session_presence"
                ):
                    presence = _session_presence_context(
                        target,
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
                        components=control.components,
                        embeds=control.embeds,
                    )
                if (
                    target.operation is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
                    and payload.get("control_kind") == "setup_required"
                ):
                    setup_claim_id = payload.get("setup_claim_id")
                    claim_generation = payload.get("claim_generation")
                    source_revision = payload.get("source_revision")
                    if (
                        files
                        or not isinstance(target.agent_name, str)
                        or not target.agent_name
                        or not isinstance(setup_claim_id, str)
                        or not setup_claim_id
                        or not isinstance(claim_generation, int)
                        or isinstance(claim_generation, bool)
                        or claim_generation <= 0
                        or not isinstance(source_revision, int)
                        or isinstance(source_revision, bool)
                        or source_revision <= 0
                    ):
                        return _discord_invalid_payload()
                    control = render_discord_setup_required(
                        agent_name=target.agent_name,
                        channel_custom_id=build_discord_settings_custom_id(
                            secret=self.config.auth.jwt.secret_key,
                            action="setup_channel",
                            origin_interaction_id=setup_claim_id,
                            setup_claim_id=setup_claim_id,
                            claim_generation=claim_generation,
                            source_revision=source_revision,
                        ),
                        threads_custom_id=build_discord_settings_custom_id(
                            secret=self.config.auth.jwt.secret_key,
                            action="setup_threads",
                            origin_interaction_id=setup_claim_id,
                            setup_claim_id=setup_claim_id,
                            claim_generation=claim_generation,
                            source_revision=source_revision,
                        ),
                    )
                    return await discord_client.create_message(
                        bot_token=bot_token,
                        guild_id=guild_id,
                        channel_id=delivery_channel_id,
                        content=control.text,
                        operation_key=operation_key,
                        components=control.components,
                        embeds=control.embeds,
                    )
                if (
                    target.operation is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
                    and payload.get("control_kind") == "scheduled_task_registration"
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
                        components=render_scheduled_task_discord_controls(
                            edit_url=edit_url,
                            delete_locator=delete_locator,
                        ),
                        embeds=embeds,
                    )
                if (
                    target.operation is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
                    and payload.get("control_kind") == "scheduled_task_deletion"
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
                        embeds=embeds,
                    )
                text = payload.get("text")
                if not isinstance(text, str):
                    return _discord_invalid_payload()
                forward_to_parent = payload.get("forward_to_parent", False)
                forward_parent_channel_id = payload.get("parent_channel_id")
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
                components = _discord_components(payload.get("components"))
                if payload.get("components") is not None and components is None:
                    return _discord_invalid_payload()
                embeds = _discord_embeds(payload.get("embeds"))
                if payload.get("embeds") is not None and embeds is None:
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
                        file_storage is None
                        or agent_id is None
                        or not callable(getattr(file_storage, "read_range", None))
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
                        None
                        if file_storage is None
                        else cast(RangedFileStorage, file_storage)
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
                text = payload.get("text")
                embeds = _discord_embeds(payload.get("embeds"))
                context = _session_navigation_context(
                    target,
                    web_url=self.config.web_url,
                )
                message_id = _discord_provider_message_id(
                    payload.get("provider_message_key"),
                    guild_id=guild_id,
                )
                if (
                    not isinstance(text, str)
                    or embeds is None
                    or context is None
                    or message_id is None
                ):
                    return _discord_invalid_payload()
                components = _discord_tracker_components(
                    target,
                    session_url=context.session_url,
                    secret=self.config.auth.jwt.secret_key,
                )
                if components is None:
                    return _discord_invalid_payload()
                return await discord_client.update_message(
                    bot_token=bot_token,
                    guild_id=guild_id,
                    channel_id=delivery_channel_id,
                    message_id=message_id,
                    content=_discord_agent_content(target, text),
                    components=components,
                    embeds=embeds,
                )
            case ExternalChannelDeliveryOperation.PROGRESS_DELETE:
                message_id = _discord_provider_message_id(
                    payload.get("provider_message_key"),
                    guild_id=guild_id,
                )
                if message_id is None:
                    return _discord_invalid_payload()
                return await discord_client.delete_message(
                    bot_token=bot_token,
                    guild_id=guild_id,
                    channel_id=delivery_channel_id,
                    message_id=message_id,
                )
            case _ as unreachable:
                assert_never(unreachable)

    async def _record_discord_delivery_channel(
        self,
        *,
        resource_id: str,
        delivery_channel_id: str,
        initial_thread_title: str | None,
    ) -> None:
        """Persist a provisioned Discord thread outside the provider mutation."""
        async with self.session_manager() as session:
            await self.repository.record_discord_delivery_channel(
                session,
                resource_id=resource_id,
                delivery_channel_id=delivery_channel_id,
                initial_thread_title=initial_thread_title,
            )
            await session.commit()

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
        payload = target.request_payload
        presentation = resolve_slack_agent_presentation(
            target,
            avatar_cdn_base_url=self.config.avatar_cdn_base_url,
        )
        tenant_id = target.provider_tenant_id
        channel_id = payload.get("channel_id")
        thread_ts = payload.get("thread_ts")
        conversation_scope = payload.get("conversation_scope")
        if (
            not isinstance(tenant_id, str)
            or not tenant_id
            or not isinstance(channel_id, str)
            or (conversation_scope == "parent_channel" and thread_ts is not None)
            or (
                conversation_scope != "parent_channel"
                and not isinstance(thread_ts, str)
            )
        ):
            return SlackControlMessageResult(
                status="failed",
                provider_message_key=None,
                error_kind="provider_target_invalid",
                error_summary="Slack delivery target is incomplete.",
            )
        match target.operation:
            case ExternalChannelDeliveryOperation.REPLY:
                text = payload.get("text")
                reply_broadcast = payload.get("reply_broadcast", False)
                if not isinstance(text, str) or not isinstance(reply_broadcast, bool):
                    return _invalid_payload()
                if reply_broadcast and conversation_scope != "thread":
                    return _invalid_payload()
                files = _outbound_files(payload.get("files"))
                if files is None:
                    return _invalid_payload()
                if files:
                    del file_storage
                    return await self._deliver_slack_files(
                        bot_token=bot_token,
                        tenant_id=tenant_id,
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        markdown_text=prepend_agent_markdown(presentation, text),
                        files=files,
                        operation_key=operation_key,
                        agent_id=agent_id,
                        session_id=session_id,
                        authority=authority,
                        provider_delivery_service=provider_delivery_service,
                        resolve_runtime_target=resolve_runtime_target,
                    )
                return await self.slack_client.post_message(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    markdown_text=prepend_agent_markdown(presentation, text),
                    icon_url=(None if presentation is None else presentation.icon_url),
                    reply_broadcast=reply_broadcast,
                )
            case ExternalChannelDeliveryOperation.PROGRESS_CREATE:
                text = payload.get("text")
                blocks = _blocks(payload.get("blocks"))
                context = _session_navigation_context(
                    target,
                    web_url=self.config.web_url,
                )
                if not isinstance(text, str) or blocks is None or context is None:
                    return _invalid_payload()
                blocks.append(
                    render_slack_session_navigation_actions(context.session_url)
                )
                return await self.slack_client.post_blocks(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    text=prepend_agent_fallback(presentation, text),
                    blocks=prepend_agent_blocks(presentation, blocks),
                    icon_url=(None if presentation is None else presentation.icon_url),
                )
            case ExternalChannelDeliveryOperation.PROGRESS_UPDATE:
                text = payload.get("text")
                blocks = _blocks(payload.get("blocks"))
                context = _session_navigation_context(
                    target,
                    web_url=self.config.web_url,
                )
                message_ts = _provider_message_ts(payload.get("provider_message_key"))
                if (
                    not isinstance(text, str)
                    or blocks is None
                    or context is None
                    or message_ts is None
                ):
                    return _invalid_payload()
                blocks.append(
                    render_slack_session_navigation_actions(context.session_url)
                )
                return await self.slack_client.update_message(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    message_ts=message_ts,
                    text=prepend_agent_fallback(presentation, text),
                    blocks=prepend_agent_blocks(presentation, blocks),
                )
            case ExternalChannelDeliveryOperation.PROGRESS_DELETE:
                message_ts = _provider_message_ts(payload.get("provider_message_key"))
                if message_ts is None:
                    return _invalid_payload()
                return await self.slack_client.delete_message(
                    bot_token=bot_token,
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    message_ts=message_ts,
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
        payload = target.request_payload
        payload_tenant_id = payload.get("tenant_id")
        if payload_tenant_id is not None and payload_tenant_id != tenant_id:
            return _invalid_payload()
        control_kind = payload.get("control_kind")
        if control_kind in {
            "scheduled_task_registration",
            "scheduled_task_deletion",
        }:
            text = payload.get("text")
            blocks = _blocks(payload.get("blocks"))
            if not isinstance(text, str) or blocks is None:
                return _invalid_payload()
            return await self.slack_client.post_blocks(
                bot_token=bot_token,
                tenant_id=tenant_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                text=prepend_agent_fallback(presentation, text),
                blocks=prepend_agent_blocks(presentation, blocks),
                icon_url=(None if presentation is None else presentation.icon_url),
            )
        if control_kind == "agent_selector":
            selector_interaction_id = payload.get("selector_interaction_id")
            if (
                not isinstance(selector_interaction_id, str)
                or not selector_interaction_id
            ):
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
        if control_kind == "binding_settings_on_demand":
            context = _session_navigation_context(
                target,
                web_url=self.config.web_url,
            )
            if (
                context is None
                or target.resource_id is None
                or target.binding_id is None
            ):
                return _invalid_payload()
            control = render_slack_binding_settings_on_demand(
                agent_name=context.agent_name,
                settings_action_id=SLACK_SETTINGS_OPEN_ACTION_ID,
                settings_action_value=build_slack_settings_locator(
                    secret=self.config.auth.jwt.secret_key,
                    connection_id=target.connection_id,
                    provider_parent_channel_id=channel_id,
                    resource_id=target.resource_id,
                    binding_id=target.binding_id,
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
                payload.get("recorded_agent_name")
                if isinstance(payload.get("recorded_agent_name"), str)
                else None
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
        approval_url = payload.get("approval_url")
        participant_provider_user_id = payload.get("participant_provider_user_id")
        participant_label = payload.get("participant_label")
        if (
            not isinstance(approval_url, str)
            or not approval_url
            or not isinstance(participant_provider_user_id, str)
            or not participant_provider_user_id
            or not isinstance(participant_label, str)
            or not participant_label
            or thread_ts is None
        ):
            return _invalid_payload()
        return await self.slack_client.post_approval_control_message(
            bot_token=bot_token,
            tenant_id=tenant_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            approval_url=approval_url,
            participant_label=participant_label,
            participant_provider_user_id=participant_provider_user_id,
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
    web_url: str,
) -> _SessionPresenceContext | None:
    """Resolve one presence control without trusting persisted display content."""
    match target.request_payload.get("presence_state"):
        case "joined":
            state: ExternalChannelSessionPresenceState = "joined"
        case "left":
            state = "left"
        case _:
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
    web_url: str,
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


def _discord_tracker_components(
    target: ProviderTarget,
    *,
    session_url: str,
    secret: str,
) -> list[dict[str, object]] | None:
    """Render current Discord Tracker controls from exact target authority."""
    if target.request_payload.get("tracker_kind") == "scheduled_task":
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
    web_url: str,
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
