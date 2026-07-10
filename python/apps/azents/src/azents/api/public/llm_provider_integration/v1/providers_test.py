"""LLM provider capability route tests."""

from azents.core.auth.deps import WorkspaceMember
from azents.core.auth.permissions import Permissions
from azents.core.enums import LLMProvider, WorkspaceUserRole

from . import list_integration_providers


async def test_xai_oauth_is_available_without_operator_configuration() -> None:
    """Expose xAI OAuth through its built-in public client identity."""
    member = WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
        permissions={Permissions.LLM_INTEGRATIONS_READ},
        session_id="session-1",
    )

    response = await list_integration_providers(member)

    xai = next(
        item for item in response.items if item.provider == LLMProvider.XAI_OAUTH
    )
    assert xai.display_name == "xAI Grok OAuth"
    assert xai.experimental is True
