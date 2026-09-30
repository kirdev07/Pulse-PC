"""Shared services for the Qt panel and Telegram commands."""
import asyncio
from collections import deque
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import threading
import time
from aiogram.types import FSInputFile
from modules.background_io import FileIOExecutor
from modules.transfer_history import track_transfer, record_transfer


def redact(text, token=""):
    text = re.sub(r"\b\d{5,}:[A-Za-z0-9_-]{15,}\b", "[TOKEN скрыт]", str(text))
    return text.replace(token, "[TOKEN скрыт]") if token else text


class EventJournal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "pulse.log"
        self.handler = RotatingFileHandler(self.path, maxBytes=2_000_000, backupCount=3, encoding="utf-8", delay=True)
        self.handler.setFormatter(logging.Formatter("%(message)s"))

    def append(self, text):
        self.handler.emit(logging.LogRecord("pulse.journal", logging.INFO, "", 0, redact(text), (), None))

    def history(self, limit=2000):
        lines = deque(maxlen=limit)
        for path in [self.path.with_name(f"pulse.log.{n}") for n in (3, 2, 1)] + [self.path]:
            if path.exists():
                with path.open(encoding="utf-8", errors="replace") as stream:
                    lines.extend(redact(line.rstrip()) for line in stream)
        return list(lines)

    def close(self):
        self.handler.close()


def telegram_error(exc):
    from aiogram.exceptions import TelegramUnauthorizedError, TelegramNetworkError, TelegramServerError, TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter, TelegramConflictError
    from aiogram.utils.token import TokenValidationError
    if isinstance(exc, (TokenValidationError, TelegramUnauthorizedError)):
        return "Неверный или отозванный токен. Проверьте токен от @BotFather."
    if isinstance(exc, PermissionError):
        return "Нет доступа к файлу или папке. Проверьте права доступа."
    if isinstance(exc, FileNotFoundError):
        return "Файл или папка не найдены. Проверьте путь."
    if isinstance(exc, (TelegramNetworkError, asyncio.TimeoutError, ConnectionError)):
        return "Нет связи с Telegram. Проверьте интернет, VPN или прокси."
    if isinstance(exc, OSError):
        return "Ошибка файловой системы или устройства: " + redact(str(exc))
    if isinstance(exc, TelegramServerError):
        return "Сервис Telegram временно недоступен. Повторите попытку позже."
    if isinstance(exc, TelegramForbiddenError):
        return "Бот не может написать администратору. Откройте чат с ботом, нажмите /start и проверьте блокировку."
    if isinstance(exc, TelegramConflictError):
        return "Этот бот уже запущен в другой программе или использует webhook. Остановите другое подключение."
    if isinstance(exc, TelegramRetryAfter):
        return f"Telegram просит подождать {exc.retry_after} с."
    if isinstance(exc, TelegramBadRequest):
        return "Telegram отклонил запрос. Проверьте ID администратора, чат с ботом и параметры файла."
    return redact(str(exc))


async def probe_bot(token):
    from aiogram import Bot
    bot = Bot(token=token)
    try:
        user = await bot.get_me(request_timeout=12)
        return f"Подключение успешно: {user.full_name} (@{user.username})."
    finally:
        await bot.session.close()


MAX_UPLOAD_SIZE = 50 * 1024 * 1024


def validate_upload(path):
    path = Path(os.path.expandvars(str(path).strip().strip('"'))).expanduser().resolve()
    if not path.is_file():
        raise ValueError("Файл не найден. Укажите полный путь к обычному файлу.")
    if path.stat().st_size > MAX_UPLOAD_SIZE:
        raise ValueError("Файл больше 50 МБ. Выберите файл меньшего размера.")
    if path.stat().st_size == 0:
        raise ValueError("Пустой файл нельзя отправить в Telegram.")
    return path


async def send_file(bot, chat_id, path):
    from aiogram.types import FSInputFile
    async with track_transfer(path):
        path = await asyncio.to_thread(validate_upload, path)
        await bot.send_document(chat_id=chat_id, document=FSInputFile(path), request_timeout=120)
    return f"Файл «{path.name}» отправлен в Telegram."


class ProgressInputFile(FSInputFile):
    """Count chunks consumed by the HTTP transport, not server acknowledgements."""
    def __init__(self, path, on_chunk):
        super().__init__(path, chunk_size=256 * 1024)
        self.on_chunk = on_chunk

    async def read(self, bot):
        async for chunk in super().read(bot):
            yield chunk
            self.on_chunk(len(chunk))


def format_bytes(size):
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.1f} {unit}" if unit != "Б" else f"{size:.0f} Б"
        size /= 1024


