"""Real retained Session diagnostic endpoints and their admin authority."""

import datetime
from unittest.mock import AsyncMock, create_autospec

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI

from azents.app import create_dummy_admin_app, create_dummy_public_app
from azents.core.auth.deps import CurrentUser, get_current_user
from azents.core.config import (
    AuthConfig,
    JWTConfig,
    RefreshTokenConfig,
    SignupTokenConfig,
)
from azents.core.deps import get_auth_config
from azents.core.enums import AgentSessionStatus, EventKind, WorkspaceUserRole
from azents.engine.events.historical_memory_projection import (
    project_historical_memory_event,
)
from azents.engine.events.historical_memory_projection_test import _native_artifact
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolCallPayload,
    CompactionSummaryPayload,
    Event,
    ReasoningPayload,
    SystemReminderPayload,
    UnknownAdapterOutputPayload,
    UserMessagePayload,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.session_execution_file import RDBSessionExecutionFile
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.archived_session_retention_operations import (
    ArchivedSessionRetentionOperations,
)
from azents.repos.lifecycle_target_test import seed_internal_session
from azents.repos.session_diagnostics import SessionDiagnosticRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.services.account_access import AccountAccessService
from azents.services.archived_session_retention import ArchivedSessionRetentionService
from azents.services.chat import ChatSessionService
from azents.services.chat.team_session_test import _service as _chat_service
from azents.services.session_diagnostics import SessionDiagnosticService
from azents.services.system_user_role.service import SystemUserRoleService


def _app(manager: SessionManager[WriteSession], *, system_admin: bool) -> FastAPI:
    """Use the actual Admin mount and role check with controlled role data."""
    app = create_dummy_admin_app()
    role_service = create_autospec(SystemUserRoleService, instance=True)
    role_service.require_system_admin = AsyncMock(return_value=system_admin)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="u" * 32, session_id="a" * 32, elevated=False
    )
    app.dependency_overrides[SystemUserRoleService] = lambda: role_service
    service = SessionDiagnosticService(
        repository=SessionDiagnosticRepository(session_manager=manager)
    )
    app.dependency_overrides[SessionDiagnosticService] = lambda: service
    return app


async def test_session_diagnostics_require_authenticated_system_admin() -> None:
    """Missing authentication cannot read retained content through Admin routes."""
    app = create_dummy_admin_app()
    app.dependency_overrides[get_auth_config] = lambda: AuthConfig(
        jwt=JWTConfig(secret_key="test-only-auth-key"),
        refresh_token=RefreshTokenConfig(),
        signup_token=SignupTokenConfig(),
    )
    app.dependency_overrides[AccountAccessService] = lambda: create_autospec(
        AccountAccessService, instance=True
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/debug/v1/sessions/" + "s" * 32,
            params={"workspace_id": "w" * 32},
        )
    assert response.status_code == 401


