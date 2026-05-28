import logging
import pyautogui
from aiogram import Router, F
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)
router = Router()

# Мультимедиа: Предыдущий трек
@router.callback_query(F.data == "media_prev")
async def callback_media_prev(callback: CallbackQuery):
    try:
        pyautogui.press('prevtrack')
        await callback.answer("⏮️ Предыдущий трек")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

# Мультимедиа: Плей / Пауза
@router.callback_query(F.data == "media_play")
async def callback_media_play(callback: CallbackQuery):
    try:
        pyautogui.press('playpause')
        await callback.answer("⏯️ Воспроизведение / Пауза")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

# Мультимедиа: Следующий трек
@router.callback_query(F.data == "media_next")
async def callback_media_next(callback: CallbackQuery):
    try:
        pyautogui.press('nexttrack')
        await callback.answer("⏭️ Следующий трек")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

# Мультимедиа: Громкость тише
@router.callback_query(F.data == "media_voldown")
async def callback_media_voldown(callback: CallbackQuery):
    try:
        pyautogui.press('volumedown')
        await callback.answer("🔉 Звук тише (-2%)")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

# Мультимедиа: Выключение звука
@router.callback_query(F.data == "media_mute")
async def callback_media_mute(callback: CallbackQuery):
    try:
        pyautogui.press('volumemute')
        await callback.answer("🔇 Вкл/Выкл звук")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

# Мультимедиа: Громкость громче
@router.callback_query(F.data == "media_volumeup")
async def callback_media_volumeup(callback: CallbackQuery):
    try:
        pyautogui.press('volumeup')
        await callback.answer("🔊 Звук громче (+2%)")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

