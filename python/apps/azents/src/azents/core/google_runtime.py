"""Detached current execution snapshots, independent of setup-manager identity."""

import dataclasses

from azents.core.google_oauth import GoogleConnection
from azents.core.google_system_setting import GoogleApplicationRegistration
from azents.core.tools import GoogleToolkitConfig


@dataclasses.dataclass(frozen=True)
class GoogleExecutionState:
    """Current saved authority; unpublished attempts never participate."""

    config: GoogleToolkitConfig
    connection: GoogleConnection = dataclasses.field(repr=False)
    registration: GoogleApplicationRegistration = dataclasses.field(repr=False)
