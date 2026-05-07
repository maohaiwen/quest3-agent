"""Beijing time (UTC+8) utilities"""

from datetime import datetime, timezone, timedelta

_BEIJING_TZ = timezone(timedelta(hours=8))


def beijing_now() -> datetime:
    """Return current Beijing time as a timezone-aware datetime (UTC+8)."""
    return datetime.now(_BEIJING_TZ)
