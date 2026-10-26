"""Immutable authority for connection-only ordinary operation admission."""

import dataclasses
from typing import Protocol


@dataclasses.dataclass(frozen=True)
class RuntimeAdmissionAuthority:
    """Freeze the physical Runtime and selected applied configuration."""

    runtime_id: str
    capability_version: int
    desired_generation: int
    configuration_sequence: int
    configuration_digest: str
    workspace_path: str


@dataclasses.dataclass(frozen=True)
class RuntimeAdmissionReady:
    """Current ready connection under unchanged frozen authority."""

    runner_generation: int


@dataclasses.dataclass(frozen=True)
class RuntimeAdmissionWaiting:
    """Unchanged authority whose Runner is transiently unavailable."""


@dataclasses.dataclass(frozen=True)
class RuntimeAdmissionRejected:
    """Revoked or replaced physical/configuration authority."""


type RuntimeAdmissionState = (
    RuntimeAdmissionReady | RuntimeAdmissionWaiting | RuntimeAdmissionRejected
)


class RuntimeAdmissionReader(Protocol):
    """Read detached current authority without holding I/O transactions."""

    async def resolve(
        self, authority: RuntimeAdmissionAuthority
    ) -> RuntimeAdmissionState:
        """Validate frozen authority and project connection readiness."""
        ...
