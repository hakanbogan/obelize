import datetime
from datetime import datetime as DateTime

aware = datetime.datetime.now(datetime.timezone.utc)
local = DateTime.now()
epoch = DateTime.fromtimestamp(0, datetime.timezone.utc)
