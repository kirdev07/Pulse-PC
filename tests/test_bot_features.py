"""Feature checks with temporary settings; OS and Telegram effects are mocked."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiogram import Bot, Dispatcher
from aiogram.types import Message, User, Update, CallbackQuery
import config
from modules import bot_preferences as prefs, bot_features as services
from modules import transfer_history as history
from desktop_services import send_file, send_files_with_token


class TemporarySettings:
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.config_patch = patch.multiple(config, BASE_DIR=str(self.directory),
                                          PROGRAMS_FILE_PATH=str(self.directory / "programs.json"), ADMIN_ID=123)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)


class PreferencesTests(TemporarySettings, unittest.TestCase):
    def test_round_trip_and_invalid_file_is_not_overwritten(self):
        value = prefs.load_preferences()
        value.update(device_name="Домашний ПК", greeting="Привет <друг>!", favorites=["sys_info"])
        value["alerts"].update(enabled=True, processes=["obs64.exe"])
        value["extension"] = "keep"
        prefs.save_preferences(value)
        self.assertEqual(prefs.load_preferences(), value)
        path = self.directory / "bot_options.json"
        path.write_text("invalid", encoding="utf-8")
        with self.assertRaises(ValueError):
            prefs.save_preferences(value)
        self.assertEqual(path.read_text(), "invalid")

    def test_limits_reject_bad_values_without_writing(self):
        for value in ({"favorites": ["sys_info"] * 7}, {"favorites": ["unknown"]},
                      {"scenarios": [{"id": "bad:1", "name": "x", "program_ids": ["p"]}]},
                      {"alerts": {"interval_seconds": 0}}, {"alerts": {"processes": [r"C:\bad.exe"]}}):
            with self.assertRaises(ValueError):
                prefs.save_preferences(value)
        self.assertFalse((self.directory / "bot_options.json").exists())

    def test_favorites_and_custom_welcome_use_saved_settings(self):
        from modules import keyboards, welcome
        value = prefs.load_preferences()
        value.update(device_name="<Home>", greeting="<Custom>", show_time=False, show_tips=False,
                     favorites=["sys_info", "program:demo", "program:removed"])
        prefs.save_preferences(value)
        (self.directory / "programs.json").write_text(json.dumps([dict(id="demo", name="Demo", path="demo.exe")]))
        buttons = [b for row in keyboards.get_main_inline_keyboard().inline_keyboard for b in row]
        self.assertEqual(buttons[0].callback_data, "sys_info")
        self.assertEqual(buttons[1].callback_data, "run_demo")
        self.assertNotIn("run_removed", {b.callback_data for b in buttons})
        self.assertIn("&lt;Home&gt;", welcome.control_panel_text())
        self.assertNotIn("обновлена", welcome.control_panel_text())
        self.assertIn("&lt;Custom&gt;", welcome.welcome_text("User"))


class FileAndAlertTests(TemporarySettings, unittest.TestCase):
    def test_browsing_pages_folders_first_and_deleted_directory(self):
        for n in range(15):
            (self.directory / f"{n:02}.txt").write_text("data")
        (self.directory / "Folder").mkdir()
        path, entries, page, total, capped = services.list_directory(self.directory)
        self.assertTrue(entries[0][0])
        self.assertEqual((len(entries), page, total, capped), (12, 0, 16, False))
        second = services.list_directory(path, 1)[1]
        self.assertEqual(len(second), 4)
        self.assertFalse({e[1] for e in entries} & {e[1] for e in second})
        with self.assertRaises(FileNotFoundError):
            services.list_directory(self.directory / "missing")

    def test_tokens_are_bound_expiring_and_single_use(self):
        tokens = services.ActionTokens()
        with patch.object(services.time, "monotonic", return_value=10):
            key = tokens.create((123, 123), "power", ("shutdown", 15), ttl=5)
            for who, kind in (((999, 123), "power"), ((123, 123), "file")):
                with self.assertRaises(ValueError):
                    tokens.get(key, who, kind)
        with patch.object(services.time, "monotonic", return_value=16):
            with self.assertRaises(ValueError):
                tokens.get(key, (123, 123), "power")
        key = tokens.create((123, 123), "file", "path")
        self.assertEqual(tokens.get(key, (123, 123), "file", consume=True), "path")
        with self.assertRaises(ValueError):
            tokens.get(key, (123, 123), "file")

    def test_cpu_duration_disk_cooldown_and_process_transition(self):
        evaluator = services.AlertEvaluator()
        settings = deepcopy(prefs.DEFAULTS["alerts"])
        settings.update(cpu_seconds=20, cooldown_minutes=1, processes=["obs.exe"])
        snapshot = dict(cpu=95, disks=[("C:", 1)], processes={"obs.exe"})
        first = evaluator.evaluate(settings, snapshot, 0)
        self.assertEqual(len(first), 1)  # Low disk; CPU duration not reached.
        self.assertEqual(evaluator.evaluate(settings, snapshot, 10), [])
        snapshot["processes"] = set()
        events = evaluator.evaluate(settings, snapshot, 21)
        self.assertEqual(len(events), 2)
        self.assertTrue(any("obs.exe" in text for text in events))
        self.assertEqual(evaluator.evaluate(settings, snapshot, 30), [])
        snapshot["cpu"] = 10
        evaluator.evaluate(settings, snapshot, 40)
        snapshot["cpu"] = 95
        self.assertFalse(any("Процессор" in text for text in evaluator.evaluate(settings, snapshot, 81)))

    def test_no_false_process_exit_at_start(self):
        settings = deepcopy(prefs.DEFAULTS["alerts"])
        settings["processes"] = ["missing.exe"]
        result = services.AlertEvaluator().evaluate(settings, dict(cpu=0, disks=[], processes=set()), 10)
        self.assertEqual(result, [])

    def test_window_revalidates_identity_before_os_action(self):
        window = dict(hwnd=10, pid=20, title="App")
        with patch("win32gui.IsWindow", return_value=True), patch("win32process.GetWindowThreadProcessId", return_value=(1, 21)), patch("win32gui.ShowWindow") as show:
            with self.assertRaises(ValueError):
                services.change_window(window, "min")
            show.assert_not_called()
        with patch("win32gui.IsWindow", return_value=True), patch("win32process.GetWindowThreadProcessId", return_value=(1, 20)), patch("win32gui.ShowWindow") as show, patch("modules.winutil.bring_to_front") as focus:
            for action in ("min", "max", "focus"):
                services.change_window(window, action)
            self.assertEqual(show.call_count, 2)          # focus no longer un-maximizes the window
            focus.assert_called_once_with(10)


class RuntimeFeatureTests(TemporarySettings, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = SimpleNamespace(send_message=AsyncMock(), send_document=AsyncMock())
        self.features = services.BotFeatures(self.bot)

    async def asyncTearDown(self):
        await self.features.close()

    async def test_power_cancel_and_stop_never_execute_shutdown(self):
        with patch.object(services.subprocess, "Popen") as execute:
            self.assertEqual(self.features.schedule_power("shutdown", 15), 900)
            with self.assertRaises(ValueError):
                self.features.schedule_power("restart", 1)
            await asyncio.sleep(0)
            self.assertTrue(await self.features.cancel_power())
            self.features.schedule_power("restart", 0)
            await self.features.close()
            execute.assert_not_called()
            with self.assertRaises(ValueError):
                self.features.schedule_power("shutdown", 1)

    async def test_confirmed_power_executes_selected_action_after_delay(self):
        with patch.object(services.asyncio, "sleep", new=AsyncMock()) as delay, patch.object(services.subprocess, "Popen") as execute:
            await self.features._power_after(900, "restart")
        delay.assert_awaited_once_with(900)
        self.assertEqual(execute.call_args.args[0], ["shutdown", "/r", "/t", "0"])

    async def test_scenario_checks_all_paths_and_preserves_order(self):
        one, two = self.directory / "one.exe", self.directory / "two.exe"
        one.touch()
        programs = [dict(id="one", name="One", path=str(one)), dict(id="two", name="Two", path=str(two))]
        (self.directory / "programs.json").write_text(json.dumps(programs))
        value = prefs.load_preferences()
        value["scenarios"] = [dict(id="work", name="Work", program_ids=["two", "one"])]
        prefs.save_preferences(value)
        with patch("os.startfile") as launch, patch("modules.monitor.pc_is_locked", False):
            with self.assertRaises(ValueError):
                await self.features.run_scenario("work")
            launch.assert_not_called()
            two.touch()
            with patch.object(services.asyncio, "sleep", new=AsyncMock()):
                self.assertEqual(await self.features.run_scenario("work"), ["Two", "One"])
            self.assertEqual([call.args[0] for call in launch.call_args_list], [str(two), str(one)])

    async def test_transfer_history_success_error_cancel_and_batch(self):
        path = self.directory / "file.txt"
        path.write_text("hello")
        await send_file(self.bot, 123, path)
        self.bot.send_document.side_effect = OSError("failed")
        with self.assertRaises(OSError):
            await send_file(self.bot, 123, path)
        self.bot.send_document.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await send_file(self.bot, 123, path)
        self.assertEqual([item["status"] for item in history.load_history()], ["sent", "error", "cancelled"])
        self.bot.send_document.side_effect = None
        self.bot.session = SimpleNamespace(close=AsyncMock())
        with patch("aiogram.Bot", return_value=self.bot):
            await send_files_with_token("token", "123", [path], lambda state: None)
        self.assertEqual(history.load_history()[-1]["status"], "sent")

    async def test_history_bad_file_does_not_break_successful_transfer(self):
        path = self.directory / "file.txt"
        path.write_text("hello")
        (self.directory / "transfers.json").write_text("broken")
        await send_file(self.bot, 123, path)
        self.assertEqual((self.directory / "transfers.json").read_text(), "broken")

    async def test_monitor_respects_enable_switch_and_sends_threshold_notice(self):
        with patch.object(services, "alert_snapshot", return_value=dict(cpu=0, disks=[("C:", 1)], processes=set())) as snapshot, \
             patch.object(services.asyncio, "sleep", new=AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await self.features.monitor_alerts()
            snapshot.assert_not_called()
            value = prefs.load_preferences()
            value["alerts"]["enabled"] = True
            prefs.save_preferences(value)
            with self.assertRaises(asyncio.CancelledError):
                await self.features.monitor_alerts()
            snapshot.assert_called_once()
            self.bot.send_message.assert_awaited_once()
            self.assertIn("1.0 ГБ", self.bot.send_message.await_args.args[1])

    async def test_incoming_files_are_in_history_and_history_is_bounded(self):
        from modules import file_handlers
        async def download(remote, target):
            Path(target).write_text("received")
        with patch.object(file_handlers, "FILES_DIR", str(self.directory)):
            received = await file_handlers.save_incoming_file(SimpleNamespace(download_file=download), "remote", "incoming.txt")
        self.assertEqual(history.load_history()[0]["status"], "received")
        self.assertEqual(history.load_history()[0]["path"], str(received))
        for i in range(105):
            history.record_transfer(self.directory / f"{i}.txt", "outgoing", "error")
        self.assertEqual(len(history.load_history()), 100)
        self.assertEqual(history.load_history()[-1]["name"], "104.txt")


class RoutingTests(TemporarySettings, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from modules import advanced_handlers
        from modules.middleware import AuthMiddleware
        self.advanced = importlib.reload(advanced_handlers)
        self.dispatcher = Dispatcher()
        self.dispatcher.message.middleware(AuthMiddleware())
        self.dispatcher.callback_query.middleware(AuthMiddleware())
        self.dispatcher.include_router(self.advanced.router)
        self.bot = Bot(token="123456789:" + "A" * 35)
        self.features = services.BotFeatures(self.bot)
        self.dispatcher["features"] = self.features
        self.api = AsyncMock(return_value=True)
        self.api_patch = patch.object(Bot, "__call__", self.api)
        self.api_patch.start()
        self.addCleanup(self.api_patch.stop)
        self.throttle = patch("modules.middleware.THROTTLE_RATE", 0)
        self.throttle.start()
        self.addCleanup(self.throttle.stop)
        self.lock = patch("modules.monitor.pc_is_locked", False)
        self.lock.start()
        self.addCleanup(self.lock.stop)
        self.serial = 0

    async def asyncTearDown(self):
        await self.features.close()
        await self.bot.session.close()

    async def feed(self, text=None, data=None, user=123):
        self.serial += 1
        message = Message(message_id=self.serial, date=datetime.now(timezone.utc), chat={"id": user, "type": "private"},
                          from_user=User(id=user, is_bot=False, first_name="Test"), text=text or "Menu")
        if data:
            update = Update(update_id=self.serial, callback_query=CallbackQuery(id=str(self.serial), from_user=message.from_user,
                            chat_instance="test", message=message, data=data))
        else:
            update = Update(update_id=self.serial, message=message)
        await self.dispatcher.feed_update(self.bot, update)

    def messages(self):
        return [call.args[0] for call in self.api.call_args_list if getattr(call.args[0], "text", None)]

    async def test_old_shutdown_button_requires_selection_and_confirmation(self):
        with patch.object(services.subprocess, "Popen") as execute:
            await self.feed(data="sys_shutdown")
            self.assertIsNone(self.features.power_task)
            await self.feed(data="delay:shutdown:15")
            confirm = self.messages()[-1].reply_markup.inline_keyboard[0][0].callback_data
            self.assertTrue(confirm.startswith("confirm_power:"))
            await self.feed(data=confirm)
            self.assertIsNotNone(self.features.power_task)
            execute.assert_not_called()
            await self.feed(text="/cancel")
            self.assertIsNone(self.features.power_task)
            execute.assert_not_called()

    async def test_locked_admin_can_cancel_and_read_help_but_not_browse(self):
        self.features.schedule_power("shutdown", 15)
        with patch("modules.monitor.pc_is_locked", True):
            await self.feed(text="/cancel")
            self.assertIsNone(self.features.power_task)
            await self.feed(text="/help")
            self.assertIn("Инструкция", self.messages()[-1].text)
            await self.feed(data="help:files")
            self.assertIn("Файлы и история", self.messages()[-1].text)
            await self.feed(text="/files")
            self.assertIn("заблокирован", self.messages()[-1].text)

    async def test_other_user_cannot_confirm_or_cancel(self):
        key = self.features.tokens.create((123, 123), "power", ("shutdown", 15))
        await self.feed(data="confirm_power:" + key, user=999)
        self.assertIsNone(self.features.power_task)
        self.features.schedule_power("shutdown", 15)
        await self.feed(text="/cancel", user=999)
        self.assertIsNotNone(self.features.power_task)

    async def test_browser_file_confirmation_and_history_retry(self):
        path = self.directory / "report.txt"
        path.write_text("data")
        key = self.features.tokens.create((123, 123), "browse", (str(self.directory), 0))
        await self.feed(data="browse:" + key)
        file_button = next(button for row in self.messages()[-1].reply_markup.inline_keyboard for button in row if button.callback_data.startswith("file:"))
        await self.feed(data=file_button.callback_data)
        send_button = self.messages()[-1].reply_markup.inline_keyboard[0][0]
        with patch.object(self.advanced, "send_file", new=AsyncMock(return_value="sent")) as send:
            await self.feed(data=send_button.callback_data)
            send.assert_awaited_once_with(self.bot, 123, str(path))
        history.record_transfer(path, "outgoing", "error", "network")
        await self.feed(text="/history")
        retry = self.messages()[-1].reply_markup.inline_keyboard[0][0]
        with patch.object(self.advanced, "send_file", new=AsyncMock(return_value="sent")) as send:
            await self.feed(data=retry.callback_data)
            send.assert_awaited_once()

    async def test_help_topics_and_empty_scenarios(self):
        for topic in self.advanced.HELP:
            await self.feed(data="help:" + topic)
            self.assertEqual(self.messages()[-1].text, self.advanced.HELP[topic])
        await self.feed(text="/scenarios")
        self.assertIn("Добавьте сценарий", self.messages()[-1].text)


class OptionsEditorTests(TemporarySettings, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_qt_migration import WindowTests
        WindowTests.setUpClass()
        cls.app = WindowTests.app

    def test_editor_saves_all_features_and_scenario_draft(self):
        from bot_options_ui import BotOptionsDialog
        from PySide6.QtCore import Qt
        dialog = BotOptionsDialog([dict(id="one", name="One", path="one.exe")])
        try:
            dialog.device_name.setText("Studio")
            dialog.greeting.setText("Hello!")
            dialog.panel_checks["show_time"].setChecked(False)
            dialog.favorites.item(0).setCheckState(Qt.CheckState.Checked)
            dialog.scenario_name.setText("Work")
            dialog.scenario_programs.item(0).setCheckState(Qt.CheckState.Checked)
            dialog.alert_checks["enabled"].setChecked(True)
            dialog.alert_numbers["cpu_percent"].setValue(85)
            dialog.processes.setText("OBS64.exe, obs64.exe")
            dialog.save()
            value = prefs.load_preferences()
            self.assertEqual(value["device_name"], "Studio")
            self.assertFalse(value["show_time"])
            self.assertEqual(value["scenarios"][0]["program_ids"], ["one"])
            self.assertEqual(value["favorites"], ["sys_screenshot"])
            self.assertEqual(value["alerts"]["cpu_percent"], 85)
            self.assertEqual(value["alerts"]["processes"], ["obs64.exe"])
            self.assertTrue(value["alerts"]["enabled"])
        finally:
            dialog.deleteLater()
            self.app.processEvents()

    def test_editor_rejects_empty_scenario_and_cancel_does_not_write(self):
        from bot_options_ui import BotOptionsDialog
        dialog = BotOptionsDialog([])
        try:
            dialog.scenario_name.setText("Empty")
            dialog.save()
            self.assertFalse((self.directory / "bot_options.json").exists())
            self.assertIn("Выберите", dialog.message.text())
            dialog.reject()
            self.assertFalse((self.directory / "bot_options.json").exists())
        finally:
            dialog.deleteLater()
            self.app.processEvents()
