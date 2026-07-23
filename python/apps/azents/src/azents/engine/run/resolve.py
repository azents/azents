"""Agent run request resolution logic.

Provides standalone function that loads Agent and Integration from InvokeInput
and builds RunRequest.
"""

import asyncio
import dataclasses
import hashlib
import json
import logging
import time
from collections.abc import Awaitable
from typing import Any, Literal, assert_never

from azcommon.result import Failure, Result, Success
from azcommon.uuid import uuid7
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import (
    AgentModelSelection,
    ModelParameters,
    SelectableModelOption,
    SelectableModelSettings,
)
from azents.core.builtin_tools import (
    BuiltinToolValidationContext,
    validate_builtin_tools,
)
from azents.core.enums import ExchangeFileStatus, LLMProvider
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.llm_catalog import ModelCapabilities, ModelReasoningEffort
from azents.core.llm_mapping import build_credential_kwargs, to_runtime_model
from azents.core.tools import (
    ResolveContext,
    Toolkit,
    ToolkitContext,
    ToolkitExecutionMode,
    ToolkitProvider,
)
from azents.engine.context.window import get_max_input_tokens
from azents.engine.events.model_file_parts import file_output_part_from_model_file
from azents.engine.events.types import FileOutputPart
from azents.engine.events.user_messages import make_run_user_message
from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.io.user_input import RunUserMessage
from azents.engine.run.contracts import RunRequest, ToolkitBinding
from azents.engine.run.types import (
    BuiltinToolSpec,
)
from azents.engine.tools.builtin import (
    BuiltinToolkitProvider,
    MemoryReadToolkit,
    MemoryWriteToolkit,
    RuntimeToolkit,
)
from azents.engine.tools.claude_rules import (
    ClaudeRulesToolkit,
    ClaudeRulesToolkitProvider,
)
from azents.engine.tools.goal import GoalToolkit, GoalToolkitProvider
from azents.engine.tools.runtime_instruction_context import (
    RuntimeInstructionContextStore,
)
from azents.engine.tools.skill import SkillToolkit, SkillToolkitProvider
from azents.engine.tools.todo import TodoToolkit, TodoToolkitProvider
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.toolkit import AgentToolkitRepository, ToolkitRepository
from azents.runtime.types import RuntimeDomainConfig
from azents.services.chatgpt_oauth.data import (
    ProviderRejected as ChatGPTOAuthProviderRejected,
)
from azents.services.chatgpt_oauth.data import (
    ProviderUnavailable as ChatGPTOAuthProviderUnavailable,
)
from azents.services.chatgpt_oauth.runtime import (
    ensure_runtime_tokens as ensure_chatgpt_oauth_runtime_tokens,
)
from azents.services.exchange_file import ExchangeFileService
from azents.services.kimi_oauth.data import (
    ProviderRejected as KimiOAuthProviderRejected,
)
from azents.services.kimi_oauth.data import (
    ProviderUnavailable as KimiOAuthProviderUnavailable,
)
from azents.services.kimi_oauth.runtime import (
    ensure_runtime_tokens as ensure_kimi_oauth_runtime_tokens,
)
from azents.services.model_file import (
    ModelFileInvalidImage,
    ModelFileOversized,
    ModelFileService,
    model_file_size_limit_message,
)
from azents.services.xai_oauth.data import (
    ProviderEntitlementDenied as XaiOAuthProviderEntitlementDenied,
)
from azents.services.xai_oauth.data import (
    ProviderRejected as XaiOAuthProviderRejected,
)
from azents.services.xai_oauth.data import (
    ProviderUnavailable as XaiOAuthProviderUnavailable,
)
from azents.services.xai_oauth.runtime import (
    ensure_runtime_tokens as ensure_xai_oauth_runtime_tokens,
)

from .input import (
    AgentDisabled,
    AgentNotFound,
    IntegrationDisabled,
    IntegrationNotFound,
    InvalidModelParameters,
    InvokeInput,
)

logger = logging.getLogger(__name__)

_SLOW_TOOLKIT_RESOLVE_SECONDS = 1.0
_ROOT_EXECUTION_MODES = frozenset({ToolkitExecutionMode.ROOT})
_ROOT_AND_SUBAGENT_EXECUTION_MODES = frozenset(
    {ToolkitExecutionMode.ROOT, ToolkitExecutionMode.SUBAGENT}
)


def _allows_execution_mode(
    allowed_modes: frozenset[ToolkitExecutionMode],
    execution_mode: ToolkitExecutionMode,
) -> bool:
    """Return whether a Toolkit candidate should bind in this execution mode."""
    return execution_mode in allowed_modes


def _toolkit_resolve_log_extra(
    *,
    agent_id: str,
    context: ToolkitContext,
    source: str,
    slug: str,
    provider: ToolkitProvider[Any],
    toolkit_id: str | None = None,
    toolkit_type: str | None = None,
    toolkit_name: str | None = None,
    duration_seconds: float | None = None,
) -> dict[str, object]:
    """Build common structured fields for Toolkit resolve boundary log."""
    extra: dict[str, object] = {
        "agent_id": agent_id,
        "session_id": context.session_id,
        "workspace_id": context.workspace_id,
        "user_id": context.user_id,
        "source": source,
        "toolkit_slug": slug,
        "toolkit_type": toolkit_type,
        "toolkit_id": toolkit_id,
        "toolkit_name": toolkit_name,
        "provider_slug": provider.slug,
        "provider_name": provider.name,
    }
    if duration_seconds is not None:
        extra["duration_seconds"] = round(duration_seconds, 3)
    return extra


async def _resolve_toolkit_with_logging(
    *,
    agent_id: str,
    context: ToolkitContext,
    source: str,
    slug: str,
    provider: ToolkitProvider[Any],
    resolve: Awaitable[Toolkit[Any]],
    toolkit_id: str | None = None,
    toolkit_type: str | None = None,
    toolkit_name: str | None = None,
) -> Toolkit[Any]:
    """Record Toolkit resolve failures and slow boundaries."""
    log_extra = _toolkit_resolve_log_extra(
        agent_id=agent_id,
        context=context,
        source=source,
        slug=slug,
        provider=provider,
        toolkit_id=toolkit_id,
        toolkit_type=toolkit_type,
        toolkit_name=toolkit_name,
    )
    started_at = time.monotonic()
    resolved = await resolve
    duration_seconds = time.monotonic() - started_at
    if duration_seconds > _SLOW_TOOLKIT_RESOLVE_SECONDS:
        logger.warning(
            "Toolkit resolve slow",
            extra={
                **log_extra,
                "duration_seconds": round(duration_seconds, 3),
                "threshold_seconds": _SLOW_TOOLKIT_RESOLVE_SECONDS,
            },
        )
    return resolved


