"""Events from this PC that the phone shows as notifications."""
import itertools
import threading
import time
from collections import deque

_LOCK = threading.Lock()
_EVENTS = deque(maxlen=100)
_IDS = itertools.count(1)


def push(title, text):
    with _LOCK:
        _EVENTS.append({"id": next(_IDS), "time": time.strftime("%H:%M"), "title": title, "text": text})


def since(last_id):
    """Events newer than last_id. A phone that has never asked gets only the newest id."""
    with _LOCK:
        if last_id < 0:
            return [], (_EVENTS[-1]["id"] if _EVENTS else 0)
        items = [e for e in _EVENTS if e["id"] > last_id]
        return items, (_EVENTS[-1]["id"] if _EVENTS else last_id)
