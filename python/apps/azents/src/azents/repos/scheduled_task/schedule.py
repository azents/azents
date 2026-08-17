"""Canonical Scheduled Task schedule parsing and cursor calculations."""

import datetime
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterBadCronError, croniter

from azents.core.enums import ScheduledTaskScheduleType

_MAX_CRON_ITERATIONS = 10_000
_RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)


class InvalidScheduledTaskSchedule(ValueError):
    """Raised when a Scheduled Task schedule is not canonical."""


@dataclass(frozen=True)
class CanonicalSchedule:
    """Validated schedule values persisted by a Scheduled Task."""

    schedule_type: ScheduledTaskScheduleType
    scheduled_at: datetime.datetime | None
    cron_expression: str | None
    timezone: str | None
    next_eligible_at: datetime.datetime


def parse_rfc3339_explicit_offset(value: str) -> datetime.datetime:
    """Parse one RFC3339 timestamp that carries an explicit UTC offset."""
    if not value or _RFC3339_PATTERN.fullmatch(value) is None:
        raise InvalidScheduledTaskSchedule(
            "Scheduled time must be RFC3339 with an explicit UTC offset."
        )
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise InvalidScheduledTaskSchedule(
            "Scheduled time must be RFC3339 with an explicit UTC offset."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidScheduledTaskSchedule(
            "Scheduled time must include Z or an explicit UTC offset."
        )
    return parsed.astimezone(datetime.UTC)


def validate_schedule(
    *,
    at: str | None,
    cron_expression: str | None,
    timezone: str | None,
    now: datetime.datetime | None = None,
    allow_past_once: bool = False,
) -> CanonicalSchedule:
    """Validate one canonical one-time or recurring schedule."""
    current = _ensure_utc(now or datetime.datetime.now(datetime.UTC))
    if at is not None and cron_expression is None and timezone is None:
        scheduled_at = parse_rfc3339_explicit_offset(at)
        if scheduled_at < current and not allow_past_once:
            raise InvalidScheduledTaskSchedule(
                "One-time scheduled time cannot be in the past."
            )
        return CanonicalSchedule(
            schedule_type=ScheduledTaskScheduleType.ONCE,
            scheduled_at=scheduled_at,
            cron_expression=None,
            timezone=None,
            next_eligible_at=scheduled_at,
        )
    if at is None and cron_expression is not None and timezone is not None:
        expression = _validate_cron_expression(cron_expression)
        zone = _validate_timezone(timezone)
        local_now = current.astimezone(zone)
        next_local = croniter(expression, local_now).get_next(datetime.datetime)
        if not isinstance(next_local, datetime.datetime):
            raise InvalidScheduledTaskSchedule(
                "Cron iterator returned an invalid instant."
            )
        return CanonicalSchedule(
            schedule_type=ScheduledTaskScheduleType.CRON,
            scheduled_at=None,
            cron_expression=expression,
            timezone=timezone,
            next_eligible_at=_ensure_utc(next_local),
        )
    raise InvalidScheduledTaskSchedule(
        "Exactly one of at or cron with timezone must be supplied."
    )


def next_cron_occurrence(
    expression: str,
    timezone: str,
    after: datetime.datetime,
) -> datetime.datetime:
    """Return the next UTC cron instant after the supplied UTC cursor."""
    zone = _validate_timezone(timezone)
    cursor = _ensure_utc(after).astimezone(zone)
    next_value = croniter(_validate_cron_expression(expression), cursor).get_next(
        datetime.datetime
    )
    if not isinstance(next_value, datetime.datetime):
        raise InvalidScheduledTaskSchedule("Cron iterator returned an invalid instant.")
    return _ensure_utc(next_value)


def advance_cron_cursor(
    *,
    expression: str,
    timezone: str,
    cursor: datetime.datetime,
    now: datetime.datetime,
    max_iterations: int = _MAX_CRON_ITERATIONS,
) -> tuple[datetime.datetime, datetime.datetime]:
    """Return earliest due occurrence and first future occurrence.

    The iteration guard prevents malformed or pathological persisted schedules from
    turning one dispatcher transaction into an unbounded loop.
    """
    current = _ensure_utc(now)
    occurrence = _ensure_utc(cursor)
    first_due = occurrence
    for _ in range(max_iterations):
        if occurrence > current:
            return first_due, occurrence
        occurrence = next_cron_occurrence(expression, timezone, occurrence)
    raise InvalidScheduledTaskSchedule("Cron cursor advancement exceeded its bound.")


def canonical_schedule_text(schedule: CanonicalSchedule) -> str:
    """Render one schedule in its provider-neutral canonical form."""
    if schedule.schedule_type is ScheduledTaskScheduleType.ONCE:
        assert schedule.scheduled_at is not None
        return schedule.scheduled_at.isoformat().replace("+00:00", "Z")
    assert schedule.cron_expression is not None
    assert schedule.timezone is not None
    return f"{schedule.cron_expression} ({schedule.timezone})"


def _validate_cron_expression(expression: str) -> str:
    fields = expression.split()
    if len(fields) != 5:
        raise InvalidScheduledTaskSchedule(
            "Cron expression must contain exactly five fields."
        )
    try:
        if not croniter.is_valid(expression):
            raise InvalidScheduledTaskSchedule("Cron expression is invalid.")
    except (CroniterBadCronError, ValueError) as exc:
        raise InvalidScheduledTaskSchedule("Cron expression is invalid.") from exc
    return expression


def _validate_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidScheduledTaskSchedule(
            "Timezone must be a valid IANA identifier."
        ) from exc


def _ensure_utc(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidScheduledTaskSchedule("Datetime values must be timezone-aware.")
    return value.astimezone(datetime.UTC)
