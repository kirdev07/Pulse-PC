from html import escape
import logging
import subprocess
import pyautogui
import urllib.parse
import webbrowser
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command

from modules.keyboards import (
    get_reply_keyboard, get_main_inline_keyboard, get_system_inline_keyboard,
    get_media_inline_keyboard, get_launch_inline_keyboard, get_close_inline_keyboard
)
from modules.utils import safe_edit_text
from modules.welcome import control_panel_text, welcome_text

logger = logging.getLogger(__name__)
router = Router()

# Обработчик команды /start
@router.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer(
        welcome_text(message.from_user.first_name if message.from_user else None),
        reply_markup=get_reply_keyboard(),
        parse_mode="HTML"
    )
    await message.answer(
        control_panel_text(),
        reply_markup=get_main_inline_keyboard(),
        parse_mode="HTML"
    )

# Обработчик вызова главного меню через Reply-клавиатуру
@router.message(F.text == "🖥️ Меню управления")
async def show_main_menu_text(message: Message):
    await message.answer(
        control_panel_text(),
        reply_markup=get_main_inline_keyboard(),
        parse_mode="HTML"
    )

# Быстрый скриншот через Reply-клавиатуру
@router.message(F.text == "📸 Скриншот")
async def make_screenshot_text(message: Message):
    try:
        import mss
        from aiogram.types import InlineKeyboardButton
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from io import BytesIO
        
        with mss.mss() as sct:
            monitors = sct.monitors
            if len(monitors) > 2:
                builder = InlineKeyboardBuilder()
                builder.row(InlineKeyboardButton(text="🖥 Все мониторы", callback_data="screenshot_0"))
                for i in range(1, len(monitors)):
                    builder.add(InlineKeyboardButton(text=f"💻 Монитор {i}", callback_data=f"screenshot_{i}"))
                builder.adjust(1, 2)
                await message.answer(
                    "📸 <b>Скриншот экрана</b>\n\nОбнаружено несколько мониторов. Выберите, какой заскринить:",
                    reply_markup=builder.as_markup(),
                    parse_mode="HTML"
                )
            else:
                sct_img = sct.grab(monitors[1])
                from PIL import Image
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                img_buffer = BytesIO()
                img.save(img_buffer, format="PNG")
                img_buffer.seek(0)
                
                photo = BufferedInputFile(img_buffer.getvalue(), filename="screenshot.png")
                await message.answer_photo(photo, caption="📸 Текущий снимок экрана")
    except Exception as e:
        await message.answer(f"Ошибка при создании скриншота: {e}")

# Навигация: Главное меню
@router.callback_query(F.data == "menu_main")
async def callback_menu_main(callback: CallbackQuery):
    await safe_edit_text(
        callback.message,
        control_panel_text(),
        get_main_inline_keyboard()
    )
    await callback.answer()

# Навигация: Меню системы
@router.callback_query(F.data == "menu_system")
async def callback_menu_system(callback: CallbackQuery):
    await safe_edit_text(
        callback.message,
        "⚙️ <b>Управление системой</b>\n\nВыберите действие с системой:",
        get_system_inline_keyboard()
    )
    await callback.answer()

# Навигация: Меню мультимедиа
@router.callback_query(F.data == "menu_media")
async def callback_menu_media(callback: CallbackQuery):
    await safe_edit_text(
        callback.message,
        "🎵 <b>Управление мультимедиа</b>\n\nИспользуйте кнопки ниже для управления плеерами и громкостью звука на ПК:",
        get_media_inline_keyboard()
    )
    await callback.answer()

# Навигация: Меню запуска программ
@router.callback_query(F.data == "menu_launch")
async def callback_menu_launch(callback: CallbackQuery):
    await safe_edit_text(
        callback.message,
        "🚀 <b>Запуск программ</b>\n\nВыберите программу для запуска:",
        get_launch_inline_keyboard()
    )
    await callback.answer()

# Навигация: Меню закрытия программ
@router.callback_query(F.data == "menu_close")
async def callback_menu_close(callback: CallbackQuery):
    await safe_edit_text(
        callback.message,
        "❌ <b>Закрытие программ</b>\n\nВыберите программу для принудительного закрытия или закройте активное окно:",
        get_close_inline_keyboard()
    )
    await callback.answer()

# Системное действие: Сон
@router.callback_query(F.data == "sys_sleep")
async def callback_sleep(callback: CallbackQuery):
    try:
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"])
        await callback.answer("Компьютер переходит в спящий режим!")
    except Exception as e:
        await callback.answer(f"Ошибка спящего режима: {e}", show_alert=True)

# Системное действие: Блокировка
@router.callback_query(F.data == "sys_lock")
async def callback_lock(callback: CallbackQuery):
    try:
        subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
        await callback.answer("Компьютер заблокирован!")
    except Exception as e:
        await callback.answer(f"Ошибка блокировки ПК: {e}", show_alert=True)

