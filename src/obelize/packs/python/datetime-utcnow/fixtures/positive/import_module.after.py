import datetime
import json


def event(name):
    stamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return json.dumps({"name": name, "at": stamp.isoformat()})