async def send_files_with_token(token, admin_id, paths, progress, *, parallel=2):
    """Bounded parallel uploads with shared progress and cancellation."""
    from aiogram import Bot
    state = dict(phase="preparing", total=len(paths), completed=0, index=0,
                 name="", size=0, transferred=0, total_size=0, total_transferred=0, speed=0.0)
    bot = None
    ticker = None
    workers = []
    active = {}
    terminal = False

    def emit():
        if active and not terminal:
            current = next(iter(active.values()))
            state.update({key: current[key] for key in ("index", "name", "size", "transferred")})
            phases = {item["phase"] for item in active.values()}
            state["phase"] = "uploading" if "uploading" in phases else ("confirming" if "confirming" in phases else "waiting")
        progress({**state, "active": [dict(item) for item in active.values()]})

    progress(dict(state))
    try:
        if not str(admin_id).isascii() or not str(admin_id).isdigit() or int(admin_id) <= 0:
            raise ValueError("Укажите числовой ID администратора в настройках.")
        files = []
        for path in paths:
            try:
                validated = await asyncio.to_thread(validate_upload, path)
            except Exception as exc:
                record_transfer(path, "outgoing", "error", exc)
                raise
            size = await asyncio.to_thread(lambda p=validated: p.stat().st_size)
            files.append((validated, size))
        state["total_size"] = sum(size for _, size in files)
        bot = Bot(token=token)
        previous_bytes, previous_time = 0, time.monotonic()

        async def report():
            nonlocal previous_bytes, previous_time
            while True:
                await asyncio.sleep(0.25)
                now = time.monotonic()
                state["speed"] = max(0, state["total_transferred"] - previous_bytes) / max(now - previous_time, 0.001)
                previous_bytes, previous_time = state["total_transferred"], now
                emit()

        ticker = asyncio.create_task(report())
        queue = iter(enumerate(files, 1))

        async def upload_worker():
            from aiogram.exceptions import TelegramRetryAfter
            for index, (path, size) in queue:
                async with track_transfer(path):
                    def check_file():
                        checked = validate_upload(path)
                        if checked.stat().st_size != size:
                            raise ValueError(f"Размер файла «{path.name}» изменился. Выберите файлы заново.")
                    await asyncio.to_thread(check_file)
                    item = dict(index=index, name=path.name, size=size, transferred=0, phase="uploading")
                    active[index] = item
                    emit()

                    def consumed(count):
                        item["transferred"] += count
                        state["total_transferred"] += count
                        if item["transferred"] >= size:
                            item["phase"] = "confirming"
                            emit()

                    for attempt in range(3):
                        try:
                            await bot.send_document(chat_id=int(admin_id), document=ProgressInputFile(path, consumed), request_timeout=300)
                            break
                        except TelegramRetryAfter as exc:
                            if attempt == 2:
                                raise
                            item["phase"] = "waiting"
                            emit()
                            await asyncio.sleep(exc.retry_after)
                            state["total_transferred"] -= item["transferred"]
                            item.update(transferred=0, phase="uploading")
                    state["completed"] += 1
                    active.pop(index)
                    state.update({key: item[key] for key in ("index", "name", "size", "transferred")})
                    state.update(phase="sent", speed=0.0)
                    emit()
        workers = [asyncio.create_task(upload_worker()) for _ in range(min(max(1, parallel), 2, len(files)))]
        await asyncio.gather(*workers)
        terminal = True
        state.update(phase="completed", speed=0.0)
        emit()
        return f"Отправлено файлов: {state['completed']} из {state['total']}."
    except asyncio.CancelledError:
        terminal = True
        state.update(phase="cancelled", speed=0.0)
        progress(dict(state))
        raise
    except Exception:
        terminal = True
        state.update(phase="error", speed=0.0)
        progress(dict(state))
        raise
    finally:
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        if ticker:
            ticker.cancel()
            await asyncio.gather(ticker, return_exceptions=True)
        if bot:
            await bot.session.close()


def computer_info():
    import psutil
    cpu = psutil.cpu_percent(interval=0.2)
    memory = psutil.virtual_memory()
    lines = [f"Процессор: {cpu:.0f}%", f"Оперативная память: {memory.used / 1024**3:.1f} / {memory.total / 1024**3:.1f} ГБ ({memory.percent:.0f}%)"]
    for disk in psutil.disk_partitions():
        if "cdrom" in disk.opts or not disk.fstype:
            continue
        try:
            usage = psutil.disk_usage(disk.mountpoint)
            lines.append(f"Диск {disk.mountpoint} — свободно {usage.free / 1024**3:.1f} из {usage.total / 1024**3:.1f} ГБ")
        except (OSError, PermissionError):
            continue
    battery = psutil.sensors_battery()
    lines.append("Батарея: отсутствует" if battery is None else f"Батарея: {battery.percent:.0f}% · " + ("питание от сети" if battery.power_plugged else "питание от батареи"))
    return "\n".join(lines)


class AsyncJob:
    """Cancellable coroutine worker; completion is delivered via a Qt signal."""
    def __init__(self, factory, callback):
        self.factory, self.callback = factory, callback
        self.loop = self.task = None
        self.cancelled = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name="PulsePC-job")

    def start(self):
        self.thread.start()

    def cancel(self):
        self.cancelled.set()
        if self.loop and not self.loop.is_closed():
            try:
                self.loop.call_soon_threadsafe(self._cancel)
            except RuntimeError:
                pass

    def _cancel(self):
        if self.task:
            self.task.cancel()

    def run(self):
        loop = self.loop = asyncio.new_event_loop()
        loop.set_default_executor(FileIOExecutor())
        asyncio.set_event_loop(loop)
        result, error = None, None
        try:
            self.task = loop.create_task(self.factory())
            if self.cancelled.is_set():
                self.task.cancel()
            result = loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            error = "Операция отменена."
        except Exception as exc:
            error = telegram_error(exc)
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
            self.callback(result, error)
