"""LAN HTTP API for the Pulse PC mobile app (same actions as the Telegram bot).

Every request except /api/ping and /api/pair needs `Authorization: Bearer <token>`.
Each phone gets its own token when the PC owner approves it (see mobile_access.py).
The PC also answers UDP discovery broadcasts so phones can find it automatically.
"""
import asyncio
import ipaddress
import json
import logging
import os
import socket
import subprocess
import webbrowser
from io import BytesIO

from aiohttp import web

import config
from desktop_services import computer_info
from modules import mobile_access, notify_bus, now_playing, player_bridge, volume as system_volume
from modules.keyboards import load_programs
from modules.program_store import effective_process
from modules.utils import kill_process

logger = logging.getLogger(__name__)
MAX_FILE_BYTES = 200 * 1024 * 1024
# Read-only endpoints that still work while the PC is locked (phone notifications).
READ_WHEN_LOCKED = {"/api/status", "/api/events", "/api/player/state", "/api/player/cover"}
MEDIA_KEYS = {"prev": "prevtrack", "play": "playpause", "next": "nexttrack",
              "voldown": "volumedown", "volup": "volumeup", "mute": "volumemute"}


def lan_addresses():
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                found.add(ip)
    except OSError:
        pass
    return sorted(found)


def json_error(status, text):
    return web.json_response({"ok": False, "error": text}, status=status)


def is_private_ip(ip):
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


def ask_owner(text):
    """Yes/No dialog on the PC desktop (blocking; run it in a thread)."""
    import ctypes
    MB_YESNO, MB_ICONQUESTION, MB_SETFOREGROUND, MB_TOPMOST = 0x4, 0x20, 0x10000, 0x40000
    IDYES = 6
    return ctypes.windll.user32.MessageBoxW(
        0, text, "Pulse PC — новое устройство", MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND | MB_TOPMOST) == IDYES


