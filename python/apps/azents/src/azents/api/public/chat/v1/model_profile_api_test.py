"""Native HTTP coverage for Session model-profile validation and atomicity."""

import datetime
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from unittest.mock import Mock, create_autospec

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.api.public.chat.v1.data import ChatSessionModelProfileResponse
from azents.api.public.chat.v1.route_test_support import focused_chat_app
from azents.core.agent_session_data import AgentSession, SessionAgent
from azents.core.auth.deps import CurrentUser, get_current_user
from azents.core.enums import (
    AgentLifecycleStatus,
)
from azents.core.inference_profile import (
    RequestedInferenceProfile,
    SessionAppliedInferenceProfile,
    SessionInferenceState,
    validate_requested_profile_against_options,
)
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelReasoningCapabilities,
    ModelReasoningEffort,
)
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.active_profile_admission import (
    ActiveProfileAdmissionRepository,
    CapturedProfileAdmission,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.chat_write_operations import ChatWriteOperationsRepository
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.chat_write_request.data import (
    ChatWriteRequest,
    ChatWriteRequestCreate,
    IdempotentChatWriteResult,
)
from azents.repos.input_attachment_claim import InputAttachmentClaimRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.message import MessageRepository
from azents.repos.session_model_profile.repository import (
    SessionModelProfileRepository,
)
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUser
from azents.services.chat import ChatSessionService
from azents.services.chat_write import ChatWriteService
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
    make_test_selectable_model_options,
)
from azents.testing.routine import make_test_routine_execution

from .chat_api_test import _StopChatService

_NOW = datetime.datetime(2026, 10, 14, tzinfo=datetime.UTC)


@asynccontextmanager
async def _session_manager() -> AsyncIterator[WriteSession]:
    """Supply real session capabilities without a database or listener."""
    async with AsyncSession() as session:
        yield ReadWriteSession(session)


@dataclass(frozen=True)
class _ProfileHTTPFixture:
    """HTTP boundary backed by real profile orchestration and mocked storage."""

    client: httpx.AsyncClient
    sessions: Mock
    writes: Mock
    current_session: Callable[[], AgentSession]
    records: dict[str, ChatWriteRequest]
    execution_repositories: list[Mock]


