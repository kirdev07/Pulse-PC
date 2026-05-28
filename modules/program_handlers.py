import os
import subprocess
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

from modules.keyboards import load_programs, get_launch_inline_keyboard, get_close_inline_keyboard
from modules.utils import safe_edit_text, kill_process

logger = logging.getLogger(__name__)
router = Router()

# Запуск программы
@router.callback_query(F.data.startswith("run_"))
async def callback_run_program(callback: CallbackQuery):
    idx = int(callback.data.split("_")[1])
    programs = load_programs()
    if idx < 0 or idx >= len(programs):
        await callback.answer("Программа не найдена в списке.", show_alert=True)
        return
        
    prog = programs[idx]
    name = prog.get("name")
    path = prog.get("path")
    process = prog.get("process")
    
    if not path:
        await callback.answer(f"Путь для {name} не настроен.", show_alert=True)
        return
        
    try:
        expanded_path = os.path.expandvars(path)
        try:
            os.startfile(expanded_path)
        except AttributeError:
            subprocess.Popen([expanded_path])
            
        await callback.answer(f"Запуск: {name}")
        
        # Создаем Inline-кнопку для моментального закрытия этой же программы
        builder = InlineKeyboardBuilder()
        if process:
            builder.row(InlineKeyboardButton(text=f"❌ Закрыть {name}", callback_data=f"killback_{idx}"))
        else:
            builder.row(InlineKeyboardButton(text="⏹️ Закрыть активное окно (Alt+F4)", callback_data="sys_close_active_and_back"))
            
        builder.row(
            InlineKeyboardButton(text="🚀 К списку программ", callback_data="menu_launch"),
            InlineKeyboardButton(text="◀️ Назад в меню", callback_data="menu_main")
        )
        
        await safe_edit_text(
            callback.message,
            f"🚀 <b>Программа {name} запущена!</b>\n\nВы можете закрыть её прямо сейчас с помощью кнопки ниже или вернуться в меню.",
            builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Ошибка при запуске {name} ({path}): {e}")
        await callback.answer(f"Ошибка запуска: {e}", show_alert=True)

# Закрытие программы
@router.callback_query(F.data.startswith("killproc_"))
async def callback_kill_program(callback: CallbackQuery):
    idx = int(callback.data.split("_")[1])
    programs = load_programs()
    if idx < 0 or idx >= len(programs):
        await callback.answer("Программа не найдена в списке.", show_alert=True)
        return
        
    prog = programs[idx]
    name = prog.get("name")
    process = prog.get("process")
    
    if not process:
        await callback.answer(f"Имя процесса для {name} не настроено.", show_alert=True)
        return
        
    try:
        success, error_msg = await kill_process(process)

        if success:
            await callback.answer(f"Процесс {process} завершен.")
            await safe_edit_text(
                callback.message,
                f"❌ <b>Закрытие программ</b>\n\nПроцесс <b>{process}</b> ({name}) успешно завершен!\n\nВыберите программу для закрытия:",
                get_close_inline_keyboard()
            )
        else:
            if "не найден" in error_msg.lower() or "not found" in error_msg.lower():
                await callback.answer(f"Процесс {process} не найден (возможно, уже закрыт).", show_alert=True)
            else:
                await callback.answer(f"Ошибка при закрытии {process}: {error_msg}", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при закрытии процесса {process}: {e}")
        await callback.answer(f"Ошибка при завершении процесса: {e}", show_alert=True)

# Быстрое закрытие программы сразу после запуска и возврат к списку
@router.callback_query(F.data.startswith("killback_"))
async def callback_kill_and_back(callback: CallbackQuery):
    idx = int(callback.data.split("_")[1])
    programs = load_programs()
    if idx < 0 or idx >= len(programs):
        await callback.answer("Программа не найдена в списке.", show_alert=True)
        return
        
    prog = programs[idx]
    name = prog.get("name")
    process = prog.get("process")
    
    if not process:
        await callback.answer(f"Имя процесса для {name} не настроено.", show_alert=True)
        return
        
    try:
        success, error_msg = await kill_process(process)
                
        if success:
            await callback.answer(f"Программа {name} закрыта.")
            await safe_edit_text(
                callback.message,
                f"🚀 <b>Запуск программ</b>\n\nПрограмма <b>{name}</b> была успешно закрыта.\n\nВыберите программу для запуска:",
                get_launch_inline_keyboard()
            )
        else:
            if "не найден" in error_msg.lower() or "not found" in error_msg.lower():
                await callback.answer(f"Процесс {process} не найден (возможно, уже закрыт).", show_alert=True)
            else:
                await callback.answer(f"Ошибка при закрытии {process}: {error_msg}", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при закрытии в kill_and_back: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)

# Закрытие активного окна сразу после запуска и возврат к списку
@router.callback_query(F.data == "sys_close_active_and_back")
async def callback_close_active_and_back(callback: CallbackQuery):
    try:
        import pyautogui
        pyautogui.hotkey('alt', 'f4')
        await callback.answer("Активное окно закрыто (Alt+F4)")
        await safe_edit_text(
            callback.message,
            "🚀 <b>Запуск программ</b>\n\nАктивное окно закрыто.\n\nВыберите программу для запуска:",
            get_launch_inline_keyboard()
        )
    except Exception as e:
        await callback.answer(f"Ошибка при закрытии окна: {e}", show_alert=True)

# Закрытие конкретного окна по hWnd
@router.callback_query(F.data.startswith("killhwnd_"))
async def callback_kill_hwnd(callback: CallbackQuery):
    try:
        hwnd = int(callback.data.split("_")[1])
        import win32gui
        import win32con
        
        # Отправляем окну команду на закрытие
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        await callback.answer("Сигнал на закрытие окна отправлен.")
        
        # Немного ждем, чтобы окно успело закрыться перед обновлением списка
        import asyncio
        await asyncio.sleep(0.5)
        
        await safe_edit_text(
            callback.message,
            "❌ <b>Закрытие программ</b>\n\nВыберите активное окно для закрытия:",
            get_close_inline_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка при закрытии окна по hWnd: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)
