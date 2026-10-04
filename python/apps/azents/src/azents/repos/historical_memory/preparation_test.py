"""Historical Memory candidate preparation repository tests."""

import datetime
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.active_model_capabilities import (
    CapturedStoredChoice,
    ConfiguredModelIdentity,
)
from azents.core.agent import AgentModelSelection
from azents.core.enums import AgentSessionProductMode
from azents.core.historical_memory import HistoricalMemoryDueSource
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.model_catalog_identity import catalog_source_keys
from azents.core.model_catalog_source import decode_catalog_source
from azents.core.model_operation import ModelOperationKind, build_model_operation
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.active_model_capabilities_data import CapturedActiveChoiceInputs
from azents.repos.historical_memory import HistoricalMemoryPreparationAdmission
from azents.repos.historical_memory.preparation import (
    HistoricalMemoryPreparationRepository,
)
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_options,
)

_NOW = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.UTC)


@pytest.mark.parametrize("reuse", [False, True])
@pytest.mark.parametrize("inputs_current", [False, True])
async def test_begin_next_freezes_lightweight_candidate_and_source_boundary(
    monkeypatch: pytest.MonkeyPatch,
    reuse: bool,
    inputs_current: bool,
) -> None:
    """Candidate selection and source capture commit in one DB-only transaction."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        yield session

    source = HistoricalMemoryDueSource(
        source_session_id="s" * 32,
        agent_id="a" * 32,
        workspace_id="w" * 32,
        source_activity_at=_NOW - datetime.timedelta(hours=7),
        source_tail_event_id="e" * 32,
        source_title="Prior work",
        admitted_at=_NOW - datetime.timedelta(hours=1),
        prepared_at=None,
        completed_source_activity_at=None,
        next_retry_at=None,
        failure_count=0,
        model_operation_state=None,
    )
    admission = HistoricalMemoryPreparationAdmission(
        source=source,
        product_mode=AgentSessionProductMode.TEAM,
        associated_user_id=None,
    )
    historical = Mock()
    historical.list_due_for_agent_in_session = AsyncMock(return_value=[source])
    historical.lock_preparation_admission_in_session = AsyncMock(return_value=admission)
    historical.lock_preparation_membership_in_session = AsyncMock(return_value=True)
    prepared = SimpleNamespace(source_session_id="s" * 32)
    historical.persist_preparation_operation_in_session = AsyncMock(
        return_value=prepared
    )
    saved_selection = make_test_model_selection()
    raw_selection = saved_selection.model_dump(mode="json")
    raw_selection["normalized_capabilities"] = _legacy_v2_capabilities()
    saved_selection = AgentModelSelection.model_validate(raw_selection)
    option = make_test_selectable_model_options(saved_selection)[0]
    agent = SimpleNamespace(
        id="a" * 32,
        workspace_id="w" * 32,
        memory_enabled=True,
        lightweight_model_label=option.label,
        selectable_model_options=[option],
    )
    agent_repository = Mock()
    agent_repository.lock_by_id = AsyncMock(return_value=agent)
    agent_repository.get_by_id = AsyncMock()
    frozen = build_model_operation(
        option=option,
        profile=RequestedInferenceProfile(
            model_target_label=option.label,
            reasoning_effort=None,
            enabled_execution_options=[],
        ),
        kind=ModelOperationKind.HISTORICAL_MEMORY,
        operation_id="f" * 32,
        recorded_at=_NOW,
    )
    if reuse:
        source = source.model_copy(update={"model_operation_state": frozen})
        admission = HistoricalMemoryPreparationAdmission(
            source=source,
            product_mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
        )
        historical.lock_preparation_admission_in_session.return_value = admission
    build = Mock(wraps=build_model_operation)

    async def select(
        _session: WriteSession, *, operation: object, **_kwargs: object
    ) -> SimpleNamespace:
        return SimpleNamespace(operation=operation)

    select_candidate = AsyncMock(side_effect=select)
    active_metadata = _active_metadata_repository(structured_output=True)
    active_metadata.inputs_match_in_session.return_value = inputs_current
    monkeypatch.setattr(
        "azents.repos.historical_memory.preparation.build_model_operation",
        build,
    )
    monkeypatch.setattr(
        "azents.repos.historical_memory.preparation.select_model_operation_candidate",
        select_candidate,
    )
    repository = HistoricalMemoryPreparationRepository(
        historical_repository=historical,
        agent_repository=agent_repository,
        health_repository=Mock(),
        active_capabilities_repository=active_metadata,
        session_manager=session_manager,
    )

    result = await repository.begin_next(
        agent_id="a" * 32,
        attempted_at=_NOW,
        inactive_before=_NOW - datetime.timedelta(hours=6),
    )

    if not reuse and not inputs_current:
        assert result is None
        historical.persist_preparation_operation_in_session.assert_not_awaited()
        _raw_session.commit.assert_not_awaited()
        return
    assert result is prepared
    agent_repository.lock_by_id.assert_awaited_once_with(session, "a" * 32)
    agent_repository.get_by_id.assert_not_awaited()
    if reuse:
        build.assert_not_called()
        active_metadata.capture_exact_choices_in_session.assert_not_awaited()
        active_metadata.inputs_match_in_session.assert_not_awaited()
    else:
        build.assert_called_once()
        active_metadata.capture_exact_choices_in_session.assert_awaited_once()
        active_metadata.inputs_match_in_session.assert_awaited_once()
    operation = historical.persist_preparation_operation_in_session.await_args.kwargs[
        "operation"
    ]
    assert (
        operation.current_candidate.model_selection.normalized_capabilities.tool_calling.supported
        == (not reuse)
    )
    assert operation.current_candidate.settings == option.candidates[0].settings
    assert saved_selection.normalized_capabilities.tool_calling.supported is False
    select_candidate.assert_awaited_once()
    historical.persist_preparation_operation_in_session.assert_awaited_once_with(
        session,
        admission,
        attempted_at=_NOW,
        operation=operation,
    )
    _raw_session.commit.assert_awaited_once()


def _active_metadata_repository(*, structured_output: bool) -> AsyncMock:
    """Capture synthetic exact declarations, never the saved capability object."""
    repository = AsyncMock(spec=ActiveModelCapabilitiesRepository)

    async def capture(
        session: WriteSession,
        *,
        workspace_id: str,
        identities: tuple[ConfiguredModelIdentity, ...],
    ) -> CapturedActiveChoiceInputs:
        del session
        choices = []
        for identity in identities:
            key = catalog_source_keys(
                provider=identity.provider, model_identifier=identity.model_identifier
            )[0]
            source = decode_catalog_source(
                json.dumps(
                    {
                        key.source_model_key: {
                            "litellm_provider": key.provider,
                            "mode": "chat",
                            "supported_endpoints": ["/v1/responses"],
                            "supported_modalities": ["text"],
                            "supported_output_modalities": ["text"],
                            "supports_function_calling": True,
                            "supports_response_schema": structured_output,
                            "max_input_tokens": 128000,
                            "max_output_tokens": 16384,
                        }
                    }
                ).encode()
            ).models[0]
            choices.append(
                CapturedStoredChoice(
                    identity=identity,
                    source_metadata=None,
                    source_models=(source,),
                    supported_execution_options=(),
                    model_developer=None,
                    catalog_id="synthetic-local-catalog",
                )
            )
        return CapturedActiveChoiceInputs(
            workspace_id=workspace_id,
            choices=tuple(choices),
            catalog_choices=(),
            source_metadata=None,
            source_expectations=(),
        )

    repository.capture_exact_choices_in_session.side_effect = capture
    repository.inputs_match_in_session.return_value = True
    return repository


def _legacy_v2_capabilities() -> dict[str, object]:
    """Keep a real persisted v2 declaration unknown until exact facts compile it."""
    unknown = {"state": "unknown", "origin": None, "predicate": None}
    return {
        "semantic_contract": {
            "version": 2,
            "reasoning": {
                "support": unknown,
                "completeness": "unknown",
                "efforts": [],
                "default_effort": None,
            },
            "reasoning_summaries": unknown,
            "function_calling": unknown,
            "parallel_function_calls": unknown,
            "strict_function_schema": unknown,
            "structured_response": unknown,
            "parameters": {
                name: unknown
                for name in (
                    "temperature",
                    "max_output_tokens",
                    "top_p",
                    "top_k",
                    "stop_sequences",
                )
            },
            "input_modalities": [],
            "output_modalities": [],
            "built_in_tools": [],
        }
    }
