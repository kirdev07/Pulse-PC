import asyncio
import json
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import config
from desktop_services import AsyncJob, telegram_error
from modules import file_handlers, monitor, keyboards, program_handlers
from modules.program_store import validate_programs, effective_process


class IncomingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.history_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.history_directory.cleanup)
        self.history_config = patch.object(config, "BASE_DIR", self.history_directory.name)
        self.history_config.start()
        self.addCleanup(self.history_config.stop)

    async def test_duplicate_names_and_paths_stay_inside_downloads(self):
        async def download(remote, destination):
            Path(destination).write_bytes(remote.encode())
            await asyncio.sleep(0)
        bot = SimpleNamespace(download_file=download)
        with tempfile.TemporaryDirectory() as directory, patch.object(file_handlers, "FILES_DIR", directory):
            original = Path(directory) / "repeat.txt"
            original.write_text("original")
            first, second = await asyncio.gather(
                file_handlers.save_incoming_file(bot, "first", "../repeat.txt"),
                file_handlers.save_incoming_file(bot, "second", r"C:\elsewhere\repeat.txt"))
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, Path(directory))
            self.assertEqual(second.parent, Path(directory))
            self.assertEqual(first.read_text(), "first")
            self.assertEqual(second.read_text(), "second")
            self.assertEqual(original.read_text(), "original")
            self.assertEqual(list((Path(directory) / ".incoming").iterdir()), [])

    async def test_failure_and_cancel_preserve_original_and_remove_partial(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(file_handlers, "FILES_DIR", directory):
            original = Path(directory) / "repeat.txt"
            original.write_text("original")
            for exception in (OSError("connection lost"), asyncio.CancelledError()):
                async def download(remote, destination):
                    Path(destination).write_bytes(b"partial")
                    raise exception
                with self.assertRaises(type(exception)):
                    await file_handlers.save_incoming_file(SimpleNamespace(download_file=download), "remote", original.name)
                self.assertEqual(original.read_text(), "original")
                self.assertEqual(list((Path(directory) / ".incoming").iterdir()), [])

    async def test_url_after_emoji_and_unsupported_scheme(self):
        url = "https://example.org"
        message = SimpleNamespace(text="😀 " + url, entities=[SimpleNamespace(type="url", offset=3, length=len(url))], answer=AsyncMock())
        with patch.object(file_handlers.webbrowser, "open") as opened:
            await file_handlers.handle_url(message)
            opened.assert_called_once_with(url)
            message.text = "ftp://example.org"
            message.entities[0].offset = 0
            message.entities[0].length = len(message.text)
            message.answer.reset_mock()
            await file_handlers.handle_url(message)
            message.answer.assert_not_awaited()

    async def test_media_caption_after_emoji(self):
        url = "https://example.org"
        message = SimpleNamespace(document=SimpleNamespace(file_id="abc", file_name="file.txt", file_size=4),
            caption="😀 " + url, caption_entities=[SimpleNamespace(type="url", offset=3, length=len(url))], answer=AsyncMock())
        bot = SimpleNamespace(get_file=AsyncMock(return_value=SimpleNamespace(file_path="remote")))
        with patch.object(file_handlers, "save_incoming_file", new=AsyncMock(return_value=Path("file.txt"))), patch.object(file_handlers.webbrowser, "open") as opened:
            await file_handlers.handle_media_files(message, bot)
            opened.assert_called_once_with(url)


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_on_unlocked_desktop_clears_stale_flag(self):
        with patch.object(monitor, "pc_is_locked", True), patch.object(monitor, "workstation_locked", return_value=False), patch.object(monitor.asyncio, "sleep", new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await monitor.lock_monitor(SimpleNamespace(send_message=AsyncMock()))
            self.assertFalse(monitor.pc_is_locked)

    async def test_network_notification_does_not_delay_lock_detection(self):
        actual_sleep = asyncio.sleep
        calls = []
        async def pause(_):
            calls.append(monitor.pc_is_locked)
            if len(calls) == 2:
                raise asyncio.CancelledError
            await actual_sleep(0)
        async def slow_send(**kwargs):
            await asyncio.Event().wait()
        with patch.object(config, "ADMIN_ID", 123), patch.object(monitor, "pc_is_locked", False), patch.object(monitor, "workstation_locked", side_effect=[True, False]), patch.object(monitor.asyncio, "sleep", pause):
            with self.assertRaises(asyncio.CancelledError):
                await monitor.lock_monitor(SimpleNamespace(send_message=slow_send))
        self.assertEqual(calls, [True, False])


class ProgramTests(unittest.IsolatedAsyncioTestCase):
    async def test_program_names_are_escaped_in_html_reply(self):
        program = dict(id="demo", name="<OBS> & Test", path="demo.exe", process="demo.exe")
        callback = SimpleNamespace(data="run_demo", answer=AsyncMock(), message=Mock())
        with patch.object(program_handlers, "load_programs", return_value=[program]), patch("os.startfile"), patch.object(program_handlers, "safe_edit_text", new=AsyncMock()) as edited:
            await program_handlers.callback_run_program(callback)
            self.assertIn("&lt;OBS&gt; &amp; Test", edited.call_args.args[1])

    async def test_invalid_program_structure_is_rejected_consistently(self):
        for value in ({"programs": []}, [None], [{"name": "x"}], [dict(name="a", path="a", id="same"), dict(name="b", path="b", id="same")]):
            with self.assertRaises(ValueError):
                validate_programs(value)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "programs.json"
                path.write_text(json.dumps(value))
                with patch.object(config, "PROGRAMS_FILE_PATH", str(path)), self.assertLogs("modules.keyboards", level="ERROR"):
                    self.assertEqual(keyboards.load_programs(), [])


class CancellationTests(unittest.TestCase):
    def test_process_exits_while_os_worker_is_blocked(self):
        code = """
import asyncio, threading, time
from desktop_services import AsyncJob
entered = threading.Event()
done = threading.Event()
def blocked():
    entered.set()
    time.sleep(60)
job = AsyncJob(lambda: asyncio.to_thread(blocked), lambda *_: done.set())
job.start()
assert entered.wait(3)
job.cancel()
assert done.wait(3)
job.thread.join(1)
"""
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_legacy_shortcut_process_is_resolved(self):
        with patch("win32com.client.Dispatch") as dispatch:
            dispatch.return_value.CreateShortcut.return_value.TargetPath = r"C:\Apps\actual.exe"
            self.assertEqual(effective_process(dict(path="old.lnk", process="old.lnk")), "actual.exe")
        self.assertEqual(effective_process(dict(path="old.bat", process="old.bat")), "")

    def test_cancel_does_not_wait_for_blocked_filesystem(self):
        entered, release, completed = threading.Event(), threading.Event(), threading.Event()
        def blocked():
            entered.set()
            release.wait(10)
        job = AsyncJob(lambda: asyncio.to_thread(blocked), lambda result, error: completed.set())
        try:
            job.start()
            self.assertTrue(entered.wait(2))
            job.cancel()
            self.assertTrue(completed.wait(3))
            job.thread.join(1)
            self.assertFalse(job.thread.is_alive())
            self.assertFalse(release.is_set())
        finally:
            release.set()

    def test_file_errors_are_not_reported_as_telegram_network_errors(self):
        self.assertIn("доступ", telegram_error(PermissionError()))
        self.assertIn("не найдены", telegram_error(FileNotFoundError()))
        self.assertIn("файловой системы", telegram_error(OSError("disk full")))
