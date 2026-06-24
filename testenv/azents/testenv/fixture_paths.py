"""fixture manifest runtime path helper."""

import re
from pathlib import Path

from testenv.fixture_errors import FixtureErrorDetail, FixtureManifestSchemaError

_FIXTURE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")


def default_testenv_root() -> Path:
    """Return the default testenv/azents root path."""
    return Path(__file__).resolve().parent.parent


def validate_fixture_id(fixture_id: str) -> str:
    """Validate that a fixture id is safe for manifest file paths."""
    if not _FIXTURE_ID_RE.fullmatch(fixture_id):
        detail = FixtureErrorDetail(
            code="FIXTURE_MANIFEST_SCHEMA_ERROR",
            message="Fixture id must match ^[a-z][a-z0-9-]{0,62}$",
            fixture_id=fixture_id,
        )
        raise FixtureManifestSchemaError(detail)
    return fixture_id


def fixture_state_root(testenv_root: Path | None = None) -> Path:
    """Return the .state/fixtures directory for fixture manifests."""
    root = testenv_root if testenv_root is not None else default_testenv_root()
    return root / ".state" / "fixtures"


def fixture_manifest_path(fixture_id: str, testenv_root: Path | None = None) -> Path:
    """Return the manifest JSON path for a fixture id."""
    safe_fixture_id = validate_fixture_id(fixture_id)
    return fixture_state_root(testenv_root) / f"{safe_fixture_id}.json"


def fixture_private_state_path(fixture_id: str, testenv_root: Path | None = None) -> Path:
    """Return the private setup state JSON path for a fixture id."""
    safe_fixture_id = validate_fixture_id(fixture_id)
    return fixture_state_root(testenv_root) / f"{safe_fixture_id}.state.json"
