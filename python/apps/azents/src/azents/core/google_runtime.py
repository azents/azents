"""Detached current execution snapshots, independent of setup-manager identity."""

import dataclasses

from azents.core.google_oauth import GoogleConnection
from azents.core.google_system_setting import GoogleApplicationRegistration
from azents.core.google_workspace_policy import GoogleWorkspaceOperation
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.core.tools import GoogleToolkitConfig


@dataclasses.dataclass(frozen=True)
class GoogleExecutionState:
    """Current saved authority; unpublished attempts never participate."""

    config: GoogleToolkitConfig
    connection: GoogleConnection = dataclasses.field(repr=False)
    registration: GoogleApplicationRegistration = dataclasses.field(repr=False)
    revision: int


@dataclasses.dataclass(frozen=True)
class GoogleOperationAuthorization:
    """Call-local exact-current direct operation authority, never model metadata."""

    owner: SessionExecutionOwner
    operation: GoogleWorkspaceOperation
    auxiliary_operations: tuple[GoogleWorkspaceOperation, ...]
    snapshot: GoogleExecutionState = dataclasses.field(repr=False)