@dataclasses.dataclass(frozen=True)
class _SelectionProviderModel:
    """Selected model view used by runtime built-in tool validation."""

    model_identifier: str
    capabilities: ModelCapabilities


@dataclasses.dataclass(frozen=True)
class ResolvedInvokeInputProfile:
    """Run request plus the exact selected profile snapshot for activation."""

    run_request: RunRequest
    model_selection: AgentModelSelection
    model_settings: SelectableModelSettings
    reasoning_effort: ModelReasoningEffort | None


@dataclasses.dataclass(frozen=True)
class _ResolvedInvokeInputModelSource:
    """Run request and main selection resolved from one Agent snapshot."""

    run_request: RunRequest
    model_selection: AgentModelSelection
    model_settings: SelectableModelSettings


@dataclasses.dataclass(frozen=True)
class ModelTargetNotFound:
    """Requested Agent-owned model target label no longer exists."""

    model_target_label: str


@dataclasses.dataclass(frozen=True)
class ReasoningEffortUnsupported:
    """Requested effort is unsupported by the selected model target."""

    model_target_label: str
    reasoning_effort: ModelReasoningEffort


ResolveError = (
    AgentNotFound
    | AgentDisabled
    | IntegrationNotFound
    | IntegrationDisabled
    | InvalidModelParameters
    | ModelTargetNotFound
    | ReasoningEffortUnsupported
)
RuntimeTokenRefreshError = (
    ChatGPTOAuthProviderRejected
    | ChatGPTOAuthProviderUnavailable
    | XaiOAuthProviderRejected
    | XaiOAuthProviderEntitlementDenied
    | XaiOAuthProviderUnavailable
    | KimiOAuthProviderRejected
    | KimiOAuthProviderUnavailable
)


def _find_model_option(
    options: list[SelectableModelOption],
    label: str,
) -> SelectableModelOption | None:
    """Return one Agent-owned selectable option by label."""
    return next((option for option in options if option.label == label), None)


async def _ensure_provider_runtime_tokens(
    *,
    integration: LLMProviderIntegrationWithSecrets,
    integration_repository: LLMProviderIntegrationRepository,
    session_manager: SessionManager[AsyncSession],
) -> Result[LLMProviderIntegrationWithSecrets, RuntimeTokenRefreshError]:
    """Refresh provider OAuth credentials before Runtime execution."""
    if integration.provider == LLMProvider.XAI_OAUTH:
        result = await ensure_xai_oauth_runtime_tokens(
            integration=integration,
            integration_repository=integration_repository,
            session_manager=session_manager,
        )
    elif integration.provider == LLMProvider.KIMI_OAUTH:
        result = await ensure_kimi_oauth_runtime_tokens(
            integration=integration,
            integration_repository=integration_repository,
            session_manager=session_manager,
        )
    else:
        result = await ensure_chatgpt_oauth_runtime_tokens(
            integration=integration,
            integration_repository=integration_repository,
            session_manager=session_manager,
        )
    match result:
        case Success(value):
            return Success(value)
        case Failure(error):
            return Failure(error)
        case _:
            assert_never(result)


def _resolve_reasoning_effort(
    selection: AgentModelSelection,
    params: ModelParameters | None,
) -> str | None:
    """Return reasoning effort based on model selection capability contract."""
    if params is None or params.reasoning_effort is None:
        return None
    reasoning = selection.normalized_capabilities.reasoning
    if not reasoning.supported:
        return None
    if params.reasoning_effort not in reasoning.effort_levels:
        return None
    return params.reasoning_effort


def _effective_max_output_tokens(
    selection: AgentModelSelection,
    settings: SelectableModelSettings,
) -> int | None:
    """Clamp an explicit output cap to the selected model capability."""
    requested = settings.max_output_tokens
    if requested is None:
        return None
    supported = selection.normalized_capabilities.context_window.max_output_tokens
    if supported is None:
        return requested
    return min(requested, supported)


def _validate_model_settings(
    *,
    agent_id: str,
    selection: AgentModelSelection,
    settings: SelectableModelSettings,
) -> Result[SelectableModelSettings, InvalidModelParameters]:
    """Defensively validate a selected settings snapshot before runtime."""
    errors: list[str] = []
    names = [tool.name for tool in settings.builtin_tools]
    if len(names) != len(set(names)):
        errors.append("Built-in tool names must be unique.")
    validation_errors = validate_builtin_tools(
        settings.builtin_tools,
        BuiltinToolValidationContext(
            provider_model=_SelectionProviderModel(
                model_identifier=selection.model_identifier,
                capabilities=selection.normalized_capabilities,
            )
        ),
    )
    for tool_errors in validation_errors.values():
        errors.extend(tool_errors)
    if errors:
        return Failure(InvalidModelParameters(agent_id=agent_id, errors=errors))
    return Success(settings)


def _validate_model_parameters(
    *,
    agent_id: str,
    params: ModelParameters | None,
) -> Result[ModelParameters | None, InvalidModelParameters]:
    """Validate Agent model parameters before runtime."""
    if params is None:
        return Success(None)
    try:
        return Success(ModelParameters.model_validate(params.model_dump(mode="json")))
    except ValidationError as e:
        return Failure(
            InvalidModelParameters(
                agent_id=agent_id,
                errors=[error["msg"] for error in e.errors()],
            )
        )


async def resolve_invoke_input(
    invoke_input: InvokeInput,
    *,
    agent_repository: AgentRepository,
    integration_repository: LLMProviderIntegrationRepository,
    session_manager: SessionManager[AsyncSession],
    exchange_file_service: ExchangeFileService,
    model_file_service: ModelFileService,
) -> Result[RunRequest, ResolveError]:
    """Load Agent/Integration and build RunRequest."""
    resolved = await resolve_invoke_input_with_model_source(
        invoke_input,
        model_source_agent_id=invoke_input.agent_id,
        requested_profile=None,
        resolved_model_selection=None,
        resolved_model_settings=None,
        agent_repository=agent_repository,
        integration_repository=integration_repository,
        session_manager=session_manager,
        exchange_file_service=exchange_file_service,
        model_file_service=model_file_service,
    )
    match resolved:
        case Success(value):
            return Success(value.run_request)
        case Failure(error):
            return Failure(error)
        case _:
            assert_never(resolved)


