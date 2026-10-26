from datetime import datetime


def stamp(event):
    match event:
        case {"zone": timezone}:
            return datetime.utcnow(), timezone
        case [first, *timezone]:
            return first, timezone
