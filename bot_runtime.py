"""Telegram worker independent of the desktop toolkit."""
import asyncio
import importlib
import threading

import config
from desktop_services import telegram_error
from modules.background_io import FileIOExecutor


class BotRunner:
    def __init__(self, log_callback, status_callback, restart_callback, quit_callback):
        self.log_callback = log_callback
        self.status_callback = status_callback
        self.restart_callback = restart_callback
        self.quit_callback = quit_callback
        self.loop = None
        self.thread = None
        self.bot = None
        self.dp = None
        self.is_running = False
        self._stop = threading.Event()
        self._task = None
        self.connection_state = None

    def start(self):
        if self.is_running or (self.thread and self.thread.is_alive()):
            return
        self._stop.clear()
        self.connection_state = None
        self.is_running = True
        self.status_callback("STARTING")
        self.thread = threading.Thread(target=self._run_loop, daemon=True, name="PulsePC-bot")
        self.thread.start()

    def _run_loop(self):
        loop = asyncio.new_event_loop()
        loop.set_default_executor(FileIOExecutor())
        self.loop = loop
        asyncio.set_event_loop(loop)
        exit_code = None
        try:
            self._task = loop.create_task(self._main_async())
            if self._stop.is_set():
                self._task.cancel()
            loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        except SystemExit as exc:
            exit_code = exc.code
        except Exception as exc:
            self.log_callback(f"Ошибка в работе бота: {telegram_error(exc)}")
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
            self.loop = None
            self._task = None
            self.bot = self.dp = None
            self.is_running = False
            self.status_callback("STOPPED")
            if exit_code == 42:
                self.restart_callback()
            elif exit_code == 0:
                self.quit_callback()

    async def _main_async(self):
        from aiogram import Bot, Dispatcher
        from modules.keyboards import get_reply_keyboard, get_main_inline_keyboard
        from modules.monitor import lock_monitor
        from modules.utils import cleanup_old_files, should_send_startup_notification
        from modules.welcome import control_panel_text, welcome_text
        from modules.bot_features import BotFeatures

        importlib.reload(config)
        if not config.BOT_TOKEN or config.BOT_TOKEN == "your_telegram_bot_token_here":
            raise ValueError("Токен бота не настроен. Откройте настройки.")
        if not config.ADMIN_ID:
            raise ValueError("Укажите ID администратора в настройках.")

        self.bot = Bot(token=config.BOT_TOKEN)
        monitor = None
        features = None
        local_api = None
        try:
            self.bot.session.middleware(self._request_status)
            self.dp = Dispatcher()
            features = BotFeatures(self.bot)
            self.dp["features"] = features
            from modules.local_api import LocalApiServer
            local_api = LocalApiServer(self.log_callback, lambda: features)
            await local_api.start()
            middleware = importlib.import_module("modules.middleware")
            auth = middleware.AuthMiddleware()
            self.dp.message.middleware(auth)
            self.dp.edited_message.middleware(auth)
            self.dp.callback_query.middleware(auth)
            # A Router can only belong to one Dispatcher. Reload and use the
            # fresh module attribute, never an earlier `from ... import router`.
            for name in ("advanced_handlers", "remote_tools", "system_handlers", "media_handlers", "program_handlers", "file_handlers"):
                module_name = f"modules.{name}"
                module = importlib.import_module(module_name)
                module = importlib.reload(module)
                self.dp.include_router(module.router)
            await self._connect()
            if self._stop.is_set():
                return
            cleanup_old_files(days=3)
            if should_send_startup_notification():
                try:
                    await self.bot.send_message(
                        config.ADMIN_ID,
                        welcome_text(startup=True),
                        reply_markup=get_reply_keyboard(), parse_mode="HTML",
                    )
                    await self.bot.send_message(
                        config.ADMIN_ID, control_panel_text(),
                        reply_markup=get_main_inline_keyboard(), parse_mode="HTML",
                    )
                except Exception as exc:
                    self.log_callback(f"Не удалось отправить уведомление о старте: {exc}")
            monitor = asyncio.create_task(lock_monitor(self.bot))
            features.start()
            self._connection_status("RUNNING")
            self.log_callback("Бот запущен. Ожидание команд Telegram.")
            await self.dp.start_polling(self.bot, polling_timeout=10, handle_signals=False, close_bot_session=False)
        finally:
            if local_api:
                await local_api.close()
            if features:
                await features.close()
            if monitor:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
            await self.bot.session.close()

    def _connection_status(self, status):
        if self._stop.is_set() or self.connection_state == status:
            return
        self.connection_state = status
        self.status_callback(status)
        self.log_callback("Связь с Telegram восстановлена." if status == "RUNNING" else "WARNING  Нет связи с Telegram. Переподключение…")

    async def _connect(self):
        from aiogram.exceptions import TelegramNetworkError, TelegramServerError, TelegramRetryAfter
        delay = 2
        while not self._stop.is_set():
            try:
                return await asyncio.wait_for(self.bot.me(), timeout=12)
            except (TelegramNetworkError, TelegramServerError, asyncio.TimeoutError, OSError) as exc:
                self._connection_status("RECONNECTING")
                self.log_callback(telegram_error(exc))
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
            except TelegramRetryAfter as exc:
                self._connection_status("RECONNECTING")
                await asyncio.sleep(exc.retry_after)

    async def _request_status(self, make_request, bot, method):
        from aiogram.methods import GetUpdates
        from aiogram.exceptions import TelegramUnauthorizedError, TelegramConflictError
        if not isinstance(method, GetUpdates):
            return await make_request(bot, method)
        try:
            result = await make_request(bot, method)
        except (TelegramUnauthorizedError, TelegramConflictError) as exc:
            self.log_callback("ERROR  " + telegram_error(exc))
            self.stop()
            raise
        except Exception:
            self._connection_status("RECONNECTING")
            raise
        self._connection_status("RUNNING")
        return result

    def stop(self):
        if not self.is_running:
            return
        self._stop.set()
        self.status_callback("STOPPING")
        loop = self.loop
        if loop and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._cancel)
            except RuntimeError:
                pass  # The worker finished between the check and the call.

    def _cancel(self):
        if self._task and not self._task.done():
            self._task.cancel()
