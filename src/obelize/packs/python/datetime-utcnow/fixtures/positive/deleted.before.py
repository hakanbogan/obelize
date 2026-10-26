from datetime import datetime, timezone

DEFAULT = timezone
del timezone
NOW = datetime.utcnow()
