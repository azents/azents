"""Immutable human input admission outcomes."""

import dataclasses

from azents.core.exchange_file_errors import ExchangeFileInputClaimError
from azents.core.session_workspace_paths import InvalidProjectPath
from azents.repos.agent_session.data import AgentSession
from azents.repos.mailbox.data import MailboxItem


@dataclasses.dataclass(frozen=True)
class BufferedAgentSessionInputResult:
    """MailboxItem creation and broker wake-up result."""

    agent_runtime_id: str | None
    agent_session_id: str
    accepted_mailbox_item_id: str
    mailbox_item: MailboxItem | None
    created: bool


@dataclasses.dataclass(frozen=True)
class CreatedAgentSessionInputResult:
    """New AgentSession creation and first input enqueue result."""

    agent_runtime_id: str | None
    agent_session: AgentSession
    accepted_mailbox_item_id: str
    mailbox_item: MailboxItem | None
    created: bool


@dataclasses.dataclass(frozen=True)
class AgentSessionInputSessionNotFound:
    """Requested AgentSession was not found."""


@dataclasses.dataclass(frozen=True)
class AgentSessionInputWrongAgent:
    """Requested AgentSession does not belong to the requested agent."""


@dataclasses.dataclass(frozen=True)
class AgentSessionInputInactiveSession:
    """Requested AgentSession is not writable."""


@dataclasses.dataclass(frozen=True)
class AgentSessionInputRuntimeRemoving(AgentSessionInputInactiveSession):
    """Agent Runtime removal is fencing ordinary input admission."""


@dataclasses.dataclass(frozen=True)
class AgentSessionInputSubagentReadOnly:
    """Requested child subagent session does not accept direct human input."""


@dataclasses.dataclass(frozen=True)
class AgentSessionInputIdempotencyConflict:
    """Client request ID was reused with incompatible input."""

    reason: str


@dataclasses.dataclass(frozen=True)
class AgentSessionInputInvalidInferenceProfile:
    """Requested inference profile is not selectable for the Agent."""

    reason: str


AgentSessionInputError = (
    AgentSessionInputSessionNotFound
    | AgentSessionInputWrongAgent
    | AgentSessionInputInactiveSession
    | AgentSessionInputRuntimeRemoving
    | AgentSessionInputSubagentReadOnly
    | AgentSessionInputIdempotencyConflict
    | AgentSessionInputInvalidInferenceProfile
    | ExchangeFileInputClaimError
    | InvalidProjectPath
)
