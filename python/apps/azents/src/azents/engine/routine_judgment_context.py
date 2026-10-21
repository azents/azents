"""Canonical context preparation for the tool-free Routine judgment operation."""

import datetime
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from azents.core.agent import AgentModelSelection
from azents.core.enums import LLMProvider
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.routine import RoutineScope
from azents.core.routine_judgment import RoutineJudgmentCandidate
from azents.core.tools import TurnContext
from azents.engine.events.file_parts import RequestLocalModelFileResolver
from azents.engine.events.model_file_materializer import (
    ModelFileDownloader,
    ModelFileMaterializer,
)
from azents.engine.events.openai_responses import OpenAIResponsesLowerer
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.system_prompt import build_system_prompt
from azents.engine.events.tools import (
    build_tool_catalog,
    project_tool_catalog_for_client_compatibility,
)
from azents.engine.events.types import Event
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.routine_judgment import (
    RoutineJudgmentModel,
    RoutineJudgmentRequest,
    prepare_routine_judgment_request,
)
from azents.engine.run.client_tool_compatibility import (
    ClientToolRoute,
    resolve_client_tool_adapter_profile,
    resolve_client_tool_model_profiles,
)
from azents.engine.run.contracts import RunRequest


@dataclass(frozen=True)
class PreparedRoutineJudgment:
    """Detached request and exact model authority for one physical call."""

    selection: RoutineJudgmentModel
    request: RoutineJudgmentRequest


@dataclass(frozen=True)
class RoutineJudgmentContext:
    """Ordinary host context resolved without foreground model admission."""

    request: RunRequest
    model_selection: AgentModelSelection
    model_target_label: str
    turn: TurnContext
    admit_dispatch: Callable[[], Awaitable[None]]
    advance_after_quota: Callable[[], Awaitable["RoutineJudgmentContext | None"]]


PrepareRoutineJudgmentContext = Callable[[], Awaitable[RoutineJudgmentContext]]


@dataclass(frozen=True)
class RoutineJudgmentActionContext:
    """Exact Session scope and context preparation for one queued operation."""

    scope: RoutineScope
    prepare_context: PrepareRoutineJudgmentContext


@dataclass(frozen=True)
class RoutineJudgmentHost:
    """The ordinary Run's context resolver, bound at each FIFO action boundary."""

    scope: RoutineScope
    prepare_context: Callable[
        [RequestedInferenceProfile], Awaitable[RoutineJudgmentContext]
    ]

    def for_profile(
        self, profile: RequestedInferenceProfile
    ) -> RoutineJudgmentActionContext:
        """Freeze this boundary's normal requested profile before operation I/O."""

        async def prepare() -> RoutineJudgmentContext:
            return await self.prepare_context(profile)

        return RoutineJudgmentActionContext(scope=self.scope, prepare_context=prepare)


async def prepare_canonical_routine_judgment(
    *,
    run_request: RunRequest,
    model_selection: AgentModelSelection,
    transcript: Sequence[Event],
    candidates: tuple[RoutineJudgmentCandidate, ...],
    current_time: datetime.datetime,
    context: TurnContext,
    model_file_service: ModelFileDownloader,
) -> PreparedRoutineJudgment:
    """Reuse ordinary input/prompt units without entering a normal model turn.

    Toolkit context is prepared for the actual Session and host Run, but no
    executable declarations, turn hooks, prompt snapshots or Run usage are
    admitted by this operation. Historical tool messages retain normal dialect
    projection through the same model/adapter compatibility evidence.
    """
    if (
        context.session_id != run_request.session_id
        or context.workspace_id != run_request.workspace_id
        or context.model != run_request.model
        or model_selection.provider != run_request.provider
        or model_selection.model_identifier != run_request.model
    ):
        raise ValueError("Routine context does not match the selected Session model.")
    assembly = ModelAssemblyMetadata.from_selection(model_selection)
    lowerer_type = (
        OpenAIResponsesLowerer
        if run_request.provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}
        else PydanticAILowerer
    )
    catalog = project_tool_catalog_for_client_compatibility(
        await build_tool_catalog(
            toolkit_bindings=run_request.toolkits, context=context
        ),
        resolve_client_tool_model_profiles(
            model_identifier=model_selection.model_identifier,
            model_developer=model_selection.model_developer,
            model_family=model_selection.model_family,
        ),
        resolve_client_tool_adapter_profile(
            route=ClientToolRoute(
                provider=run_request.provider,
                adapter=lowerer_type.adapter,
                native_format=lowerer_type.native_format,
            )
        ),
    )
    prompt = build_system_prompt(
        agent_prompt=run_request.agent_prompt,
        static_toolkit_prompts=catalog.static_prompt_fragment_inputs,
        dynamic_toolkit_prompts=catalog.dynamic_prompt_fragment_inputs,
        injected_prompts=[],
    )
    resolver = RequestLocalModelFileResolver()
    await ModelFileMaterializer(
        model_file_service=model_file_service,
        resolver=resolver,
        authority=context.resource_authority,
    ).materialize(transcript=transcript)
    selection = RoutineJudgmentModel(
        provider=run_request.provider,
        model=run_request.model,
        assembly=assembly,
        temperature=run_request.temperature,
        max_output_tokens=run_request.max_output_tokens,
        top_p=run_request.top_p,
        top_k=run_request.top_k,
        stop=run_request.stop,
        reasoning_effort=run_request.reasoning_effort,
        supported_execution_options=tuple(model_selection.supported_execution_options),
        enabled_execution_options=tuple(run_request.enabled_execution_options),
    )
    request = prepare_routine_judgment_request(
        selection=selection,
        transcript=transcript,
        system_prompt=prompt.prompt or "",
        candidates=candidates,
        current_time=current_time,
        session_id=run_request.session_id,
        native_replay_context=catalog.native_replay_context,
        model_file_resolver=resolver,
    )
    return PreparedRoutineJudgment(selection=selection, request=request)
