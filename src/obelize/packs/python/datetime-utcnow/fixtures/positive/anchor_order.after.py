from datetime import datetime
from datetime import timezone


def stamp(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).replace(tzinfo=None)


FIRST = stamp(0)

import logging

log = logging.getLogger(__name__)
NOW = datetime.now(timezone.utc).replace(tzinfo=None)