def make_app(features_getter=lambda: None):
    from modules.monitor import workstation_locked
    pairing_lock = asyncio.Lock()

    @web.middleware
    async def guard(request, handler):
        if request.path not in ("/api/ping", "/api/pair"):
            given = request.headers.get("Authorization", "")
            device = await asyncio.to_thread(mobile_access.authenticate, given[7:] if given.startswith("Bearer ") else "")
            if not device:
                return json_error(401, "Устройство не подключено или отозвано.")
            # Same rule as the Telegram bot: no control while the PC is locked.
            if request.path not in READ_WHEN_LOCKED and await asyncio.to_thread(workstation_locked):
                return json_error(423, "ПК заблокирован. Управление недоступно.")
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except ValueError as exc:
            return json_error(400, str(exc))
        except Exception as exc:
            logger.exception("Local API error")
            return json_error(500, str(exc))

    routes = web.RouteTableDef()

    @routes.get("/api/ping")
    async def ping(_):
        return web.json_response({"ok": True, "app": "PulsePC", "name": socket.gethostname()})

    @routes.get("/api/status")
    async def status(_):
        text = await asyncio.to_thread(computer_info)
        locked = await asyncio.to_thread(workstation_locked)
        features = features_getter()
        power = None
        if features and features.power_task and not features.power_task.done() and features.power_deadline:
            import time
            power = {"action": features.power_action, "seconds": max(0, int(features.power_deadline - time.monotonic()))}
        return web.json_response({"ok": True, "name": socket.gethostname(), "locked": locked, "info": text, "power": power})

    @routes.get("/api/programs")
    async def programs(_):
        items = load_programs()
        return web.json_response({"ok": True, "programs": [
            {"id": p.get("id") or str(i), "name": p["name"]} for i, p in enumerate(items)]})

    def find_program(key):
        for i, program in enumerate(load_programs()):
            if (program.get("id") or str(i)) == key:
                return program
        raise ValueError("Программа не найдена.")

    @routes.post("/api/programs/{key}/run")
    async def run_program(request):
        program = find_program(request.match_info["key"])
        path = os.path.expandvars(program["path"])
        try:
            os.startfile(path)
        except AttributeError:
            subprocess.Popen([path])
        return web.json_response({"ok": True, "message": f"Запущено: {program['name']}"})

    @routes.post("/api/programs/{key}/kill")
    async def kill_program(request):
        program = find_program(request.match_info["key"])
        process = await asyncio.to_thread(effective_process, program)
        if not process:
            raise ValueError("Имя процесса не настроено.")
        ok, error = await kill_process(process)
        if not ok:
            raise ValueError(error or "Не удалось закрыть программу.")
        return web.json_response({"ok": True, "message": f"Закрыто: {program['name']}"})

    @routes.get("/api/volume")
    async def get_volume(_):
        level = await asyncio.to_thread(system_volume.get)
        if level is None:
            raise ValueError("Точная громкость недоступна: установите pycaw (pip install pycaw).")
        return web.json_response({"ok": True, **level})

    @routes.post("/api/volume")
    async def set_volume(request):
        """{level: 0..100} | {delta: -100..100} | {muted: bool}"""
        if not system_volume.AVAILABLE:
            raise ValueError("Точная громкость недоступна: установите pycaw (pip install pycaw).")
        body = await request.json() if request.can_read_body else {}
        if "level" in body:
            if type(body["level"]) is not int:
                raise ValueError("Уровень должен быть числом 0–100.")
            await asyncio.to_thread(system_volume.set_level, body["level"])
        elif "delta" in body:
            if type(body["delta"]) is not int or not -100 <= body["delta"] <= 100:
                raise ValueError("Изменение должно быть числом от -100 до 100.")
            await asyncio.to_thread(system_volume.adjust, body["delta"])
        elif "muted" in body:
            if type(body["muted"]) is not bool:
                raise ValueError("muted: true или false.")
            await asyncio.to_thread(system_volume.set_muted, body["muted"])
        else:
            raise ValueError("Укажите level, delta или muted.")
        return web.json_response({"ok": True, **(await asyncio.to_thread(system_volume.get) or {})})

    @routes.post("/api/media/{action}")
    async def media(request):
        key = MEDIA_KEYS.get(request.match_info["action"])
        if not key:
            raise ValueError("Неизвестное действие.")
        body = await request.json() if request.can_read_body else {}
        count = body.get("count", 1)
        if type(count) is not int or not 1 <= count <= 25:
            raise ValueError("Повторов должно быть от 1 до 25.")
        import pyautogui
        await asyncio.to_thread(pyautogui.press, key, presses=count, interval=0.02)
        return web.json_response({"ok": True})

    @routes.post("/api/system/{action}")
    async def system(request):
        action = request.match_info["action"]
        if action == "lock":
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
        elif action == "sleep":
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"])
        elif action == "close_active":
            from modules.winutil import close_foreground_window
            title = await asyncio.to_thread(close_foreground_window)
            return web.json_response({"ok": True, "message": f"Закрыто: {title}"})
        elif action in ("shutdown", "restart"):
            features = features_getter()
            if not features:
                raise ValueError("Бот ещё не готов.")
            body = await request.json() if request.can_read_body else {}
            minutes = body.get("minutes", 1)
            if type(minutes) is not int:
                raise ValueError("Укажите минуты числом.")
            features.schedule_power(action, minutes)
        elif action == "cancel":
            features = features_getter()
            cancelled = bool(features and await features.cancel_power())
            return web.json_response({"ok": True, "message": "Таймер отменён." if cancelled else "Нет активного таймера."})
        else:
            raise ValueError("Неизвестное действие.")
        return web.json_response({"ok": True})

    @routes.get("/api/screenshot")
    async def screenshot(request):
        monitor = int(request.query.get("monitor", "0"))
        width = min(max(int(request.query.get("width", "1280")), 320), 3840)

        def grab():
            import mss
            from PIL import Image
            with mss.mss() as sct:
                if not 0 <= monitor < len(sct.monitors):
                    raise ValueError("Монитор не найден.")
                shot = sct.grab(sct.monitors[monitor])
                image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            if image.width > width:
                image = image.resize((width, round(image.height * width / image.width)))
            out = BytesIO()
            image.save(out, format="JPEG", quality=70)
            return out.getvalue()
        return web.Response(body=await asyncio.to_thread(grab), content_type="image/jpeg")

    @routes.post("/api/open_url")
    async def open_url(request):
        url = str((await request.json()).get("url", "")).strip()
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("Нужна ссылка http:// или https://")
        webbrowser.open(url)
        return web.json_response({"ok": True})

    @routes.get("/api/windows")
    async def windows(_):
        from modules.bot_features import list_windows
        items = await asyncio.to_thread(list_windows)
        return web.json_response({"ok": True, "windows": items[:40]})

    @routes.post("/api/windows/{hwnd}/{action}")
    async def window_action(request):
        from modules.bot_features import list_windows, change_window
        hwnd = int(request.match_info["hwnd"])
        window = next((w for w in await asyncio.to_thread(list_windows) if w["hwnd"] == hwnd), None)
        if not window:
            raise ValueError("Это окно уже закрыто. Обновите список.")
        if request.match_info["action"] == "close":
            import win32gui
            import win32con
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        else:
            await asyncio.to_thread(change_window, window, request.match_info["action"])
        return web.json_response({"ok": True})

    # ---- Files ----
    @routes.get("/api/files/roots")
    async def files_roots(_):
        from modules.bot_features import file_roots
        roots = await asyncio.to_thread(file_roots)
        return web.json_response({"ok": True, "roots": [{"name": t, "path": str(p)} for t, p in roots]})

    def scan_directory(path):
        from pathlib import Path
        target = Path(path).resolve(strict=True)
        if not target.is_dir():
            raise ValueError("Это не папка.")
        items = []
        with os.scandir(target) as scan:
            for entry in scan:
                if len(items) >= 2000:
                    break
                try:
                    is_dir = entry.is_dir()
                    size = 0 if is_dir else entry.stat().st_size
                except OSError:
                    continue
                items.append({"name": entry.name, "dir": is_dir, "size": size})
        items.sort(key=lambda i: (not i["dir"], i["name"].casefold()))
        parent = str(target.parent) if target.parent != target else ""
        return {"ok": True, "path": str(target), "parent": parent, "items": items}

    @routes.get("/api/files/list")
    async def files_list(request):
        path = request.query.get("path", "")
        if not path:
            raise ValueError("Не указана папка.")
        try:
            return web.json_response(await asyncio.to_thread(scan_directory, path))
        except OSError as exc:
            raise ValueError(f"Папка недоступна: {exc.strerror or exc}")

    @routes.get("/api/files/download")
    async def files_download(request):
        from modules.transfer_history import record_transfer
        from pathlib import Path
        path = Path(request.query.get("path", "")).resolve()
        if not path.is_file():
            raise ValueError("Файл не найден.")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Файл больше 200 МБ.")
        record_transfer(path, "outgoing", "sent")
        return web.FileResponse(path, headers={"Content-Disposition": "attachment"})

    @routes.post("/api/files/upload")
    async def files_upload(request):
        from pathlib import Path
        from modules.transfer_history import record_transfer
        name = Path(request.query.get("name", "file").replace("\\", "/")).name or "file"
        target_dir = Path(config.APP_DIR) / "files"
        target_dir.mkdir(exist_ok=True)
        target = target_dir / name
        counter = 1
        while target.exists():
            target = target_dir / f"{Path(name).stem}_{counter}{Path(name).suffix}"
            counter += 1
        part = target.with_name(target.name + ".part")
        size = 0
        try:
            with open(part, "wb") as stream:
                async for chunk in request.content.iter_chunked(1 << 16):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise ValueError("Файл больше 200 МБ.")
                    await asyncio.to_thread(stream.write, chunk)
            if size == 0:
                raise ValueError("Пустой файл.")
            os.replace(part, target)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        record_transfer(target, "incoming", "received")
        return web.json_response({"ok": True, "message": f"Сохранено на ПК: {target.name}"})

    @routes.get("/api/history")
    async def history(_):
        from modules.transfer_history import load_history
        items = await asyncio.to_thread(load_history)
        return web.json_response({"ok": True, "history": list(reversed(items))})

    # ---- Scenarios, search, monitors ----
    @routes.get("/api/scenarios")
    async def scenarios(_):
        from modules.bot_preferences import load_preferences
        prefs = await asyncio.to_thread(load_preferences)
        return web.json_response({"ok": True, "scenarios": [
            {"id": s["id"], "name": s["name"], "count": len(s["program_ids"])} for s in prefs["scenarios"]]})

    @routes.post("/api/scenarios/{key}/run")
    async def run_scenario(request):
        features = features_getter()
        if not features:
            raise ValueError("Бот ещё не готов.")
        launched = await features.run_scenario(request.match_info["key"])
        return web.json_response({"ok": True, "message": "Запущено: " + ", ".join(launched)})

    @routes.post("/api/search")
    async def search(request):
        import urllib.parse
        query = str((await request.json()).get("query", "")).strip()
        if not query:
            raise ValueError("Введите запрос.")
        webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(query))
        return web.json_response({"ok": True})

    @routes.get("/api/monitors")
    async def monitors(_):
        def count():
            import mss
            with mss.mss() as sct:
                return len(sct.monitors) - 1
        return web.json_response({"ok": True, "count": await asyncio.to_thread(count)})

    # ---- Player ----
    def own_player():
        """State of the built-in player in the same shape as a media session."""
        own = player_bridge.snapshot()
        return {"id": "pulse", "source": "Pulse PC", "kind": "own", "title": own["title"], "artist": own["artist"],
                "album": own["album"], "status": own["status"], "position": own["position"],
                "duration": own["duration"], "can_prev": True, "can_next": True,
                "cover": own["cover_key"] if own["cover"] else "", "volume": own["volume"]}

    async def external_player(source=None):
        return await now_playing.state(source) if now_playing.AVAILABLE else None

    @routes.get("/api/player/state")
    async def player_state(request):
        """source: '' = automatic, 'pulse' = built-in player, anything else = app id of a media session."""
        source = request.query.get("source", "")
        own = player_bridge.snapshot()
        if source == "pulse":
            data = own_player() if own["active"] else None
        elif source:
            data = await external_player(source)
        else:
            external = await external_player()
            # The built-in player wins unless it is paused while another app is playing.
            if own["active"] and (own["status"] == "playing" or not external or external["status"] != "playing"):
                data = own_player()
            else:
                data = external
        level = await asyncio.to_thread(system_volume.get)        # exact PC volume when pycaw is installed
        return web.json_response({"ok": True, "player": data or {"status": "none"}, "system_volume": level})

    @routes.get("/api/player/sessions")
    async def player_sessions(_):
        """Everything that can be controlled: the built-in player and media sessions of other apps."""
        items = await now_playing.sessions() if now_playing.AVAILABLE else []
        own = player_bridge.snapshot()
        if own["active"]:
            items.insert(0, {"id": "pulse", "source": "Pulse PC", "kind": "own", "title": own["title"],
                             "artist": own["artist"], "status": own["status"], "current": False})
        return web.json_response({"ok": True, "sessions": items})

    @routes.post("/api/player/focus")
    async def player_focus(request):
        """Show the window of the app that is playing (streaming service or browser) on the PC."""
        body = await request.json() if request.can_read_body else {}
        source = str(body.get("source") or "")
        data = await external_player(source or None)
        if not data:
            raise ValueError("Сейчас нечего открывать.")
        title = await asyncio.to_thread(now_playing.focus_source_window, data["id"], data["title"])
        return web.json_response({"ok": True, "message": f"Открыто на ПК: {title}"})

    @routes.get("/api/player/cover")
    async def player_cover(request):
        key = request.query.get("key", "")
        own = player_bridge.snapshot()
        data = own["cover"] if own["cover"] and own["cover_key"] == key else now_playing.cover_bytes(key)
        if not data:
            return json_error(404, "Обложки нет.")
        return web.Response(body=data, content_type="image/png" if data[1:4] == b"PNG" else "image/jpeg")

    @routes.post("/api/player/tracks/open")
    async def player_open(request):
        path = str((await request.json()).get("path", ""))
        if not await asyncio.to_thread(player_bridge.is_library_track, path):
            raise ValueError("Этого трека нет в библиотеке плеера Pulse PC.")
        player_bridge.send("open", path)
        return web.json_response({"ok": True})

    @routes.get("/api/player/tracks")
    async def player_tracks(_):
        tracks = await asyncio.to_thread(player_bridge.scan_tracks)
        return web.json_response({"ok": True, "tracks": tracks})

    @routes.post("/api/player/{cmd}")
    async def player_command(request):
        cmd = request.match_info["cmd"]
        body = await request.json() if request.can_read_body else {}
        value = body.get("value")
        source = str(body.get("source") or "")
        if cmd not in ("toggle", "play", "pause", "next", "prev", "seek", "volume"):
            raise ValueError("Неизвестная команда плеера.")
        own = player_bridge.snapshot()
        if source == "pulse" or (not source and own["active"]):
            player_bridge.send(cmd, value)
            return web.json_response({"ok": True})
        if cmd == "volume":
            raise ValueError("Громкость плеера доступна только во встроенном плеере Pulse PC.")
        handled = now_playing.AVAILABLE and await now_playing.command(cmd, value, source or None)
        if not handled and source:
            raise ValueError("Этот источник больше не играет.")
        if not handled:
            keys = {"toggle": "playpause", "play": "playpause", "pause": "playpause", "next": "nexttrack", "prev": "prevtrack"}
            if cmd not in keys:
                raise ValueError("Сейчас ничего не играет.")
            import pyautogui
            await asyncio.to_thread(pyautogui.press, keys[cmd])
        return web.json_response({"ok": True})

    # ---- Notifications for the phone ----
    @routes.get("/api/events")
    async def events(request):
        items, last = notify_bus.since(int(request.query.get("after", "-1")))
        return web.json_response({"ok": True, "events": items, "last": last})

    # ---- Pairing ----
    @routes.post("/api/pair")
    async def pair(request):
        # The phone asks to be added; the PC owner must approve it in a dialog.
        if not mobile_access.load()["allow_pairing"]:
            return json_error(403, "Новые устройства отключены в настройках Pulse PC (вкладка «Телефон»).")
        if not is_private_ip(request.remote or ""):
            return json_error(403, "Сопряжение доступно только из локальной сети.")
        if pairing_lock.locked():
            return json_error(409, "На ПК уже открыт запрос. Ответьте на него.")
        try:
            device = str((await request.json()).get("device", ""))[:40] or "Телефон"
        except ValueError:
            device = "Телефон"
        async with pairing_lock:
            try:
                allowed = await asyncio.wait_for(asyncio.to_thread(
                    ask_owner, f"Телефон «{device}» ({request.remote}) хочет управлять этим ПК.\n\nРазрешить?"), timeout=60)
            except asyncio.TimeoutError:
                return json_error(408, "На ПК не ответили на запрос.")
            if not allowed:
                return json_error(403, "Владелец ПК отклонил подключение.")
            token = await asyncio.to_thread(mobile_access.add_device, device)
        logger.info("Phone paired: %s (%s)", device, request.remote)
        return web.json_response({"ok": True, "token": token, "name": socket.gethostname()})

    app = web.Application(middlewares=[guard], client_max_size=MAX_FILE_BYTES + (1 << 20))
    app.add_routes(routes)
    return app


