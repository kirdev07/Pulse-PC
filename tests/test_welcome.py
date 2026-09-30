"""Offline checks for the Telegram welcome and every main-menu entry point."""
import importlib
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import config
from bot_runtime import BotRunner
from modules import welcome
from modules.bot_preferences import validate_preferences


class WelcomeTests(unittest.TestCase):
    def test_personal_greeting_escapes_telegram_html(self):
        text = welcome.welcome_text('<Admin> & "Name"')
        self.assertIn("&lt;Admin&gt; &amp;", text)
        self.assertNotIn("<Admin>", text)
        self.assertIn("Добро пожаловать", welcome.welcome_text())
        self.assertNotIn("Компьютер успешно запущен", welcome.welcome_text(startup=True))

    def test_panel_uses_real_program_count_and_handles_empty_list(self):
        with patch.object(welcome.socket, "gethostname", return_value="PC <Home>"), \
             patch.object(welcome, "datetime") as clock, patch.object(welcome, "load_programs", return_value=[]) as programs, \
             patch.object(welcome, "load_preferences", return_value=validate_preferences({})):
            clock.now.return_value = datetime(2026, 9, 10, 14, 35)
            text = welcome.control_panel_text()
            self.assertIn("PC &lt;Home&gt;", text)
            self.assertIn("14:35", text)
            self.assertIn("Добавьте программы", text)
            self.assertIn("до 20 МБ", text)
            self.assertIn("до 50 МБ", text)
            programs.return_value = [{"name": "One"}, {"name": "Two"}]
            self.assertIn("<b>2</b>", welcome.control_panel_text())


class WelcomeRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_reply_and_back_keep_keyboards_and_shared_panel(self):
        from modules import system_handlers as system
        message = SimpleNamespace(from_user=SimpleNamespace(first_name="<User>"), answer=AsyncMock(), edit_text=AsyncMock())
        callback = SimpleNamespace(message=message, answer=AsyncMock())
        with patch.object(system, "control_panel_text", return_value="<b>Test panel</b>"):
            await system.start_cmd(message)
            calls = message.answer.await_args_list
            self.assertEqual(len(calls), 2)
            self.assertIn("&lt;User&gt;", calls[0].args[0])
            self.assertEqual(calls[0].kwargs["parse_mode"], "HTML")
            self.assertTrue(calls[0].kwargs["reply_markup"].keyboard)
            self.assertEqual(calls[1].args[0], "<b>Test panel</b>")
            buttons = {button.callback_data for row in calls[1].kwargs["reply_markup"].inline_keyboard for button in row}
            self.assertTrue({"menu_system", "menu_files", "menu_history", "menu_help", "menu_windows", "menu_power", "menu_scenarios"} <= buttons)
            await system.show_main_menu_text(message)
            self.assertEqual(message.answer.await_args.args[0], "<b>Test panel</b>")
            await system.callback_menu_main(callback)
            self.assertEqual(message.edit_text.await_args.args[0], "<b>Test panel</b>")
            callback.answer.assert_awaited_once()

    async def test_startup_notification_uses_same_panel_and_closes_session(self):
        from aiogram import Dispatcher
        fake_bot = SimpleNamespace(me=AsyncMock(), send_message=AsyncMock(),
                                   session=SimpleNamespace(middleware=Mock(), close=AsyncMock()))
        runner = BotRunner(Mock(), Mock(), Mock(), Mock())
        real_reload = importlib.reload
        with patch.multiple(config, BOT_TOKEN="123456789:" + "A" * 35, ADMIN_ID=123456), \
             patch("bot_runtime.importlib.reload", side_effect=lambda module: module if module is config else real_reload(module)), \
             patch("aiogram.Bot", return_value=fake_bot), \
             patch.object(Dispatcher, "start_polling", new=AsyncMock()), \
             patch("modules.monitor.lock_monitor", new=AsyncMock()), \
             patch("modules.utils.cleanup_old_files"), \
             patch("modules.utils.should_send_startup_notification", return_value=True), \
             patch.object(welcome, "control_panel_text", return_value="<b>Same panel</b>"):
            await runner._main_async()
        calls = fake_bot.send_message.await_args_list
        self.assertEqual(len(calls), 2)
        self.assertIn("Pulse PC на связи", calls[0].args[1])
        self.assertEqual(calls[1].args[:2], (123456, "<b>Same panel</b>"))
        fake_bot.session.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
