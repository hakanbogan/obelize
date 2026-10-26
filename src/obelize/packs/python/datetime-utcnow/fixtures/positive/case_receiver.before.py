from datetime import datetime


def stamp(event):
    match event:
        case {"clock": datetime}:
            return datetime.utcnow()
