"""Generic metadata writes cannot bypass Google policy/reconnect authority."""

import dataclasses
from typing import Literal
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success

from azents.core.enums import WorkspaceUserRole
from azents.core.google_oauth import GoogleConnectionStatus
from azents.core.google_workspace_policy import drive_access
from azents.core.toolkit_ownership import PersonalToolkitAccessMode, ToolkitOwnerKind
from azents.engine.tools.google import GoogleToolkitProvider
from azents.rdb.models.google_oauth import RDBGoogleConnection
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.toolkit.personal_management_test import Harness
from azents.repos.toolkit.personal_management_test import (
    fixture as fixture,  # noqa: PLC0414 -- isolated real database foundation
)
from azents.repos.toolkit.personal_management_test import (
    harness as harness,  # noqa: PLC0414 -- existing owner/manager service fixture
)
from azents.repos.toolkit_operations.owned import AgentToolkitOperationsRepository
from azents.services.google_oauth.data import GoogleConnectionOutput
from azents.services.google_oauth.runtime import GoogleRuntimeService
from azents.services.google_oauth.service import GoogleOAuthService
from azents.services.google_workspace.transport import GoogleWorkspaceSdk
from azents.services.toolkit.data import InvalidConfig, ToolkitUpdateInput

Owner = Literal["workspace", "agent", "user"]
_SCOPES = ("email", "https://www.googleapis.com/auth/gmail.readonly", "openid")
_CONFIG: dict[str, object] = {
    "services": [],
    "oauth_request_scopes": list(_SCOPES),
    "timeout": 30,
}


@pytest.mark.parametrize("owner", ["workspace", "agent", "user"])
@pytest.mark.parametrize("edit", ["stale_services", "scope_intent", "metadata"])
async def test_generic_google_updates_preserve_policy_and_current_grant(
    harness: Harness, owner: Owner, edit: str
) -> None:
    h = harness
    f = h.foundation
    shared = h.common.operations_repository
    common = dataclasses.replace(
        h.common,
        toolkit_registry={
            **h.common.toolkit_registry,
            "google": GoogleToolkitProvider(
                runtime=Mock(spec=GoogleRuntimeService),
                sdk=Mock(spec=GoogleWorkspaceSdk),
                files=None,
            ),
        },
        owned_operations=AgentToolkitOperationsRepository(
            toolkit_repo=shared.toolkit_repository,
            mcp_oauth_connection_repo=shared.oauth_connection_repository,
            agent_repo=shared.agent_repository,
            namespace_repo=shared.namespace_repository,
            agent_admin_repo=AgentAdminRepository(),
            github_user_installation_repo=shared.github_installation_repository,
            session_manager=f.writes,
            shared_operations=shared,
        ),
    )
    async with f.writes() as session:
        membership = (
            await session.write_session.execute(
                sa.update(RDBWorkspaceUser)
                .where(
                    RDBWorkspaceUser.user_id == f.user_id,
                    RDBWorkspaceUser.workspace_id == f.workspace_ids[0],
                )
                .values(role=WorkspaceUserRole.OWNER)
                .returning(RDBWorkspaceUser.id)
            )
        ).scalar_one()
        toolkit = RDBToolkitConfig(
            owner_kind=ToolkitOwnerKind(owner),
            workspace_id=f.workspace_ids[0],
            owner_agent_id=f.agent_ids[0] if owner == "agent" else None,
            owner_user_id=f.user_id if owner == "user" else None,
            personal_access_mode=PersonalToolkitAccessMode.ALL
            if owner == "user"
            else None,
            toolkit_type="google",
            slug="google",
            name="Google",
            config=_CONFIG,
            description="Saved description",
            prompt="Saved prompt",
            revision=7,
        )
        session.write_session.add(toolkit)
        await session.write_session.flush()
        grant = RDBGoogleConnection(
            toolkit_id=toolkit.id,
            client_id="same-client",
            encrypted_payload="opaque-current-grant",
            status=GoogleConnectionStatus.CONNECTED,
        )
        session.write_session.add(grant)
        await session.write_session.flush()
        toolkit_id, grant_id = toolkit.id, grant.id
    google = Mock(spec=GoogleOAuthService)
    google.status = AsyncMock(
        return_value=GoogleConnectionOutput(
            toolkit_id=toolkit_id,
            revision=7,
            connection_id=grant_id,
            status="connected",
            identity=None,
            services=(),
            oauth_request_scopes=_SCOPES,
            granted_scopes=None,
            timeout=30,
            accesses=(),
            drive_access=drive_access((), None),
            renewable=True,
            service_access_verified=False,
        )
    )
    personal = dataclasses.replace(h.service, common=common, google=google)
    update: ToolkitUpdateInput
    if edit == "metadata":
        update = {"name": "Renamed", "description": "Edited", "prompt": "Safe"}
    else:
        submitted = dict(_CONFIG)
        if edit == "stale_services":
            submitted["services"] = ["gmail"]
        else:
            submitted["oauth_request_scopes"] = [
                "openid",
                "email",
                "https://www.googleapis.com/auth/gmail.modify",
            ]
        update = {"config": submitted}
    match owner:
        case "workspace":
            result = await common.update_by_id(
                toolkit_id, update, workspace_id=f.workspace_ids[0], user_id=f.user_id
            )
        case "agent":
            result = await common.update_agent_owned(
                f.agent_ids[0],
                toolkit_id,
                update,
                workspace_id=f.workspace_ids[0],
                workspace_user_id=membership,
                user_id=f.user_id,
                role=WorkspaceUserRole.OWNER,
            )
        case "user":
            result = await personal.update(h.subject, toolkit_id, update)
    if edit == "metadata":
        assert isinstance(result, Success)
    else:
        assert isinstance(result, Failure)
        assert isinstance(result.error, InvalidConfig)
        assert "Google connection settings" in result.error.detail
        google.status.assert_not_awaited()
    async with f.writes() as session:
        current = await session.write_session.get(RDBToolkitConfig, toolkit_id)
        current_grant = await session.write_session.get(RDBGoogleConnection, grant_id)
        assert current is not None and current_grant is not None
        assert current.config == _CONFIG
        assert current.owner_kind.value == owner
        assert current.owner_agent_id == (f.agent_ids[0] if owner == "agent" else None)
        assert current.owner_user_id == (f.user_id if owner == "user" else None)
        assert current.name == ("Renamed" if edit == "metadata" else "Google")
        assert current.description == (
            "Edited" if edit == "metadata" else "Saved description"
        )
        assert current.prompt == ("Safe" if edit == "metadata" else "Saved prompt")
        assert current.revision == (8 if edit == "metadata" else 7)
        assert current_grant.toolkit_id == toolkit_id
        assert current_grant.client_id == "same-client"
        assert current_grant.encrypted_payload == "opaque-current-grant"
        assert current_grant.status is GoogleConnectionStatus.CONNECTED
