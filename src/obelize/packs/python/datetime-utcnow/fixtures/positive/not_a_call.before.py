from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Event:
    created: datetime = field(default_factory=datetime.utcnow)
    seen: datetime = field(default_factory=lambda: datetime.utcnow())
