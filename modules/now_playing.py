"""What is playing on this PC (Windows media sessions: streaming apps, browsers, players)
and how to control it."""
import time

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
    )
    from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions
    AVAILABLE = True
except ImportError:  # optional dependency: winrt-Windows.Media.Control
    AVAILABLE = False

_manager = None
_cover_cache = {"key": None, "data": None}

BROWSERS = ("chrome", "msedge", "edge", "firefox", "opera", "brave", "vivaldi", "yandex.exe", "yandexbrowser", "browser")
STREAMING = ("spotify", "yandex.desktop.music", "yandexmusic", "music.yandex", "deezer", "tidal", "soundcloud",
             "applemusic", "apple music", "itunes", "amazon", "youtube", "vk", "boom", "zvuk", "napster", "qobuz")
# Window-title / process hints to find the window of a session's app.
WINDOW_HINTS = {
    "yandex.desktop.music": ("яндекс музыка", "yandex music", "yandexmusic"),
    "spotify": ("spotify",),
    "applemusic": ("apple music", "itunes"),
}


def kind_of(app_id):
    """'browser' | 'stream' | 'local' for a media session's app id."""
    low = (app_id or "").lower()
    if any(word in low for word in STREAMING):
        return "stream"
    if any(word in low for word in BROWSERS):
        return "browser"
    return "local"


async def _manager_():
    global _manager
    if not AVAILABLE:
        return None
    if _manager is None:
        _manager = await SessionManager.request_async()
    return _manager


async def _session(source=None):
    manager = await _manager_()
    if manager is None:
        return None
    if source:
        for session in manager.get_sessions():
            if session.source_app_user_model_id == source:
                return session
        return None
    return manager.get_current_session()


async def _read_cover(thumbnail):
    stream = await thumbnail.open_read_async()
    size = stream.size
    if not size or size > 8 * 1024 * 1024:
        return None
    buffer = Buffer(size)
    await stream.read_async(buffer, size, InputStreamOptions.NONE)
    data = bytearray(size)
    DataReader.from_buffer(buffer).read_bytes(data)
    return bytes(data)


def _status_name(info):
    return {Status.PLAYING: "playing", Status.PAUSED: "paused"}.get(info.playback_status, "stopped")


async def sessions():
    """All media sessions: [{id, kind, title, artist, status}] (who is playing right now)."""
    manager = await _manager_()
    if manager is None:
        return []
    current = manager.get_current_session()
    current_id = current.source_app_user_model_id if current else None
    result = []
    for session in manager.get_sessions():
        try:
            props = await session.try_get_media_properties_async()
            app_id = session.source_app_user_model_id
            result.append({
                "id": app_id, "source": app_id.replace(".exe", ""), "kind": kind_of(app_id),
                "title": props.title or "", "artist": props.artist or "",
                "status": _status_name(session.get_playback_info()), "current": app_id == current_id,
            })
        except Exception:
            continue
    return result


async def state(source=None):
    """A media session as a dict (the current one, or the one of `source`), None if nothing."""
    session = await _session(source)
    if session is None:
        return None
    props = await session.try_get_media_properties_async()
    info = session.get_playback_info()
    timeline = session.get_timeline_properties()
    status = _status_name(info)
    position = timeline.position.total_seconds()
    if status == "playing":
        try:
            position += max(0.0, time.time() - timeline.last_updated_time.timestamp())
        except (OverflowError, OSError, ValueError):
            pass
    duration = timeline.end_time.total_seconds() - timeline.start_time.total_seconds()
    controls = info.controls
    app_id = session.source_app_user_model_id
    key = f"{app_id}|{props.title}|{props.artist}|{props.album_title}"
    # Some players publish the cover a moment after the title, so keep retrying
    # until it arrives instead of remembering "no cover" for this track.
    if _cover_cache["key"] != key or _cover_cache["data"] is None:
        data = None
        if props.thumbnail is not None:
            try:
                data = await _read_cover(props.thumbnail)
            except Exception:
                data = None
        _cover_cache.update(key=key, data=data)
    return {
        "id": app_id, "source": app_id.replace(".exe", ""), "kind": kind_of(app_id),
        "title": props.title or "", "artist": props.artist or "", "album": props.album_title or "",
        "status": status, "position": max(0.0, position), "duration": max(0.0, duration),
        "can_prev": controls.is_previous_enabled, "can_next": controls.is_next_enabled,
        "cover": key if _cover_cache["data"] else "",
    }


def cover_bytes(key):
    return _cover_cache["data"] if _cover_cache["key"] == key else None


async def command(name, value=None, source=None):
    """Returns False when there is no media session to control."""
    session = await _session(source)
    if session is None:
        return False
    if name == "toggle":
        return await session.try_toggle_play_pause_async()
    if name == "play":
        return await session.try_play_async()
    if name == "pause":
        return await session.try_pause_async()
    if name == "next":
        return await session.try_skip_next_async()
    if name == "prev":
        return await session.try_skip_previous_async()
    if name == "seek":
        return await session.try_change_playback_position_async(int(float(value) * 10_000_000))
    raise ValueError("Неизвестная команда плеера.")


def focus_source_window(app_id, title=""):
    """Bring the window of the app that is playing (streaming app or browser tab) to the front.
    Returns the window title, or raises ValueError when nothing matches."""
    import os
    import psutil
    import win32con
    import win32gui
    import win32process

    low_id = (app_id or "").lower()
    hints = [low_id.replace(".exe", "")]
    for key, extra in WINDOW_HINTS.items():
        if key in low_id:
            hints += list(extra)
    wanted_title = (title or "").strip().lower()
    candidates = []

    def visit(hwnd, _):
        window_title = win32gui.GetWindowText(hwnd)
        if not window_title or not win32gui.IsWindowVisible(hwnd):
            return
        if win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            exe = os.path.basename(psutil.Process(pid).exe()).lower()
        except (psutil.Error, OSError):
            exe = ""
        text = window_title.lower()
        score = 0
        if wanted_title and wanted_title in text:
            score += 10                      # a browser tab title usually contains the track name
        if any(h and (h in exe or h in text) for h in hints):
            score += 5
        if score:
            candidates.append((score, hwnd, window_title))

    win32gui.EnumWindows(visit, None)
    if not candidates:
        raise ValueError("Окно плеера не найдено на ПК.")
    _, hwnd, window_title = max(candidates)
    from modules.winutil import bring_to_front
    bring_to_front(hwnd)
    return window_title
