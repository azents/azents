"""Controlled-clock tests of the exact restarted-Owner readiness boundary."""

from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, Mock

import psycopg
import pytest

from support.runtime_web_route_observations import (
    RuntimeWebRouteObservation,
    wait_for_renewed_runtime_web_route,
)
from tests.web.public.test_runtime_web_gateway import _read_runtime_web_route

_NOW = datetime(2026, 10, 15, tzinfo=UTC)
_PREVIOUS = RuntimeWebRouteObservation(
    runtime_id="target-runtime",
    desired_generation=1,
    runner_generation=1,
    owner_boot_id="old-owner",
    session_lease_id="old-lease",
    lease_generation=1,
    protocol_fingerprint="protocol",
    join_consumed=True,
    lease_expires_at=_NOW + timedelta(seconds=10),
    database_now=_NOW,
    draining=False,
)
_JOINED = replace(
    _PREVIOUS,
    runner_generation=2,
    owner_boot_id="new-owner",
    session_lease_id="new-lease",
    lease_generation=2,
)
_RENEWED = replace(_JOINED, lease_expires_at=_NOW + timedelta(seconds=13))


class _Receipts:
    """Advance only when the real helper requests another authoritative read."""

    def __init__(self, receipts: Iterable[RuntimeWebRouteObservation | None]) -> None:
        self.receipts = iter(receipts)
        self.now = 0.0
        self.reads = 0
        self.last: RuntimeWebRouteObservation | None = None

    def read(self) -> RuntimeWebRouteObservation | None:
        self.reads += 1
        self.last = next(self.receipts, self.last)
        return self.last

    def clock(self) -> float:
        return self.now

    def pause(self, duration: float) -> None:
        self.now += duration

    def wait(self) -> RuntimeWebRouteObservation:
        return wait_for_renewed_runtime_web_route(
            read=self.read,
            previous=_PREVIOUS,
            runner_generation=2,
            clock=self.clock,
            pause=self.pause,
            timeout_seconds=1,
            interval_seconds=0.25,
        )


def test_waits_through_old_lease_offer_join_and_subsequent_renewal() -> None:
    receipts = _Receipts(
        [
            _PREVIOUS,
            None,
            replace(_JOINED, join_consumed=False),
            _JOINED,
            _RENEWED,
        ]
    )
    assert receipts.wait() == _RENEWED
    assert receipts.reads == 5
    assert receipts.now == 1


@pytest.mark.parametrize(
    "invalid",
    [
        _PREVIOUS,
        None,
        replace(_JOINED, runtime_id="unrelated-runtime"),
        replace(_JOINED, desired_generation=2),
        replace(_JOINED, runner_generation=1),
        replace(_JOINED, owner_boot_id="old-owner"),
        replace(_JOINED, session_lease_id="old-lease"),
        replace(_JOINED, protocol_fingerprint="different-protocol"),
        replace(_JOINED, join_consumed=False),
        replace(_JOINED, draining=True),
        replace(_JOINED, lease_expires_at=_NOW),
        _JOINED,
    ],
    ids=[
        "old-epoch",
        "absent",
        "wrong-runtime",
        "wrong-desired-generation",
        "stale-runner-generation",
        "old-owner",
        "old-lease",
        "wrong-protocol",
        "offer-not-joined",
        "draining",
        "expired",
        "joined-but-not-renewed",
    ],
)
def test_never_accepts_unready_or_unrenewed_routes(
    invalid: RuntimeWebRouteObservation | None,
) -> None:
    receipts = _Receipts([invalid])
    with pytest.raises(AssertionError, match="did not renew within 1s") as error:
        receipts.wait()
    assert receipts.now == 1
    assert receipts.reads == 5
    assert "target-runtime" not in str(error.value)
    assert "old-owner" not in str(error.value)
    assert "old-lease" not in str(error.value)


def test_new_epoch_cannot_borrow_another_epochs_renewal() -> None:
    replacement = replace(
        _RENEWED, session_lease_id="another-lease", lease_generation=3
    )
    receipts = _Receipts([_JOINED, replacement])
    with pytest.raises(AssertionError, match="did not renew"):
        receipts.wait()


def test_invalid_receipt_resets_prior_renewal_candidate() -> None:
    receipts = _Receipts([_JOINED, None, _RENEWED])
    with pytest.raises(AssertionError, match="did not renew"):
        receipts.wait()


def test_decreasing_expiry_is_not_renewal() -> None:
    receipts = _Receipts(
        [_JOINED, replace(_JOINED, lease_expires_at=_NOW + timedelta(seconds=9))]
    )
    with pytest.raises(AssertionError, match="did not renew"):
        receipts.wait()


def test_lease_generation_can_restart_after_exact_old_route_release() -> None:
    joined = replace(_JOINED, lease_generation=1)
    renewed = replace(_RENEWED, lease_generation=1)
    assert _Receipts([joined, renewed]).wait() == renewed


@pytest.mark.parametrize("observed", [None, _JOINED])
def test_database_observation_uses_bounded_read_only_target_query(
    monkeypatch: pytest.MonkeyPatch,
    observed: RuntimeWebRouteObservation | None,
) -> None:
    postgres = Mock()
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.execute.return_value.fetchone.return_value = observed
    connect = Mock(return_value=connection)
    monkeypatch.setattr(psycopg.Connection, "connect", connect)
    assert _read_runtime_web_route(postgres, "selected-target") == observed
    assert connect.call_args.kwargs["options"] == (
        "-c default_transaction_read_only=on -c statement_timeout=5000"
    )
    assert connect.call_args.kwargs["connect_timeout"] == 5
    query, parameters = connection.execute.call_args.args
    assert parameters == ("selected-target",)
    assert "FROM runtime_web_session_routes" in query
    assert "WHERE runtime_id = %s" in query
    assert "sha256(convert_to(" in query
    assert "'consumed:' || session_lease_id || ':' ||" in query
    assert "now() AS database_now" in query
    assert connection.execute.call_count == 1
