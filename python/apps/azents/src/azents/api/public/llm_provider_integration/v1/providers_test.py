"""LLM provider capability route tests."""

from azents.core.auth.deps import WorkspaceMember
from azents.core.auth.permissions import Permissions
from azents.core.enums import LLMProvider, WorkspaceUserRole

from . import list_integration_providers


def _member() -> WorkspaceMember:
    return WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
        permissions={Permissions.LLM_INTEGRATIONS_READ},
        session_id="session-1",
    )


async def test_xai_api_key_is_available_as_stable_provider() -> None:
    """Expose stable xAI API key credentials without operator configuration."""
    response = await list_integration_providers(_member())

    xai = next(item for item in response.items if item.provider == LLMProvider.XAI)
    assert xai.display_name == "xAI API key"
    assert xai.credential_type == "api_key"
    assert xai.experimental is False


async def test_openrouter_is_available_as_stable_api_key_provider() -> None:
    """Expose OpenRouter through the generic API-key integration contract."""
    response = await list_integration_providers(_member())

    openrouter = next(
        item for item in response.items if item.provider == LLMProvider.OPENROUTER
    )
    assert openrouter.display_name == "OpenRouter"
    assert openrouter.credential_type == "api_key"
    assert openrouter.experimental is False


async def test_xai_oauth_is_available_without_operator_configuration() -> None:
    """Expose xAI OAuth through its built-in public client identity."""
    response = await list_integration_providers(_member())

    xai = next(
        item for item in response.items if item.provider == LLMProvider.XAI_OAUTH
    )
    assert xai.display_name == "xAI Grok OAuth"
    assert xai.experimental is True
