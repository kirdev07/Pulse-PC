"""Offline integration checks: no Telegram traffic or registry writes."""
import asyncio
import importlib
import logging
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from dotenv import dotenv_values
import config
import gui
from bot_runtime import BotRunner


class FakeRunner:
    def __init__(self, log, status, restart, quit):
        self.status = status
        self.is_running = False
        self.thread = None

    def start(self):
        self.is_running = True
        self.status("RUNNING")

    def stop(self):
        self.is_running = False
        self.status("STOPPED")


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # The offscreen Windows plugin does not enumerate system fonts.
        for name in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf"):
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = Path(self.temp.name) / ".env"
        self.env.write_text("# Keep this comment\nEXTRA=value\nBOT_TOKEN=\nADMIN_ID=\n", encoding="utf-8")
        self.config_patch = patch.multiple(config, BASE_DIR=self.temp.name, PROGRAMS_FILE_PATH=str(Path(self.temp.name) / "programs.json"))
        self.config_patch.start()
        self.reload_patch = patch.object(gui.importlib, "reload", side_effect=lambda module: module)
        self.reload_patch.start()
        self.window = gui.PulsePCApp(auto_start=False, enable_tray=False, runner_factory=FakeRunner)

    def tearDown(self):
        logging.getLogger().removeHandler(self.window.log_handler)
        self.window.metrics_timer.stop()
        self.app.processEvents()
        if self.window.journal:
            self.window.journal.close()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.reload_patch.stop()
        self.config_patch.stop()
        self.temp.cleanup()

    def test_navigation_and_render(self):
        self.window.show()
        for width, height in ((1120, 820), (800, 600)):
            self.window.resize(width, height)
            for index in range(6):
                self.window.switch_tab(index)
                self.app.processEvents()
                self.assertEqual(self.window.pages.currentIndex(), index)
                self.assertFalse(self.window.grab().isNull())

    def test_switching_editor_keeps_previous_changes(self):
        executable = Path(self.temp.name) / "demo.exe"
        executable.touch()
        for name in ("First", "Second"):
            self.window.program_name.setText(name)
            self.window.program_path.setText(str(executable))
            self.window.add_program()
        self.window.edit_program(0)
        self.window.program_name.setText("Changed")
        self.window.edit_program(1)
        self.assertEqual(self.window.temp_programs[0]["name"], "Changed")
        self.assertEqual(self.window.edit_index, 1)

    def test_dashboard_distinguishes_credentials_from_connection(self):
        self.assertIn("Начните с настроек", self.window.status_hint.text())
        self.window.token.setText("123456789:" + "A" * 35)
        self.window.admin_id.setText("123456")
        self.assertIn("Запустите бота", self.window.status_hint.text())
        self.assertIn("Не подключён", self.window.connection.text())
        self.window.update_bot_status("RUNNING")
        self.assertIn("принимает команды", self.window.status_hint.text())
        self.window.update_bot_status("RECONNECTING")
        self.assertNotIn("принимает команды", self.window.status_hint.text())
        self.assertIn("Проверьте интернет", self.window.status_hint.text())

    def test_compact_layout_and_filtered_event_count(self):
        self.window.show()
        self.window.resize(800, 600)
        self.app.processEvents()
        self.assertEqual(self.window.nav_buttons[0][0].text(), "")
        self.assertEqual(self.window.program_columns.direction(), gui.QBoxLayout.Direction.TopToBottom)
        for index in range(6):
            self.window.switch_tab(index)
            self.app.processEvents()
            page = self.window.pages.currentWidget()
            self.assertLessEqual(page.widget().width(), page.viewport().width())
        self.window.resize(1120, 820)
        self.app.processEvents()
        self.assertEqual(self.window.nav_buttons[0][0].text(), "Главная")
        self.window.clear_logs()
        self.window.append_log("INFO ready")
        self.window.append_log("ERROR failed")
        self.window.errors_only.setChecked(True)
        self.assertEqual(self.window.log_count.text(), "Событий: 1 / 2")
        self.window.clear_logs()
        self.assertEqual(self.window.log_count.text(), "Событий: 0 / 0")

    def test_window_corners_are_transparent_after_resize_and_notification(self):
        self.window.show()
        self.window.notify("Проверка оформления")
        for width, height in ((1120, 820), (800, 600)):
            self.window.resize(width, height)
            self.app.processEvents()
            rendered = self.window.grab().toImage()
            w, h = rendered.width(), rendered.height()
            for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
                self.assertEqual(rendered.pixelColor(x, y).alpha(), 0)
            self.assertEqual(rendered.pixelColor(w // 2, h // 2).alpha(), 255)

    def test_custom_window_controls_restore_and_close_to_tray(self):
        self.window.show()
        self.app.processEvents()
        original = self.window.size()
        QTest.mouseClick(self.window.title_bar.maximize_button, gui.Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertTrue(self.window.isMaximized())
        QTest.mouseClick(self.window.title_bar.maximize_button, gui.Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertFalse(self.window.isMaximized())
        self.assertEqual(self.window.size(), original)
        self.window.tray_icon = Mock()
        QTest.mouseClick(self.window.title_bar.close_button, gui.Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window.is_quitting)

    def test_waiting_and_parallel_progress(self):
        state = dict(phase="waiting", total=2, completed=0, index=1, name="one", size=10, transferred=5, total_size=20, total_transferred=10, speed=0,
                     active=[dict(name="one", transferred=5, size=10), dict(name="two", transferred=5, size=10)])
        self.window.update_transfer_progress(state)
        self.assertIn("подождать", self.window.transfer_message.text())
        self.assertIn("two", self.window.transfer_file.text())
        self.assertIn("one", self.window.transfer_file.text())

    def test_shortcut_process_and_scripts(self):
        with patch("win32com.client.Dispatch") as dispatch:
            dispatch.return_value.CreateShortcut.return_value.TargetPath = r"C:\Apps\demo.exe"
            self.assertEqual(self.window.program_process("demo.lnk"), "demo.exe")
        self.assertEqual(self.window.program_process("demo.cmd"), "")

    def test_autostart_removes_legacy_key(self):
        with patch.object(gui.winreg, "CreateKey"), patch.object(gui.winreg, "SetValueEx") as write, patch.object(gui.winreg, "DeleteValue") as delete:
            self.window.change_autostart(True)
            self.assertEqual(write.call_args.args[1], "PulsePC")
            self.assertEqual(delete.call_args.args[1], "PulsePC_Bot")
            delete.reset_mock()
            self.window.change_autostart(False)
            self.assertEqual({call.args[1] for call in delete.call_args_list}, {"PulsePC", "PulsePC_Bot"})

    def test_settings_round_trip_and_unknown_values(self):
        self.window.token.setText("123456789:" + "A" * 35)
        self.window.admin_id.setText("123456")
        self.assertTrue(self.window.save_settings())
        values = dotenv_values(self.env)
        self.assertEqual(values["BOT_TOKEN"], "123456789:" + "A" * 35)
        self.assertEqual(values["EXTRA"], "value")
        self.assertIn("# Keep this comment", self.env.read_text(encoding="utf-8"))
        self.window.load_settings()
        self.assertEqual(self.window.token.text(), "123456789:" + "A" * 35)
        self.window.admin_id.setText("abc")
        self.assertFalse(self.window.save_settings())
        self.assertEqual(dotenv_values(self.env)["ADMIN_ID"], "123456")

    def test_program_add_save_reload_delete_and_limit(self):
        executable = Path(self.temp.name) / "demo.exe"
        executable.touch()
        for i in range(16):
            self.window.program_name.setText(f"Программа {i}")
            self.window.program_path.setText(str(executable))
            self.window.add_program()
        self.assertEqual(len(self.window.temp_programs), 15)
        self.assertTrue(self.window.save_programs())
        self.window.temp_programs = []
        self.window.load_programs()
        self.assertEqual(len(self.window.temp_programs), 15)
        self.assertEqual(self.window.temp_programs[0]["process"], "demo.exe")
        self.window.delete_program(0)
        self.assertTrue(self.window.programs_dirty)
        self.assertEqual(len(self.window.temp_programs), 14)

    def test_invalid_program_file_is_preserved(self):
        path = Path(config.PROGRAMS_FILE_PATH)
        path.write_text("broken json", encoding="utf-8")
        self.window.load_programs()
        self.assertFalse(self.window.save_programs())
        self.assertEqual(path.read_text(encoding="utf-8"), "broken json")

    def test_failed_program_save_keeps_dirty_state(self):
        self.window.programs_dirty = True
        with patch.object(gui, "atomic_write", side_effect=OSError("disk full")):
            self.assertFalse(self.window.save_programs())
        self.assertTrue(self.window.programs_dirty)

    def test_start_stop_and_queued_log_redaction(self):
        self.window.token.setText("123456789:" + "A" * 35)
        self.window.admin_id.setText("123456")
        self.window.toggle_bot_state()
        self.app.processEvents()
        self.assertEqual(self.window.state, "RUNNING")
        message = "ERROR " + self.window.token.text()
        worker = threading.Thread(target=lambda: self.window.signals.log.emit(message))
        worker.start()
        worker.join()
        self.app.processEvents()
        self.assertNotIn("A" * 35, self.window.console.toPlainText())
        self.assertIn("TOKEN скрыт", self.window.console.toPlainText())
        self.window.toggle_bot_state()
        self.app.processEvents()
        self.assertEqual(self.window.state, "STOPPED")

    def test_edit_reorder_preserves_program_identity(self):
        executable = Path(self.temp.name) / "demo.exe"
        executable.touch()
        for name in ("First", "Second"):
            self.window.program_name.setText(name)
            self.window.program_path.setText(str(executable))
            self.window.add_program()
        original_id = self.window.temp_programs[0]["id"]
        self.window.edit_program(0)
        self.window.program_name.setText("Changed")
        self.window.move_program(0, 1)
        self.assertTrue(self.window.save_programs())
        self.assertEqual(self.window.temp_programs[1]["id"], original_id)
        self.assertEqual(self.window.temp_programs[1]["name"], "Changed")
        with patch("os.startfile") as launch:
            self.window.test_program(1)
            launch.assert_called_once_with(str(executable.resolve()))

    def test_journal_history_filter_export_and_redaction(self):
        secret = "123456789:" + "X" * 35
        self.window.append_log("INFO normal")
        self.window.append_log("ERROR " + secret)
        self.window.errors_only.setChecked(True)
        self.assertNotIn("INFO normal", self.window.console.toPlainText())
        self.assertNotIn(secret, self.window.journal.path.read_text(encoding="utf-8"))
        export = Path(self.temp.name) / "export.txt"
        with patch.object(gui.QFileDialog, "getSaveFileName", return_value=(str(export), "")):
            self.window.export_logs()
        self.assertIn("ERROR", export.read_text(encoding="utf-8"))
        self.window.clear_logs()
        self.assertTrue(any("INFO normal" in line for line in self.window.journal.history()))

    def test_reconnecting_can_be_stopped(self):
        self.window.bot_runner.is_running = True
        self.window.update_bot_status("RECONNECTING")
        self.assertIn("Нет связи", self.window.connection.text())
        self.assertTrue(self.window.toggle_button.isEnabled())
        self.assertEqual(self.window.toggle_button.property("kind"), "stop")
        self.window.toggle_bot_state()
        self.app.processEvents()
        self.assertEqual(self.window.state, "STOPPED")

    def test_probe_and_file_jobs_return_to_ui(self):
        self.window.token.setText("123456789:" + "A" * 35)
        self.window.admin_id.setText("123456")
        with patch("gui.probe_bot", new=AsyncMock(return_value="Подключение успешно: Test (@test_bot).")) as probe:
            self.window.check_bot()
            deadline = time.monotonic() + 3
            while self.window.jobs and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            probe.assert_awaited_once()
            self.assertTrue(self.window.probe_button.isEnabled())
            self.assertIn("@test_bot", self.window.probe_message.text())
        with patch("gui.send_files_with_token", new=AsyncMock(return_value="Файл отправлен")) as send:
            self.window.enqueue_files(["demo.pdf"])
            deadline = time.monotonic() + 3
            while self.window.jobs and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)
            self.assertEqual(send.call_args.args[:3], (self.window.token.text(), "123456", ["demo.pdf"]))
            self.assertTrue(self.window.send_file_button.isEnabled())
            self.assertIn("отправлен", self.window.transfer_message.text())

    def test_file_picker_is_nonmodal(self):
        self.window.choose_file_to_send()
        dialog = self.window.file_dialog
        self.assertIsNotNone(dialog)
        self.assertEqual(dialog.windowModality(), gui.Qt.WindowModality.NonModal)
        self.assertTrue(dialog.testOption(gui.QFileDialog.Option.DontUseNativeDialog))
        self.window.switch_tab(2)
        self.app.processEvents()
        self.assertEqual(self.window.pages.currentIndex(), 2)
        dialog.reject()
        self.assertIsNone(self.window.file_dialog)

    def test_transfer_progress_and_cancel(self):
        state = dict(phase="uploading", total=3, completed=1, index=2, name="demo.bin", size=1024, transferred=512, total_size=3072, total_transferred=1536, speed=2048)
        self.window.update_transfer_progress(state)
        self.assertIn("1 из 3", self.window.transfer_count.text())
        self.assertEqual(self.window.file_progress.value(), 50)
        self.assertEqual(self.window.batch_progress.value(), 50)
        self.assertIn("2.0 КБ/с", self.window.transfer_speed.text())
        fake_job = Mock()
        self.window.jobs["file"] = fake_job
        self.window.cancel_transfer()
        fake_job.cancel.assert_called_once()
        self.assertFalse(self.window.cancel_transfer_button.isEnabled())
        self.window.jobs.clear()


class WorkerTests(unittest.TestCase):
    def test_real_router_restart_and_session_cleanup(self):
        from aiogram import Bot, Dispatcher
        import modules.utils
        reload_module = importlib.reload
        closed = AsyncMock()

        class FakeBot:
            def __init__(self, **kwargs):
                from types import SimpleNamespace
                self.session = SimpleNamespace(close=closed, middleware=lambda handler: None)

            get_me = AsyncMock()
            me = AsyncMock()

        entered = threading.Event()
        routers = []

        async def polling(dispatcher, *args, **kwargs):
            routers.append(tuple(dispatcher.sub_routers))
            entered.set()
            await asyncio.Event().wait()

        async def monitor(bot):
            await asyncio.Event().wait()

        statuses = []
        errors = []
        runner = BotRunner(errors.append, statuses.append, lambda: None, lambda: None)
        with patch.multiple(config, BOT_TOKEN="123456789:" + "A" * 35, ADMIN_ID=123456), \
             patch("bot_runtime.importlib.reload", side_effect=lambda module: module if module is config else reload_module(module)), \
             patch("aiogram.Bot", FakeBot), \
             patch.object(Dispatcher, "start_polling", polling), \
             patch("modules.monitor.lock_monitor", monitor), \
             patch("modules.utils.cleanup_old_files"), \
             patch("modules.utils.should_send_startup_notification", return_value=False):
            for _ in range(2):
                entered.clear()
                runner.start()
                self.assertTrue(entered.wait(15), errors)
                runner.stop()
                runner.thread.join(5)
                self.assertFalse(runner.thread.is_alive())
                self.assertFalse(runner.is_running)
                self.assertIsNone(runner.loop)
        self.assertEqual(len(routers), 2)
        self.assertEqual(len(routers[0]), 6)
        self.assertTrue(all(a is not b for a, b in zip(*routers)))
        self.assertEqual(closed.await_count, 2)
        self.assertEqual(statuses.count("RUNNING"), 2)

    def test_stop_during_startup(self):
        entered = threading.Event()

        async def startup():
            entered.set()
            await asyncio.Event().wait()

        runner = BotRunner(lambda message: None, lambda status: None, lambda: None, lambda: None)
        with patch.object(runner, "_main_async", startup):
            runner.start()
            self.assertTrue(entered.wait(5))
            runner.stop()
            runner.thread.join(5)
            self.assertFalse(runner.thread.is_alive())
            self.assertFalse(runner.is_running)


if __name__ == "__main__":
    unittest.main()
