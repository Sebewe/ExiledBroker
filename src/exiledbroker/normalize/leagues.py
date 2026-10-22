from datetime import datetime

SECONDS_PER_DAY = 86_400


def day_offset(observed_at: datetime, league_start: datetime) -> float:
    """Days elapsed since the league started; the axis all price curves share."""
    return (observed_at - league_start).total_seconds() / SECONDS_PER_DAY
