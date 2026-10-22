"""Detached manager-bound Picker issuance authority; no credential cache or store."""

import dataclasses

from azents.core.google_oauth import GoogleConnection, GoogleManager
from azents.core.google_system_setting import GooglePickerApplication
from azents.core.google_workspace_policy import GoogleWorkspaceConfig


@dataclasses.dataclass(frozen=True)
class GooglePickerState:
    """Exact pre-I/O snapshot must be rechecked before browser token delivery."""

    subject: GoogleManager
    toolkit_id: str
    revision: int
    config: GoogleWorkspaceConfig
    connection: GoogleConnection = dataclasses.field(repr=False)
    application: GooglePickerApplication = dataclasses.field(repr=False)
