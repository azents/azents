"""Immutable Team-scoped GitHub user credential resolution context."""

import dataclasses
from typing import Literal

from azents.core.github_user_oauth import GitHubUserConnection
from azents.repos.toolkit.data import ToolkitConfig


@dataclasses.dataclass(frozen=True)
class GitHubUserExecutionContext:
    """Existing resolved Toolkit/App identity, never an initiating manager login."""

    workspace_id: str
    agent_id: str
    session_id: str
    toolkit_id: str
    source: Literal["byoa_user", "platform_user"]
    app_id: str
    client_id: str | None


@dataclasses.dataclass(frozen=True)
class GitHubUserExecutionState:
    """Current encrypted-credential projection after a completed authorized read."""

    toolkit: ToolkitConfig = dataclasses.field(repr=False)
    connection: GitHubUserConnection
