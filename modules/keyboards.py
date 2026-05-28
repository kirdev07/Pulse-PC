import os
import json
import logging
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

import config

logger = logging.getLogger(__name__)

# Загрузка списка программ из JSON
def load_programs() -> list:
    if not os.path.exists(config.PROGRAMS_FILE_PATH):
        logger.warning(f"Файл {config.PROGRAMS_FILE_PATH} не найден.")
        return []
    try:
        with open(config.PROGRAMS_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке JSON-файла программ: {e}")
        return []

# Постоянная Reply-клавиатура внизу экрана
def get_reply_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🖥️ Меню управления"))
    builder.add(KeyboardButton(text="📸 Скриншот"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# Главное встроенное меню
def get_main_inline_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚙️ Система", callback_data="menu_system"),
        InlineKeyboardButton(text="🚀 Запуск программ", callback_data="menu_launch")
    )
    builder.row(
        InlineKeyboardButton(text="❌ Закрытие программ", callback_data="menu_close"),
        InlineKeyboardButton(text="📸 Скриншот экрана", callback_data="sys_screenshot")
    )
    builder.row(
        InlineKeyboardButton(text="🎵 Мультимедиа", callback_data="menu_media"),
        InlineKeyboardButton(text="🔍 Поиск", callback_data="menu_search")
    )
    return builder.as_markup()

# Меню управления системой (Выкл, Сон, Блокировка)
def get_system_inline_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔌 Выкл", callback_data="sys_shutdown"),
        InlineKeyboardButton(text="🔄 Перезагрузка", callback_data="sys_restart"),
        InlineKeyboardButton(text="💤 Сон", callback_data="sys_sleep")
    )
    builder.row(
        InlineKeyboardButton(text="🔒 Блокировка", callback_data="sys_lock"),
        InlineKeyboardButton(text="🧹 Очистить загрузки", callback_data="sys_clear_files")
    )

    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")
    )
    return builder.as_markup()

# Меню управления мультимедиа
def get_media_inline_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏮️ Назад", callback_data="media_prev"),
        InlineKeyboardButton(text="⏯️ Старт/Пауза", callback_data="media_play"),
        InlineKeyboardButton(text="⏭️ Вперед", callback_data="media_next")
    )
    builder.row(
        InlineKeyboardButton(text="🔉 Тише", callback_data="media_voldown"),
        InlineKeyboardButton(text="🔇 Звук", callback_data="media_mute"),
        InlineKeyboardButton(text="🔊 Громче", callback_data="media_volumeup")
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu_main")
    )
    return builder.as_markup()

# Меню запуска программ
def get_launch_inline_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    programs = load_programs()
    for idx, prog in enumerate(programs):
        name = prog.get("name", f"Программа {idx + 1}")
        builder.add(InlineKeyboardButton(text=f"🚀 {name}", callback_data=f"run_{idx}"))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main"))
    return builder.as_markup()

# Меню закрытия программ
def get_close_inline_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⏹️ Закрыть активное окно (Alt+F4)", callback_data="sys_close_active"))
    
    try:
        import win32gui
        import win32con
        import win32process
        import psutil
        
        valid_windows = []
        def enum_windows_proc(hwnd, lParam):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                # Игнорируем ToolWindow (фоновые служебные окна)
                if not (ex_style & win32con.WS_EX_TOOLWINDOW):
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        p_name = psutil.Process(pid).name()
                        if p_name.lower().endswith('.exe'):
                            p_name = p_name[:-4]
                    except:
                        p_name = "App"
                    valid_windows.append((hwnd, p_name.capitalize(), win32gui.GetWindowText(hwnd)))
                    
        win32gui.EnumWindows(enum_windows_proc, 0)
        
        # Дополнительная фильтрация системных окон
        ignore_titles = ["Program Manager", "Settings", "Taskbar"]
        filtered_windows = [(h, p, t) for h, p, t in valid_windows if t not in ignore_titles]
                
        for hwnd, p_name, title in filtered_windows[:40]:
            short_title = title[:20] + "..." if len(title) > 20 else title
            btn_text = f"❌ [{p_name}] {short_title}"
            # Ограничиваем длину текста кнопки (максимум ~40 символов для красоты)
            btn_text = btn_text[:40]
            builder.row(InlineKeyboardButton(text=btn_text, callback_data=f"killhwnd_{hwnd}"))
            
    except Exception as e:
        pass
        
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить", callback_data="menu_close"),
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main")
    )
    return builder.as_markup()
