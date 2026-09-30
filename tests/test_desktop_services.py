import asyncio
import importlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.methods import GetMe, GetUpdates
from aiogram.types import Message, Update, User
import config
from bot_runtime import BotRunner
from desktop_services import EventJournal, probe_bot, send_file, send_files_with_token, validate_upload, computer_info, telegram_error


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.history_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.history_directory.cleanup)
        self.history_config = patch.object(config, "BASE_DIR", self.history_directory.name)
        self.history_config.start()
        self.addCleanup(self.history_config.stop)

    async def test_batch_progress_requires_server_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f"file-{i}.bin" for i in range(2)]
            for path in paths:
                path.write_bytes(b"a" * 100000)
            events = []
            calls = []
            async def upload(**kwargs):
                calls.append(kwargs)
                async for chunk in kwargs["document"].read(None):
                    await asyncio.sleep(0)
                # Reading all bytes must not count a file as delivered yet.
                self.assertEqual(events[-1]["completed"], len(calls) - 1)
                self.assertEqual(events[-1]["phase"], "confirming")
            bot = SimpleNamespace(send_document=upload, session=SimpleNamespace(close=AsyncMock()))
            with patch("aiogram.Bot", return_value=bot):
                result = await send_files_with_token("test", "123", paths, events.append, parallel=1)
            self.assertIn("2 из 2", result)
            self.assertEqual(events[-1]["total_transferred"], 200000)
            self.assertEqual(events[-1]["completed"], 2)
            self.assertEqual(events[-1]["phase"], "completed")
            bot.session.close.assert_awaited_once()

    async def test_batch_cancel_stops_remaining_files(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f"file-{i}.bin" for i in range(3)]
            for path in paths:
                path.write_bytes(b"a" * 100)
            entered = asyncio.Event()
            events, calls = [], []
            async def upload(**kwargs):
                calls.append(kwargs)
                if len(calls) == 2:
                    entered.set()
                    await asyncio.Event().wait()
                async for chunk in kwargs["document"].read(None):
                    pass
            bot = SimpleNamespace(send_document=upload, session=SimpleNamespace(close=AsyncMock()))
            with patch("aiogram.Bot", return_value=bot):
                task = asyncio.create_task(send_files_with_token("test", "123", paths, events.append, parallel=1))
                await asyncio.wait_for(entered.wait(), 3)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertEqual(len(calls), 2)
            self.assertEqual(events[-1]["completed"], 1)
            self.assertEqual(events[-1]["phase"], "cancelled")
            bot.session.close.assert_awaited_once()

    async def test_batch_invalid_file_does_not_send_anything(self):
        events = []
        with tempfile.TemporaryDirectory() as directory, patch("aiogram.Bot") as bot:
            with self.assertRaises(ValueError):
                await send_files_with_token("test", "123", [Path(directory) / "missing"], events.append)
            bot.assert_not_called()
            self.assertEqual(events[-1]["phase"], "error")

    async def test_parallel_upload_limit_and_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f"file-{i}.bin" for i in range(4)]
            for path in paths:
                path.write_bytes(b"a" * 10)
            entered = asyncio.Event()
            active = 0
            finished = 0
            async def upload(**kwargs):
                nonlocal active, finished
                active += 1
                if active == 2:
                    entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    active -= 1
                    finished += 1
            bot = SimpleNamespace(send_document=upload, session=SimpleNamespace(close=AsyncMock()))
            events = []
            with patch("aiogram.Bot", return_value=bot):
                task = asyncio.create_task(send_files_with_token("test", "123", paths, events.append))
                await asyncio.wait_for(entered.wait(), 3)
                self.assertEqual(active, 2)
                self.assertEqual(len(events[-1]["active"]), 2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertEqual(active, 0)
            self.assertEqual(finished, 2)
            bot.session.close.assert_awaited_once()

    async def test_offline_start_retries_and_recovers(self):
        statuses = []
        runner = BotRunner(lambda text: None, statuses.append, lambda: None, lambda: None)
        error = TelegramNetworkError(method=GetMe(), message="offline")
        runner.bot = SimpleNamespace(me=AsyncMock(side_effect=[error, "connected"]))
        with patch("bot_runtime.asyncio.sleep", new=AsyncMock()) as sleep:
            self.assertEqual(await runner._connect(), "connected")
        self.assertEqual(statuses, ["RECONNECTING"])
        sleep.assert_awaited_once_with(2)

    async def test_request_loss_recovery_and_bad_token(self):
        statuses = []
        runner = BotRunner(lambda text: None, statuses.append, lambda: None, lambda: None)
        runner.is_running = True
        method = GetUpdates()
        error = TelegramNetworkError(method=method, message="offline")
        request = AsyncMock(side_effect=[error, []])
        with self.assertRaises(TelegramNetworkError):
            await runner._request_status(request, None, method)
        self.assertEqual(await runner._request_status(request, None, method), [])
        self.assertEqual(statuses, ["RECONNECTING", "RUNNING"])
        with self.assertRaises(TelegramUnauthorizedError):
            await runner._request_status(AsyncMock(side_effect=TelegramUnauthorizedError(method=method, message="invalid")), None, method)
        self.assertTrue(runner._stop.is_set())
        self.assertEqual(statuses[-1], "STOPPING")

    async def test_probe_closes_session_on_success_and_error(self):
        bot = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(full_name="Test", username="test_bot")), session=SimpleNamespace(close=AsyncMock()))
        with patch("aiogram.Bot", return_value=bot):
            self.assertIn("@test_bot", await probe_bot("test"))
            bot.get_me.side_effect = TelegramUnauthorizedError(method=GetMe(), message="invalid")
            with self.assertRaises(TelegramUnauthorizedError) as caught:
                await probe_bot("test")
            self.assertIn("токен", telegram_error(caught.exception))
        self.assertEqual(bot.session.close.await_count, 2)

    async def test_upload_validation_and_send(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "файл с пробелами.txt"
            path.write_text("test", encoding="utf-8")
            bot = SimpleNamespace(send_document=AsyncMock())
            await send_file(bot, 123, path)
            self.assertEqual(bot.send_document.call_args.kwargs["chat_id"], 123)
            self.assertEqual(Path(bot.send_document.call_args.kwargs["document"].path), path)
            with self.assertRaises(ValueError):
                validate_upload(directory)
            with self.assertRaises(ValueError):
                validate_upload(path.with_name("missing"))
            path.write_bytes(b"")
            with self.assertRaises(ValueError):
                validate_upload(path)
            with path.open("wb") as stream:
                stream.truncate(50 * 1024 * 1024 + 1)
            with self.assertRaises(ValueError):
                validate_upload(path)

    async def test_telegram_routes_and_authorization(self):
        import modules.remote_tools as remote
        import modules.system_handlers as system
        from modules.middleware import AuthMiddleware
        from datetime import datetime, timezone
        remote = importlib.reload(remote)
        system = importlib.reload(system)
        dispatcher = Dispatcher()
        dispatcher.message.middleware(AuthMiddleware())
        dispatcher.include_router(remote.router)
        dispatcher.include_router(system.router)
        bot = Bot(token="123456789:" + "A" * 35)
        try:
            with patch.multiple(config, ADMIN_ID=123), patch("modules.monitor.pc_is_locked", False), patch("modules.middleware.user_last_activity", {}), patch("modules.middleware.THROTTLE_RATE", 0), patch("modules.remote_tools.computer_info", return_value="CPU info"), patch("modules.remote_tools.send_file", new=AsyncMock()) as send, patch.object(Bot, "__call__", new=AsyncMock(return_value=True)) as api:
                for number, (user_id, command) in enumerate(((999, "/getfile C:\\demo.txt"), (123, "/getfile C:\\demo.txt"), (123, "/status")), 1):
                    message = Message(message_id=number, date=datetime.now(timezone.utc), chat={"id": user_id, "type": "private"}, from_user=User(id=user_id, is_bot=False, first_name="Test"), text=command)
                    await dispatcher.feed_update(bot, Update(update_id=number, message=message))
                    if user_id == 999:
                        send.assert_not_awaited()
                send.assert_awaited_once_with(bot, 123, "C:\\demo.txt")
                self.assertTrue(any(getattr(call.args[0], "text", "") == "CPU info" for call in api.call_args_list))
        finally:
            await bot.session.close()


class DataTests(unittest.TestCase):
    def test_metrics_with_no_battery_and_inaccessible_disk(self):
        with patch("psutil.cpu_percent", return_value=25), patch("psutil.virtual_memory", return_value=SimpleNamespace(used=8*1024**3, total=16*1024**3, percent=50)), patch("psutil.disk_partitions", return_value=[SimpleNamespace(opts="rw", fstype="NTFS", mountpoint="C:\\")]), patch("psutil.disk_usage", side_effect=PermissionError), patch("psutil.sensors_battery", return_value=None):
            result = computer_info()
        self.assertIn("25%", result)
        self.assertIn("8.0 / 16.0", result)
        self.assertIn("отсутствует", result)

    def test_rotated_journal_survives_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = EventJournal(directory)
            journal.handler.maxBytes = 50
            journal.append("first " + "a" * 20)
            journal.append("second " + "b" * 20)
            journal.close()
            journal = EventJournal(directory)
            self.assertEqual(len(journal.history()), 2)
            self.assertTrue(journal.path.with_name("pulse.log.1").exists())
            journal.close()

    def test_program_callbacks_survive_reorder(self):
        from modules.program_handlers import program_index
        programs = [{"id": "first"}, {"id": "second"}]
        self.assertEqual(program_index("first", programs[::-1]), 1)
        self.assertEqual(program_index("0", programs), -1)
        self.assertEqual(program_index("deleted", programs), -1)
        self.assertEqual(program_index("0", [{}]), 0)
