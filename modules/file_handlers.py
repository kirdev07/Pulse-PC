import os
import webbrowser
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
import config
from modules.keyboards import get_main_inline_keyboard

logger = logging.getLogger(__name__)
router = Router()

# Ensure files folder exists in the executable's directory
FILES_DIR = os.path.join(config.APP_DIR, "files")
os.makedirs(FILES_DIR, exist_ok=True)

@router.message(F.text)
@router.edited_message(F.text)
async def handle_url(message: Message):
    urls = []
    if message.entities:
        for entity in message.entities:
            if entity.type == "url":
                # Extract URL from text using entity offset and length
                url = message.text[entity.offset:entity.offset + entity.length]
                urls.append(url)
            elif entity.type == "text_link":
                urls.append(entity.url)
                
    if urls:
        try:
            valid_urls = [u for u in urls if u.lower().startswith(("http://", "https://"))]
            for url in valid_urls:
                webbrowser.open(url)
            
            if len(urls) == 1:
                await message.answer("🌐 Ссылка успешно открыта в браузере.")
            else:
                await message.answer(f"🌐 Успешно открыто ссылок: {len(urls)}.")
        except Exception as e:
            await message.answer(f"Ошибка при открытии ссылки: {e}")
            logger.error(f"Error opening URL: {e}")

@router.message(F.document | F.photo | F.video | F.audio | F.voice | F.animation)
@router.edited_message(F.document | F.photo | F.video | F.audio | F.voice | F.animation)
async def handle_media_files(message: Message, bot: Bot):
    try:
        file_id = None
        file_name = None
        file_size = None
        
        if message.document:
            file_id = message.document.file_id
            file_name = message.document.file_name
            file_size = message.document.file_size
        elif message.photo:
            file_id = message.photo[-1].file_id
            file_name = f"photo_{file_id[:8]}.jpg"
            file_size = message.photo[-1].file_size
        elif message.video:
            file_id = message.video.file_id
            file_name = message.video.file_name or f"video_{file_id[:8]}.mp4"
            file_size = message.video.file_size
        elif message.audio:
            file_id = message.audio.file_id
            file_name = message.audio.file_name or f"audio_{file_id[:8]}.mp3"
            file_size = message.audio.file_size
        elif message.voice:
            file_id = message.voice.file_id
            file_name = f"voice_{file_id[:8]}.ogg"
            file_size = message.voice.file_size
        elif message.animation:
            file_id = message.animation.file_id
            file_name = message.animation.file_name or f"animation_{file_id[:8]}.mp4"
            file_size = message.animation.file_size
            
        if not file_id:
            return
            
        MAX_SIZE_MB = 20
        if file_size and file_size > MAX_SIZE_MB * 1024 * 1024:
            await message.answer(f"❌ Файл <b>{file_name or 'unknown'}</b> слишком большой ({(file_size/1024/1024):.1f} MB).\n\nМаксимальный допустимый размер для загрузки бота: {MAX_SIZE_MB} MB.", parse_mode="HTML")
            return
            
        if not file_name:
            file_name = f"unknown_{file_id[:8]}"

        file = await bot.get_file(file_id)
        file_path = os.path.join(FILES_DIR, file_name)
        await bot.download_file(file.file_path, file_path)
        
        await message.answer(f"✅ Файл <b>{file_name}</b> успешно сохранен.", parse_mode="HTML")
        
        # Также проверяем ссылки в подписи к медиа (caption)
        urls = []
        if message.caption_entities and message.caption:
            for entity in message.caption_entities:
                if entity.type == "url":
                    url = message.caption[entity.offset:entity.offset + entity.length]
                    urls.append(url)
                elif entity.type == "text_link":
                    urls.append(entity.url)
                    
        if urls:
            valid_urls = [u for u in urls if u.lower().startswith(("http://", "https://"))]
            for url in valid_urls:
                webbrowser.open(url)
            if len(urls) == 1:
                await message.answer("🌐 Ссылка из подписи успешно открыта в браузере.")
            else:
                await message.answer(f"🌐 Успешно открыто ссылок из подписи: {len(urls)}.")
                
    except Exception as e:
        await message.answer(f"Ошибка при сохранении файла: {e}")
        logger.error(f"Error saving file: {e}")

@router.callback_query(F.data == "sys_clear_files")
async def callback_clear_files(callback: CallbackQuery):
    try:
        if os.path.exists(FILES_DIR):
            deleted = 0
            for filename in os.listdir(FILES_DIR):
                file_path = os.path.join(FILES_DIR, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    deleted += 1
            await callback.answer(f"🧹 Удалено файлов: {deleted}", show_alert=True)
        else:
            await callback.answer("📂 Папка файлов не найдена", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при очистке файлов: {e}")
        await callback.answer(f"Ошибка при удалении: {e}", show_alert=True)
