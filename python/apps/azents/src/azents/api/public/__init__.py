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
    external_channel,
    health,
    invitation,
    join_request,
    llm_provider_integration,
    runtime_provider_enrollment,
    security,
    toolkit,
    user,
    workspace,
    workspace_model_settings,
    workspace_user,
    xai_oauth,
)
from .kimi_oauth.v1 import route as kimi_oauth

modules = [
    agent,
    agent_runtime,
    auth,
    chatgpt_oauth,
    chat,
    external_channel,
    health,
    invitation,
    join_request,
    kimi_oauth,
    llm_provider_integration,
    runtime_provider_enrollment,
    security,
    workspace_model_settings,
    toolkit,
    user,
    workspace,
    workspace_user,
    xai_oauth,
]


def mount(mounter: RouteMounter) -> None:
    """Mounts Public API routes."""
    for module in modules:
        module.mount(mounter)
