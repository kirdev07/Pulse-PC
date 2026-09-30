import logging
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

import config

import time

logger = logging.getLogger(__name__)

user_last_activity = {}
THROTTLE_RATE = 0.5 # Ограничение в 0.5 секунд между действиями

# Middleware для проверки авторизации пользователей
class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data: dict):
        if not event.from_user:
            return await handler(event, data)
        
        user_id = event.from_user.id
        
        if not config.ADMIN_ID:
            logger.warning("⚠️ Попытка доступа, но ADMIN_ID не настроен в .env! Игнорируем запрос для безопасности.")
            if isinstance(event, CallbackQuery):
                await event.answer("Настройте ADMIN_ID в приложении!", show_alert=True)
                return
            
            if isinstance(event, Message):
                await event.answer(
                    f"⚠️ <b>В приложении не настроен ID администратора!</b>\n\n"
                    f"Ваш Telegram User ID: <code>{user_id}</code>\n\n"
                    f"Скопируйте этот ID и вставьте его в настройки программы Pulse PC, чтобы получить доступ к управлению.",
                    parse_mode="HTML"
                )
                return
            return            
        if user_id != config.ADMIN_ID:
            logger.warning(
                f"Неавторизованная попытка доступа от ID: {user_id} "
                f"(Username: @{event.from_user.username or 'unknown'})"
            )
            
            if isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ ограничен!", show_alert=True)
                return
            
            if isinstance(event, Message):
                await event.answer(
                    f"⛔ <b>Доступ ограничен!</b>\n\n"
                    f"Ваш Telegram User ID: <code>{user_id}</code>\n"
                    f"Для управления компьютером укажите этот ID в настройках программы.",
                    parse_mode="HTML"
                )
                return
            return
            
        import modules.monitor as monitor_module
        text = (event.text or "") if isinstance(event, Message) else ""
        command = text.split()[0].split("@")[0].lower() if text.split() else ""
        allowed_when_locked = (isinstance(event, Message) and (command in ("/help", "/cancel") or text == "📖 Помощь")) or (
            isinstance(event, CallbackQuery) and (event.data in ("power_cancel", "menu_help") or (event.data or "").startswith("help:")))
        if monitor_module.pc_is_locked and not allowed_when_locked:
            if isinstance(event, CallbackQuery):
                await event.answer("⛔ ПК заблокирован. Управление недоступно.", show_alert=True)
                return
            if isinstance(event, Message):
                await event.answer("⛔ <b>ПК заблокирован.</b>\n\nВ данный момент управление через Telegram недоступно.", parse_mode="HTML")
                return
            return
            
        current_time = time.time()
        last_time = user_last_activity.get(user_id, 0)
        if current_time - last_time < THROTTLE_RATE:
            if isinstance(event, CallbackQuery):
                await event.answer("⚠️ Не так быстро!", show_alert=False)
            return
            
        user_last_activity[user_id] = current_time
        
        return await handler(event, data)
