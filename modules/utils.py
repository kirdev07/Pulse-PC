import logging
from aiogram.types import Message, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)

# Безопасное изменение текста сообщения (игнорируем ошибку, если текст не изменился)
async def safe_edit_text(message: Message, text: str, reply_markup: InlineKeyboardMarkup = None):
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"Ошибка при редактировании сообщения: {e}")

import os
import time
import config

def cleanup_old_files(days=3):
    """Удаляет файлы старше `days` дней из папки files."""
    try:
        files_dir = os.path.join(config.APP_DIR, "files")
        if not os.path.exists(files_dir):
            return
            
        current_time = time.time()
        age_seconds = days * 24 * 60 * 60
        
        deleted_count = 0
        for filename in os.listdir(files_dir):
            filepath = os.path.join(files_dir, filename)
            if os.path.isfile(filepath):
                file_age = current_time - os.path.getmtime(filepath)
                if file_age > age_seconds:
                    os.remove(filepath)
                    deleted_count += 1
                    
        if deleted_count > 0:
            logger.info(f"Очистка: удалено {deleted_count} старых файлов из папки files.")
    except Exception as e:
        logger.error(f"Ошибка при очистке старых файлов: {e}")

def should_send_startup_notification() -> bool:
    state_file = os.path.join(config.BASE_DIR, "last_start.txt")
    current_time = time.time()
    
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                last_time = float(f.read().strip())
            if current_time - last_time < 300:  # 5 минут коулдауна
                logger.info("Уведомление о запуске пропущено (коулдаун 5 минут).")
                return False
        except Exception:
            pass
            
    try:
        with open(state_file, "w") as f:
            f.write(str(current_time))
    except Exception as e:
        logger.error(f"Не удалось записать время запуска в last_start.txt: {e}")
        
    return True
import asyncio

import psutil

async def kill_process(process_name: str) -> tuple[bool, str]:
    """Убивает процесс по его имени. Возвращает (успех, сообщение_об_ошибке)."""
    try:
        process_name_lower = process_name.lower().strip()
        if not process_name_lower.endswith(".exe"):
            process_name_exe = process_name_lower + ".exe"
        else:
            process_name_exe = process_name_lower
            
        def _kill():
            killed = False
            for proc in psutil.process_iter(['name']):
                try:
                    p_name = proc.info['name']
                    if p_name and (p_name.lower() == process_name_lower or p_name.lower() == process_name_exe):
                        proc.kill()
                        killed = True
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            return killed
            
        killed_any = await asyncio.to_thread(_kill)
        
        if killed_any:
            return True, ""
            
        # Fallback to taskkill
        proc = await asyncio.create_subprocess_exec(
            "taskkill", "/f", "/im", process_name_exe,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode == 0:
            return True, ""
            
        return False, "Процесс не найден или нет прав на его завершение."
    except Exception as e:
        return False, str(e)
