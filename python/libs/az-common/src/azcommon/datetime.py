import datetime

import pytz


def localize(tz: datetime.tzinfo, dt: datetime.datetime) -> datetime.datetime:
    """
    Localize a datetime consistently for both pytz and zoneinfo timezones.
    """
    if isinstance(tz, pytz.BaseTzInfo):
        return tz.localize(dt)
    else:
        return dt.replace(tzinfo=tz)


def tznow(tz: datetime.tzinfo | None = None) -> datetime.datetime:
    """
    Return the current time in the requested timezone.
    Use the system local timezone when timezone is None.
    """
    return datetime.datetime.now(datetime.UTC).astimezone(tz)
