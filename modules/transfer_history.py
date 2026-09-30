"""Bounded transfer history; recording failures never breaks a file operation."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import threading
import uuid

import config
from modules.bot_preferences import atomic_json

LOCK = threading.RLock()
logger = logging.getLogger(__name__)


def load_history():
    with LOCK:
        path = Path(config.BASE_DIR) / "transfers.json"
        entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        if not isinstance(entries, list) or any(not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("id", "time", "path", "name", "direction", "status")) for item in entries):
            raise ValueError("Повреждена история передач.")
        return entries[-100:]


def record_transfer(path, direction, status, error=""):
    from desktop_services import redact
    try:
        path = Path(os.path.expandvars(str(path).strip().strip('"'))).expanduser()
        item = dict(id=uuid.uuid4().hex, time=datetime.now().isoformat(timespec="seconds"),
                    path=str(path.absolute()), name=path.name, direction=direction, status=status,
                    error=redact(str(error))[:300])
        with LOCK:
            entries = load_history()
            atomic_json(Path(config.BASE_DIR) / "transfers.json", (entries + [item])[-100:])
    except (OSError, ValueError) as exc:
        logger.warning("Не удалось сохранить историю передачи: %s", exc)


@asynccontextmanager
async def track_transfer(path, direction="outgoing"):
    try:
        yield
    except asyncio.CancelledError:
        record_transfer(path, direction, "cancelled")
        raise
    except Exception as exc:
        record_transfer(path, direction, "error", exc)
        raise
    else:
        record_transfer(path, direction, "sent" if direction == "outgoing" else "received")
