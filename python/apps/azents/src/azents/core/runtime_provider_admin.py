"""Defining detached Runtime management contracts."""

import dataclasses

from azents_runtime_control.provider import RuntimeProviderOperationalDiagnostics


@dataclasses.dataclass(frozen=True)
class RuntimeProviderAdminUnavailable(Exception):
    """The requested Runtime Provider Admin operation cannot be completed."""

    code: str
    message: str

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


@dataclasses.dataclass(frozen=True)
class RuntimeProviderOperationalDiagnosticsProjection:
    """Safe current Provider diagnostics for internal Admin projection."""

    generation: int
    protocol_version: str
    diagnostics: RuntimeProviderOperationalDiagnostics
