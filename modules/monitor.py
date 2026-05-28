import asyncio
import ctypes
import logging

from aiogram import Bot
import config

logger = logging.getLogger(__name__)

pc_is_locked = False

async def lock_monitor(bot: Bot):
    global pc_is_locked
    
    user32 = ctypes.windll.user32
    was_locked = False
    
    while True:
        try:
            is_locked = True
            
            # Check if workstation is unlocked
            hDesktop = user32.OpenInputDesktop(0, False, 0x0100) # DESKTOP_READOBJECTS
            if hDesktop:
                name_buffer = ctypes.create_unicode_buffer(256)
                length = ctypes.c_ulong(0)
                res = user32.GetUserObjectInformationW(hDesktop, 2, name_buffer, 512, ctypes.byref(length))
                user32.CloseDesktop(hDesktop)
                
                if res and name_buffer.value.lower() == "default":
                    is_locked = False
            
            if is_locked and not was_locked:
                was_locked = True
                pc_is_locked = True
                if config.ADMIN_ID:
                    try:
                        await bot.send_message(
                            chat_id=config.ADMIN_ID,
                            text="🔒 <b>Внимание!</b>\n\nКомпьютер был заблокирован.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
            elif not is_locked and was_locked:
                was_locked = False
                pc_is_locked = False
                if config.ADMIN_ID:
                    try:
                        await bot.send_message(
                            chat_id=config.ADMIN_ID,
                            text="🔓 <b>Внимание!</b>\n\nКомпьютер был разблокирован.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                    
        except Exception as e:
            logger.error(f"Ошибка в мониторе блокировки: {e}")
        await asyncio.sleep(2)
