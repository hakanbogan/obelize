from datetime import datetime


def stamp():
    return datetime.utcnow().isoformat()


def at(timestamp):
    return datetime.utcfromtimestamp(timestamp)
