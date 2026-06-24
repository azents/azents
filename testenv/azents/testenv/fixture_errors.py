"""Fixture manifest error types."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FixtureErrorDetail:
    """Machine-readable fixture error detail."""

    code: str
    message: str
    fixture_id: str | None = None
    path: Path | None = None


class FixtureError(RuntimeError):
    """Base exception for the fixture subsystem."""

    detail: FixtureErrorDetail

    def __init__(self, detail: FixtureErrorDetail) -> None:
        super().__init__(detail.message)
        self.detail = detail


class FixtureManifestNotFoundError(FixtureError):
    """Raised when the requested fixture manifest file does not exist."""


class FixtureManifestReadError(FixtureError):
    """Raised when a fixture manifest file cannot be read as JSON."""


class FixtureManifestSchemaError(FixtureError):
    """Raised when fixture manifest schema validation fails."""


class FixtureSecretValidationError(FixtureError):
    """Raised when a fixture manifest contains secret-like values."""
