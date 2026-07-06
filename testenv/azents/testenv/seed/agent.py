"""Agent seeding helpers.

`AgentService` is constructed with `TestenvConfig` and exposes `create()`. The
old utils.py `create_chat_session` flow mixed WebSocket setup with integration
creation; this service keeps seeding responsibilities separate (Discussion §3.4).

Normally use this through `TestenvClient.agent`.
"""

from dataclasses import dataclass

import httpx
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_type import AgentType

from testenv.runtime_config import TestenvConfig

from .client import public_client
from .types import Agent, Integration, User, Workspace
from .unique import unique


@dataclass(frozen=True)
class AgentService:
    """Agent seed service used by `TestenvClient.agent`.

    Returned `Agent` values are lightweight `seed.types.Agent` dataclasses.
    """

    config: TestenvConfig

    def create(
        self,
        user: User,
        workspace: Workspace,
        integration: Integration,
        model: str,
        *,
        name: str | None = None,
        agent_type: str = "public",
        shell_enabled: bool = True,
        memory_enabled: bool = True,
        model_config_id: str | None = None,
    ) -> Agent:
        """Call `POST /workspace/{handle}/agents`.

        Phase 5 creates agents through ModelConfig using `model_config_id`. The
        `model` argument remains only as a legacy field on the returned dataclass.

        Defaults create an AGENT-role runtime tool agent with shell enabled.
        """
        actual_name = name if name is not None else f"Test Agent {unique()}"
        if model_config_id is None:
            raise RuntimeError(
                "model_config_id is required. "
                "Use TestenvClient.llm.create_model_config_from_first_candidate()."
            )

        api = AgentV1Api(public_client(self.config))
        agent_resp = api.agent_v1_create_agent(
            handle=workspace.handle,
            agent_create_request=AgentCreateRequest(
                name=actual_name,
                llm_provider_integration_id=None,
                llm_provider_model=None,
                additional_properties={"model_config_id": model_config_id},
                type=AgentType(agent_type),
                shell_enabled=shell_enabled,
            ),
            _headers={"Authorization": f"Bearer {user.access_token}"},
        )

        if not memory_enabled:
            httpx.patch(
                f"{self.config.public_url}/agent/v1/workspaces/{workspace.handle}/agents/{agent_resp.id}",
                json={"memory_enabled": False},
                headers={"Authorization": f"Bearer {user.access_token}"},
                timeout=10,
            ).raise_for_status()

        return Agent(
            id=agent_resp.id,
            workspace=workspace,
            integration=integration,
            name=actual_name,
            model_slug=model,
        )
