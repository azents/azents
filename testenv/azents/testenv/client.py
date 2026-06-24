"""testenv/azents client assembly helpers.

`TestenvClient` is a frozen dataclass that acts as a lightweight DI container
for testenv service objects. Use `build_client(config)` to construct services
from an explicit config.

There is no default object fallback. Tests that need custom dependencies should
construct `TestenvClient(...)` directly.

Example:
    from testenv.client import build_client_from_env

    c = build_client_from_env()
    user = c.auth.create_user()
    ws = c.workspace.create(user)
    c.llm.register_model("gpt-4o-mini")
    integration = c.llm.create_integration(user, ws)
    agent = c.agent.create(user, ws, integration, "gpt-4o-mini")
    session = c.chat.start_session(user, agent)
"""

from dataclasses import dataclass

from testenv.live.chat import Chat
from testenv.live.mcp import Mcp
from testenv.live.testenv_api import TestenvApi
from testenv.live.tools import Tools
from testenv.runtime_config import TestenvConfig
from testenv.seed.agent import AgentService
from testenv.seed.auth import Auth
from testenv.seed.llm import LLM
from testenv.seed.web import StorageState
from testenv.seed.workspace import Workspace


@dataclass(frozen=True)
class TestenvClient:
    """testenv client: `TestenvConfig` plus service objects as a DI container."""

    config: TestenvConfig
    auth: Auth
    workspace: Workspace
    llm: LLM
    agent: AgentService
    chat: Chat
    tools: Tools
    mcp: Mcp
    web: StorageState
    testenv_api: TestenvApi


def build_client(config: TestenvConfig) -> TestenvClient:
    """Build a `TestenvClient` from an explicit `TestenvConfig`."""
    chat = Chat(config)
    testenv_api = TestenvApi(config=config)
    return TestenvClient(
        config=config,
        auth=Auth(config),
        workspace=Workspace(config),
        llm=LLM(config),
        agent=AgentService(config),
        chat=chat,
        tools=Tools(config=config, chat=chat),
        mcp=Mcp(config=config),
        web=StorageState(config=config),
        testenv_api=testenv_api,
    )


def build_client_from_env() -> TestenvClient:
    """Build a client from `TestenvConfig` loaded from the environment."""
    return build_client(TestenvConfig.from_env())
