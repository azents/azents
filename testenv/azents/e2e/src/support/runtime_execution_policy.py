"""Narrow API-managed Runtime Execution Policy E2E setup."""

from dataclasses import dataclass
from typing import Any, cast

import azentsadminclient
import azentspublicclient
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets

from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
)

_RUNTIME_PROVIDER_ID = "system-docker"
RUNTIME_EXECUTION_LLM_CREDENTIAL_SENTINEL = "sk-runtime-policy-qa"


@dataclass(frozen=True)
class RuntimeExecutionAgentContext:
    """API-managed Workspace and Agent context."""

    token: str
    email: str
    workspace_handle: str
    agent_id: str


def bearer_headers(token: str) -> dict[str, str]:
    """Return one bearer authorization header."""
    return {"Authorization": f"Bearer {token}"}


def create_runtime_execution_agent_context(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> RuntimeExecutionAgentContext:
    """Create a Workspace and Agent through supported Public APIs."""
    suffix = unique()
    token, _, email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"runtime-policy-{suffix}@example.com",
    )
    workspace_handle = f"runtime-policy-{suffix}"
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Runtime Policy {suffix}",
            workspace_handle=workspace_handle,
            owner_name=f"Owner {suffix}",
        ),
        _headers=bearer_headers(token),
    )
    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=workspace_handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(
                ApiKeySecrets(api_key=RUNTIME_EXECUTION_LLM_CREDENTIAL_SENTINEL)
            ),
        ),
        _headers=bearer_headers(token),
    )
    model_selection = model_selection_from_first_candidate(
        str(cast(Any, public_api_client).configuration.host),
        token,
        workspace_handle,
        integration.id,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace_handle,
        agent_create_request=AgentCreateRequest(
            name=f"Runtime Policy Agent {suffix}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
            runtime_provider_id=_RUNTIME_PROVIDER_ID,
            shell_enabled=False,
        ),
        _headers=bearer_headers(token),
    )
    return RuntimeExecutionAgentContext(
        token=token,
        email=email,
        workspace_handle=workspace_handle,
        agent_id=agent.id,
    )