async def test_retained_internal_session_metadata_events_and_file_are_queryable(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Archived no-Conversation input/history remains readable only to admins."""
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        session_id, workspace_id = await seed_internal_session(
            session, suffix="diagnostic-route"
        )
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(
                status=AgentSessionStatus.ARCHIVED,
                archived_at=now,
                purge_after=now + datetime.timedelta(days=30),
                archive_retention_days_snapshot=30,
                archive_policy_revision=1,
            )
        )
        session.write_session.add(
            RDBSessionExecutionFile(
                session_id=session_id,
                path="summaries/source.md",
                content="Supplied summary text.",
                writable=False,
            )
        )
        session.write_session.add(
            RDBSessionExecutionFile(
                session_id=session_id,
                path="summaries/credential-boundary.md",
                content="prefix\napi_key=boundary-secret\nsuffix",
                writable=False,
            )
        )
        user = RDBEvent(
            session_id=session_id,
            kind=EventKind.USER_MESSAGE,
            payload=UserMessagePayload(
                sender_user_id=None,
                content="canonical input",
                attachments=[],
                metadata={"private_runtime_value": "must-not-project"},
                requested_inference_profile=None,
                applied_inference_profile=None,
            ).model_dump(mode="json"),
        )
        session.write_session.add(user)
        await session.write_session.flush()
        user_id = user.id
        call = RDBEvent(
            session_id=session_id,
            kind=EventKind.CLIENT_TOOL_CALL,
            payload=ClientToolCallPayload(
                call_id="read-call",
                name="read",
                arguments='{"path":"summaries/source.md","api_key":"credential-secret"}',
                wire_dialect="json_function",
                toolkit_source=None,
                native_artifact=_native_artifact(),
            ).model_dump(mode="json"),
        )
        session.write_session.add(call)
        await session.write_session.flush()
        call_id = call.id
        assistant = RDBEvent(
            session_id=session_id,
            kind=EventKind.ASSISTANT_MESSAGE,
            payload=AssistantMessagePayload(
                content="retained corrected output",
                attachments=[],
                native_artifact=_native_artifact(),
            ).model_dump(mode="json"),
            reverted=True,
        )
        session.write_session.add(assistant)
        session.write_session.add(
            RDBEvent(
                session_id=session_id,
                kind=EventKind.REASONING,
                payload=ReasoningPayload(
                    summary="hidden-reasoning-must-not-project",
                    native_artifact=_native_artifact(),
                ).model_dump(mode="json"),
            )
        )
    app = _app(rdb_session_manager, system_admin=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        metadata = await client.get(
            f"/debug/v1/sessions/{session_id}", params={"workspace_id": workspace_id}
        )
        assert metadata.status_code == 200
        assert metadata.json()["status"] == "archived"
        assert metadata.json()["archive_retention_days"] == 30
        first = await client.get(
            f"/debug/v1/sessions/{session_id}/events",
            params={"workspace_id": workspace_id, "limit": 1},
        )
        assert first.status_code == 200
        assert first.json()["items"][0]["event_id"] == user_id
        assert first.json()["next_cursor"] == user_id
        next_page = await client.get(
            f"/debug/v1/sessions/{session_id}/events",
            params={"workspace_id": workspace_id, "after": user_id},
        )
        assert next_page.status_code == 200
        items = next_page.json()["items"]
        assert items[0]["event_id"] == call_id
        assert "summaries/source.md" in items[0]["arguments"]
        assert "credential-secret" not in next_page.text
        assert items[1]["reverted"] is True
        assert "retained corrected output" in items[1]["text"]
        assert "native_artifact" not in next_page.text
        assert "hidden-reasoning-must-not-project" not in next_page.text
        assert "must-not-project" not in first.text
        file = await client.get(
            f"/debug/v1/sessions/{session_id}/file",
            params={
                "workspace_id": workspace_id,
                "path": "summaries/source.md",
                "limit": 8,
            },
        )
        assert file.status_code == 200
        assert file.json()["content"] == "Supplied"
        assert file.json()["next_offset"] == 8
        assert file.json()["writable"] is False
        safe_parts: list[str] = []
        cursor = 0
        while True:
            boundary = await client.get(
                f"/debug/v1/sessions/{session_id}/file",
                params={
                    "workspace_id": workspace_id,
                    "path": "summaries/credential-boundary.md",
                    "offset": cursor,
                    "limit": 3,
                },
            )
            assert boundary.status_code == 200
            part = boundary.json()
            assert len(part["content"]) <= 3
            safe_parts.append(part["content"])
            if part["next_offset"] is None:
                break
            assert part["next_offset"] == cursor + len(part["content"])
            cursor = part["next_offset"]
        assert "".join(safe_parts) == "prefix\napi_key=[REDACTED]\nsuffix"
        inside_secret = await client.get(
            f"/debug/v1/sessions/{session_id}/file",
            params={
                "workspace_id": workspace_id,
                "path": "summaries/credential-boundary.md",
                "offset": 15,
                "limit": 16,
            },
        )
        assert inside_secret.status_code == 200
        assert "boundary-secret" not in inside_secret.text
        wrong_scope = await client.get(
            f"/debug/v1/sessions/{session_id}", params={"workspace_id": "w" * 32}
        )
        assert wrong_scope.status_code == 404
        missing_file = await client.get(
            f"/debug/v1/sessions/{session_id}/file",
            params={"workspace_id": workspace_id, "path": "../missing"},
        )
        assert missing_file.status_code == 404
    denied_app = _app(rdb_session_manager, system_admin=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=denied_app), base_url="http://test"
    ) as client:
        for suffix in ("", "/events", "/file"):
            response = await client.get(
                f"/debug/v1/sessions/{session_id}{suffix}",
                params={"workspace_id": workspace_id, "path": "summaries/source.md"},
            )
            assert response.status_code == 403


async def test_retained_context_is_admin_only_redacted_before_truncation(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Canonical reminders/summaries are auditable without source/native expansion."""
    now = datetime.datetime.now(datetime.UTC)
    native = _native_artifact().model_copy(
        update={
            "item": {
                "opaque": "native-sdk-opaque-must-not-project",
                "api_key": "native-sdk-credential-must-not-project",
            }
        }
    )
    full_text = (
        "Retained canonical context.\n"
        'api_key="context-credential-start' + "s" * 70_000 + 'context-credential-end"\n'
        "Authorization: Bearer context-bearer-credential\n"
        "Reference: https://example.test/audit?token=context-url-credential\n"
        "Safe context after credential redaction.\n" + "x" * 70_000
    )
    canonical_payloads = [
        (EventKind.SYSTEM_REMINDER, SystemReminderPayload(text=full_text)),
        (
            EventKind.COMPACTION_SUMMARY,
            CompactionSummaryPayload(
                compaction_id="retained-compaction",
                content=full_text,
                covered_until_event_id=None,
                reason="compaction-private-reason-must-not-project",
            ),
        ),
    ]
    context_ids: list[str] = []
    async with rdb_session_manager() as session:
        session_id, workspace_id = await seed_internal_session(
            session, suffix="diagnostic-retained-context"
        )
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(
                status=AgentSessionStatus.ARCHIVED,
                archived_at=now,
                purge_after=now + datetime.timedelta(days=30),
                archive_retention_days_snapshot=30,
                archive_policy_revision=1,
            )
        )
        for kind, payload in canonical_payloads:
            row = RDBEvent(
                session_id=session_id,
                kind=kind,
                payload=payload.model_dump(mode="json"),
            )
            session.write_session.add(row)
            await session.write_session.flush()
            context_ids.append(row.id)
            assert (
                project_historical_memory_event(
                    Event(
                        id=row.id,
                        session_id=session_id,
                        kind=kind,
                        payload=payload,
                        created_at=row.created_at,
                    )
                )
                is None
            )
        session.write_session.add_all(
            [
                RDBEvent(
                    session_id=session_id,
                    kind=EventKind.ASSISTANT_MESSAGE,
                    payload=AssistantMessagePayload(
                        content="Safe canonical assistant output.",
                        native_artifact=native,
                    ).model_dump(mode="json"),
                ),
                RDBEvent(
                    session_id=session_id,
                    kind=EventKind.REASONING,
                    payload=ReasoningPayload(
                        summary="hidden-reasoning-must-not-project",
                        native_artifact=native,
                    ).model_dump(mode="json"),
                ),
                RDBEvent(
                    session_id=session_id,
                    kind=EventKind.UNKNOWN_ADAPTER_OUTPUT,
                    payload=UnknownAdapterOutputPayload(
                        native_artifact=native,
                        reason="native-output-reason-must-not-project",
                    ).model_dump(mode="json"),
                ),
            ]
        )
    app = _app(rdb_session_manager, system_admin=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/debug/v1/sessions/{session_id}/events",
            params={"workspace_id": workspace_id},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 3
        for event_id in context_ids:
            projected = next(item for item in items if item["event_id"] == event_id)
            assert projected["text"].startswith("Retained canonical context.")
            assert "Safe context after credential redaction." in projected["text"]
            assert "api_key=[REDACTED]" in projected["text"]
            assert len(projected["text"]) == 65_536
            assert projected["truncated"] is True
        assert "Safe canonical assistant output." in response.text
        for excluded in (
            "context-credential-start",
            "context-credential-end",
            "context-bearer-credential",
            "context-url-credential",
            "compaction-private-reason",
            "native_artifact",
            "native-sdk-opaque",
            "native-sdk-credential",
            "hidden-reasoning",
            "native-output-reason",
        ):
            assert excluded not in response.text
        wrong_scope = await client.get(
            f"/debug/v1/sessions/{session_id}/events",
            params={"workspace_id": "w" * 32},
        )
        assert wrong_scope.status_code == 404
    denied_app = _app(rdb_session_manager, system_admin=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=denied_app), base_url="http://test"
    ) as client:
        denied = await client.get(
            f"/debug/v1/sessions/{session_id}/events",
            params={"workspace_id": workspace_id},
        )
        assert denied.status_code == 403