class DiscoveryProtocol(asyncio.DatagramProtocol):
    """Answers the phone's UDP broadcast "PULSEPC?" with this PC's name and port."""
    def __init__(self, port):
        self.port = port

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        if data.strip() == b"PULSEPC?" and is_private_ip(addr[0]):
            reply = json.dumps({"app": "PulsePC", "name": socket.gethostname(), "port": self.port})
            self.transport.sendto(reply.encode(), addr)


class LocalApiServer:
    def __init__(self, log_callback, features_getter=lambda: None):
        self.log = log_callback
        self.features_getter = features_getter
        self.runner = None
        self.discovery = None

    async def start(self):
        settings = mobile_access.load()
        if not settings["enabled"]:
            return
        self.runner = web.AppRunner(make_app(self.features_getter), access_log=None)
        await self.runner.setup()
        try:
            await web.TCPSite(self.runner, "0.0.0.0", settings["port"]).start()
        except OSError as exc:
            self.log(f"Локальный API не запущен (порт {settings['port']}): {exc}")
            await self.runner.cleanup()
            self.runner = None
            return
        try:
            loop = asyncio.get_running_loop()
            self.discovery, _ = await loop.create_datagram_endpoint(
                lambda: DiscoveryProtocol(settings["port"]), local_addr=("0.0.0.0", mobile_access.DISCOVERY_PORT))
        except OSError as exc:
            self.log(f"Автопоиск телефоном недоступен (UDP {mobile_access.DISCOVERY_PORT}): {exc}")
        addresses = [f"{ip}:{settings['port']}" for ip in lan_addresses()]
        mobile_access.STATE.update(running=True, port=settings["port"], addresses=addresses)
        self.log(f"Мобильный доступ: {', '.join(addresses) or settings['port']}. Телефоны: {len(settings['devices'])}")

    async def close(self):
        mobile_access.STATE.update(running=False, addresses=[])
        if self.discovery:
            self.discovery.close()
            self.discovery = None
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
