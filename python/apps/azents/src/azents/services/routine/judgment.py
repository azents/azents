"""Routine judgment domain operation hosted by ordinary inbox action execution."""

import asyncio
import datetime
import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.action_execution_data import ActionExecution
from azents.core.model_pricing import capture_model_pricing
from azents.core.routine import RoutineScope, RoutineUnavailable
from azents.core.routine_judgment import RoutineJudgmentConsidered
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.core.worker_model_profile import ProfileResolutionRuntimeError
from azents.engine.events.action_messages import RoutineJudgmentAction
from azents.engine.events.effective_model_request import (
    EffectiveRequestNormalizationError,
)
from azents.engine.events.model_file_materializer import ModelFileDownloader
from azents.engine.events.model_support_contract import ModelRequestFeatureError
from azents.engine.events.types import RoutineJudgmentPayload
from azents.engine.model_factories import get_model_sdk_factories
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.model_stream import (
    ModelStreamCallContext,
    ModelStreamWatchdog,
    get_model_stream_watchdog,
)
from azents.engine.providers.observation_state import InternalModelExecutionError
from azents.engine.routine_judgment import call_routine_judgment
from azents.engine.routine_judgment_context import (
    PrepareRoutineJudgmentContext,
    prepare_canonical_routine_judgment,
)
from azents.engine.run.errors import ModelCallError
from azents.engine.run.provider_failure import UnclassifiedModelProviderError
from azents.repos.routine.judgment_inbox import (
    RoutineJudgmentInboxRepository,
    RoutineJudgmentSettlement,
)
from azents.services.model_file import ModelFileService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoutineJudgmentService:
    """One call and one database settlement; no independent owner or retry loop."""

    repository: Annotated[RoutineJudgmentInboxRepository, Depends()]
    sdk_factories: Annotated[ModelSDKFactories, Depends(get_model_sdk_factories)]
    watchdog: Annotated[ModelStreamWatchdog, Depends(get_model_stream_watchdog)]
    model_file_service: Annotated[ModelFileDownloader, Depends(ModelFileService)]

    async def cancel(
        self, *, execution: ActionExecution, owner: SessionExecutionOwner
    ) -> None:
        """Apply ordinary action recovery without emitting a worktree terminal."""
        await self.repository.cancel_action(execution=execution, owner=owner)

    async def execute(
        self,
        *,
        scope: RoutineScope,
        action: RoutineJudgmentAction,
        execution: ActionExecution,
        owner: SessionExecutionOwner,
        prepare_context: PrepareRoutineJudgmentContext,
    ) -> RoutineJudgmentSettlement:
        """Resolve candidates/context at execution, then call outside transactions."""
        captured = await self.repository.capture(
            scope=scope,
            action=action,
            execution=execution,
            owner=owner,
            now=datetime.datetime.now(datetime.UTC),
        )
        if not captured.candidates:
            return await self.repository.settle(
                scope=scope,
                captured=captured,
                execution=execution,
                owner=owner,
                outcome=None,
                provider=None,
                model=None,
                now=datetime.datetime.now(datetime.UTC),
            )
        provider: str | None = None
        model: str | None = None
        try:
            context = await prepare_context()
            request = context.request
            if (
                request.session_id != scope.session_id
                or request.agent_id != scope.agent_id
                or request.workspace_id != scope.workspace_id
                or context.turn.resource_authority is None
                or context.turn.resource_authority.execution_owner != owner
                or context.turn.resource_authority.workspace_id != scope.workspace_id
                or context.turn.resource_authority.agent_id != scope.agent_id
                or context.turn.resource_authority.run_id != context.turn.run_id
            ):
                raise RoutineUnavailable(
                    "Routine judgment context does not match its owner."
                )
            provider = request.provider.value
            model = request.model
            transcript = await self.repository.capture_transcript(
                scope=scope, owner=owner
            )
            prepared = await prepare_canonical_routine_judgment(
                run_request=request,
                model_selection=context.model_selection,
                transcript=transcript,
                candidates=captured.candidates,
                context=context.turn,
                model_file_service=self.model_file_service,
            )
            # Preparation can perform file/Toolkit I/O. Recheck the ordinary owner
            # immediately before spending this call, without a judgment lease.
            await self.repository.assert_current_owner(owner=owner)
            await context.admit_dispatch()
            if context.turn.check_stop is not None and await context.turn.check_stop():
                raise asyncio.CancelledError(
                    "Routine judgment stopped before dispatch."
                )
            outcome = await call_routine_judgment(
                judgment_id=action.judgment_id,
                candidates=captured.candidates,
                selection=prepared.selection,
                request=prepared.request,
                sdk_factories=self.sdk_factories,
                credential_kwargs=request.credential_kwargs,
                pricing=capture_model_pricing(
                    provider=request.provider,
                    model_identifier=context.model_selection.model_identifier,
                    definition=context.model_selection.pricing,
                    request_timestamp=datetime.datetime.now(datetime.UTC),
                ),
                watchdog=self.watchdog,
                timeout_policy=self.watchdog.resolve_policy(
                    provider=request.provider.value,
                    model=request.model,
                    inference_profile=context.model_target_label,
                ),
                call_context=ModelStreamCallContext(
                    call_kind="routine_judgment",
                    provider=request.provider.value,
                    provider_integration_id=context.model_selection.llm_provider_integration_id,
                    model=request.model,
                    session_id=scope.session_id,
                    run_id=None,
                    attempt_number=1,
                    check_stop=context.turn.check_stop,
                ),
            )
        except asyncio.CancelledError:
            raise
        except (
            ModelCallError,
            UnclassifiedModelProviderError,
            InternalModelExecutionError,
            EffectiveRequestNormalizationError,
            ModelRequestFeatureError,
            ProfileResolutionRuntimeError,
        ):
            logger.exception(
                "Routine judgment model operation failed",
                extra={
                    "session_id": scope.session_id,
                    "judgment_id": action.judgment_id,
                },
            )
            outcome = RoutineJudgmentPayload(
                judgment_id=action.judgment_id,
                considered=tuple(
                    RoutineJudgmentConsidered(
                        routine_id=item.routine_id,
                        slug=item.slug,
                        title=item.content.title,
                    )
                    for item in captured.candidates
                ),
                status="failed",
                decision=None,
                error="The Routine judgment model operation failed.",
                usage=None,
            )
        return await self.repository.settle(
            scope=scope,
            captured=captured,
            execution=execution,
            owner=owner,
            outcome=outcome,
            provider=provider,
            model=model,
            now=datetime.datetime.now(datetime.UTC),
        )
