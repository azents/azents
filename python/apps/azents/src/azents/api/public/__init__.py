"""Public API routes.

Read-only API endpoints with cursor pagination for public clients.
"""

from azents.utils.fastapi.route import RouteMounter

from . import (
    agent,
    agent_runtime,
    auth,
    chat,
    chatgpt_oauth,
    health,
    invitation,
    join_request,
    llm_provider_integration,
    security,
    toolkit,
    user,
    workspace,
    workspace_model_settings,
    workspace_user,
)

modules = [
    agent,
    agent_runtime,
    auth,
    chatgpt_oauth,
    chat,
    health,
    invitation,
    join_request,
    llm_provider_integration,
    security,
    workspace_model_settings,
    toolkit,
    user,
    workspace,
    workspace_user,
]


def mount(mounter: RouteMounter) -> None:
    """Mounts Public API routes."""
    for module in modules:
        module.mount(mounter)
