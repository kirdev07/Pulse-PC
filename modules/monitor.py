import asyncio
import ctypes
from ctypes import wintypes
import logging
import config

logger = logging.getLogger(__name__)
pc_is_locked = False


def workstation_locked():
    user32 = ctypes.windll.user32
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    desktop = user32.OpenInputDesktop(0, False, 1)
    if not desktop:
        return True
    try:
        name = ctypes.create_unicode_buffer(256)
        length = wintypes.DWORD()
        ok = user32.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(length))
        return not (ok and name.value.lower() == "default")
    finally:
        user32.CloseDesktop(desktop)


async def lock_monitor(bot):
    global pc_is_locked
    previous = None
    notification = None

    async def notify(locked):
        try:
            await bot.send_message(chat_id=config.ADMIN_ID,
                text="🔒 Компьютер был заблокирован." if locked else "🔓 Компьютер был разблокирован.",
                request_timeout=5)
        except Exception as exc:
            logger.warning("Не удалось отправить состояние блокировки: %s", exc)

    try:
        while True:
            try:
                locked = workstation_locked()
                pc_is_locked = locked
                if locked != previous and (previous is not None or locked):
                    from modules import notify_bus
                    notify_bus.push("Pulse PC", "Компьютер заблокирован." if locked else "Компьютер разблокирован.")
                if locked != previous and config.ADMIN_ID and (previous is not None or locked):
                    if notification:
                        notification.cancel()
                        await asyncio.gather(notification, return_exceptions=True)
                    notification = asyncio.create_task(notify(locked))
                previous = locked
            except Exception as exc:
                pc_is_locked = True
                logger.error("Ошибка в мониторе блокировки: %s", exc)
            await asyncio.sleep(2)
    finally:
        if notification:
            notification.cancel()
            await asyncio.gather(notification, return_exceptions=True)
