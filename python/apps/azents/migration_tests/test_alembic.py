"""Standard pytest-alembic invariants for the Azents RDB revision graph."""

from pytest_alembic import tests
from pytest_alembic.runner import MigrationContext


def test_single_head_revision(alembic_runner: MigrationContext) -> None:
    """Require one deployable Alembic head."""
    tests.test_single_head_revision(alembic_runner)


def test_upgrade(alembic_runner: MigrationContext) -> None:
    """Require a complete base-to-head upgrade."""
    tests.test_upgrade(alembic_runner)


def test_up_down_consistency(alembic_runner: MigrationContext) -> None:
    """Require reversible migrations after the suite downgrade baseline."""
    tests.test_up_down_consistency(alembic_runner)
