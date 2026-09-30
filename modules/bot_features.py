"""Per-run state for browsing, power timers, scenarios and notifications."""
import asyncio
from collections import OrderedDict
import logging
import os
from pathlib import Path
import secrets
import subprocess
import time

import psutil
import config
from modules.bot_preferences import load_preferences
from modules.keyboards import load_programs

logger = logging.getLogger(__name__)


class ActionTokens:
    def __init__(self):
        self.items = OrderedDict()

    def create(self, owner, kind, value, ttl=1800):
        key = secrets.token_hex(6)
        self.items[key] = (owner, kind, value, time.monotonic() + ttl)
        while len(self.items) > 1000:
            self.items.popitem(last=False)
        return key

    def get(self, key, owner, kind, *, consume=False):
        item = self.items.get(key)
        if not item or item[0] != owner or item[1] != kind or item[3] < time.monotonic():
            raise ValueError("Кнопка устарела. Откройте нужное меню заново.")
        if consume:
            self.items.pop(key)
        return item[2]


def file_roots():
    import winreg
    result = []
    for title, key, fallback in (("Рабочий стол", "Desktop", "Desktop"),
                                 ("Документы", "Personal", "Documents"),
                                 ("Загрузки", "{374DE290-123F-4565-9164-39C4925E467B}", "Downloads")):
        path = Path.home() / fallback
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as registry:
                path = Path(os.path.expandvars(winreg.QueryValueEx(registry, key)[0]))
        except OSError:
            pass
        result.append((title, path))
    result.append(("Домашняя папка", Path.home()))
    result.append(("Полученные файлы", Path(config.APP_DIR) / "files"))
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        path = Path(f"{letter}:\\")
        if path.exists():
            result.append((f"Диск {letter}:", path))
    return result


