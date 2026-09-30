"""Telegram menus for files, timers, scenarios, history, windows and help."""
import asyncio
from html import escape
import math
import time

from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from desktop_services import send_file, validate_upload, format_bytes, telegram_error
from modules.bot_features import file_roots, list_directory, list_windows, change_window
from modules.bot_preferences import load_preferences
from modules.transfer_history import load_history
from modules.utils import safe_edit_text

router = Router()

HELP = {
    "main": ("📖 <b>Инструкция Pulse PC</b>\n\n"
             "1. На ПК укажите токен от @BotFather и свой Telegram ID.\n"
             "2. Сохраните настройки и запустите бота.\n"
             "3. Откройте личный чат и отправьте /start.\n\n"
             "Управление доступно только администратору, пока приложение работает и ПК не заблокирован. "
             "При блокировке остаются доступны /help и /cancel.\n\n"
             "Крестик сворачивает приложение в трей. Полный выход — через меню значка Pulse PC.\n\n"
             "Выберите раздел инструкции:"),
    "files": ("📁 <b>Файлы и история</b>\n\n"
              "«Файлы» или /files → папка → файл → «Отправить». Есть Рабочий стол, Документы, Загрузки и диски; "
              "папки отображаются страницами по 12 элементов (до 5 000 в каталоге).\n\n"
              "Получить файл по пути: <code>/getfile C:\\папка\\файл.pdf</code>. До 50 МБ, только непустые файлы.\n"
              "Отправить файл на ПК: прикрепите его к чату. До 20 МБ; сохранение в папку files. "
              "Голосовое сообщение сохраняется как аудиофайл, а не команда.\n\n"
              "«История» или /history: последние 100 передач. «Повторить» доступно для неудачных и отменённых отправок с ПК. "
              "После перезапуска бота старые кнопки файлов нужно обновить.\n\n"
              "Файлы в папке files старше трёх дней удаляются при запуске бота."),
    "power": ("⏲ <b>Питание</b>\n\n"
              "«Таймер» → выключение или перезагрузка → время → подтверждение.\n"
              "Своё время: <code>/shutdown 30</code> или <code>/restart 15</code> — минуты, максимум 1440. "
              "0 означает через 10 секунд после подтверждения.\n\n"
              "Отмена: /cancel или «Отменить таймер». Доступна даже при заблокированном ПК. "
              "Одновременно работает один таймер. Остановка бота отменяет его.\n\n"
              "Сон и блокировка находятся в меню «Система». Бот на уснувшем или выключенном ПК не отвечает. "
              "Перед выключением сохраните документы: автосохранение бот не выполняет."),
    "programs": ("🚀 <b>Программы, избранное и сценарии</b>\n\n"
                 "Добавьте программы в приложении и нажмите «Сохранить список».\n"
                 "Настройки → «Возможности бота»: до 6 избранных действий на главной панели.\n\n"
                 "Вкладка «Сценарии»: задайте название, отметьте программы, нажмите «Добавить / применить», "
                 "затем сохраните настройки. Сценарий запускает программы в порядке списка с небольшой паузой.\n"
                 "В Telegram: «Сценарии» или /scenarios. Одновременно выполняется один сценарий. "
                 "При удалении программы сценарий нужно обновить.\n\n"
                 "«Закрытие программ» закрывает окно или завершает процесс. "
                 "«Окна» или /windows позволяет свернуть, развернуть и вывести окно на передний план."),
    "settings": ("⚙️ <b>Настройки и уведомления</b>\n\n"
                 "В приложении: Настройки → «Возможности бота».\n"
                 "«Панель»: имя ПК, приветствие, видимые сведения и избранное. Изменения видны после обновления меню.\n"
                 "«Уведомления»: включение мониторинга, порог CPU и длительность нагрузки, минимум свободного места, "
                 "частота проверки и пауза между повторными уведомлениями.\n"
                 "Имена отслеживаемых процессов указываются через запятую: <code>obs64.exe, notepad.exe</code>. "
                 "Уведомление приходит после перехода «работал → завершился»; отсутствие программы при старте не считается завершением.\n\n"
                 "Ссылку отправьте в чат — она откроется на ПК. Поиск: <code>/search запрос</code>. "
                 "Состояние ПК: /status. Мультимедиа: меню треков и громкости.\n\n"
                 "Нет связи — проверьте интернет и токен. Не удаётся отправить файл — проверьте путь, размер и начало чата с ботом."),
}