async def resolve_invoke_input_with_profile(
    invoke_input: InvokeInput,
    *,
    requested_profile: RequestedInferenceProfile,
    agent_repository: AgentRepository,
    integration_repository: LLMProviderIntegrationRepository,
    session_manager: SessionManager[AsyncSession],
    exchange_file_service: ExchangeFileService,
    model_file_service: ModelFileService,
) -> Result[ResolvedInvokeInputProfile, ResolveError]:
    """Build a run request from one explicit Agent-owned inference profile."""
    resolved = await resolve_invoke_input_with_model_source(
        invoke_input,
        model_source_agent_id=invoke_input.agent_id,
        requested_profile=requested_profile,
        resolved_model_selection=None,
        resolved_model_settings=None,
        agent_repository=agent_repository,
        integration_repository=integration_repository,
        session_manager=session_manager,
        exchange_file_service=exchange_file_service,
        model_file_service=model_file_service,
    )
    match resolved:
        case Success(value):
            return Success(
                ResolvedInvokeInputProfile(
                    run_request=value.run_request,
                    model_selection=value.model_selection,
                    model_settings=value.model_settings,
                    reasoning_effort=requested_profile.reasoning_effort,
                )
            )
        case Failure(error):
            return Failure(error)
        case _:
            assert_never(resolved)


async def resolve_invoke_input_with_resolved_profile(
    invoke_input: InvokeInput,
    *,
    resolved_model_selection: AgentModelSelection,
    resolved_model_settings: SelectableModelSettings,
    resolved_reasoning_effort: ModelReasoningEffort | None,
    agent_repository: AgentRepository,
    integration_repository: LLMProviderIntegrationRepository,
    session_manager: SessionManager[AsyncSession],
    exchange_file_service: ExchangeFileService,
    model_file_service: ModelFileService,
) -> Result[RunRequest, ResolveError]:
    """Rebuild a run request from an already activated model snapshot."""
    resolved = await resolve_invoke_input_with_model_source(
        invoke_input,
        model_source_agent_id=invoke_input.agent_id,
        requested_profile=None,
        resolved_model_selection=resolved_model_selection,
        resolved_model_settings=resolved_model_settings,
        agent_repository=agent_repository,
        integration_repository=integration_repository,
        session_manager=session_manager,
        exchange_file_service=exchange_file_service,
        model_file_service=model_file_service,
    )
    match resolved:
        case Success(value):
            return Success(
                dataclasses.replace(
                    value.run_request,
                    reasoning_effort=resolved_reasoning_effort,
                )
            )
        case Failure(error):
            return Failure(error)
        case _:
            assert_never(resolved)


