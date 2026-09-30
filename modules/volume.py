"""Exact Windows master volume (optional dependency: pycaw). Without it the phone uses volume keys.

IMPORTANT: comtypes/pycaw must be imported only inside the dedicated thread below. Importing comtypes
initializes COM as a single-threaded apartment for the importing thread, and in the API (asyncio) thread
that would freeze the WinRT "now playing" calls. All volume COM work therefore lives in one thread of its own.
"""
import importlib.util
from concurrent.futures import ThreadPoolExecutor

AVAILABLE = importlib.util.find_spec("pycaw") is not None and importlib.util.find_spec("comtypes") is not None

_executor = None
_audio = {}


def _init_thread():
    from pycaw.pycaw import AudioUtilities      # imports comtypes -> COM initialized for THIS thread only
    _audio["utilities"] = AudioUtilities


def _run(function, *args):
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pulse-volume", initializer=_init_thread)
    return _executor.submit(function, *args).result(timeout=5)


def _endpoint():
    return _audio["utilities"].GetSpeakers().EndpointVolume


def _get():
    endpoint = _endpoint()
    return {"level": round(endpoint.GetMasterVolumeLevelScalar() * 100), "muted": bool(endpoint.GetMute())}


def _set_level(level):
    _endpoint().SetMasterVolumeLevelScalar(level / 100.0, None)
    return level


def _adjust(delta):
    endpoint = _endpoint()
    level = max(0, min(100, round(endpoint.GetMasterVolumeLevelScalar() * 100) + delta))
    endpoint.SetMasterVolumeLevelScalar(level / 100.0, None)
    return level


def _set_muted(muted):
    _endpoint().SetMute(1 if muted else 0, None)


def get():
    """{'level': 0..100, 'muted': bool}, or None when exact volume is not available."""
    if not AVAILABLE:
        return None
    try:
        return _run(_get)
    except Exception:
        return None


def set_level(level):
    return _run(_set_level, max(0, min(100, int(level))))


def adjust(delta):
    return _run(_adjust, int(delta))


def set_muted(muted):
    _run(_set_muted, bool(muted))
