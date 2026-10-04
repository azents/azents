"""Detached database inputs for Worker Executor orchestration."""

from dataclasses import dataclass

from azents.core.agent_session_data import AgentSession
from azents.engine.events.types import Event
from azents.repos.agent.data import Agent


@dataclass(frozen=True)
class WorkerSessionTreeChangeRouting:
    """One changed SessionAgent and its ordered tree audience."""

    root_session_agent_id: str
    changed_session_agent_id: str
    target_session_ids: tuple[str, ...]


@dataclass(frozen=True)
class WorkerModelConfigurationSnapshot:
    """Current Agent and Session inputs for pure model drift comparison."""

    agent: Agent | None
    session: AgentSession | None


@dataclass(frozen=True)
class WorkerModelInputTranscript:
    """One consistent Session head and non-reverted model-input transcript."""

    head_event_id: str | None
    events: tuple[Event, ...]