async def resolve_invoke_input_with_model_source(
    invoke_input: InvokeInput,
    *,
    model_source_agent_id: str,
    requested_profile: RequestedInferenceProfile | None,
    resolved_model_selection: AgentModelSelection | None,
    resolved_model_settings: SelectableModelSettings | None,
    agent_repository: AgentRepository,
    integration_repository: LLMProviderIntegrationRepository,
    session_manager: SessionManager[AsyncSession],
    exchange_file_service: ExchangeFileService,
    model_file_service: ModelFileService,
) -> Result[_ResolvedInvokeInputModelSource, ResolveError]:
    """Resolve a run request and main selection from one Agent snapshot."""
    async with session_manager() as session:
        agent = await agent_repository.get_by_id(session, invoke_input.agent_id)
        if agent is None:
            return Failure(AgentNotFound(agent_id=invoke_input.agent_id))
        if not agent.enabled:
            return Failure(AgentDisabled(agent_id=invoke_input.agent_id))

        if model_source_agent_id == invoke_input.agent_id:
            model_agent = agent
        else:
            model_agent = await agent_repository.get_by_id(
                session,
                model_source_agent_id,
            )
            if model_agent is None:
                return Failure(AgentNotFound(agent_id=model_source_agent_id))

        main_option = _find_model_option(
            model_agent.selectable_model_options,
            model_agent.main_model_label,
        )
        if main_option is None:
            return Failure(
                ModelTargetNotFound(model_target_label=model_agent.main_model_label)
            )
        main_selection = main_option.model_selection
        main_settings = main_option.settings
        if resolved_model_selection is not None:
            if resolved_model_settings is None:
                raise ValueError("Resolved model settings are required")
            main_selection = resolved_model_selection
            main_settings = resolved_model_settings
        elif requested_profile is not None:
            selected_option = _find_model_option(
                model_agent.selectable_model_options,
                requested_profile.model_target_label,
            )
            if selected_option is None:
                return Failure(
                    ModelTargetNotFound(
                        model_target_label=requested_profile.model_target_label
                    )
                )
            main_selection = selected_option.model_selection
            main_settings = selected_option.settings
            requested_effort = requested_profile.reasoning_effort
            if requested_effort is not None:
                reasoning = main_selection.normalized_capabilities.reasoning
                if (
                    not reasoning.supported
                    or requested_effort not in reasoning.effort_levels
                ):
                    return Failure(
                        ReasoningEffortUnsupported(
                            model_target_label=requested_profile.model_target_label,
                            reasoning_effort=requested_effort,
                        )
                    )
        lightweight_option = _find_model_option(
            model_agent.selectable_model_options,
            model_agent.lightweight_model_label,
        )
        if lightweight_option is None:
            return Failure(
                ModelTargetNotFound(
                    model_target_label=model_agent.lightweight_model_label
                )
            )
        lightweight_selection = lightweight_option.model_selection

        integration = await integration_repository.get_by_id_with_secrets(
            session,
            main_selection.llm_provider_integration_id,
        )
        if integration is None:
            return Failure(
                IntegrationNotFound(
                    integration_id=main_selection.llm_provider_integration_id,
                )
            )
        if not integration.enabled:
            return Failure(
                IntegrationDisabled(
                    integration_id=main_selection.llm_provider_integration_id,
                )
            )

        loaded_lightweight_integration = integration
        if lightweight_selection.llm_provider_integration_id != integration.id:
            loaded_lightweight_integration = (
                await integration_repository.get_by_id_with_secrets(
                    session,
                    lightweight_selection.llm_provider_integration_id,
                )
            )
            if loaded_lightweight_integration is None:
                return Failure(
                    IntegrationNotFound(
                        integration_id=lightweight_selection.llm_provider_integration_id,
                    )
                )
            if not loaded_lightweight_integration.enabled:
                return Failure(
                    IntegrationDisabled(
                        integration_id=lightweight_selection.llm_provider_integration_id,
                    )
                )

    refreshed_integration = await _ensure_provider_runtime_tokens(
        integration=integration,
        integration_repository=integration_repository,
        session_manager=session_manager,
    )
    match refreshed_integration:
        case Success(value):
            integration = value
        case Failure():
            return Failure(
                IntegrationDisabled(
                    integration_id=main_selection.llm_provider_integration_id,
                )
            )

    lightweight_integration = integration
    if loaded_lightweight_integration.id != integration.id:
        refreshed_lightweight_integration = await _ensure_provider_runtime_tokens(
            integration=loaded_lightweight_integration,
            integration_repository=integration_repository,
            session_manager=session_manager,
        )
        match refreshed_lightweight_integration:
            case Success(value):
                lightweight_integration = value
            case Failure():
                return Failure(
                    IntegrationDisabled(
                        integration_id=(
                            lightweight_selection.llm_provider_integration_id
                        ),
                    )
                )

    model = to_runtime_model(
        main_selection.provider,
        main_selection.model_identifier,
    )
    credential_kwargs = build_credential_kwargs(integration)
    params_result = _validate_model_parameters(
        agent_id=invoke_input.agent_id,
        params=agent.model_parameters,
    )
    match params_result:
        case Success(value):
            params = value
        case Failure(error):
            return Failure(error)
        case _:
            assert_never(params_result)

    settings_result = _validate_model_settings(
        agent_id=invoke_input.agent_id,
        selection=main_selection,
        settings=main_settings,
    )
    match settings_result:
        case Success():
            pass
        case Failure(error):
            return Failure(error)
        case _:
            assert_never(settings_result)

    user_messages: list[RunUserMessage] = []
    for msg in invoke_input.messages:
        msg_attachments: list[RuntimeAttachment] = []
        msg_file_parts: list[FileOutputPart] = list(msg.file_parts)
        if msg.attachments and invoke_input.user_id is not None:
            materialized = await materialize_user_input_exchange_file_attachments(
                msg.attachments,
                agent_id=invoke_input.agent_id,
                session_id=invoke_input.session_id,
                exchange_file_service=exchange_file_service,
                model_file_service=(None if msg_file_parts else model_file_service),
                user_id=invoke_input.user_id,
            )
            msg_attachments.extend(materialized.attachments)
            if not msg_file_parts:
                msg_file_parts.extend(materialized.file_parts)

        user_messages.append(
            make_run_user_message(
                content=msg.text,
                metadata=msg.metadata,
                attachments=msg_attachments,
                file_parts=msg_file_parts,
                external_id=uuid7().hex,
                attachment_source="user_upload",
                requested_inference_profile=requested_profile,
            )
        )

    reasoning_effort = (
        requested_profile.reasoning_effort
        if requested_profile is not None
        else _resolve_reasoning_effort(main_selection, params)
    )
    max_input = get_max_input_tokens(
        main_selection.normalized_capabilities.context_window.max_input_tokens,
        model,
    )

    compaction_model = to_runtime_model(
        lightweight_selection.provider,
        lightweight_selection.model_identifier,
    )
    compaction_provider = lightweight_selection.provider
    compaction_credential_kwargs = build_credential_kwargs(lightweight_integration)
    compaction_max_input_tokens = get_max_input_tokens(
        lightweight_selection.normalized_capabilities.context_window.max_input_tokens,
        compaction_model,
    )
    if lightweight_option.settings.context_window_tokens is not None:
        compaction_max_input_tokens = min(
            compaction_max_input_tokens,
            lightweight_option.settings.context_window_tokens,
        )

    model_developer = main_selection.model_developer
    builtin_tools = [
        BuiltinToolSpec(name=tool.name, config=tool.config)
        for tool in main_settings.builtin_tools
    ]

    return Success(
        _ResolvedInvokeInputModelSource(
            run_request=RunRequest(
                session_id=invoke_input.session_id,
                user_messages=user_messages,
                agent_prompt=agent.system_prompt,
                toolkits=[],
                provider=main_selection.provider,
                model=model,
                model_capabilities=main_selection.normalized_capabilities,
                model_developer=model_developer,
                credential_kwargs=credential_kwargs,
                workspace_id=agent.workspace_id,
                agent_id=invoke_input.agent_id,
                tool_search_enabled=agent.tool_search_enabled,
                auto_compaction_threshold_tokens=None,
                inference_state=None,
                compaction_provider_integration_id=(
                    lightweight_selection.llm_provider_integration_id
                ),
                temperature=params.temperature if params else None,
                max_output_tokens=_effective_max_output_tokens(
                    main_selection,
                    main_settings,
                ),
                top_p=params.top_p if params else None,
                stop=params.stop_sequences if params else None,
                reasoning_effort=reasoning_effort,
                builtin_tools=builtin_tools,
                max_input_tokens=max_input,
                context_window_tokens=main_settings.context_window_tokens,
                max_turns=agent.max_turns,
                compaction_model=compaction_model,
                compaction_provider=compaction_provider,
                compaction_credential_kwargs=compaction_credential_kwargs,
                compaction_max_input_tokens=compaction_max_input_tokens,
            ),
            model_selection=main_selection,
            model_settings=main_settings,
        )
    )


@dataclasses.dataclass(frozen=True)
class MaterializedUserInputAttachments:
    """Attachment/FilePart result created at user input boundary."""

    attachments: list[RuntimeAttachment]
    file_parts: list[FileOutputPart]


@dataclasses.dataclass(frozen=True)
class _MaterializedUserInputAttachment:
    """One attachment and its optional rich model input part."""

    attachment: RuntimeAttachment
    file_part: FileOutputPart | None


async def materialize_user_input_exchange_file_attachments(
    attachment_uris: list[str],
    *,
    agent_id: str,
    session_id: str,
    exchange_file_service: ExchangeFileService,
    model_file_service: ModelFileService | None,
    user_id: str,
) -> MaterializedUserInputAttachments:
    """Convert Exchange attachment to FilePart only at user input creation boundary.

    Unlike general attachment metadata resolve, this function resolves URI inside
    current agent namespace and creates FilePart backing ModelFile for model rich
    input of user input.
    """
    attachments: list[RuntimeAttachment] = []
    file_parts: list[FileOutputPart] = []

    try:
        for uri in attachment_uris:
            materialized = await _materialize_user_input_exchange_file_attachment(
                uri=uri,
                agent_id=agent_id,
                session_id=session_id,
                exchange_file_service=exchange_file_service,
                model_file_service=model_file_service,
                user_id=user_id,
            )
            if materialized is None:
                continue
            attachments.append(materialized.attachment)
            if materialized.file_part is not None:
                file_parts.append(materialized.file_part)
    except asyncio.CancelledError:
        await _discard_partial_user_input_model_files(
            model_file_service=model_file_service,
            file_parts=file_parts,
            reason="attachment materialization cancellation",
        )
        raise
    except Exception:
        await _discard_partial_user_input_model_files(
            model_file_service=model_file_service,
            file_parts=file_parts,
            reason="attachment materialization failure",
        )
        raise

    return MaterializedUserInputAttachments(
        attachments=attachments,
        file_parts=file_parts,
    )


