"""Detached facts from completed Worker model-operation phases."""

import dataclasses

from azents.repos.agent.data import Agent
from azents.repos.agent_session.data import AgentSession
from azents.repos.model_candidate_selection import ModelCandidateSelection


@dataclasses.dataclass(frozen=True)
class FreshProfileSnapshot:
    """Unchanged unlocked Agent and Session profile snapshot."""

    agent: Agent
    session: AgentSession


@dataclasses.dataclass(frozen=True)
class FreshModelPreparation:
    """Committed foreground and background selections before external work."""

    selection: ModelCandidateSelection
    compaction_selection: ModelCandidateSelection
