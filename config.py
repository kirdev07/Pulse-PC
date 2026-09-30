import os
import sys
from dotenv import load_dotenv

# Определяем базовую директорию проекта
if getattr(sys, 'frozen', False):
    # Если запущено как скомпилированный EXE через PyInstaller
    APP_DIR = os.path.dirname(sys.executable)
else:
    # При обычном запуске
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_DIR = os.path.join(APP_DIR, "config")
os.makedirs(CONFIG_DIR, exist_ok=True)

# Для обратной совместимости, BASE_DIR теперь указывает на config
BASE_DIR = CONFIG_DIR

# Загружаем переменные из файла .env в директории config
env_path = os.path.join(CONFIG_DIR, ".env")
if not os.path.exists(env_path):
    with open(env_path, "w") as f:
        f.write("BOT_TOKEN=your_telegram_bot_token_here\nADMIN_ID=\n")

load_dotenv(dotenv_path=env_path, override=True)

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN", "your_telegram_bot_token_here")

# ID администратора (один человек)
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "")
ADMIN_ID = None

if ADMIN_ID_RAW.strip() and ADMIN_ID_RAW.strip().isdigit():
    ADMIN_ID = int(ADMIN_ID_RAW.strip())

# Путь к файлу конфигурации программ
PROGRAMS_FILE_PATH = os.path.join(CONFIG_DIR, "programs.json")
