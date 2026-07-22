"""Runtime Provider migration preflight validation tests."""

import pytest

from .migration_preflight import (
    LegacyProviderReference,
    RuntimeProviderMigrationPreflightFailure,
    RuntimeProviderMigrationPreflightSnapshot,
    validate_runtime_provider_migration_preflight,
)

_EXPECTED_PROVIDER_ID = "system-kubernetes"


def _snapshot(
    *,
    legacy_provider_logical_ids: tuple[str, ...] = (),
    agent_references: tuple[LegacyProviderReference, ...] = (),
    runtime_references: tuple[LegacyProviderReference, ...] = (),
    runtime_ids_with_nonempty_provider_config: tuple[str, ...] = (),
) -> RuntimeProviderMigrationPreflightSnapshot:
    """Build one read-only legacy-state snapshot."""
    return RuntimeProviderMigrationPreflightSnapshot(
        legacy_provider_logical_ids=legacy_provider_logical_ids,
        agent_references=agent_references,
        runtime_references=runtime_references,
        runtime_ids_with_nonempty_provider_config=(
            runtime_ids_with_nonempty_provider_config
        ),
    )


def test_preflight_accepts_expected_empty_legacy_state() -> None:
    """The observed empty Provider table and known ID references are valid."""
    snapshot = _snapshot(
        agent_references=(LegacyProviderReference("agent-1", _EXPECTED_PROVIDER_ID),),
        runtime_references=(
            LegacyProviderReference("runtime-1", _EXPECTED_PROVIDER_ID),
        ),
    )

    validate_runtime_provider_migration_preflight(
        snapshot,
        expected_legacy_provider_logical_id=_EXPECTED_PROVIDER_ID,
    )


@pytest.mark.parametrize(
    ("snapshot", "code", "owner_ids"),
    (
        (
            _snapshot(legacy_provider_logical_ids=("unexpected-provider",)),
            "legacy_runtime_provider_rows_present",
            ("unexpected-provider",),
        ),
        (
            _snapshot(
                agent_references=(
                    LegacyProviderReference("agent-1", "unexpected-provider"),
                )
            ),
            "unexpected_agent_provider_id",
            ("agent-1",),
        ),
        (
            _snapshot(
                runtime_references=(
                    LegacyProviderReference("runtime-1", "unexpected-provider"),
                )
            ),
            "unexpected_runtime_provider_id",
            ("runtime-1",),
        ),
        (
            _snapshot(runtime_ids_with_nonempty_provider_config=("runtime-1",)),
            "legacy_runtime_provider_config_present",
            ("runtime-1",),
        ),
    ),
)
def test_preflight_rejects_unexpected_legacy_state(
    snapshot: RuntimeProviderMigrationPreflightSnapshot,
    code: str,
    owner_ids: tuple[str, ...],
) -> None:
    """Preflight rejects state that would need a guessed backfill."""
    with pytest.raises(RuntimeProviderMigrationPreflightFailure) as raised:
        validate_runtime_provider_migration_preflight(
            snapshot,
            expected_legacy_provider_logical_id=_EXPECTED_PROVIDER_ID,
        )

    assert raised.value.code == code
    assert raised.value.owner_ids == owner_ids
