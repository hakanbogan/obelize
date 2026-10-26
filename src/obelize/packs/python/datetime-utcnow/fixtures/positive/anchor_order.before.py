from datetime import datetime


def stamp(timestamp):
    return datetime.utcfromtimestamp(timestamp)


FIRST = stamp(0)

import logging

log = logging.getLogger(__name__)
NOW = datetime.utcnow()
