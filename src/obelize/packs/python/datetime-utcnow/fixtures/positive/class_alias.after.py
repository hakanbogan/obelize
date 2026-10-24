from datetime import datetime as DateTime
from datetime import timezone


class Entry:
    def __init__(self):
        self.created = DateTime.now(timezone.utc).replace(tzinfo=None)
        self.updated = self.created
