from datetime import datetime as DateTime


class Entry:
    def __init__(self):
        self.created = DateTime.utcnow()
        self.updated = self.created