@pytest.fixture
async def profile_http() -> AsyncIterator[_ProfileHTTPFixture]:
    """Keep API parsing, service, repository ordering, and profile validation real."""
    chat = _StopChatService()
    current = chat.result.value
    prepared = SessionInferenceState(
        model_target_label="Quality",
        model_selection=make_test_model_selection(),
        model_settings=make_test_model_settings(),
        reasoning_effort=None,
        enabled_execution_options=[],
        effective_context_window_tokens=1000,
        effective_auto_compaction_threshold_tokens=500,
        resolved_at=_NOW,
    )
    current = current.model_copy(update={"inference_state": prepared})
    options = []
    for label, supported in (
        ("Quality", [ModelExecutionOptionId.FAST]),
        ("Fast", []),
        ("Astra", [ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST]),
        ("Sol", [ModelExecutionOptionId.FAST, ModelExecutionOptionId.ULTRAFAST]),
    ):
        selection = make_test_model_selection(model_identifier=label)
        selection.supported_execution_options = supported
        selection.normalized_capabilities = ModelCapabilities(
            reasoning=ModelReasoningCapabilities(
                supported=True,
                effort_levels=[ModelReasoningEffort.HIGH, ModelReasoningEffort.XHIGH],
            )
        )
        options.extend(make_test_selectable_model_options(selection, label=label))
    agent = Agent.model_construct(
        id=current.agent_id,
        workspace_id=current.workspace_id,
        lifecycle_status=AgentLifecycleStatus.ACTIVE,
        selectable_model_options=options,
    )
    agents = create_autospec(AgentRepository, instance=True)
    agents.lock_by_id.return_value = agent
    sessions = create_autospec(AgentSessionRepository, instance=True)
    sessions.lock_by_id.side_effect = lambda *_: current
    sessions.get_root_session_agent_by_session_id.return_value = (
        SessionAgent.model_construct(agent_session_id=current.id)
    )
    memberships = create_autospec(WorkspaceUserRepository, instance=True)
    memberships.get_by_workspace_and_user.return_value = WorkspaceUser.model_construct(
        id="member-1", workspace_id=current.workspace_id, user_id="user-1"
    )
    records: dict[str, ChatWriteRequest] = {}
    writes = create_autospec(ChatWriteRequestRepository, instance=True)

    async def lookup(
        session: WriteSession,
        *,
        session_id: str,
        requester_user_id: str,
        client_request_id: str,
    ) -> ChatWriteRequest | None:
        del session, session_id, requester_user_id
        return records.get(client_request_id)

    async def create(
        session: WriteSession, request: ChatWriteRequestCreate
    ) -> IdempotentChatWriteResult:
        del session
        record = ChatWriteRequest(
            id=f"write-{len(records)}",
            created_at=_NOW,
            **request.model_dump(),
        )
        records[record.client_request_id] = record
        return IdempotentChatWriteResult(record=record, created=True)

    async def apply(
        session: WriteSession,
        *,
        session_id: str,
        model_target_label: str,
        reasoning_effort: ModelReasoningEffort | None,
        enabled_execution_options: list[ModelExecutionOptionId],
    ) -> AgentSession:
        nonlocal current
        del session
        assert session_id == current.id
        current = current.model_copy(
            update={
                "applied_profile_generation": current.applied_profile_generation + 1,
                "applied_inference_profile": SessionAppliedInferenceProfile(
                    model_target_label=model_target_label,
                    reasoning_effort=reasoning_effort,
                    enabled_execution_options=enabled_execution_options,
                ),
            }
        )
        return current

    writes.get_by_client_request_id.side_effect = lookup
    writes.create_idempotent.side_effect = create
    sessions.set_applied_inference_profile.side_effect = apply
    admission = create_autospec(ActiveProfileAdmissionRepository, instance=True)

    async def validate(
        session: WriteSession,
        *,
        agent: Agent,
        profile: RequestedInferenceProfile,
        captured: CapturedProfileAdmission | None,
    ) -> None:
        """Replace metadata retrieval only; use the product capability validator."""
        del session, captured
        validate_requested_profile_against_options(
            agent.selectable_model_options, profile
        )

    admission.validate_in_session.side_effect = validate
    profiles = SessionModelProfileRepository(
        agent_repository=agents,
        agent_session_repository=sessions,
        workspace_user_repository=memberships,
        chat_write_request_repository=writes,
        active_profile_repository=admission,
        session_manager=_session_manager,
    )
    runs = create_autospec(AgentRunRepository, instance=True)
    messages = create_autospec(MessageRepository, instance=True)
    mailbox = create_autospec(MailboxRepository, instance=True)
    attachments = create_autospec(InputAttachmentClaimRepository, instance=True)
    mailbox_admission = create_autospec(MailboxAdmissionRepository, instance=True)
    service = ChatWriteService(
        operations=ChatWriteOperationsRepository(
            routine_execution_repository=make_test_routine_execution(),
            agent_repository=agents,
            agent_session_repository=sessions,
            workspace_user_repository=memberships,
            agent_run_repository=runs,
            chat_write_request_repository=writes,
            message_repository=messages,
            attachment_claim_repository=attachments,
            mailbox_repository=mailbox,
            mailbox_admission_repository=mailbox_admission,
            session_model_profile_repository=profiles,
            active_profile_repository=admission,
            session_manager=_session_manager,
        )
    )
    app = focused_chat_app("/sessions/{session_id}/model-profile")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="user-1", session_id="auth-session"
    )
    app.dependency_overrides[ChatSessionService] = lambda: chat
    app.dependency_overrides[ChatWriteService] = lambda: service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield _ProfileHTTPFixture(
            client=client,
            sessions=sessions,
            writes=writes,
            current_session=lambda: current,
            records=records,
            execution_repositories=[
                runs,
                messages,
                mailbox,
                attachments,
                mailbox_admission,
            ],
        )


def _payload(
    target: str,
    enabled: list[str],
    *,
    client_request_id: str,
    effort: str | None,
) -> dict[str, object]:
    """Build the public request at its HTTP egress boundary."""
    return {
        "client_request_id": client_request_id,
        "model_target_label": target,
        "reasoning_effort": effort,
        "enabled_execution_options": enabled,
    }


