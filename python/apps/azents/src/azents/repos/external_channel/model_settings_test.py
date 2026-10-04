"""Saved private model display projection and immutable Apply replay."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import SelectableModelCandidate, SelectableModelOption
from azents.core.enums import ExternalChannelProvider, LLMProvider
from azents.core.external_model_settings import (
    ExternalModelActorContext,
    ExternalModelApplied,
    ExternalModelNoticeOutcome,
    ExternalModelRejected,
    ExternalModelSettingsRejectionCode,
)
from azents.core.inference_profile import SessionAppliedInferenceProfile
from azents.core.model_execution_options import (
    MODEL_EXECUTION_OPTION_DEFINITIONS,
    ModelExecutionOptionId,
    list_model_execution_option_definitions,
)
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelPrincipal,
    RDBExternalChannelResource,
)
from azents.rdb.models.external_model_settings import (
    RDBExternalModelDraft,
    RDBExternalModelMutation,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_execution.repository_test import _model_operation_state
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.external_account_link import ExternalAccountLinkRepository
from azents.repos.external_account_link.data import ExternalAccountLink
from azents.repos.external_channel.model_settings import (
    ExternalModelSettingsRepository,
    _AuthorizationResult,
    _AuthorizedModelTarget,
    _SavedModelOptionIdentity,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.session_model_profile.repository import SessionModelProfileRepository

_NOW = datetime.datetime(2026, 9, 12, tzinfo=datetime.UTC)
_ACTOR = ExternalModelActorContext(
    provider=ExternalChannelProvider.SLACK,
    connection_id="connection-1",
    configuration_generation=1,
    principal_id="principal-1",
    provider_tenant_id="team-1",
    provider_user_id="provider-user-1",
    provider_display_name="Synthetic actor",
)


def _snapshot(
    execution_options: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "option_id": "opaque-option-1",
        "target_label": "Quality",
        "label": "Quality",
        "model_display_name": "Saved model",
        "reasoning_efforts": [],
        "execution_options": execution_options,
    }


def _saved_fast(provider: LLMProvider) -> dict[str, object]:
    definition = list_model_execution_option_definitions(
        provider=provider, supported=[ModelExecutionOptionId.FAST]
    )[0].model_dump(mode="json")
    del definition["exclusive_group"]
    return definition


@dataclass(frozen=True)
class _ReplayFixture:
    repository: ExternalModelSettingsRepository
    session: AsyncMock
    authorized: _AuthorizedModelTarget
    draft: RDBExternalModelDraft
    mutation: MagicMock
    agent_repository: AsyncMock
    agent_session_repository: AsyncMock


def _replay_fixture(
    *, saved_definition: dict[str, object], removed_target: bool
) -> _ReplayFixture:
    session = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def sessions() -> AsyncIterator[AsyncSession]:
        yield session

    agent_repository = AsyncMock(spec=AgentRepository)
    agent_session_repository = AsyncMock(spec=AgentSessionRepository)
    repository = ExternalModelSettingsRepository(
        session_manager=sessions,
        external_channel_repository=AsyncMock(spec=ExternalChannelRepository),
        external_account_link_repository=AsyncMock(spec=ExternalAccountLinkRepository),
        session_model_profile_repository=AsyncMock(spec=SessionModelProfileRepository),
        agent_repository=agent_repository,
        agent_session_repository=agent_session_repository,
    )
    profile = SessionAppliedInferenceProfile(
        model_target_label="Quality",
        reasoning_effort=None,
        enabled_execution_options=[ModelExecutionOptionId.FAST],
    )
    agent = MagicMock(spec=Agent)
    agent.main_model_label = "Replacement" if removed_target else "Quality"
    current_option = MagicMock(spec=SelectableModelOption)
    current_option.label = agent.main_model_label
    agent.selectable_model_options = [current_option]
    authorized = _AuthorizedModelTarget(
        connection=MagicMock(spec=RDBExternalChannelConnection),
        principal=MagicMock(spec=RDBExternalChannelPrincipal),
        binding=MagicMock(spec=RDBExternalChannelBinding),
        resource=MagicMock(spec=RDBExternalChannelResource),
        route=MagicMock(spec=RDBExternalChannelAgentRoute),
        session=AgentSession.model_construct(
            id="session-1",
            agent_id="agent-1",
            applied_profile_generation=3,
            applied_inference_profile=profile,
        ),
        agent=agent,
        link=ExternalAccountLink(
            id="link-1",
            user_id="user-1",
            provider=_ACTOR.provider,
            identity_scope=_ACTOR.provider_tenant_id,
            provider_user_id=_ACTOR.provider_user_id,
            provider_tenant_display_label=None,
            provider_display_label="Synthetic actor",
            linked_at=_NOW - datetime.timedelta(days=1),
            revoked_at=None,
            legacy_workspace_id=None,
            revocation_reason=None,
        ),
    )
    draft = RDBExternalModelDraft(
        provider=_ACTOR.provider,
        connection_id=_ACTOR.connection_id,
        principal_id=_ACTOR.principal_id,
        link_id="link-1",
        link_id_snapshot="link-1",
        user_id="user-1",
        user_id_snapshot="user-1",
        binding_id="binding-1",
        session_id="session-1",
        agent_id="agent-1",
        owner_interaction_key="open-1",
        expected_generation=2,
        options_snapshot=[_snapshot([saved_definition])],
        selected_option_id="opaque-option-1",
        selected_model_target_label="Quality",
        selected_reasoning_effort=None,
        selected_enabled_execution_options=["fast"],
        scope_label="Synthetic thread",
        expires_at=_NOW + datetime.timedelta(minutes=10),
        cancelled_at=None,
        applied_at=_NOW - datetime.timedelta(minutes=1),
    )
    mutation = MagicMock(spec=RDBExternalModelMutation)
    mutation.id = "mutation-1"
    mutation.provider = _ACTOR.provider
    mutation.connection_id = _ACTOR.connection_id
    mutation.apply_interaction_key = "apply-1"
    mutation.principal_id_snapshot = _ACTOR.principal_id
    mutation.provider_tenant_id_snapshot = _ACTOR.provider_tenant_id
    mutation.provider_user_id_snapshot = _ACTOR.provider_user_id
    mutation.binding_id_snapshot = draft.binding_id
    mutation.session_id = draft.session_id
    mutation.agent_id_snapshot = draft.agent_id
    mutation.user_id_snapshot = authorized.link.user_id
    mutation.old_model_target_label = "Balanced"
    mutation.old_reasoning_effort = None
    mutation.old_enabled_execution_options = []
    mutation.new_model_target_label = "Quality"
    mutation.new_reasoning_effort = None
    mutation.new_enabled_execution_options = ["fast"]
    mutation.expected_generation = 2
    mutation.resulting_generation = 3
    mutation.notice_outcome = ExternalModelNoticeOutcome.DELIVERED
    session.scalar.return_value = mutation
    return _ReplayFixture(
        repository=repository,
        session=session,
        authorized=authorized,
        draft=draft,
        mutation=mutation,
        agent_repository=agent_repository,
        agent_session_repository=agent_session_repository,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("removed_target", [False, True])
@pytest.mark.parametrize("provider", [LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH])
async def test_applied_fast_snapshot_replay_preserves_immutable_result(
    provider: LLMProvider, removed_target: bool
) -> None:
    """Reproject display authority without touching saved support or history."""
    fixture = _replay_fixture(
        saved_definition=_saved_fast(provider), removed_target=removed_target
    )
    repository = fixture.repository
    draft = fixture.draft
    mutation = fixture.mutation
    snapshot_before = deepcopy(draft.options_snapshot)
    profile_before = fixture.authorized.session.applied_inference_profile
    assert profile_before is not None
    fingerprint = repository._selection_fingerprint(draft)
    audit_before = (
        mutation.old_model_target_label,
        mutation.old_reasoning_effort,
        deepcopy(mutation.old_enabled_execution_options),
        mutation.new_model_target_label,
        mutation.new_reasoning_effort,
        deepcopy(mutation.new_enabled_execution_options),
        mutation.expected_generation,
        mutation.resulting_generation,
    )
    with (
        patch.object(repository, "_lock_draft", AsyncMock(return_value=draft)),
        patch.object(
            repository,
            "_authorize",
            AsyncMock(
                return_value=_AuthorizationResult(
                    target=fixture.authorized, rejection=None
                )
            ),
        ) as authorize,
        patch.object(repository, "_refresh_options") as refresh,
    ):
        commit = await repository.apply_draft(
            actor=_ACTOR,
            draft_id=draft.id,
            expected_selection_fingerprint=fingerprint,
            apply_interaction_key="apply-1",
            now=_NOW,
        )
    result = commit.result
    assert isinstance(result, ExternalModelApplied)
    assert not result.created
    assert result.mutation_id == "mutation-1"
    assert result.notice_outcome is ExternalModelNoticeOutcome.DELIVERED
    assert commit.notice_plan is None
    assert result.editor.draft.selection_fingerprint == fingerprint
    assert result.editor.draft.expected_generation == 2
    assert result.editor.current_generation == 3
    assert result.editor.current_profile is not None
    assert result.editor.current_profile.model_dump() == profile_before.model_dump()
    assert result.editor.draft.selection.option_id == "opaque-option-1"
    assert result.editor.draft.selection.enabled_execution_options == [
        ModelExecutionOptionId.FAST
    ]
    assert result.editor.selected_option.label == "Quality"
    assert result.editor.selected_option.model_display_name == "Saved model"
    definitions = result.editor.selected_option.execution_options
    assert [definition.id for definition in definitions] == [
        ModelExecutionOptionId.FAST
    ]
    assert definitions[0].exclusive_group == "processing_speed"
    assert definitions[0].cost_hint == _saved_fast(provider)["cost_hint"]
    assert draft.options_snapshot == snapshot_before
    assert repository._selection_fingerprint(draft) == fingerprint
    assert draft.expected_generation == 2
    assert fixture.authorized.session.applied_profile_generation == 3
    assert fixture.authorized.session.applied_inference_profile is profile_before
    assert audit_before == (
        mutation.old_model_target_label,
        mutation.old_reasoning_effort,
        mutation.old_enabled_execution_options,
        mutation.new_model_target_label,
        mutation.new_reasoning_effort,
        mutation.new_enabled_execution_options,
        mutation.expected_generation,
        mutation.resulting_generation,
    )
    authorize.assert_awaited_once()
    refresh.assert_not_called()
    fixture.agent_repository.lock_by_id_nowait.assert_not_awaited()
    fixture.agent_session_repository.set_applied_inference_profile.assert_not_awaited()
    fixture.session.add.assert_not_called()
    fixture.session.flush.assert_not_awaited()
    assert fixture.session.execute.await_count == 1
    assert "SET LOCAL lock_timeout" in str(fixture.session.execute.await_args.args[0])


@pytest.mark.parametrize(
    "cost_hint",
    [
        "Additional OpenAI API cost may apply.",
        "Additional ChatGPT usage or credits may apply.",
        "Saved provider-specific usage explanation.",
    ],
)
def test_saved_copy_is_not_registry_definition_authority(cost_hint: str) -> None:
    cached: dict[str, object] = {
        "id": "fast",
        "cost_hint": cost_hint,
        "label": "Obsolete label",
        "description": "Obsolete description",
        "control": "obsolete_control",
        "exclusive_group": "obsolete_group",
    }
    projected = ExternalModelSettingsRepository._public_option(_snapshot([cached]))
    definition = projected.execution_options[0]
    current = MODEL_EXECUTION_OPTION_DEFINITIONS[ModelExecutionOptionId.FAST]
    assert definition == current.model_copy(update={"cost_hint": cost_hint})


def test_both_saved_supported_speed_ids_project_without_preference_conflict() -> None:
    projected = ExternalModelSettingsRepository._public_option(
        _snapshot(
            [
                {"id": "ultrafast", "cost_hint": "Saved Ultrafast hint."},
                {"id": "fast", "cost_hint": "Saved Fast hint."},
            ]
        )
    )
    assert [item.id for item in projected.execution_options] == [
        ModelExecutionOptionId.FAST,
        ModelExecutionOptionId.ULTRAFAST,
    ]
    assert all(
        item.exclusive_group == "processing_speed"
        for item in projected.execution_options
    )


@pytest.mark.parametrize(
    "execution_options",
    [
        [{"id": "unknown", "cost_hint": "Saved hint."}],
        [{"id": "fast"}],
        [{"cost_hint": "Saved hint."}],
        [{"id": "fast", "cost_hint": ""}],
    ],
)
def test_invalid_saved_support_or_required_hint_remains_visible(
    execution_options: list[dict[str, object]],
) -> None:
    with pytest.raises(ValidationError):
        ExternalModelSettingsRepository._public_option(_snapshot(execution_options))


def test_duplicate_saved_support_remains_invalid() -> None:
    with pytest.raises(ValueError, match="Supported execution options must be unique"):
        ExternalModelSettingsRepository._public_option(
            _snapshot(
                [
                    {"id": "fast", "cost_hint": "First hint."},
                    {"id": "fast", "cost_hint": "Second hint."},
                ]
            )
        )


def test_no_supported_execution_options_stays_empty() -> None:
    projected = ExternalModelSettingsRepository._public_option(_snapshot([]))
    assert projected.execution_options == []


def test_saved_id_lookup_preserves_prefix_and_ignored_target_validation() -> None:
    draft = MagicMock(spec=RDBExternalModelDraft)
    draft.options_snapshot = [
        {"option_id": "other", "target_label": None},
        {"option_id": "selected", "target_label": "Quality", "opaque": {"future": 1}},
        {"option_id": None, "target_label": None},
    ]
    restored = ExternalModelSettingsRepository._snapshot_option(draft, "selected")
    assert restored == _SavedModelOptionIdentity("selected", "Quality")
    with pytest.raises(RuntimeError, match="option snapshot is invalid"):
        ExternalModelSettingsRepository._snapshot_option(draft, "missing")


def test_saved_target_lookup_preserves_unconsumed_ids_and_ignored_tail() -> None:
    values: list[dict[str, object]] = [
        {"option_id": None, "target_label": "Other"},
        {"option_id": "selected", "target_label": "Quality"},
        {"option_id": None, "target_label": None},
    ]
    restored = ExternalModelSettingsRepository._saved_option_for_target(
        values, "Quality"
    )
    assert restored == _SavedModelOptionIdentity("selected", "Quality")
    with pytest.raises(RuntimeError, match="option snapshot is invalid"):
        ExternalModelSettingsRepository._saved_option_for_target(values, "Missing")


def test_identity_refresh_ignores_display_metadata_that_is_replaced() -> None:
    retained: dict[str, object] = {
        "option_id": "selected",
        "target_label": "Quality",
        "label": None,
        "reasoning_efforts": False,
        "execution_options": "obsolete invalid display",
    }
    assert _SavedModelOptionIdentity.from_saved(retained) == (
        _SavedModelOptionIdentity("selected", "Quality")
    )
    agent = MagicMock(spec=Agent)
    agent.selectable_model_options = []
    repository = _replay_fixture(
        saved_definition={"id": "fast", "cost_hint": "Retained hint."},
        removed_target=False,
    ).repository
    assert repository._options_snapshot(agent, previous=[retained]) == []


def test_fresh_snapshot_keeps_flat_storage_shape_and_retained_identity() -> None:
    operation = _model_operation_state().foreground
    assert operation is not None
    candidate = operation.current_candidate
    option = SelectableModelOption(
        label="Quality",
        candidates=[
            SelectableModelCandidate(
                model_selection=candidate.model_selection,
                settings=candidate.settings,
            )
        ],
        subagent_enabled=True,
        subagent_guidance=None,
    )
    agent = MagicMock(spec=Agent)
    agent.selectable_model_options = [option]
    repository = _replay_fixture(
        saved_definition={"id": "fast", "cost_hint": "Retained hint."},
        removed_target=False,
    ).repository
    snapshot = repository._options_snapshot(
        agent,
        previous=[{"option_id": "retained", "target_label": "Quality"}],
    )[0]
    assert snapshot.option_id == "retained"
    assert snapshot.target_label == option.label
    stored = snapshot.to_storage()
    assert set(stored) == {
        "option_id",
        "target_label",
        "label",
        "model_display_name",
        "reasoning_efforts",
        "execution_options",
    }
    projected = repository._public_option(stored)
    assert projected.option_id == snapshot.option_id
    assert projected.model_display_name == candidate.model_selection.model_display_name


@pytest.mark.parametrize("invalid", [None, "", 123, False, []])
def test_saved_required_identity_keeps_visible_invalid_shape(
    invalid: object,
) -> None:
    with pytest.raises(RuntimeError, match="option snapshot is invalid"):
        _SavedModelOptionIdentity.from_saved(
            {"option_id": invalid, "target_label": "Quality"}
        )


def test_public_display_keeps_unused_target_and_extra_metadata_opaque() -> None:
    value = _snapshot([])
    value["target_label"] = False
    value["extension"] = {"future": ["retained", None]}
    projected = ExternalModelSettingsRepository._public_option(value)
    assert projected.option_id == "opaque-option-1"
    assert projected.label == "Quality"


def test_public_display_preserves_execution_validation_before_identity() -> None:
    value = _snapshot([])
    value["execution_options"] = None
    value["option_id"] = ""
    with pytest.raises(ValidationError):
        ExternalModelSettingsRepository._public_option(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["expired", "actor", "fingerprint"])
async def test_replay_keeps_existing_expiry_actor_and_fingerprint_guards(
    guard: str,
) -> None:
    fixture = _replay_fixture(
        saved_definition=_saved_fast(LLMProvider.OPENAI), removed_target=True
    )
    repository = fixture.repository
    draft = fixture.draft
    actor = _ACTOR
    expected = ExternalModelSettingsRejectionCode.ACTOR_MISMATCH
    fingerprint = repository._selection_fingerprint(draft)
    if guard == "expired":
        draft.expires_at = _NOW
        expected = ExternalModelSettingsRejectionCode.DRAFT_EXPIRED
    elif guard == "actor":
        actor = actor.model_copy(update={"principal_id": "wrong-actor"})
    else:
        fingerprint = "0" * 16
    with (
        patch.object(repository, "_lock_draft", AsyncMock(return_value=draft)),
        patch.object(
            repository,
            "_authorize",
            AsyncMock(
                return_value=_AuthorizationResult(
                    target=fixture.authorized, rejection=None
                )
            ),
        ) as authorize,
    ):
        commit = await repository.apply_draft(
            actor=actor,
            draft_id=draft.id,
            expected_selection_fingerprint=fingerprint,
            apply_interaction_key="apply-1",
            now=_NOW,
        )
    assert isinstance(commit.result, ExternalModelRejected)
    assert commit.result.code is expected
    assert commit.notice_plan is None
    if guard != "fingerprint":
        authorize.assert_not_awaited()
    fixture.agent_session_repository.set_applied_inference_profile.assert_not_awaited()
    fixture.session.flush.assert_not_awaited()
