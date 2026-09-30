"""Administrator-only file requests and computer information (AuthMiddleware)."""
import asyncio
import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery
from desktop_services import computer_info, send_file, telegram_error

router = Router()
logger = logging.getLogger(__name__)
FILE_PROMPT = "Укажите полный путь к файлу на ПК"


@router.message(Command("status"))
async def status_command(message: Message):
    try:
        await message.answer(await asyncio.to_thread(computer_info))
    except Exception as exc:
        logger.exception("Ошибка получения информации о ПК")
        await message.answer("Не удалось получить информацию о ПК: " + str(exc))


@router.callback_query(F.data == "sys_info")
async def status_callback(callback: CallbackQuery):
    await callback.answer()
    await status_command(callback.message)


async def deliver_file(message, bot, path):
    try:
        # Only return files to the requesting administrator's private chat.
        import config
        await send_file(bot, config.ADMIN_ID, path)
        await message.answer("Файл отправлен в личный чат с ботом.")
        logger.info("Файл с ПК отправлен администратору")
    except Exception as exc:
        logger.warning("Ошибка отправки файла: %s", telegram_error(exc))
        await message.answer("Не удалось отправить файл: " + telegram_error(exc))


@router.message(Command("getfile"))
async def getfile_command(message: Message, bot: Bot, command: CommandObject):
    if not command.args:
        await message.answer(FILE_PROMPT + ": /getfile C:\\папка\\файл.pdf")
        return
    await deliver_file(message, bot, command.args)


@router.message(F.reply_to_message.from_user.is_bot & F.reply_to_message.text.startswith(FILE_PROMPT))
async def getfile_reply(message: Message, bot: Bot):
    if message.reply_to_message.from_user.id != bot.id:
        return
    await deliver_file(message, bot, message.text or "")
