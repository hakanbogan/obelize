import datetime as dt

created = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
seen = dt.datetime.fromtimestamp(0, dt.timezone.utc).replace(tzinfo=None)