_PROFILE_URL = "/chat/v1/sessions/1123456789abcdef0123456789abcdef/model-profile"


@pytest.mark.parametrize(
    ("target", "enabled"),
    [
        ("Quality", []),
        ("Quality", ["fast"]),
        ("Astra", ["ultrafast"]),
        ("Sol", ["ultrafast"]),
    ],
)
async def test_valid_target_speed_profiles_are_idempotent_without_execution(
    profile_http: _ProfileHTTPFixture, target: str, enabled: list[str]
) -> None:
    """Every removed positive E2E permutation preserves state-only replacement."""
    prepared = profile_http.current_session().inference_state
    payload = _payload(
        target, enabled, client_request_id="profile-request", effort="xhigh"
    )
    first = await profile_http.client.put(_PROFILE_URL, json=payload)
    replay = await profile_http.client.put(_PROFILE_URL, json=payload)
    assert first.status_code == replay.status_code == 200
    response = ChatSessionModelProfileResponse.model_validate_json(first.text)
    assert response.model_target_label == target
    assert response.reasoning_effort is ModelReasoningEffort.XHIGH
    assert response.enabled_execution_options == [
        ModelExecutionOptionId(option) for option in enabled
    ]
    assert replay.json() == first.json()
    assert len(profile_http.records) == 1
    current = profile_http.current_session()
    assert current.applied_profile_generation == 1
    assert current.applied_inference_profile == SessionAppliedInferenceProfile(
        model_target_label=target,
        reasoning_effort=ModelReasoningEffort.XHIGH,
        enabled_execution_options=[
            ModelExecutionOptionId(option) for option in enabled
        ],
    )
    assert current.inference_state == prepared
    profile_http.sessions.set_applied_inference_profile.assert_awaited_once()
    profile_http.writes.create_idempotent.assert_awaited_once()
    conflict = await profile_http.client.put(
        _PROFILE_URL,
        json=_payload(
            target,
            [] if enabled else ["fast"],
            client_request_id="profile-request",
            effort="xhigh",
        ),
    )
    assert conflict.status_code == 409
    assert len(profile_http.records) == 1
    assert profile_http.current_session() == current
    assert profile_http.current_session().inference_state == prepared
    profile_http.sessions.set_applied_inference_profile.assert_awaited_once()
    assert all(
        not repository.mock_calls for repository in profile_http.execution_repositories
    )


@pytest.mark.parametrize(
    ("target", "enabled", "detail"),
    [
        ("Missing", [], "Model target label is not available"),
        ("Fast", ["fast"], "Enabled execution option is not supported by the model."),
        (
            "Fast",
            ["ultrafast"],
            "Enabled execution option is not supported by the model.",
        ),
        (
            "Quality",
            ["ultrafast"],
            "Enabled execution option is not supported by the model.",
        ),
        ("Astra", ["fast", "ultrafast"], None),
        ("Astra", ["ultrafast", "fast"], None),
        ("Astra", ["ultrafast", "ultrafast"], None),
        ("Astra", ["unknown-speed"], None),
    ],
)
async def test_invalid_profiles_leave_seeded_ultrafast_and_execution_unchanged(
    profile_http: _ProfileHTTPFixture,
    target: str,
    enabled: list[str],
    detail: str | None,
) -> None:
    """HTTP shape and domain failures cannot write identity or mutate the profile."""
    seed = await profile_http.client.put(
        _PROFILE_URL,
        json=_payload(
            "Astra", ["ultrafast"], client_request_id="seed-profile", effort="high"
        ),
    )
    assert seed.status_code == 200
    before = dict(profile_http.records)
    before_session = profile_http.current_session().model_copy(deep=True)
    response = await profile_http.client.put(
        _PROFILE_URL,
        json=_payload(
            target, enabled, client_request_id="invalid-profile", effort=None
        ),
    )
    assert response.status_code == 422
    if detail is not None:
        assert response.json() == {"detail": detail}
    assert profile_http.records == before
    assert profile_http.current_session() == before_session
    profile_http.sessions.set_applied_inference_profile.assert_awaited_once()
    profile_http.writes.create_idempotent.assert_awaited_once()
    assert all(
        not repository.mock_calls for repository in profile_http.execution_repositories
    )
