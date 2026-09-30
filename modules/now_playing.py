"""What is playing on this PC (Windows media session) and how to control it."""
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


async def _session():
    global _manager
    if not AVAILABLE:
        return None
    if _manager is None:
        _manager = await SessionManager.request_async()
    return _manager.get_current_session()


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


async def state():
    """Current media session as a dict, or None when nothing is playing."""
    session = await _session()
    if session is None:
        return None
    props = await session.try_get_media_properties_async()
    info = session.get_playback_info()
    timeline = session.get_timeline_properties()
    status = {Status.PLAYING: "playing", Status.PAUSED: "paused"}.get(info.playback_status, "stopped")
    position = timeline.position.total_seconds()
    if status == "playing":
        try:
            position += max(0.0, time.time() - timeline.last_updated_time.timestamp())
        except (OverflowError, OSError, ValueError):
            pass
    duration = timeline.end_time.total_seconds() - timeline.start_time.total_seconds()
    controls = info.controls
    key = f"{session.source_app_user_model_id}|{props.title}|{props.artist}|{props.album_title}"
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
        "source": session.source_app_user_model_id.replace(".exe", ""),
        "title": props.title or "", "artist": props.artist or "", "album": props.album_title or "",
        "status": status, "position": max(0.0, position), "duration": max(0.0, duration),
        "can_prev": controls.is_previous_enabled, "can_next": controls.is_next_enabled,
        "cover": key if _cover_cache["data"] else "",
    }


def cover_bytes(key):
    return _cover_cache["data"] if _cover_cache["key"] == key else None


async def command(name, value=None):
    """Returns False when there is no media session to control."""
    session = await _session()
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
