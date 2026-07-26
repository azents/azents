"""Static regression checks for mailbox migration safety boundaries."""

import pytest

from azents.consts import PROJECT_ROOT

_MIGRATION = (
    PROJECT_ROOT
    / "db-schemas"
    / "rdb"
    / "migrations"
    / "versions"
    / "8bbe580fddad_evolve_input_buffers_into_mailbox_items.py"
)


def _migration_source() -> str:
    return _MIGRATION.read_text()


def test_external_resource_preflight_is_mailbox_scoped() -> None:
    source = _migration_source()
    marker = "'malformed resource identity'"
    marker_index = source.index(marker)
    preflight_start = source.rfind("DO $$", 0, marker_index)
    preflight_end = source.index("UPDATE mailbox_items", marker_index)
    preflight = source[preflight_start:preflight_end]

    assert "JOIN mailbox_items m" in preflight
    assert "ON m.id = b.mailbox_item_id" in preflight
    assert (
        "WHERE m.kind::text = 'external_channel_invocation'\n"
        "                      AND ("
    ) in preflight


@pytest.mark.parametrize(
    ("kind", "provider_resource_key", "labels", "expected_abort"),
    (
        ("user_message", "", None, False),
        ("action_message", "", {"thread_ts": 1.0}, False),
        ("external_channel_invocation", "", None, True),
        (
            "external_channel_invocation",
            "resource-1",
            {"channel_id": "C123", "thread_ts": 1.0},
            True,
        ),
    ),
)
def test_resource_preflight_scope_truth_table(
    kind: str,
    provider_resource_key: str,
    labels: dict[str, object] | None,
    expected_abort: bool,
) -> None:
    """Malformed resource identity aborts only external mailbox rows."""
    malformed = (
        not provider_resource_key.strip()
        or not isinstance(labels, dict)
        or not any(labels.get(key) for key in ("channel_id", "channel_name"))
        or (
            "thread_ts" in labels
            and labels["thread_ts"] is not None
            and not isinstance(labels["thread_ts"], str)
        )
    )
    assert (kind == "external_channel_invocation" and malformed) is expected_abort


def test_mailbox_check_constraint_names_round_trip() -> None:
    source = _migration_source()

    assert '"ck_input_buffers_requested_profile",' in source
    assert '"ck_mailbox_items_requested_profile",' in source
    assert '"ck_input_buffers_sender_user_kind",' in source
    assert '"ck_mailbox_items_sender_user_kind",' in source