def list_directory(path, page=0):
    path = Path(path).resolve(strict=True)
    entries = []
    capped = False
    with os.scandir(path) as scan:
        for item in scan:
            if len(entries) >= 5000:
                capped = True
                break
            try:
                entries.append((item.is_dir(), item.name, Path(item.path)))
            except OSError:
                continue
    entries.sort(key=lambda entry: (not entry[0], entry[1].casefold()))
    page = max(0, min(page, max(0, (len(entries) - 1) // 12)))
    return path, entries[page * 12:(page + 1) * 12], page, len(entries), capped


def list_windows():
    import win32gui
    import win32con
    import win32process
    result = []
    def visit(hwnd, _):
        title = win32gui.GetWindowText(hwnd)
        if title and win32gui.IsWindowVisible(hwnd) and not win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if title not in ("Program Manager", "Taskbar"):
                result.append(dict(hwnd=hwnd, pid=pid, title=title))
    win32gui.EnumWindows(visit, None)
    return result


def change_window(window, action):
    import win32gui
    import win32con
    import win32process
    hwnd = window["hwnd"]
    if not win32gui.IsWindow(hwnd) or win32process.GetWindowThreadProcessId(hwnd)[1] != window["pid"]:
        raise ValueError("Это окно уже закрыто. Обновите список.")
    if action == "min":
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
    elif action == "max":
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    elif action == "focus":
        from modules.winutil import bring_to_front
        bring_to_front(hwnd)
    else:
        raise ValueError("Неизвестное действие с окном.")


class AlertEvaluator:
    def __init__(self):
        self.cpu_since = None
        self.last_sent = {}
        self.previous_processes = None
        self.watched = set()

    def evaluate(self, settings, snapshot, now):
        events = []
        cooldown = settings["cooldown_minutes"] * 60
        def add(key, text):
            if now - self.last_sent.get(key, -float("inf")) >= cooldown:
                events.append(text)
                self.last_sent[key] = now
        if settings["cpu_enabled"] and snapshot["cpu"] >= settings["cpu_percent"]:
            if self.cpu_since is None:
                self.cpu_since = now
            if now - self.cpu_since >= settings["cpu_seconds"]:
                add("cpu", f"Процессор: {snapshot['cpu']:.0f}% — высокая нагрузка дольше {settings['cpu_seconds']} с.")
        else:
            self.cpu_since = None
        if settings["disk_enabled"]:
            for disk, free in snapshot["disks"]:
                if free < settings["disk_free_gb"]:
                    add("disk:" + disk, f"На диске {disk} осталось {free:.1f} ГБ.")
        watched = {p.lower() for p in settings["processes"]}
        current = snapshot["processes"]
        if self.previous_processes is not None:
            for process in watched & self.watched & self.previous_processes - current:
                add("process:" + process, f"Программа завершена: {process}")
        self.previous_processes, self.watched = current, watched
        return events


def alert_snapshot():
    disks = []
    for disk in psutil.disk_partitions():
        if not disk.fstype or "cdrom" in disk.opts:
            continue
        try:
            disks.append((disk.mountpoint, psutil.disk_usage(disk.mountpoint).free / 1024 ** 3))
        except OSError:
            continue
    processes = set()
    for process in psutil.process_iter(["name"]):
        try:
            if process.info["name"]:
                processes.add(process.info["name"].lower())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return dict(cpu=psutil.cpu_percent(interval=0.2), disks=disks, processes=processes)


class BotFeatures:
    def __init__(self, bot):
        self.bot = bot
        self.tokens = ActionTokens()
        self.power_task = None
        self.power_deadline = None
        self.power_action = None
        self.alert_task = None
        self.closed = False
        self.scenario_lock = asyncio.Lock()

    def start(self):
        self.alert_task = asyncio.create_task(self.monitor_alerts())

    async def close(self):
        self.closed = True
        tasks = [task for task in (self.power_task, self.alert_task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.power_task = self.alert_task = None
        self.power_deadline = None
        self.tokens.items.clear()

    async def cancel_power(self):
        task = self.power_task
        if not task or task.done():
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.power_task = None
        self.power_deadline = None
        return True

    def schedule_power(self, action, minutes):
        if self.closed or action not in ("shutdown", "restart") or type(minutes) is not int or not 0 <= minutes <= 1440:
            raise ValueError("Таймер: от 0 до 1440 минут.")
        if self.power_task and not self.power_task.done():
            raise ValueError("Уже есть таймер. Сначала отмените его.")
        # Even 'now' provides a short cancellation window after confirmation.
        seconds = max(10, minutes * 60)
        self.power_deadline = time.monotonic() + seconds
        self.power_action = action
        self.power_task = asyncio.create_task(self._power_after(seconds, action))
        return seconds

    async def _power_after(self, seconds, action):
        try:
            await asyncio.sleep(seconds)
            if self.closed:
                return
            try:
                await self.bot.send_message(config.ADMIN_ID, "Выполняю подтверждённую перезагрузку." if action == "restart" else "Выполняю подтверждённое выключение.", request_timeout=5)
            except Exception:
                logger.warning("Не удалось отправить сообщение перед выключением")
            if not self.closed:
                subprocess.Popen(["shutdown", "/r" if action == "restart" else "/s", "/t", "0"], creationflags=subprocess.CREATE_NO_WINDOW)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Не удалось выполнить таймер питания")
            try:
                await self.bot.send_message(config.ADMIN_ID, f"Не удалось выполнить таймер: {exc}", request_timeout=5)
            except Exception:
                pass
        finally:
            self.power_deadline = None

    async def run_scenario(self, key):
        if self.scenario_lock.locked():
            raise ValueError("Дождитесь завершения текущего сценария.")
        async with self.scenario_lock:
            settings = await asyncio.to_thread(load_preferences)
            scenario = next((s for s in settings["scenarios"] if s["id"] == key), None)
            if scenario is None:
                raise ValueError("Сценарий удалён. Обновите меню.")
            programs = await asyncio.to_thread(load_programs)
            programs = {p.get("id", str(i)): p for i, p in enumerate(programs)}
            # Validate every target before starting any program.
            selected = []
            for key in scenario["program_ids"]:
                if key not in programs:
                    raise ValueError("Одна из программ сценария удалена. Измените сценарий в приложении.")
                program = programs[key]
                path = Path(os.path.expandvars(program["path"]))
                if not await asyncio.to_thread(path.is_file):
                    raise ValueError(f"Не найден файл программы «{program['name']}».")
                selected.append((program["name"], path))
            launched = []
            for name, path in selected:
                if self.closed:
                    raise asyncio.CancelledError()
                import modules.monitor as monitor
                if monitor.pc_is_locked:
                    raise ValueError("ПК заблокирован. Выполнение сценария остановлено.")
                try:
                    await asyncio.to_thread(os.startfile, str(path))
                    launched.append(name)
                    await asyncio.sleep(0.3)
                except OSError as exc:
                    raise ValueError(f"Не удалось запустить {name}. Уже запущено: {', '.join(launched) or 'ничего'}. {exc}") from exc
            return launched

    async def monitor_alerts(self):
        evaluator = AlertEvaluator()
        while True:
            interval = 10
            try:
                settings = (await asyncio.to_thread(load_preferences))["alerts"]
                interval = settings["interval_seconds"]
                if settings["enabled"]:
                    snapshot = await asyncio.to_thread(alert_snapshot)
                    for event in evaluator.evaluate(settings, snapshot, time.monotonic()):
                        from modules import notify_bus
                        notify_bus.push("Pulse PC", event)  # the phone shows it too
                        await self.bot.send_message(config.ADMIN_ID, "🔔 " + event, request_timeout=10)
                else:
                    evaluator = AlertEvaluator()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Ошибка уведомлений ПК: %s", exc)
            await asyncio.sleep(interval)
