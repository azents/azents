"""fixture command orchestration entry point."""

import datetime as dt
from pathlib import Path

from testenv.fixture_errors import FixtureError, FixtureErrorDetail
from testenv.fixture_resources import (
    FixtureCommandResult,
    FixtureContext,
    FixtureProvider,
    fixture_providers,
)


class UnknownFixtureError(FixtureError):
    """Raised when a requested fixture id is not registered."""


def run_fixture_up(fixture_id: str, testenv_root: Path) -> FixtureCommandResult:
    """Run the fixture up command."""
    return _get_provider(fixture_id).up(_context(testenv_root))


def run_fixture_doctor(fixture_id: str, testenv_root: Path) -> FixtureCommandResult:
    """Run the fixture doctor command."""
    return _get_provider(fixture_id).doctor(_context(testenv_root))


def run_fixture_doctor_all(testenv_root: Path) -> list[FixtureCommandResult]:
    """Run doctor for every registered fixture provider."""
    ctx = _context(testenv_root)
    return [provider.doctor(ctx) for provider in fixture_providers().values()]


def run_fixture_reset(fixture_id: str, testenv_root: Path) -> FixtureCommandResult:
    """Run the fixture reset command."""
    return _get_provider(fixture_id).reset(_context(testenv_root))


def _get_provider(fixture_id: str) -> FixtureProvider:
    """Return the provider registered for a fixture id."""
    providers = fixture_providers()
    provider = providers.get(fixture_id)
    if provider is None:
        detail = FixtureErrorDetail(
            code="FIXTURE_UNKNOWN_ID",
            message=f"unknown fixture: {fixture_id}",
            fixture_id=fixture_id,
        )
        raise UnknownFixtureError(detail)
    return provider


def _context(testenv_root: Path) -> FixtureContext:
    """Create the context used for a fixture command run."""
    return FixtureContext(testenv_root=testenv_root, now=dt.datetime.now(dt.UTC))
