"""Shared Telegram welcome copy for /start, startup and the main menu."""
from datetime import datetime
from html import escape
import socket

from modules.keyboards import load_programs
from modules.bot_preferences import load_preferences


def welcome_text(first_name=None, *, startup=False):
    if startup:
        return "🟣 <b>Pulse PC на связи</b>\nБот подключился к Telegram. Панель управления — ниже."
    name = escape(str(first_name or ""))
    greeting = f"Привет, {name}!" if name else "Добро пожаловать!"
    custom = escape(load_preferences()["greeting"])
    return f"🟣 <b>Pulse PC</b>\n{greeting}" + (f" {custom}" if custom else "")


def control_panel_text():
    settings = load_preferences()
    name = escape(settings["device_name"].strip() or socket.gethostname() or "Мой компьютер")
    count = len(load_programs())
    programs = f"Программ в быстром запуске: <b>{count}</b>." if count else "Добавьте программы в приложении на ПК для быстрого запуска."
    parts = ["<b>Ваш компьютер</b>"]
    if settings["show_device"]:
        parts.append(f"💻 <code>{name}</code>")
    if settings["show_time"]:
        parts.append(f"Панель обновлена в {datetime.now():%H:%M}")
    if settings["show_programs"]:
        parts.append("\n" + programs)
    if settings["show_tips"]:
        parts.append("\nСсылка в чат → открыть на ПК.\nФайл в чат → сохранить на ПК (до 20 МБ).\n«Файлы» → получить файл (до 50 МБ).")
    parts.append("\nВыберите действие ниже ↓\nИнструкция: /help")
    return "\n".join(parts)
