import datetime
import json


def event(name):
    stamp = datetime.datetime.utcnow()
    return json.dumps({"name": name, "at": stamp.isoformat()})
