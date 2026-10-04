"""Current exact support gates public admission without rewriting saved choices."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.active_model_capabilities import (
    ActiveModelCapabilitiesUnavailable,
    ActiveModelMetadataUnavailable,
    CapturedStoredChoice,
    ConfiguredModelIdentity,
)
from azents.core.agent import AgentModelSelection
from azents.core.agent_session_data import AgentSession
from azents.core.agent_session_input_data import (
    AgentSessionInputInvalidInferenceProfile,
)
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionRunState,
    AgentSessionStatus,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.llm_catalog import ModelReasoningCapabilities, ModelReasoningEffort
from azents.core.model_catalog_source import decode_catalog_source
from azents.engine.run.input import InputMessage
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.active_model_capabilities import ActiveModelCapabilitiesRepository
from azents.repos.active_model_capabilities_data import CapturedActiveChoiceInputs
from azents.repos.active_profile_admission import (
    ActiveProfileAdmissionRepository,
    ActiveProfileCaptureRequired,
)
from azents.repos.agent.data import Agent
from azents.repos.agent_session_input_operations import (
    AgentSessionInputOperationsRepository,
)
from azents.repos.chat_write_operations import ChatWriteOperationsRepository
from azents.repos.session_model_profile.repository import SessionModelProfileRepository
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_options,
)


def _agent() -> Agent:
    saved = make_test_model_selection(model_identifier="gpt-6-sol")
    saved.normalized_capabilities.reasoning = ModelReasoningCapabilities(
        supported=True, effort_levels=[ModelReasoningEffort.MAX]
    )
    options = make_test_selectable_model_options(saved)
    return Agent.model_construct(
        id="agent",
        workspace_id="workspace",
        main_model_label="default",
        lightweight_model_label="default",
        selectable_model_options=options,
    )


def _capture(agent: Agent, *, missing: bool) -> CapturedActiveChoiceInputs:
    selection = agent.selectable_model_options[0].candidates[0].model_selection
    identity = ConfiguredModelIdentity.from_selection(selection)
    models = decode_catalog_source(
        json.dumps(
            {
                selection.model_identifier: {
                    "litellm_provider": "openai",
                    "mode": "chat",
                    "supported_endpoints": ["/v1/responses"],
                    "supported_modalities": ["text"],
                    "supported_output_modalities": ["text"],
                    "supports_function_calling": True,
                    "supports_reasoning": True,
                    "reasoning_effort_levels": ["low", "high"],
                    "max_input_tokens": 128000,
                }
            }
        ).encode()
    ).models
    choices = (
        (ActiveModelMetadataUnavailable(identity, "exact_entry_unavailable"),)
        if missing
        else (
            CapturedStoredChoice(
                identity, None, models, (), selection.model_developer, "catalog"
            ),
        )
    )
    return CapturedActiveChoiceInputs("workspace", choices, (), None, ())


@pytest.mark.parametrize(
    "case",
    [
        "removed",
        "supported",
        "missing",
        "source-drift",
        "identity-drift",
        "settings-drift",
        "intent-drift",
    ],
)
async def test_exact_active_profile_capture_and_fences(case: str) -> None:
    agent = _agent()
    before = agent.model_dump(mode="json")
    profile = RequestedInferenceProfile(
        model_target_label="default",
        reasoning_effort="high" if case == "supported" else "max",
        enabled_execution_options=[],
    )
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    active = AsyncMock(spec=ActiveModelCapabilitiesRepository)
    active.capture_exact_choices.return_value = _capture(
        agent, missing=case == "missing"
    )
    active.inputs_match_in_session.return_value = case != "source-drift"
    helper = ActiveProfileAdmissionRepository(active)
    with pytest.raises(ActiveProfileCaptureRequired) as needed:
        await helper.validate_in_session(
            session, agent=agent, profile=profile, captured=None
        )
    active.capture_exact_choices.assert_not_awaited()
    active.inputs_match_in_session.assert_not_awaited()
    captured = await helper.capture(needed.value.choice)
    active.capture_exact_choices.assert_awaited_once()
    assert agent.model_dump(mode="json") == before
    if case == "identity-drift":
        candidate = agent.selectable_model_options[0].candidates[0]
        candidate.model_selection = AgentModelSelection.model_validate(
            {
                **candidate.model_selection.model_dump(mode="json"),
                "model_identifier": "other",
            }
        )
    elif case == "settings-drift":
        agent.selectable_model_options[0].candidates[
            0
        ].settings.context_window_tokens = 1000
    elif case == "intent-drift":
        profile = profile.model_copy(
            update={"reasoning_effort": ModelReasoningEffort.LOW}
        )
    if case == "supported":
        await helper.validate_in_session(
            session, agent=agent, profile=profile, captured=captured
        )
    else:
        error = ActiveModelCapabilitiesUnavailable if case == "missing" else ValueError
        with pytest.raises(error) as failed:
            await helper.validate_in_session(
                session, agent=agent, profile=profile, captured=captured
            )
        expected = (
            "Reasoning effort is not supported"
            if case == "removed"
            else "exact_entry_unavailable"
            if case == "missing"
            else "Model metadata changed"
            if case == "source-drift"
            else "Model configuration changed"
        )
        assert expected in str(failed.value)
    if not case.endswith("drift") or case == "source-drift":
        assert agent.model_dump(mode="json") == before


@pytest.mark.parametrize("route", ["buffered", "team", "user", "edit", "profile"])
@pytest.mark.parametrize("revoked", [False, True])
async def test_public_new_admission_compiles_after_scope_and_rechecks_authority(
    route: str,
    revoked: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every real wrapper exits before writes and rejects before mailbox admission."""
    agent = _agent()
    agent.lifecycle_status = AgentLifecycleStatus.ACTIVE
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    scopes = 0
    events: list[str] = []

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        nonlocal scopes
        scopes += 1
        events.append("enter")
        try:
            yield session
        finally:
            scopes -= 1
            events.append("exit")

    active = AsyncMock(spec=ActiveModelCapabilitiesRepository)

    def capture(*, workspace_id: str, identities: object) -> CapturedActiveChoiceInputs:
        del workspace_id, identities
        assert scopes == 0
        events.append("capture")
        assert not _raw_session.commit.await_count
        return _capture(agent, missing=False)

    active.capture_exact_choices.side_effect = capture
    active.inputs_match_in_session.return_value = True
    helper = ActiveProfileAdmissionRepository(active)
    agents = AsyncMock()
    agents.lock_by_id.side_effect = [agent, None if revoked else agent]
    sessions = AsyncMock()
    current = AgentSession.model_construct(
        id="session",
        agent_id=agent.id,
        workspace_id=agent.workspace_id,
        status=AgentSessionStatus.ACTIVE,
        session_kind=AgentSessionKind.ROOT,
        product_mode=AgentSessionProductMode.TEAM,
        associated_user_id=None,
        run_state=AgentSessionRunState.IDLE,
        pending_command_id=None,
    )
    sessions.lock_by_id.return_value = current
    writes = AsyncMock()
    writes.get_by_client_request_id.return_value = None
    writes.get_by_session_creation_client_request_id.return_value = None
    mailbox = AsyncMock()
    attachments = AsyncMock()
    root = AsyncMock()
    membership = AsyncMock()
    profile = RequestedInferenceProfile(
        model_target_label="default",
        reasoning_effort="max",
        enabled_execution_options=[],
    )
    message = InputMessage(text="must reject", headers=[], metadata={}, attachments=[])
    if route in {"buffered", "team", "user"}:
        operations = AgentSessionInputOperationsRepository(
            agent_repository=agents,
            agent_session_repository=sessions,
            agent_project_preset_repository=AsyncMock(),
            agent_project_catalog_repository=AsyncMock(),
            agent_project_default_repository=AsyncMock(),
            agent_runtime_repository=AsyncMock(),
            root_session_repository=root,
            chat_write_request_repository=writes,
            session_workspace_project_repository=AsyncMock(),
            workspace_user_repository=membership,
            attachment_claim_repository=attachments,
            mailbox_repository=AsyncMock(),
            mailbox_database_repository=AsyncMock(),
            mailbox_admission_repository=mailbox,
            active_profile_repository=helper,
            session_manager=manager,
        )
        if route == "buffered":
            outcome = await operations.create_buffered_agent_input(
                agent_id=agent.id,
                agent_session_id="session",
                message=message,
                inference_profile=profile,
                user_id="user",
                request_payload={},
                client_request_id="new",
            )
        elif route == "team":
            outcome = await operations.create_team_session_with_buffered_input(
                agent_id=agent.id,
                message=message,
                inference_profile=profile,
                user_id="user",
                existing_project_paths=[],
                setup_actions=[],
                request_payload={},
                client_request_id="new",
            )
        else:
            outcome = await operations.create_user_session_with_buffered_input(
                agent_id=agent.id,
                message=message,
                inference_profile=profile,
                user_id="user",
                existing_project_paths=[],
                setup_actions=[],
                request_payload={},
                client_request_id="new",
            )
        assert isinstance(outcome, Failure)
        if not revoked:
            assert isinstance(outcome.error, AgentSessionInputInvalidInferenceProfile)
            assert (
                outcome.error.reason
                == "Reasoning effort is not supported by model target"
            )
    elif route == "edit":
        operations = ChatWriteOperationsRepository(
            agent_repository=agents,
            agent_session_repository=sessions,
            workspace_user_repository=membership,
            agent_run_repository=AsyncMock(),
            chat_write_request_repository=writes,
            message_repository=AsyncMock(),
            attachment_claim_repository=attachments,
            mailbox_repository=AsyncMock(),
            mailbox_admission_repository=mailbox,
            session_model_profile_repository=AsyncMock(),
            active_profile_repository=helper,
            session_manager=manager,
        )
        monkeypatch.setattr(
            operations, "_lock_and_reauthorize_session", AsyncMock(return_value=current)
        )
        with pytest.raises(
            ValueError,
            match="not active" if revoked else "Reasoning effort is not supported",
        ):
            await operations.create_idempotent_edit_input(
                agent_id=agent.id,
                session_id="session",
                user_id="user",
                client_request_id="new",
                message_id="message",
                text="reject",
                inference_profile=profile,
                metadata={},
                attachments=[],
                file_parts=[],
                payload={},
            )
    else:
        operations = SessionModelProfileRepository(
            agents,
            sessions,
            membership,
            writes,
            helper,
            manager,
        )
        monkeypatch.setattr(
            operations, "lock_writable_root", AsyncMock(return_value=current)
        )
        with pytest.raises(
            ValueError,
            match="not active" if revoked else "Reasoning effort is not supported",
        ):
            await operations.replace_web_profile(
                agent_id=agent.id,
                session_id="session",
                user_id="user",
                client_request_id="new",
                profile=profile,
                payload={},
            )
    assert events == ["enter", "exit", "capture", "enter", "exit"]
    writes.create_idempotent.assert_not_awaited()
    mailbox.enqueue_in_session.assert_not_awaited()
    attachments.claim_input_attachments.assert_not_awaited()
    root.create_root_session.assert_not_awaited()
    sessions.set_applied_inference_profile.assert_not_awaited()
    active.capture_exact_choices.assert_awaited_once()
    if revoked:
        active.inputs_match_in_session.assert_not_awaited()
    else:
        active.inputs_match_in_session.assert_awaited_once()
