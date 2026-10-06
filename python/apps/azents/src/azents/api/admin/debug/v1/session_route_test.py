"""Real retained Session diagnostic endpoints and their admin authority."""

import datetime
from unittest.mock import AsyncMock, create_autospec

import httpx
import sqlalchemy as sa
from fastapi import FastAPI

from azents.app import create_dummy_admin_app
from azents.core.auth.deps import CurrentUser, get_current_user
from azents.core.config import (
    AuthConfig,
    JWTConfig,
    RefreshTokenConfig,
    SignupTokenConfig,
)
from azents.core.deps import get_auth_config
from azents.core.enums import AgentSessionStatus, EventKind
from azents.engine.events.historical_memory_projection_test import _native_artifact
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolCallPayload,
    ReasoningPayload,
    UserMessagePayload,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.session_execution_file import RDBSessionExecutionFile
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.lifecycle_target_test import seed_internal_session
from azents.repos.session_diagnostics import SessionDiagnosticRepository
from azents.services.account_access import AccountAccessService
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
