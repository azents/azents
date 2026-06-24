"""Timezone-aware datetime type."""

import datetime

import pytz
from sqlalchemy import DateTime, TypeDecorator


class TimeZoneDateTime(TypeDecorator[datetime.datetime]):
    """Timezone-aware datetime type.

    Values are converted to UTC before storage, and result values are returned
    with UTC timezone information attached.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self,
        value: datetime.datetime | None,
        dialect: object,
    ) -> datetime.datetime | None:
        """Convert values to UTC before storing them in the DB."""
        if value is None:
            return None
        if value.tzinfo is None:
            # Treat naive datetimes as UTC.
            return value.replace(tzinfo=pytz.UTC)
        return value.astimezone(pytz.UTC)

    def process_result_value(
        self,
        value: datetime.datetime | None,
        dialect: object,
    ) -> datetime.datetime | None:
        """Attach UTC timezone information to values read from the DB."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=pytz.UTC)
        return value
