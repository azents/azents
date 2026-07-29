"""External Channel cutover preflight report tests."""

import dataclasses

import pytest

from azents.services.external_channel.cutover_preflight import (
    ExternalChannelCutoverPreflightReport,
    build_external_channel_cutover_preflight_report,
)


@dataclasses.dataclass(frozen=True)
class _Counts:
    """Complete aggregate repository projection for one test."""

    undrained_events: int = 0
    unactivated_bindings: int = 0
    incomplete_hydrations: int = 0
    pending_contexts: int = 0
    open_conversation_admissions: int = 0
    pending_access_requests: int = 0
    inflight_resource_provisionings: int = 0
    active_bindings_without_delivery_target: int = 0
    active_bindings_without_session: int = 0
    active_bindings_without_route: int = 0
    active_bindings_without_latest_batch: int = 0
    active_bindings_without_thread_position: int = 0
    active_bindings_with_ambiguous_thread_position: int = 0


def test_preflight_report_is_ready_only_when_every_category_is_zero() -> None:
    ready = build_external_channel_cutover_preflight_report(_Counts())
    blocked = build_external_channel_cutover_preflight_report(
        dataclasses.replace(
            _Counts(),
            undrained_events=2,
            active_bindings_without_thread_position=1,
        )
    )

    assert ready.ready is True
    assert blocked.ready is False
    assert ("legacy_events_not_drained", 2) in blocked.category_counts
    assert (
        "active_binding_thread_position_missing",
        1,
    ) in blocked.category_counts


def test_preflight_report_rejects_negative_or_duplicate_categories() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        ExternalChannelCutoverPreflightReport(category_counts=(("invalid", -1),))

    with pytest.raises(ValueError, match="must be unique"):
        ExternalChannelCutoverPreflightReport(
            category_counts=(("duplicate", 0), ("duplicate", 1))
        )
