"""Root AgentSession creation contracts."""

import dataclasses

from azents.repos.agent_session.data import AgentSession


@dataclasses.dataclass(frozen=True, kw_only=True)
class ExplicitRootWorkspaceIntent:
    """Caller-selected existing Projects for a root Session."""

    existing_project_paths: list[str]


@dataclasses.dataclass(frozen=True)
class AgentDefaultRootWorkspaceIntent:
    """Use the Agent automatic root Session Project policy."""


RootWorkspaceIntent = ExplicitRootWorkspaceIntent | AgentDefaultRootWorkspaceIntent


@dataclasses.dataclass(frozen=True, kw_only=True)
class RootAgentSessionCreationResult:
    """Created or reused root Session and its durable Project snapshot."""

    agent_session: AgentSession
    created: bool
    initial_project_paths: tuple[str, ...]
    policy_revision: int | None
