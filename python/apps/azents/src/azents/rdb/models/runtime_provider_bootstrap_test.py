"""Runtime Provider bootstrap persistence model tests."""

import subprocess
import sys


def test_runtime_provider_audit_event_resolves_fk_targets_in_isolation() -> None:
    """Load audit-event foreign keys in the standalone Runtime Control process."""
    script = """
from azents.rdb.models.runtime_provider_bootstrap import (
    RDBRuntimeProviderAuditEvent,
)

target_tables = {
    foreign_key.column.table.name
    for foreign_key in RDBRuntimeProviderAuditEvent.__table__.foreign_keys
}
assert target_tables == {"runtime_providers", "users"}
"""

    subprocess.run([sys.executable, "-c", script], check=True)
