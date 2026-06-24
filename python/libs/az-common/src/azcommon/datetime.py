import datetime

import pytz


def localize(tz: datetime.tzinfo, dt: datetime.datetime) -> datetime.datetime:
    """
    pytz, zoneinfo 모두를 기준으로 isomorphic한 localize를 수행합니다.
    """
    if isinstance(tz, pytz.BaseTzInfo):
        return tz.localize(dt)
    else:
        return dt.replace(tzinfo=tz)


def tznow(tz: datetime.tzinfo | None = None) -> datetime.datetime:
    """
    timezone을 기준으로 현재 시간을 반환합니다.
    timezone이 None이면 시스템의 local timezone을 사용합니다.
    """
    return datetime.datetime.now().astimezone(tz)