async def _materialize_user_input_exchange_file_attachment(
    *,
    uri: str,
    agent_id: str,
    session_id: str,
    exchange_file_service: ExchangeFileService,
    model_file_service: ModelFileService | None,
    user_id: str,
) -> _MaterializedUserInputAttachment | None:
    """Materialize one claimed Exchange attachment for user input."""
    metadata_result = await exchange_file_service.resolve_attachment_metadata_for_agent(
        uri=uri,
        agent_id=agent_id,
        session_id=session_id,
        user_id=user_id,
    )
    if isinstance(metadata_result, Failure):
        logger.warning(
            "Failed to resolve exchange attachment in agent namespace",
            extra={"uri": uri, "session_id": session_id, "agent_id": agent_id},
        )
        return None

    file = metadata_result.value
    availability: Literal["available", "expired", "unavailable"] = (
        "expired" if file.status == ExchangeFileStatus.EXPIRED else "available"
    )
    attachment = RuntimeAttachment(
        attachment_id=file.id,
        uri=file.uri,
        media_type=file.media_type,
        size=file.size_bytes,
        name=file.filename,
        text_preview=_attachment_text_preview(file, availability=availability),
        preview_thumbnail_uri=file.preview_thumbnail_uri,
        availability=availability,
        preview_title=file.preview_title,
        preview_thumbnail_media_type=file.preview_thumbnail_media_type,
        preview_thumbnail_width=file.preview_thumbnail_width,
        preview_thumbnail_height=file.preview_thumbnail_height,
        preview_generated_at=file.preview_generated_at,
    )
    if availability != "available" or model_file_service is None:
        return _MaterializedUserInputAttachment(
            attachment=attachment,
            file_part=None,
        )

    download_result = await exchange_file_service.resolve_attachment_for_agent(
        uri=uri,
        agent_id=agent_id,
        session_id=session_id,
        user_id=user_id,
    )
    if isinstance(download_result, Failure):
        logger.warning(
            "Failed to download exchange attachment for user input FilePart",
            extra={
                "uri": uri,
                "session_id": session_id,
                "agent_id": agent_id,
                "error": download_result.error.__class__.__name__,
            },
        )
        return _MaterializedUserInputAttachment(
            attachment=attachment,
            file_part=None,
        )

    download = download_result.value
    model_file_result = await model_file_service.create_for_agent_pending_input(
        agent_id=agent_id,
        session_id=session_id,
        user_id=user_id,
        filename=download.file.filename,
        media_type=download.file.media_type,
        body=download.body,
        metadata={
            "source_kind": "user_upload",
            "source_attachment_id": download.file.id,
            "source_attachment_uri": download.file.uri,
        },
    )
    if isinstance(model_file_result, Failure):
        if isinstance(model_file_result.error, ModelFileOversized):
            reason = model_file_size_limit_message(model_file_result.error)
        elif isinstance(model_file_result.error, ModelFileInvalidImage):
            reason = "Uploaded image could not be normalized for model input."
        else:
            reason = model_file_result.error.__class__.__name__
        logger.warning(
            "Failed to create ModelFile for user input attachment",
            extra={
                "uri": uri,
                "session_id": session_id,
                "agent_id": agent_id,
                "reason": reason,
            },
        )
        return _MaterializedUserInputAttachment(
            attachment=attachment,
            file_part=None,
        )

    return _MaterializedUserInputAttachment(
        attachment=attachment,
        file_part=file_output_part_from_model_file(
            model_file_result.value,
            metadata={
                "source_kind": "user_upload",
                "source_attachment_id": download.file.id,
                "source_attachment_uri": download.file.uri,
            },
        ),
    )


async def _discard_partial_user_input_model_files(
    *,
    model_file_service: ModelFileService | None,
    file_parts: list[FileOutputPart],
    reason: str,
) -> None:
    """Discard ModelFiles created before attachment preparation was interrupted."""
    if model_file_service is None or not file_parts:
        return
    model_file_ids = [part.model_file_id for part in file_parts]
    try:
        await asyncio.shield(
            model_file_service.discard_pending_input(
                model_file_ids=model_file_ids,
            )
        )
    except Exception:
        logger.exception(
            "Failed to discard partially materialized user input ModelFiles",
            extra={"model_file_ids": model_file_ids, "reason": reason},
        )


def _attachment_text_preview(
    file: ExchangeFile,
    *,
    availability: Literal["available", "expired", "unavailable"],
) -> str | None:
    """Create metadata-only context preview for attachment."""
    if file.preview_summary is not None:
        return file.preview_summary
    if file.media_type.startswith("image/"):
        return None
    return (
        f"File {availability} as {file.uri}. "
        "Use the import_file tool in a runtime-enabled agent to read or edit "
        f"this file. Filename: {file.filename}. "
        f"Media type: {file.media_type}. Size: {file.size_bytes} bytes."
    )


async def process_exchange_file_attachments(
    attachment_uris: list[str],
    *,
    session_id: str,
    exchange_file_service: ExchangeFileService,
    user_id: str,
) -> list[RuntimeAttachment]:
    """Process Exchange URI attachments.

    Leave Exchange files as metadata-only attachments.

    :param attachment_uris: Attachment URI list
    :param session_id: Session ID
    :param exchange_file_service: Exchange file service
    :param user_id: User ID
    :return: Attachment list
    """
    attachments: list[RuntimeAttachment] = []

    for uri in attachment_uris:
        result = await exchange_file_service.resolve_attachment_metadata(
            uri=uri,
            user_id=user_id,
        )
        if isinstance(result, Failure):
            logger.warning(
                "Failed to resolve exchange attachment",
                extra={"uri": uri, "session_id": session_id},
            )
            continue

        file = result.value
        availability: Literal["available", "expired", "unavailable"] = (
            "expired" if file.status == ExchangeFileStatus.EXPIRED else "available"
        )
        text_preview = _attachment_text_preview(file, availability=availability)

        attachments.append(
            RuntimeAttachment(
                attachment_id=file.id,
                uri=file.uri,
                media_type=file.media_type,
                size=file.size_bytes,
                name=file.filename,
                text_preview=text_preview,
                preview_thumbnail_uri=file.preview_thumbnail_uri,
                availability=availability,
                preview_title=file.preview_title,
                preview_thumbnail_media_type=file.preview_thumbnail_media_type,
                preview_thumbnail_width=file.preview_thumbnail_width,
                preview_thumbnail_height=file.preview_thumbnail_height,
                preview_generated_at=file.preview_generated_at,
            )
        )

    return attachments