@pytest.mark.parametrize(
    "status", [AgentSessionStatus.ACTIVE, AgentSessionStatus.ARCHIVED]
)
async def test_internal_execution_is_absent_from_authorized_public_routes(
    rdb_session_manager: SessionManager[WriteSession], status: AgentSessionStatus
) -> None:
    """Internal executions are hidden even when a real member can read Conversation."""
    async with rdb_session_manager() as session:
        internal_id, workspace_id = await seed_internal_session(
            session, suffix=f"diagnostic-public-exclusion-{status.value}"
        )
        internal = await session.read_session.get(RDBAgentSession, internal_id)
        assert internal is not None
        agent_id = internal.agent_id
        public_id = await session.read_session.scalar(
            sa.select(RDBConversation.session_id)
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBConversation.session_id,
            )
            .where(RDBAgentSession.agent_id == agent_id)
        )
        assert public_id is not None
        assert await session.read_session.get(RDBConversation, internal_id) is None
        user = await UserRepository().create(
            session, UserCreate(email=f"public-exclusion-{status.value}@example.test")
        )
        session.write_session.add(
            RDBWorkspaceUser(
                workspace_id=workspace_id,
                user_id=user.id,
                name="Authorized public reader",
                role=WorkspaceUserRole.MEMBER,
            )
        )
        if status is AgentSessionStatus.ARCHIVED:
            now = datetime.datetime.now(datetime.UTC)
            internal.status = status
            internal.archived_at = now
            internal.purge_after = now + datetime.timedelta(days=30)
            internal.archive_retention_days_snapshot = 30
            internal.archive_policy_revision = 1
        user_id = user.id
    app = create_dummy_public_app()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=user_id, session_id="a" * 32, elevated=False
    )
    chat = _chat_service(rdb_session_manager)
    app.dependency_overrides[ChatSessionService] = lambda: chat
    retention = ArchivedSessionRetentionService(
        ArchivedSessionRetentionOperations(
            ArchivedSessionRetentionRepository(),
            rdb_session_manager,
            rdb_session_manager,
        )
    )
    app.dependency_overrides[ArchivedSessionRetentionService] = lambda: retention
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        visible = await client.get(f"/chat/v1/agents/{agent_id}/sessions/{public_id}")
        assert visible.status_code == 200
        assert visible.json()["id"] == public_id
        for directory_status in ("active", "archived"):
            directory = await client.get(
                f"/chat/v1/agents/{agent_id}/sessions",
                params={"status": directory_status},
            )
            assert directory.status_code == 200
            ids = [item["id"] for item in directory.json()["items"]]
            assert internal_id not in ids
            if directory_status == "active":
                assert public_id in ids
        for route in (
            f"/chat/v1/agents/{agent_id}/sessions/{internal_id}",
            f"/chat/v1/sessions/{internal_id}/history",
        ):
            excluded = await client.get(route)
            assert excluded.status_code == 404
