from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo


BUSINESS_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def local_datetime(value: datetime) -> datetime:
    """MySQL returns stored UTC timestamps without timezone information."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BUSINESS_ZONE)


def utc_start_of_day(value: date) -> datetime:
    return datetime.combine(value, time.min, BUSINESS_ZONE).astimezone(timezone.utc).replace(tzinfo=None)
