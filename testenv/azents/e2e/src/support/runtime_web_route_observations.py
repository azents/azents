"""Content-free, exact-epoch Runtime Web readiness observations."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from azentspublicclient.models.agent_runtime_raw_state_response import (
    AgentRuntimeRawStateResponse,
)


def runtime_web_runner_generation(state: AgentRuntimeRawStateResponse) -> int:
    """Decode the public canonical positive signed-BIGINT generation string."""
    value: object = state.runner_generation
    if (
        not isinstance(value, str)
        or not value
        or not value.isascii()
        or not value.isdigit()
        or value.startswith("0")
        or len(value) > 19
        or (len(value) == 19 and value > "9223372036854775807")
    ):
        raise ValueError(
            "Runtime Web ready Runner generation must be a canonical "
            "positive signed-BIGINT public string"
        )
    return int(value)


@dataclass(frozen=True, repr=False)
class RuntimeWebRouteObservation:
    """A schema-typed read of one committed PostgreSQL route and DB time."""

    runtime_id: str
    desired_generation: int
    runner_generation: int
    owner_boot_id: str
    session_lease_id: str
    lease_generation: int
    protocol_fingerprint: str
    join_consumed: bool
    lease_expires_at: datetime
    database_now: datetime
    draining: bool


def wait_for_renewed_runtime_web_route(
    *,
    read: Callable[[], RuntimeWebRouteObservation | None],
    previous: RuntimeWebRouteObservation,
    runner_generation: int,
    clock: Callable[[], float],
    pause: Callable[[float], None],
    timeout_seconds: float,
    interval_seconds: float,
) -> RuntimeWebRouteObservation:
    """Await a new consumed epoch and its subsequent committed renewal.

    Nonce consumption precedes local registration. A later lease extension is
    stronger evidence: the renewal task starts only after joined registration.
    Polling never invokes or retries the transport assertions being synchronized.
    """
    deadline = clock() + timeout_seconds
    candidate: RuntimeWebRouteObservation | None = None
    while True:
        current = read()
        valid = (
            current is not None
            and current.runtime_id == previous.runtime_id
            and current.desired_generation == previous.desired_generation
            and current.runner_generation == runner_generation
            and runner_generation != previous.runner_generation
            and current.owner_boot_id != previous.owner_boot_id
            and current.session_lease_id != previous.session_lease_id
            and current.protocol_fingerprint == previous.protocol_fingerprint
            and current.join_consumed
            and not current.draining
            and current.lease_expires_at > current.database_now
        )
        if not valid:
            candidate = None
        elif current is not None:
            if (
                candidate is not None
                and current.owner_boot_id == candidate.owner_boot_id
                and current.session_lease_id == candidate.session_lease_id
                and current.lease_generation == candidate.lease_generation
                and current.lease_expires_at > candidate.lease_expires_at
            ):
                return current
            candidate = current
        remaining = deadline - clock()
        if remaining <= 0:
            raise AssertionError(
                "Runtime Web target new-generation joined route did not renew "
                f"within {timeout_seconds:g}s "
                f"(current_target_valid={valid}, "
                f"consumed_candidate_observed={candidate is not None})"
            )
        pause(min(interval_seconds, remaining))
