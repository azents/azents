"""Closed public Browser resource, admission and projection contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from azents_runtime_control.browser_contract import BrowserTask

from azents.services.agent_runtime.lifecycle_data import RuntimeOperationTarget

type RuntimeBrowserReasonCode = Literal[
    "runtime_unavailable",
    "browser_unavailable",
    "browser_disabled",
    "working_folder_unavailable",
]


@dataclass(frozen=True)
class RuntimeBrowserResource:
    workspace_handle: str
    agent_id: str
    session_id: str


@dataclass(frozen=True)
class RuntimeBrowserAuthority:
    """Current concrete Session authority, never a scheduling-root alias."""

    resource: RuntimeBrowserResource
    user_id: str
    authentication_session_id: str
    authentication_session_expires_at: datetime
    target: RuntimeOperationTarget
    working_directory: str
    allow_input: bool


@dataclass(frozen=True)
class RuntimeBrowserUnavailable:
    reason_code: RuntimeBrowserReasonCode


type RuntimeBrowserAdmission = RuntimeBrowserAuthority | RuntimeBrowserUnavailable


@dataclass(frozen=True)
class RuntimeBrowserProjection:
    available: bool
    reason_code: RuntimeBrowserReasonCode | None
    allow_input: bool
    tasks: tuple[BrowserTask, ...]


class RuntimeBrowserRequestError(RuntimeError):
    """Expected access, unavailable-target or conflict rejection without content."""

    def __init__(self, status_code: Literal[401, 403, 404, 409], detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class RuntimeBrowserOperationError(RuntimeError):
    """A command failed without establishing a successful Browser projection."""


class RuntimeBrowserTargetUnavailable(RuntimeBrowserRequestError):
    def __init__(self) -> None:
        super().__init__(409, "Browser target is unavailable.")


class RuntimeBrowserStreamUnavailable(RuntimeBrowserRequestError):
    def __init__(self) -> None:
        super().__init__(409, "Browser is unavailable.")
