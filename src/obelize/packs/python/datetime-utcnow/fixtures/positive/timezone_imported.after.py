from datetime import datetime, timedelta, timezone


def deadline(days):
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days)


def local_noon():
    return datetime.now(timezone.utc).replace(hour=12)