# Действие: Кнопка "Поиск в браузере"
@router.callback_query(F.data == "menu_search")
async def callback_menu_search(callback: CallbackQuery):
    from aiogram.types import ForceReply
    await callback.message.answer(
        "🔍 <b>Поиск в браузере</b>\n\nВведите текст для поиска ниже (ответом на это сообщение):",
        reply_markup=ForceReply(selective=True),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(F.reply_to_message.text & F.reply_to_message.text.contains("Введите текст для поиска ниже"))
async def search_reply_handler(message: Message):
    try:
        query = message.text
        if not query:
            return
            
        url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
        webbrowser.open(url)
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔍 Искать еще", callback_data="menu_search"))
        await message.answer(f"🔍 В браузере открыт поиск по запросу:\n<b>{escape(str(query))}</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Ошибка при поиске: {e}")
        await message.answer(f"Ошибка: {e}")




# Системное действие: Закрыть активное окно
@router.callback_query(F.data == "sys_close_active")
async def callback_close_active(callback: CallbackQuery):
    try:
        pyautogui.hotkey('alt', 'f4')
        await callback.answer("Активное окно закрыто (Alt+F4)")
    except Exception as e:
        await callback.answer(f"Ошибка при закрытии окна: {e}", show_alert=True)

# Системное действие: Скриншот
@router.callback_query(F.data == "sys_screenshot")
async def callback_screenshot(callback: CallbackQuery):
    try:
        import mss
        from aiogram.types import InlineKeyboardButton
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from io import BytesIO
        
        with mss.mss() as sct:
            monitors = sct.monitors
            if len(monitors) > 2:
                builder = InlineKeyboardBuilder()
                builder.row(InlineKeyboardButton(text="🖥 Все мониторы", callback_data="screenshot_0"))
                for i in range(1, len(monitors)):
                    builder.add(InlineKeyboardButton(text=f"💻 Монитор {i}", callback_data=f"screenshot_{i}"))
                builder.adjust(1, 2)
                builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu_main"))
                await safe_edit_text(
                    callback.message,
                    "📸 <b>Скриншот экрана</b>\n\nОбнаружено несколько мониторов. Выберите, какой заскринить:",
                    builder.as_markup()
                )
                await callback.answer()
            else:
                await callback.answer("Делаю скриншот...")
                def take_screenshot():
                    sct_img = sct.grab(monitors[1])
                    from PIL import Image
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    img_buffer = BytesIO()
                    img.save(img_buffer, format="PNG")
                    img_buffer.seek(0)
                    return img_buffer.getvalue()
                
                import asyncio
                img_bytes = await asyncio.to_thread(take_screenshot)
                
                photo = BufferedInputFile(img_bytes, filename="screenshot.png")
                await callback.message.answer_photo(photo, caption="📸 Текущий снимок экрана")
    except Exception as e:
        await callback.message.answer(f"Ошибка при создании скриншота: {e}")

@router.callback_query(F.data.startswith("screenshot_"))
async def callback_screenshot_specific(callback: CallbackQuery):
    await callback.answer("Делаю скриншот...")
    monitor_idx = int(callback.data.split("_")[1])
    try:
        import mss
        from io import BytesIO
        with mss.mss() as sct:
            monitors = sct.monitors
            if monitor_idx < len(monitors):
                def take_specific_screenshot():
                    sct_img = sct.grab(monitors[monitor_idx])
                    from PIL import Image
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    img_buffer = BytesIO()
                    img.save(img_buffer, format="PNG")
                    img_buffer.seek(0)
                    return img_buffer.getvalue()
                
                import asyncio
                img_bytes = await asyncio.to_thread(take_specific_screenshot)
                
                photo = BufferedInputFile(img_bytes, filename="screenshot.png")
                caption = "📸 Снимок всех мониторов" if monitor_idx == 0 else f"📸 Снимок экрана (Монитор {monitor_idx})"
                await callback.message.answer_photo(photo, caption=caption)
            else:
                await callback.answer("Монитор не найден!", show_alert=True)
    except Exception as e:
        await callback.message.answer(f"Ошибка при создании скриншота: {e}")

# Поиск в браузере по умолчанию
@router.message(F.text.startswith(("/search", "/s", "? ")))
async def cmd_search(message: Message):
    try:
        text = message.text
        if text.startswith("/search"):
            query = text[len("/search"):].strip()
        elif text.startswith("/s"):
            query = text[len("/s"):].strip()
        elif text.startswith("? "):
            query = text[len("? "):].strip()
            
        if not query:
            await message.answer("Пожалуйста, укажите текст для поиска. Пример:\n/search погода на завтра\n? погода на завтра")
            return
            
        url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
        webbrowser.open(url)
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔍 Искать еще", callback_data="menu_search"))
        await message.answer(f"🔍 В браузере открыт поиск по запросу:\n<b>{escape(str(query))}</b>", parse_mode="HTML", reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Ошибка при поиске: {e}")
        await message.answer(f"Ошибка: {e}")

# Открытие ссылок из сообщений
@router.message(F.text & (F.text.contains("http://") | F.text.contains("https://")))
async def handle_url_message(message: Message):
    try:
        import re
        import webbrowser
        urls = re.findall(r'(https?://[^\s]+)', message.text)
        if urls:
            valid_urls = [u for u in urls if u.lower().startswith(("http://", "https://"))]
            for url in valid_urls:
                webbrowser.open(url)
            
            if len(urls) == 1:
                await message.answer(f"🌐 Ссылка открыта в браузере:\n{urls[0]}", disable_web_page_preview=True)
            else:
                await message.answer(f"🌐 Открыто ссылок: {len(urls)}")
    except Exception as e:
        logger.error(f"Ошибка при открытии ссылки: {e}")
        await message.answer(f"Ошибка при открытии ссылки: {e}")
