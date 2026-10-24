from datetime import datetime


def stamp(timezone):
    # The parameter hides the name the new spelling would be imported by.
    return datetime.utcnow(), timezone
