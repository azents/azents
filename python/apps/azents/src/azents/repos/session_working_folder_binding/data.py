"""Session working-folder binding repository data."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class SessionWorkingFolderTarget:
    """Database-relevant evidence from one exact Runtime operation target."""

    id: str
    capability_snapshot_version: int
    runtime_target_capability_version: int
    workspace_path: str


@dataclasses.dataclass(frozen=True)
class SessionWorkingFolderAuthority:
    """Exact current Session folder authority for one Runtime operation."""

    context_id: str
    agent_id: str
    agent_runtime_id: str
    working_folder_path: str
    runtime_capability_version: int


class SessionWorkingFolderBindingError(RuntimeError):
    """Raised when a Session folder cannot authorize Runtime work."""

    def __init__(self, reason_code: str) -> None:
        """Create a stable content-free binding failure."""
        super().__init__("Session working-folder binding is unavailable.")
        self.reason_code = reason_code
