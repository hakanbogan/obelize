from datetime import datetime
from datetime import timezone


def stamp():
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def at(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).replace(tzinfo=None)
