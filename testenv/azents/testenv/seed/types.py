"""Seed value objects.

Seed helpers return these immutable value objects. Frozen dataclasses help catch
accidental mutation in callers.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    """User created by testenv."""

    email: str
    access_token: str
    refresh_token: str


@dataclass(frozen=True)
class Workspace:
    """Workspace created by testenv."""

    handle: str
    name: str
    owner: "User"


@dataclass(frozen=True)
class Integration:
    """LLM provider integration created by testenv."""

    id: str
    workspace: "Workspace"
    provider: str
    name: str


@dataclass(frozen=True)
class Agent:
    """Agent created by testenv."""

    id: str
    workspace: "Workspace"
    integration: "Integration"
    name: str
    model_slug: str


@dataclass(frozen=True)
class AgentSubagent:
    """Junction between a parent agent and a subagent."""

    id: str
    agent_id: str
    subagent_id: str
    description: str
    enabled: bool