def markup(rows):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=data) for text, data in row] for row in rows])


def help_rows():
    return [[("Файлы", "help:files"), ("Питание", "help:power")],
            [("Программы и окна", "help:programs"), ("Настройки", "help:settings")],
            [("Общая инструкция", "help:main"), ("Главная", "menu_main")]]


async def render(callback, text, rows):
    await safe_edit_text(callback.message, text, markup(rows))


def owner(event):
    chat = event.message.chat if isinstance(event, CallbackQuery) else event.chat
    return event.from_user.id, chat.id


async def roots_panel(features, identity):
    roots = await asyncio.to_thread(file_roots)
    rows = [[("📁 " + name, "browse:" + features.tokens.create(identity, "browse", (str(path), 0)))] for name, path in roots]
    rows += [[("История", "menu_history"), ("Главная", "menu_main")]]
    return "📁 <b>Файлы на компьютере</b>\nВыберите папку или диск.", rows


async def directory_panel(features, identity, path, page):
    path, entries, page, total, capped = await asyncio.to_thread(list_directory, path, page)
    rows = []
    for is_dir, name, child in entries:
        kind = "browse" if is_dir else "file"
        value = (str(child), 0) if is_dir else str(child)
        key = features.tokens.create(identity, kind, value)
        rows.append([(("📁 " if is_dir else "📄 ") + name[:50], kind + ":" + key)])
    pages = max(1, math.ceil(total / 12))
    navigation = []
    for label, target in (("←", page - 1), ("→", page + 1)):
        if 0 <= target < pages:
            key = features.tokens.create(identity, "browse", (str(path), target))
            navigation.append((label, "browse:" + key))
    if navigation:
        rows.append(navigation)
    if path.parent != path:
        rows.append([("↑ На уровень выше", "browse:" + features.tokens.create(identity, "browse", (str(path.parent), 0)))])
    rows.append([("Папки и диски", "menu_files"), ("Главная", "menu_main")])
    info = "\nПапка пуста." if not entries else ""
    if capped:
        info += "\nПоказаны первые 5 000 элементов каталога."
    return f"📁 <code>{escape(str(path)[:1500])}</code>\nСтраница {page + 1} / {pages}{info}", rows


def power_panel(features):
    remaining = max(0, math.ceil(features.power_deadline - time.monotonic())) if features.power_deadline else None
    text = "⏲ <b>Питание компьютера</b>\nВыберите действие и подтвердите его."
    if remaining is not None:
        text += f"\n\nАктивный таймер: {'перезагрузка' if features.power_action == 'restart' else 'выключение'}, осталось ≈ {remaining} с."
    return text, [[("Выключение", "power:shutdown"), ("Перезагрузка", "power:restart")],
                  [("Отменить таймер", "power_cancel"), ("Обновить", "menu_power")], [("Главная", "menu_main")]]


def power_confirmation(features, identity, action, minutes):
    if action not in ("shutdown", "restart") or not 0 <= minutes <= 1440:
        raise ValueError("Укажите время от 0 до 1440 минут.")
    key = features.tokens.create(identity, "power", (action, minutes), ttl=120)
    text = f"Подтвердите {'перезагрузку' if action == 'restart' else 'выключение'}: " + (f"через {minutes} мин." if minutes else "через 10 секунд.")
    return text + "\nСохраните открытые документы.", [[("Подтвердить", "confirm_power:" + key), ("Назад", "menu_power")]]