# ---------------------------------------------------------------------------
# General Toolkit resolution
# ---------------------------------------------------------------------------


async def resolve_agent_tools(
    agent_id: str,
    context: ToolkitContext,
    *,
    execution_mode: ToolkitExecutionMode,
    toolkit_registry: dict[str, ToolkitProvider[Any]],
    agent_toolkit_repository: AgentToolkitRepository,
    toolkit_repository: ToolkitRepository,
    session_manager: SessionManager[AsyncSession],
    web_url: str,
    oauth_secret_key: str,
    mcp_proxy_url: str | None,
    runtime_domain_config: RuntimeDomainConfig,
    workspace_handle: str = "",
    builtin_toolkit_provider: BuiltinToolkitProvider | None = None,
    claude_rules_toolkit_provider: ClaudeRulesToolkitProvider | None = None,
    todo_toolkit_provider: TodoToolkitProvider | None = None,
    goal_toolkit_provider: GoalToolkitProvider | None = None,
    skill_toolkit_provider: SkillToolkitProvider | None = None,
    subagent_toolkit_provider: ToolkitProvider[Any] | None = None,
    memory_enabled: bool = True,
    runtime_tools_enabled: bool = True,
) -> list[ToolkitBinding]:
    """Resolve every Toolkit connected to Agent and return instance list.

    :param agent_id: Agent ID
    :param context: Toolkit runtime context
    :param execution_mode: Toolkit resolution mode for root or future subagent runs
    :param toolkit_registry: toolkit_type to ToolkitProvider instance mapping
    :param agent_toolkit_repository: AgentToolkit repository
    :param toolkit_repository: Toolkit repository
    :param session_manager: DB session factory used only for Toolkit snapshot reads
    :param web_url: Frontend URL for OAuth redirect_uri construction
    :param oauth_secret_key: OAuth HMAC signing key
    :param runtime_domain_config: Runtime domain allow/deny policy. Parent
        agent uses workspace/agent settings;
        runtime toolkits receive this in the constructor and keep it immutable.
    :param workspace_handle: Workspace handle for settings page URL construction
    :param builtin_toolkit_provider: Builtin toolkit provider (None disables builtin)
    :param claude_rules_toolkit_provider: Claude rules provider (None disables it)
    :param todo_toolkit_provider: Todo toolkit provider (None disables todo)
    :param goal_toolkit_provider: Goal toolkit provider (None disables goal)
    :param skill_toolkit_provider: Skill toolkit provider (None disables Skill)
    :param runtime_tools_enabled: Expose builtin shell/file tools only to
        Agents connected to Runtime settings.
        Memory tools can be exposed without runtime.
    :return: List of (Toolkit, slug) tuples
    """
    async with session_manager() as session:
        agent_toolkits = await agent_toolkit_repository.list_by_agent(session, agent_id)
        registered_toolkits = []
        for agent_toolkit in agent_toolkits:
            toolkit = await toolkit_repository.get_by_id(
                session, agent_toolkit.toolkit_id
            )
            registered_toolkits.append((agent_toolkit, toolkit))
    # (provider, resolved, config, slug, prompt, use_prefix, toolkit_type, modes)
    # toolkit_type is populated only for DB-registered toolkits; auto-binding is None
    registered_toolkit_config_ids: dict[int, str] = {}
    registered_toolkit_revisions: dict[int, str] = {}
    pending: list[
        tuple[
            ToolkitProvider[Any],
            Toolkit[Any],
            Any,
            str,
            str | None,
            bool,
            str | None,
            frozenset[ToolkitExecutionMode],
        ]
    ] = []

    # DB-registered toolkit (registry-based, prefix applied)
    for at, toolkit in registered_toolkits:
        provider = toolkit_registry.get(at.toolkit_type)
        if provider is None:
            logger.warning(
                "Unknown toolkit_type, skipping",
                extra={
                    "toolkit_type": at.toolkit_type,
                    "agent_id": agent_id,
                },
            )
            continue

        if toolkit is None or not toolkit.enabled:
            continue

        resolve_ctx = ResolveContext(
            toolkit_id=at.toolkit_id,
            toolkit_name=toolkit.name,
            credentials_json=toolkit.credentials,
            agent_id=context.agent_id,
            session_id=context.session_id,
            user_id=context.user_id,
            session=None,
            web_url=web_url,
            oauth_secret_key=oauth_secret_key,
            workspace_id=context.workspace_id,
            workspace_handle=workspace_handle,
            mcp_proxy_url=mcp_proxy_url,
        )
        try:
            validated_config = type(provider).validate_config(toolkit.config)
            resolved = await _resolve_toolkit_with_logging(
                agent_id=agent_id,
                context=context,
                source="registered",
                slug=toolkit.slug,
                provider=provider,
                toolkit_id=at.toolkit_id,
                toolkit_type=at.toolkit_type,
                toolkit_name=toolkit.name,
                resolve=provider.resolve(validated_config, resolve_ctx),
            )
            resolved.display_name = provider.name
            registered_toolkit_config_ids[id(resolved)] = at.toolkit_id
            registered_toolkit_revisions[id(resolved)] = str(toolkit.revision)
        except ValidationError, ValueError:
            logger.warning(
                "Skipping Toolkit with invalid persisted configuration",
                exc_info=True,
                extra={
                    "agent_id": agent_id,
                    "toolkit_id": at.toolkit_id,
                    "toolkit_type": at.toolkit_type,
                    "toolkit_slug": toolkit.slug,
                },
            )
            continue

        pending.append(
            (
                provider,
                resolved,
                validated_config,
                toolkit.slug,
                toolkit.prompt,
                True,
                at.toolkit_type,
                _ROOT_AND_SUBAGENT_EXECUTION_MODES,
            )
        )

    # Auto-bound Toolkit: configure memory and runtime capabilities as separate
    # Toolkit bindings so future execution modes can filter capabilities without
    # changing model-visible tool names.
    if builtin_toolkit_provider is not None:
        # runtime_domain_config is required: parent uses agent/workspace settings,
        builtin_config = BuiltinToolkitProvider.validate_config(
            {
                "memory_enabled": memory_enabled,
                "allowed_domains": list(runtime_domain_config.allowed_domains),
                "denied_domains": list(runtime_domain_config.denied_domains),
            }
        )
        if memory_enabled:
            memory_read_modes = _ROOT_AND_SUBAGENT_EXECUTION_MODES
            if _allows_execution_mode(memory_read_modes, execution_mode):
                memory_read_context = ResolveContext(
                    toolkit_id="",
                    toolkit_name="memory_read",
                    credentials_json=None,
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                    user_id=context.user_id,
                    session=None,
                    web_url=web_url,
                    oauth_secret_key=oauth_secret_key,
                    workspace_id=context.workspace_id,
                    workspace_handle=workspace_handle,
                )
                memory_read_resolved = await _resolve_toolkit_with_logging(
                    agent_id=agent_id,
                    context=context,
                    source="auto",
                    slug="memory_read",
                    provider=builtin_toolkit_provider,
                    toolkit_name="memory_read",
                    resolve=builtin_toolkit_provider.resolve_memory_read(
                        builtin_config,
                        memory_read_context,
                    ),
                )
                if isinstance(memory_read_resolved, MemoryReadToolkit):
                    memory_read_resolved.set_agent_id(agent_id)
                    memory_read_resolved.set_session_id(context.session_id)
                pending.append(
                    (
                        builtin_toolkit_provider,
                        memory_read_resolved,
                        builtin_config,
                        "memory_read",
                        None,
                        False,
                        None,
                        memory_read_modes,
                    )
                )

            memory_write_modes = _ROOT_EXECUTION_MODES
            if _allows_execution_mode(memory_write_modes, execution_mode):
                memory_write_context = ResolveContext(
                    toolkit_id="",
                    toolkit_name="memory_write",
                    credentials_json=None,
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                    user_id=context.user_id,
                    session=None,
                    web_url=web_url,
                    oauth_secret_key=oauth_secret_key,
                    workspace_id=context.workspace_id,
                    workspace_handle=workspace_handle,
                )
                memory_write_resolved = await _resolve_toolkit_with_logging(
                    agent_id=agent_id,
                    context=context,
                    source="auto",
                    slug="memory_write",
                    provider=builtin_toolkit_provider,
                    toolkit_name="memory_write",
                    resolve=builtin_toolkit_provider.resolve_memory_write(
                        builtin_config,
                        memory_write_context,
                    ),
                )
                if isinstance(memory_write_resolved, MemoryWriteToolkit):
                    memory_write_resolved.set_agent_id(agent_id)
                    memory_write_resolved.set_session_id(context.session_id)
                pending.append(
                    (
                        builtin_toolkit_provider,
                        memory_write_resolved,
                        builtin_config,
                        "memory_write",
                        None,
                        False,
                        None,
                        memory_write_modes,
                    )
                )

        if runtime_tools_enabled:
            instruction_context_store = RuntimeInstructionContextStore()
            runtime_modes = _ROOT_AND_SUBAGENT_EXECUTION_MODES
            if _allows_execution_mode(runtime_modes, execution_mode):
                runtime_context = ResolveContext(
                    toolkit_id="",
                    toolkit_name="runtime",
                    credentials_json=None,
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                    user_id=context.user_id,
                    session=None,
                    web_url=web_url,
                    oauth_secret_key=oauth_secret_key,
                    workspace_id=context.workspace_id,
                    workspace_handle=workspace_handle,
                )
                runtime_resolved = await _resolve_toolkit_with_logging(
                    agent_id=agent_id,
                    context=context,
                    source="auto",
                    slug="runtime",
                    provider=builtin_toolkit_provider,
                    toolkit_name="runtime",
                    resolve=builtin_toolkit_provider.resolve(
                        builtin_config,
                        runtime_context,
                    ),
                )
                # Inject session_id / agent_id into RuntimeToolkit.
                if isinstance(runtime_resolved, RuntimeToolkit):
                    runtime_resolved.set_agent_id(agent_id)
                    runtime_resolved.set_session_id(context.session_id)
                    runtime_resolved.set_instruction_context_store(
                        instruction_context_store
                    )
                    # Register peer toolkits to collect env when runtime tools run.
                    # DB-registered toolkits are already in pending. In current
                    # structure, credential injection into runtime is limited to
                    # DB-registered toolkits such as EnvVarToolkit, so including
                    # peers up to here is sufficient.
                    peer_toolkits = [
                        resolved for _, resolved, _, _, _, _, _, _ in pending
                    ]
                    runtime_resolved.set_peer_toolkits(peer_toolkits)

                    pending.append(
                        (
                            builtin_toolkit_provider,
                            runtime_resolved,
                            builtin_config,
                            "runtime",
                            None,
                            False,
                            None,
                            runtime_modes,
                        )
                    )

            if claude_rules_toolkit_provider is not None:
                claude_rules_modes = _ROOT_AND_SUBAGENT_EXECUTION_MODES
                if _allows_execution_mode(claude_rules_modes, execution_mode):
                    claude_rules_config = ClaudeRulesToolkitProvider.validate_config({})
                    claude_rules_context = ResolveContext(
                        toolkit_id="",
                        toolkit_name="claude_rules",
                        credentials_json=None,
                        agent_id=context.agent_id,
                        session_id=context.session_id,
                        user_id=context.user_id,
                        session=None,
                        web_url=web_url,
                        oauth_secret_key=oauth_secret_key,
                        workspace_id=context.workspace_id,
                        workspace_handle=workspace_handle,
                    )
                    claude_rules_resolved = await _resolve_toolkit_with_logging(
                        agent_id=agent_id,
                        context=context,
                        source="auto",
                        slug="claude_rules",
                        provider=claude_rules_toolkit_provider,
                        toolkit_name="claude_rules",
                        resolve=claude_rules_toolkit_provider.resolve(
                            claude_rules_config,
                            claude_rules_context,
                        ),
                    )
                    if isinstance(claude_rules_resolved, ClaudeRulesToolkit):
                        claude_rules_resolved.set_agent_id(agent_id)
                        claude_rules_resolved.set_session_id(context.session_id)
                        claude_rules_resolved.set_instruction_context_store(
                            instruction_context_store
                        )
                    pending.append(
                        (
                            claude_rules_toolkit_provider,
                            claude_rules_resolved,
                            claude_rules_config,
                            "claude_rules",
                            None,
                            False,
                            None,
                            claude_rules_modes,
                        )
                    )

    # Auto-bound Toolkit: subagent collaboration
    subagent_modes = _ROOT_AND_SUBAGENT_EXECUTION_MODES
    if subagent_toolkit_provider is not None and _allows_execution_mode(
        subagent_modes,
        execution_mode,
    ):
        subagent_config = type(subagent_toolkit_provider).validate_config({})
        subagent_context = ResolveContext(
            toolkit_id="",
            toolkit_name="subagent",
            credentials_json=None,
            agent_id=context.agent_id,
            session_id=context.session_id,
            user_id=context.user_id,
            session=None,
            web_url=web_url,
            oauth_secret_key=oauth_secret_key,
            workspace_id=context.workspace_id,
            workspace_handle=workspace_handle,
        )
        subagent_resolved = await _resolve_toolkit_with_logging(
            agent_id=agent_id,
            context=context,
            source="auto",
            slug="subagent",
            provider=subagent_toolkit_provider,
            toolkit_name="subagent",
            resolve=subagent_toolkit_provider.resolve(
                subagent_config,
                subagent_context,
            ),
        )
        pending.append(
            (
                subagent_toolkit_provider,
                subagent_resolved,
                subagent_config,
                "subagent",
                None,
                False,
                None,
                subagent_modes,
            )
        )

    # Auto-bound Toolkit: session goal
    goal_modes = _ROOT_EXECUTION_MODES
    if goal_toolkit_provider is not None and _allows_execution_mode(
        goal_modes,
        execution_mode,
    ):
        goal_config = GoalToolkitProvider.validate_config({})
        goal_context = ResolveContext(
            toolkit_id="",
            toolkit_name="goal",
            credentials_json=None,
            agent_id=context.agent_id,
            session_id=context.session_id,
            user_id=context.user_id,
            session=None,
            web_url=web_url,
            oauth_secret_key=oauth_secret_key,
            workspace_id=context.workspace_id,
            workspace_handle=workspace_handle,
        )
        goal_resolved = await _resolve_toolkit_with_logging(
            agent_id=agent_id,
            context=context,
            source="auto",
            slug="goal",
            provider=goal_toolkit_provider,
            toolkit_name="goal",
            resolve=goal_toolkit_provider.resolve(
                goal_config,
                goal_context,
            ),
        )
        if isinstance(goal_resolved, GoalToolkit):
            goal_resolved.set_agent_id(agent_id)
            goal_resolved.set_session_id(context.session_id)
        pending.append(
            (
                goal_toolkit_provider,
                goal_resolved,
                goal_config,
                "goal",
                None,
                False,
                None,
                goal_modes,
            )
        )

    # Auto-bound Toolkit: filesystem Skills
    skill_modes = _ROOT_AND_SUBAGENT_EXECUTION_MODES
    if skill_toolkit_provider is not None and _allows_execution_mode(
        skill_modes,
        execution_mode,
    ):
        skill_config = SkillToolkitProvider.validate_config({})
        skill_context = ResolveContext(
            toolkit_id="",
            toolkit_name="skill",
            credentials_json=None,
            agent_id=context.agent_id,
            session_id=context.session_id,
            user_id=context.user_id,
            session=None,
            web_url=web_url,
            oauth_secret_key=oauth_secret_key,
            workspace_id=context.workspace_id,
            workspace_handle=workspace_handle,
        )
        skill_resolved = await _resolve_toolkit_with_logging(
            agent_id=agent_id,
            context=context,
            source="auto",
            slug="skill",
            provider=skill_toolkit_provider,
            toolkit_name="skill",
            resolve=skill_toolkit_provider.resolve(
                skill_config,
                skill_context,
            ),
        )
        if isinstance(skill_resolved, SkillToolkit):
            skill_resolved.set_agent_id(agent_id)
            skill_resolved.set_session_id(context.session_id)
        pending.append(
            (
                skill_toolkit_provider,
                skill_resolved,
                skill_config,
                "skill",
                None,
                False,
                None,
                skill_modes,
            )
        )

    # Auto-bound Toolkit: session todo
    todo_modes = _ROOT_AND_SUBAGENT_EXECUTION_MODES
    if todo_toolkit_provider is not None and _allows_execution_mode(
        todo_modes,
        execution_mode,
    ):
        todo_config = TodoToolkitProvider.validate_config({})
        todo_context = ResolveContext(
            toolkit_id="",
            toolkit_name="todo",
            credentials_json=None,
            agent_id=context.agent_id,
            session_id=context.session_id,
            user_id=context.user_id,
            session=None,
            web_url=web_url,
            oauth_secret_key=oauth_secret_key,
            workspace_id=context.workspace_id,
            workspace_handle=workspace_handle,
        )
        todo_resolved = await _resolve_toolkit_with_logging(
            agent_id=agent_id,
            context=context,
            source="auto",
            slug="todo",
            provider=todo_toolkit_provider,
            toolkit_name="todo",
            resolve=todo_toolkit_provider.resolve(
                todo_config,
                todo_context,
            ),
        )
        if isinstance(todo_resolved, TodoToolkit):
            todo_resolved.set_agent_id(agent_id)
            todo_resolved.set_session_id(context.session_id)
        pending.append(
            (
                todo_toolkit_provider,
                todo_resolved,
                todo_config,
                "todo",
                None,
                False,
                None,
                todo_modes,
            )
        )

    result: list[ToolkitBinding] = [
        ToolkitBinding(
            toolkit=_resolved,
            slug=_slug,
            use_prefix=_pfx,
            toolkit_type=_ttype,
            toolkit_config_id=registered_toolkit_config_ids.get(id(_resolved)),
            source_revision=registered_toolkit_revisions.get(id(_resolved))
            or _auto_toolkit_source_revision(
                slug=_slug,
                config=_cfg,
                execution_mode=execution_mode,
            ),
        )
        for _prov, _resolved, _cfg, _slug, _prompt, _pfx, _ttype, _modes in pending
        if _allows_execution_mode(_modes, execution_mode)
    ]

    return result


def _auto_toolkit_source_revision(
    *,
    slug: str,
    config: BaseModel,
    execution_mode: ToolkitExecutionMode,
) -> str:
    """Return a stable non-secret source revision for an auto-bound Toolkit."""
    payload = {
        "config": config.model_dump(mode="json"),
        "execution_mode": execution_mode.value,
        "slug": slug,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