async def history_panel(features, identity, page=0):
    entries = list(reversed(await asyncio.to_thread(load_history)))
    page = max(0, min(page, max(0, (len(entries) - 1) // 6)))
    text = ["📨 <b>История передач</b>"]
    rows = []
    names = {"sent": "отправлен", "received": "получен", "error": "ошибка", "cancelled": "отменён"}
    for item in entries[page * 6:(page + 1) * 6]:
        text.append(f"\n{escape(item['time'].replace('T', ' '))} · {'ПК → Telegram' if item['direction'] == 'outgoing' else 'Telegram → ПК'}\n"
                    f"<b>{escape(item['name'][:90])}</b> — {names.get(item['status'], 'неизвестно')}")
        if item["status"] in ("error", "cancelled") and item["direction"] == "outgoing":
            key = features.tokens.create(identity, "retry", item["path"])
            rows.append([("Повторить: " + item["name"][:35], "retry:" + key)])
    if not entries:
        text.append("\nПередач пока нет.")
    nav = []
    if page:
        nav.append(("←", f"history:{page - 1}"))
    if (page + 1) * 6 < len(entries):
        nav.append(("→", f"history:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([("Обновить", "menu_history"), ("Главная", "menu_main")])
    return "\n".join(text), rows


@router.message(Command("help"))
@router.message(F.text == "📖 Помощь")
async def help_command(message: Message):
    await message.answer(HELP["main"], parse_mode="HTML", reply_markup=markup(help_rows()))


@router.message(Command("cancel"))
async def cancel_command(message: Message, features):
    cancelled = await features.cancel_power()
    await message.answer("Таймер отменён." if cancelled else "Активного таймера нет.")


@router.message(Command("shutdown", "restart"))
async def timer_command(message: Message, command: CommandObject, features):
    try:
        minutes = int(command.args or "0")
        text, rows = power_confirmation(features, owner(message), command.command.lower(), minutes)
        await message.answer(text, reply_markup=markup(rows))
    except ValueError:
        await message.answer("Укажите минуты от 0 до 1440. Например: /shutdown 30")


@router.message(Command("files", "history", "scenarios", "windows"))
async def feature_command(message: Message, command: CommandObject, features):
    try:
        text, rows = await menu_panel("menu_" + command.command.lower(), features, owner(message))
        await message.answer(text, parse_mode="HTML", reply_markup=markup(rows))
    except (ValueError, OSError) as exc:
        await message.answer(telegram_error(exc))


async def menu_panel(data, features, identity):
    if data == "menu_files":
        return await roots_panel(features, identity)
    if data == "menu_history":
        return await history_panel(features, identity)
    if data == "menu_power":
        return power_panel(features)
    if data == "menu_scenarios":
        settings = await asyncio.to_thread(load_preferences)
        rows = [[("▶ " + item["name"], "scenario:" + features.tokens.create(identity, "scenario", item["id"]))] for item in settings["scenarios"]]
        text = "▶ <b>Сценарии</b>\nВыберите набор программ для запуска."
        if not rows:
            text = "▶ <b>Сценарии</b>\nДобавьте сценарий в приложении: Настройки → Возможности бота → Сценарии."
        rows.append([("Главная", "menu_main")])
        return text, rows
    if data == "menu_windows":
        windows = await asyncio.to_thread(list_windows)
        rows = [[(item["title"][:55], "window:" + features.tokens.create(identity, "window", item))] for item in windows[:40]]
        rows.append([("Обновить", "menu_windows"), ("Главная", "menu_main")])
        return "🪟 <b>Окна</b>\n" + ("Выберите окно (до 40 в списке)." if windows else "Открытых окон не найдено."), rows
    raise ValueError("Неизвестное меню.")


@router.callback_query(F.data.in_({"menu_files", "menu_history", "menu_power", "menu_scenarios", "menu_windows", "menu_help", "power_cancel", "sys_shutdown", "sys_restart"}) |
                       F.data.startswith(("browse:", "file:", "send:", "retry:", "history:", "power:", "delay:", "confirm_power:", "scenario:", "window:", "winact:", "help:")))
async def feature_callback(callback: CallbackQuery, bot: Bot, features):
    await callback.answer()
    if not callback.message:
        return
    data, identity = callback.data, owner(callback)
    try:
        if data == "menu_help" or data.startswith("help:"):
            topic = data.split(":", 1)[1] if ":" in data else "main"
            text, rows = HELP.get(topic, HELP["main"]), help_rows()
        elif data == "power_cancel":
            cancelled = await features.cancel_power()
            await callback.message.answer("Таймер отменён." if cancelled else "Активного таймера нет.")
            return
        elif data in ("sys_shutdown", "sys_restart") or data.startswith("power:"):
            action = data.split(":", 1)[1] if ":" in data else data[4:]
            if action not in ("shutdown", "restart"):
                raise ValueError("Неизвестное действие.")
            text = "Выберите время. Следующий шаг — подтверждение.\nСвоё время: /" + action + " 30"
            rows = [[(label, f"delay:{action}:{minutes}") for label, minutes in (("Сейчас", 0), ("15 мин", 15), ("1 час", 60))], [("Назад", "menu_power")]]
        elif data.startswith("delay:"):
            _, action, minutes = data.split(":")
            text, rows = power_confirmation(features, identity, action, int(minutes))
        elif data.startswith("confirm_power:"):
            action, minutes = features.tokens.get(data.split(":")[1], identity, "power", consume=True)
            seconds = features.schedule_power(action, minutes)
            text = f"Таймер установлен: {seconds} с. Остановка бота отменит таймер."
            rows = [[("Отменить таймер", "power_cancel"), ("Обновить", "menu_power")]]
        elif data.startswith("browse:"):
            path, page = features.tokens.get(data.split(":")[1], identity, "browse")
            text, rows = await directory_panel(features, identity, path, page)
        elif data.startswith("file:"):
            path = features.tokens.get(data.split(":")[1], identity, "file")
            checked = await asyncio.to_thread(validate_upload, path)
            size = await asyncio.to_thread(lambda: checked.stat().st_size)
            key = features.tokens.create(identity, "send", str(checked))
            text = f"📄 <b>{escape(checked.name)}</b>\n{format_bytes(size)}\nОтправить в личный чат администратора?"
            rows = [[("Отправить", "send:" + key), ("Папки", "menu_files")]]
        elif data.startswith(("send:", "retry:")):
            kind, key = data.split(":")
            path = features.tokens.get(key, identity, kind, consume=True)
            await callback.message.answer("Отправляю файл…")
            import config
            try:
                result = await send_file(bot, config.ADMIN_ID, path)
            except Exception as exc:
                result = telegram_error(exc)
            await callback.message.answer(result, reply_markup=markup([[("История", "menu_history"), ("Папки", "menu_files")]]))
            return
        elif data.startswith("history:"):
            text, rows = await history_panel(features, identity, int(data.split(":")[1]))
        elif data.startswith("scenario:"):
            key = features.tokens.get(data.split(":")[1], identity, "scenario", consume=True)
            await callback.message.answer("Запускаю сценарий…")
            launched = await features.run_scenario(key)
            text = "Запущено:\n" + "\n".join(escape(name) for name in launched)
            rows = [[("Сценарии", "menu_scenarios"), ("Главная", "menu_main")]]
        elif data.startswith("window:"):
            window = features.tokens.get(data.split(":")[1], identity, "window")
            rows = []
            for label, action in (("Свернуть", "min"), ("Развернуть", "max"), ("На передний план", "focus")):
                key = features.tokens.create(identity, "winact", (window, action))
                rows.append([(label, "winact:" + key)])
            rows.append([("Окна", "menu_windows"), ("Главная", "menu_main")])
            text = "🪟 <b>" + escape(window["title"][:250]) + "</b>"
        elif data.startswith("winact:"):
            window, action = features.tokens.get(data.split(":")[1], identity, "winact", consume=True)
            await asyncio.to_thread(change_window, window, action)
            text, rows = "Действие с окном выполнено.", [[("Окна", "menu_windows"), ("Главная", "menu_main")]]
        else:
            text, rows = await menu_panel(data, features, identity)
        await render(callback, text, rows)
    except Exception as exc:
        await callback.message.answer(telegram_error(exc), reply_markup=markup([[("Главная", "menu_main")]]))
