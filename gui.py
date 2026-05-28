import os
import sys
import json
import asyncio
import threading
import logging
import importlib
import winreg
from tkinter import filedialog, messagebox, Menu as TkMenu
import customtkinter as ctk
from PIL import Image, ImageTk
import pystray
from pystray import MenuItem as item, Menu
import webbrowser
import ctypes

# Настройка системного пути
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import config
from aiogram import Bot, Dispatcher
from modules.system_handlers import router as system_router
from modules.media_handlers import router as media_router
from modules.program_handlers import router as program_router
from modules.file_handlers import router as file_router
from modules.middleware import AuthMiddleware
from modules.keyboards import get_reply_keyboard, get_main_inline_keyboard
from modules.monitor import lock_monitor
from modules.utils import should_send_startup_notification

# =====================================================================
# ЦВЕТОВАЯ ПАЛИТРА BLACK & WHITE MINIMALIST THEME (KIRO BOT STYLE)
# =====================================================================
M3_BG = "#000000"                  # Чисто черный фон приложения
M3_SURFACE_LOW = "#000000"         # Фон бокового меню (Черный)
M3_CARD_BG = "#161616"             # Темно-серый фон карточек (под Kiro Bot)
M3_INPUT_BG = "#090909"            # Фон полей ввода
M3_BORDER = "#1f1f1f"              # Ненавязчивая темно-серая обводка (border)
M3_SURFACE_HIGH = "#121212"        # Ховер кнопок навигации (Темно-серый)
M3_PRIMARY = "#ffffff"             # Белые кнопки и активные элементы
M3_ON_PRIMARY = "#000000"          # Черный текст на белых кнопках
M3_TEXT = "#ffffff"                # Чисто белый текст
M3_TEXT_MUTED = "#888888"          # Серый текст

# Установка базовой темы CustomTkinter
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Блокировка повторного запуска GUI
try:
    import msvcrt
    has_msvcrt = True
except ImportError:
    has_msvcrt = False

gui_lock_file = None
bot_lock_file = None
def acquire_gui_lock() -> bool:
    global gui_lock_file, bot_lock_file
    if not has_msvcrt:
        return True
    lock_path = os.path.join(config.BASE_DIR, "gui.lock")
    bot_lock_path = os.path.join(config.BASE_DIR, "bot.lock")
    try:
        gui_lock_file = open(lock_path, "w")
        msvcrt.locking(gui_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        
        bot_lock_file = open(bot_lock_path, "w")
        msvcrt.locking(bot_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except (IOError, OSError):
        return False

# Кастомный обработчик логирования для вывода в текстовое поле GUI
class GuiLogHandler(logging.Handler):
    def __init__(self, textbox, append_callback):
        super().__init__()
        self.textbox = textbox
        self.append_callback = append_callback
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S'))

    def emit(self, record):
        msg = self.format(record)
        def append():
            try:
                self.append_callback(msg + "\n")
            except Exception:
                pass
        self.textbox.after(0, append)

# Класс для фонового запуска бота в asyncio loop
class BotRunner:
    def __init__(self, log_callback, status_callback, restart_callback, quit_callback):
        self.log_callback = log_callback
        self.status_callback = status_callback
        self.restart_callback = restart_callback
        self.quit_callback = quit_callback
        self.loop = None
        self.thread = None
        self.bot = None
        self.dp = None
        self.is_running = False

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.status_callback("RUNNING")
        
        exit_code = None
        try:
            self.loop.run_until_complete(self._main_async())
        except SystemExit as se:
            exit_code = se.code
        except Exception as e:
            self.log_callback(f"Ошибка в работе бота: {e}\n")
        finally:
            self.status_callback("STOPPED")
            self.is_running = False
            
            # Обработка команд завершения от Telegram
            if exit_code == 42:
                self.log_callback("Получен запрос на перезапуск бота из Telegram. Перезапускаю...\n")
                self.restart_callback()
            elif exit_code == 0:
                self.log_callback("Получен запрос на выключение бота из Telegram. Завершаю работу...\n")
                self.quit_callback()

    async def _main_async(self):
        # Перезагружаем конфигурацию, чтобы обновить переменные из .env
        importlib.reload(config)
        
        # Перезагружаем модули маршрутизаторов, чтобы создать новые экземпляры Router (избегает ошибки Router is already attached)
        import modules.system_handlers
        import modules.media_handlers
        import modules.program_handlers
        import modules.file_handlers
        import modules.middleware
        
        importlib.reload(modules.system_handlers)
        importlib.reload(modules.media_handlers)
        importlib.reload(modules.program_handlers)
        importlib.reload(modules.file_handlers)
        importlib.reload(modules.middleware)
        

        
        if not config.BOT_TOKEN or config.BOT_TOKEN == "your_telegram_bot_token_here" or not config.BOT_TOKEN.strip():
            self.log_callback("Критическая ошибка: Токен бота не настроен в .env!\n")
            raise Exception("Токен бота не настроен!")

        if not config.ADMIN_ID:
            self.log_callback("Предупреждение: ADMIN_ID пуст! Бот не примет команды.\n")

        self.bot = Bot(token=config.BOT_TOKEN)
        self.dp = Dispatcher()
        
        # Подключаем Middleware и маршрутизаторы
        self.dp.message.middleware(AuthMiddleware())
        self.dp.edited_message.middleware(AuthMiddleware())
        self.dp.callback_query.middleware(AuthMiddleware())
        self.dp.include_router(system_router)
        self.dp.include_router(media_router)
        self.dp.include_router(program_router)
        self.dp.include_router(file_router)
        
        # Очистка старых файлов при запуске
        try:
            from modules.utils import cleanup_old_files
            cleanup_old_files(days=3)
        except Exception as e:
            self.log_callback(f"Ошибка при очистке файлов: {e}\n")
        
        self.log_callback("Запуск опроса бота (aiogram polling)...\n")
        
        # Отправка уведомления о запуске (с защитой от спама)
        if should_send_startup_notification():
            if config.ADMIN_ID:
                try:
                    await self.bot.send_message(
                        chat_id=config.ADMIN_ID,
                        text="💻 <b>Компьютер успешно запущен!</b>\n\nPulse PC готов к работе.",
                        reply_markup=get_reply_keyboard(),
                        parse_mode="HTML"
                    )
                    await self.bot.send_message(
                        chat_id=config.ADMIN_ID,
                        text="🖥️ <b>Панель управления ПК</b>\n\nВыберите категорию:",
                        reply_markup=get_main_inline_keyboard(),
                        parse_mode="HTML"
                    )
                except Exception as e:
                    self.log_callback(f"Не удалось отправить уведомление о старте пользователю {config.ADMIN_ID}: {e}\n")

        try:
            self.lock_task = asyncio.create_task(lock_monitor(self.bot))
            await self.dp.start_polling(self.bot)
        finally:
            try:
                await self.bot.session.close()
            except Exception:
                pass

    def stop(self):
        if not self.is_running or not self.loop:
            return
        self.log_callback("Запрос на остановку бота...\n")
        
        async def shutdown():
            if self.dp:
                await self.dp.stop_polling()
            if self.bot:
                await self.bot.session.close()
                
        asyncio.run_coroutine_threadsafe(shutdown(), self.loop)

# Главный класс приложения GUI
class PulsePCApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Pulse PC [Остановлен]")
        self.geometry("950x650")
        self.resizable(False, False)
        self.configure(fg_color=M3_BG)
        
        # Пути к иконкам (читаем из папки image рядом с exe)
        self.icon_path = os.path.join(config.APP_DIR, "image", "icon.ico")
        self.icon_png_path = os.path.join(config.APP_DIR, "image", "icon.png")
        if os.path.exists(self.icon_path):
            try:
                self.iconbitmap(self.icon_path)
            except Exception:
                pass
            
        # Применение чисто черного заголовка окна
        self.after(10, self.apply_dark_titlebar)
            
        self.bot_runner = BotRunner(self.write_log, self.update_bot_status, self.restart_bot, self.quit_app)
        self.tray_icon = None
        self.tray_thread = None
        self.is_quitting = False
        
        # Загружаем временный список программ в память
        self.temp_programs = self.load_programs_list()
        
        self.content_frames = {}
        self.nav_buttons = {}
        
        self.setup_ui()
        self.setup_tray()
        
        # Подгружаем настройки на экран
        self.load_settings_to_ui()
        self.refresh_programs_list()
        
        # Перехват логов с передачей метода цветного логирования
        gui_log_handler = GuiLogHandler(self.textbox_logs, self.append_colored_log)
        logging.getLogger().addHandler(gui_log_handler)
        
        self.protocol("WM_DELETE_WINDOW", self.on_close_event)
        
        # Поддержка запуска в свернутом виде (для автозагрузки)
        if "--minimized" in sys.argv or "-m" in sys.argv:
            self.withdraw()
            self.write_log("Запущено в свернутом режиме (в трее).\n")
            
        # Автозапуск бота при старте приложения
        self.after(500, self.auto_start_bot_on_launch)

    def apply_dark_titlebar(self):
        try:
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            if hwnd:
                # Включаем темный режим (DWMWA_USE_IMMERSIVE_DARK_MODE = 20)
                rendering = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(rendering), ctypes.sizeof(rendering))
                
                # Устанавливаем черный цвет заголовка (DWMWA_CAPTION_COLOR = 35)
                color = ctypes.c_int(0x00000000) # Черный (BGR формат)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))
                
                # Устанавливаем белый цвет текста (DWMWA_TEXT_COLOR = 36)
                text_color = ctypes.c_int(0x00FFFFFF) # Белый
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text_color), ctypes.sizeof(text_color))
        except Exception:
            pass

    def add_context_menu(self, widget):
        menu = TkMenu(self, tearoff=0, bg=M3_CARD_BG, fg=M3_TEXT, activebackground=M3_PRIMARY, activeforeground=M3_ON_PRIMARY, bd=0)
        menu.add_command(label="Копировать", command=lambda: widget.focus() or (widget._entry.event_generate("<<Copy>>") if hasattr(widget, "_entry") else None))
        menu.add_command(label="Вставить", command=lambda: widget.focus() or (widget._entry.event_generate("<<Paste>>") if hasattr(widget, "_entry") else None))
        menu.add_command(label="Вырезать", command=lambda: widget.focus() or (widget._entry.event_generate("<<Cut>>") if hasattr(widget, "_entry") else None))
        
        def select_all(event=None):
            widget.focus()
            if hasattr(widget, '_entry'):
                widget._entry.select_range(0, 'end')
                widget._entry.icursor('end')
            return "break"
                
        menu.add_command(label="Выделить всё", command=select_all)
        
        def show_menu(event):
            widget.focus()
            menu.tk_popup(event.x_root, event.y_root)
            
        def _paste(event=None):
            if hasattr(widget, '_entry'):
                widget._entry.event_generate("<<Paste>>")
            return "break"
            
        def _copy(event=None):
            if hasattr(widget, '_entry'):
                widget._entry.event_generate("<<Copy>>")
            return "break"
            
        def _cut(event=None):
            if hasattr(widget, '_entry'):
                widget._entry.event_generate("<<Cut>>")
            return "break"
            
        target = widget._entry if hasattr(widget, "_entry") else widget
        target.bind("<Button-3>", show_menu)
        
        # Поддержка горячих клавиш (независимо от раскладки на Windows)
        def handle_ctrl_keys(e):
            if e.keycode == 86: # V
                _paste()
            elif e.keycode == 67: # C
                _copy()
            elif e.keycode == 88: # X
                _cut()
            elif e.keycode == 65: # A
                select_all()
                
        target.bind("<Control-KeyPress>", handle_ctrl_keys)

    def setup_ui(self):
        # -------------------------------------------------------------
        # Боковая панель навигации (Navigation Rail) в стиле B&W
        # -------------------------------------------------------------
        self.frame_rail = ctk.CTkFrame(
            self, width=200, fg_color=M3_SURFACE_LOW, 
            border_color=M3_BORDER, border_width=0, corner_radius=0
        )
        self.frame_rail.pack(side="left", fill="y")
        self.frame_rail.pack_propagate(False)
        
        # Заголовок приложения
        self.lbl_logo = ctk.CTkLabel(
            self.frame_rail, 
            text="Pulse PC", 
            text_color=M3_PRIMARY, 
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold")
        )
        self.lbl_logo.pack(padx=15, pady=(30, 5))
        
        self.lbl_version = ctk.CTkLabel(
            self.frame_rail, 
            text="Версия 2.0", 
            text_color=M3_TEXT_MUTED, 
            font=ctk.CTkFont(family="Segoe UI", size=11, slant="italic")
        )
        self.lbl_version.pack(padx=15, pady=(0, 2))
        
        self.lbl_author = ctk.CTkLabel(
            self.frame_rail, 
            text="KirDev", 
            text_color=M3_TEXT_MUTED, 
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold")
        )
        self.lbl_author.pack(padx=15, pady=(0, 20))
        
        # Навигационные кнопки
        self.btn_nav_home = ctk.CTkButton(
            self.frame_rail, text="🏠  Главная", height=45, corner_radius=22,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            command=lambda: self.switch_tab("home")
        )
        self.btn_nav_home.pack(fill="x", padx=12, pady=8)
        self.nav_buttons["home"] = self.btn_nav_home

        self.btn_nav_settings = ctk.CTkButton(
            self.frame_rail, text="⚙️  Настройки", height=45, corner_radius=22,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            command=lambda: self.switch_tab("settings")
        )
        self.btn_nav_settings.pack(fill="x", padx=12, pady=8)
        self.nav_buttons["settings"] = self.btn_nav_settings
        
        self.btn_nav_programs = ctk.CTkButton(
            self.frame_rail, text="🚀  Программы", height=45, corner_radius=22,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            command=lambda: self.switch_tab("programs")
        )
        self.btn_nav_programs.pack(fill="x", padx=12, pady=8)
        self.nav_buttons["programs"] = self.btn_nav_programs
        
        self.btn_nav_logs = ctk.CTkButton(
            self.frame_rail, text="📊  Консоль логов", height=45, corner_radius=22,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            command=lambda: self.switch_tab("logs")
        )
        self.btn_nav_logs.pack(fill="x", padx=12, pady=8)
        self.nav_buttons["logs"] = self.btn_nav_logs
        
        # Соцсети внизу боковой панели
        self.frame_socials = ctk.CTkFrame(self.frame_rail, fg_color="transparent")
        self.frame_socials.pack(side="bottom", fill="x", pady=20)
        
        self.lbl_socials_title = ctk.CTkLabel(
            self.frame_socials, text="Наши соц. сети:", 
            text_color=M3_TEXT_MUTED,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold")
        )
        self.lbl_socials_title.pack(pady=(0, 5))
        
        self.btn_vk = ctk.CTkButton(
            self.frame_socials, text="VK", 
            fg_color="#2787F5", text_color="#ffffff",
            hover_color="#2274d6",
            width=70, height=28, corner_radius=14,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            command=lambda: webbrowser.open("https://vk.com/kirdev_07")
        )
        self.btn_vk.pack(side="left", expand=True, padx=5)
        
        self.btn_tg = ctk.CTkButton(
            self.frame_socials, text="Telegram", 
            fg_color="#24A1DE", text_color="#ffffff",
            hover_color="#1f8bbf",
            width=85, height=28, corner_radius=14,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            command=lambda: webbrowser.open("https://web.telegram.org/k/#@kirdev_studio")
        )
        self.btn_tg.pack(side="right", expand=True, padx=5)
        
        # -------------------------------------------------------------
        # Правая основная область контента
        # -------------------------------------------------------------
        self.frame_content = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_content.pack(side="right", fill="both", expand=True)
        
        # --- Вкладка Главная ---
        self.frame_home = ctk.CTkFrame(self.frame_content, fg_color="transparent")
        self.content_frames["home"] = self.frame_home
        
        # Название бота и статус
        self.lbl_home_title = ctk.CTkLabel(
            self.frame_home, text="Pulse PC", 
            text_color=M3_TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold")
        )
        self.lbl_home_title.pack(pady=(20, 10))
        
        # Индикатор статуса (капсула)
        self.frame_status_badge = ctk.CTkFrame(
            self.frame_home, fg_color=M3_CARD_BG, corner_radius=16, height=32, border_width=1, border_color=M3_BORDER
        )
        self.frame_status_badge.pack(pady=(0, 20))
        self.frame_status_badge.pack_propagate(False)
        self.frame_status_badge.configure(width=160)
        
        self.label_status_indicator = ctk.CTkLabel(
            self.frame_status_badge, text="🔴 Бот выключен", 
            text_color="#FF5252",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        )
        self.label_status_indicator.place(relx=0.5, rely=0.5, anchor="center")
        
        # Кнопка Запустить / Остановить
        self.btn_toggle_bot_large = ctk.CTkButton(
            self.frame_home, text="Запустить", 
            fg_color="#28a745", 
            text_color="#ffffff",
            hover_color="#218838",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            width=200, height=45, corner_radius=22,
            command=self.toggle_bot_state
        )
        self.btn_toggle_bot_large.pack(pady=(0, 25))
        
        # Разделитель
        self.frame_divider = ctk.CTkFrame(self.frame_home, height=1, fg_color=M3_BORDER)
        self.frame_divider.pack(fill="x", padx=40, pady=(5, 15))
        
        # Заголовок возможностей
        self.lbl_features_header = ctk.CTkLabel(
            self.frame_home, text="Возможности системы", 
            text_color=M3_TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold")
        )
        self.lbl_features_header.pack(anchor="w", padx=40, pady=(0, 10))
        
        # Сетка возможностей
        self.frame_features_grid = ctk.CTkFrame(self.frame_home, fg_color="transparent")
        self.frame_features_grid.pack(fill="both", expand=True, padx=35)
        self.frame_features_grid.columnconfigure(0, weight=1)
        self.frame_features_grid.columnconfigure(1, weight=1)
        
        def create_feature_card(parent, row, col, icon, title, desc):
            card = ctk.CTkFrame(parent, fg_color=M3_CARD_BG, corner_radius=12, border_width=1, border_color=M3_BORDER)
            card.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
            
            lbl_icon = ctk.CTkLabel(card, text=icon, font=ctk.CTkFont(family="Segoe UI", size=24))
            lbl_icon.pack(anchor="w", padx=15, pady=(12, 0))
            
            lbl_title = ctk.CTkLabel(card, text=title, text_color=M3_TEXT, font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"))
            lbl_title.pack(anchor="w", padx=15, pady=(2, 0))
            
            lbl_desc = ctk.CTkLabel(card, text=desc, text_color=M3_TEXT_MUTED, font=ctk.CTkFont(family="Segoe UI", size=11), justify="left")
            lbl_desc.pack(anchor="w", padx=15, pady=(2, 12))
        
        create_feature_card(self.frame_features_grid, 0, 0, "🚀", "Запуск программ", "Удаленный запуск и закрытие любых программ на ПК.")
        create_feature_card(self.frame_features_grid, 0, 1, "⚡", "Управление питанием", "Выключение, перезагрузка, сон или блокировка.")
        create_feature_card(self.frame_features_grid, 1, 0, "📸", "Скриншоты экрана", "Получение снимков рабочего стола в любой момент.")
        create_feature_card(self.frame_features_grid, 1, 1, "🔔", "Фоновый режим", "Бот работает 24/7 и присылает уведомления.")
        
        # --- Вкладка Настройки ---
        self.frame_settings = ctk.CTkFrame(self.frame_content, fg_color="transparent")
        self.content_frames["settings"] = self.frame_settings
        
        # Шапка Settings
        self.frame_settings_header = ctk.CTkFrame(self.frame_settings, fg_color="transparent", height=40)
        self.frame_settings_header.pack(fill="x", pady=(0, 10))
        self.frame_settings_header.pack_propagate(False)
        
        self.lbl_settings_header_title = ctk.CTkLabel(
            self.frame_settings_header, text="⚙️   Настройки параметров", 
            text_color=M3_TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold")
        )
        self.lbl_settings_header_title.pack(side="left", padx=5)
        
        # Карточка для настроек
        self.frame_settings_card = ctk.CTkFrame(
            self.frame_settings, fg_color=M3_CARD_BG,
            border_color=M3_BORDER, border_width=1,
            corner_radius=12
        )
        self.frame_settings_card.pack(fill="x", padx=10, pady=10)
        
        self.label_token = ctk.CTkLabel(
            self.frame_settings_card, text="Telegram Bot Token (Получить через @BotFather):", 
            text_color=M3_TEXT, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        )
        self.label_token.pack(anchor="w", padx=15, pady=(15, 5))
        
        self.entry_token = ctk.CTkEntry(
            self.frame_settings_card, fg_color=M3_INPUT_BG, border_color=M3_BORDER,
            text_color=M3_TEXT, placeholder_text_color=M3_TEXT_MUTED, corner_radius=8, height=35
        )
        self.entry_token.pack(fill="x", padx=15, pady=(0, 15))
        self.add_context_menu(self.entry_token)
        
        self.label_users = ctk.CTkLabel(
            self.frame_settings_card, text="Ваш Telegram ID администратора (Узнать через @getmyid_bot):", 
            text_color=M3_TEXT, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        )
        self.label_users.pack(anchor="w", padx=15, pady=(0, 5))
        
        self.entry_users = ctk.CTkEntry(
            self.frame_settings_card, fg_color=M3_INPUT_BG, border_color=M3_BORDER,
            text_color=M3_TEXT, placeholder_text_color=M3_TEXT_MUTED, corner_radius=8, height=35
        )
        self.entry_users.pack(fill="x", padx=15, pady=(0, 15))
        self.add_context_menu(self.entry_users)
        
        # Переключатель автозагрузки
        self.switch_autostart = ctk.CTkSwitch(
            self.frame_settings_card, text="Запускать вместе с Windows (в фоновом режиме)",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            progress_color=M3_PRIMARY,
            command=self.toggle_autostart_from_ui
        )
        self.switch_autostart.pack(anchor="w", padx=15, pady=(5, 15))
        
        self.label_tip = ctk.CTkLabel(
            self.frame_settings, 
            text="* Бот обрабатывает команды ТОЛЬКО от указанного ID администратора для безопасности.", 
            text_color=M3_TEXT_MUTED, 
            font=ctk.CTkFont(family="Segoe UI", size=11, slant="italic")
        )
        self.label_tip.pack(anchor="w", padx=15, pady=5)
        
        self.btn_save_settings = ctk.CTkButton(
            self.frame_settings, text="Сохранить настройки", 
            fg_color=M3_PRIMARY, 
            text_color=M3_ON_PRIMARY,
            hover_color="#e0e0e0",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            width=220, 
            height=42,
            corner_radius=21,
            command=self.save_settings_from_ui
        )
        self.btn_save_settings.pack(pady=30)
        
        # --- Вкладка Программы ---
        self.frame_programs = ctk.CTkFrame(self.frame_content, fg_color="transparent")
        self.content_frames["programs"] = self.frame_programs
        
        # Шапка Programs
        self.frame_programs_header = ctk.CTkFrame(self.frame_programs, fg_color="transparent", height=40)
        self.frame_programs_header.pack(fill="x", pady=(0, 10))
        self.frame_programs_header.pack_propagate(False)
        
        self.lbl_programs_header_title = ctk.CTkLabel(
            self.frame_programs_header, text="🚀   Список запускаемых программ", 
            text_color=M3_TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold")
        )
        self.lbl_programs_header_title.pack(side="left", padx=5)
        
        self.lbl_programs_count = ctk.CTkLabel(
            self.frame_programs_header, text="(0/15)", 
            text_color=M3_TEXT_MUTED,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold")
        )
        self.lbl_programs_count.pack(side="left", padx=(5, 10))
        
        # Кнопка сохранения изменений списка (в шапке)
        self.btn_save_programs = ctk.CTkButton(
            self.frame_programs_header, text="Сохранить список изменений", 
            fg_color=M3_PRIMARY, text_color=M3_ON_PRIMARY, hover_color="#e0e0e0",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            width=210, height=32, corner_radius=16,
            command=self.save_programs_from_ui
        )
        self.btn_save_programs.pack(side="right", padx=5)
        
        # Форма добавления (Простая, без имени процесса)
        self.frame_add_prog = ctk.CTkFrame(
            self.frame_programs, fg_color=M3_CARD_BG, 
            border_color=M3_BORDER, border_width=1, 
            corner_radius=12, height=60
        )
        self.frame_add_prog.pack(anchor="w", padx=10, pady=5)
        
        self.entry_prog_name = ctk.CTkEntry(
            self.frame_add_prog, width=120, height=32, 
            fg_color=M3_INPUT_BG, border_color=M3_BORDER, corner_radius=6, 
            placeholder_text="Название"
        )
        self.entry_prog_name.pack(side="left", padx=(15, 5), pady=14)
        self.add_context_menu(self.entry_prog_name)
        
        self.entry_prog_path = ctk.CTkEntry(
            self.frame_add_prog, width=160, height=32, 
            fg_color=M3_INPUT_BG, border_color=M3_BORDER, corner_radius=6, 
            placeholder_text="Путь к файлу"
        )
        self.entry_prog_path.pack(side="left", padx=5, pady=14)
        self.add_context_menu(self.entry_prog_path)
        
        self.btn_browse = ctk.CTkButton(
            self.frame_add_prog, text="Обзор", 
            fg_color=M3_PRIMARY, text_color=M3_ON_PRIMARY, hover_color="#e0e0e0",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            width=65, height=32, corner_radius=16, command=self.browse_executable
        )
        self.btn_browse.pack(side="left", padx=5, pady=14)
        
        self.btn_add_prog = ctk.CTkButton(
            self.frame_add_prog, text="Добавить", 
            fg_color=M3_PRIMARY, text_color=M3_ON_PRIMARY, hover_color="#e0e0e0",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            width=100, height=32, corner_radius=16, command=self.add_program_from_ui
        )
        self.btn_add_prog.pack(side="left", padx=5, pady=14)
        
        # Список с прокруткой (Теперь внизу и занимает все оставшееся место)
        self.scroll_progs = ctk.CTkScrollableFrame(self.frame_programs, fg_color="transparent", height=180)
        self.scroll_progs.pack(fill="both", expand=True, padx=5, pady=5)
        
        # --- Вкладка Логи ---
        self.frame_logs = ctk.CTkFrame(self.frame_content, fg_color="transparent")
        self.content_frames["logs"] = self.frame_logs
        
        # Шапка Logs
        self.frame_logs_header = ctk.CTkFrame(self.frame_logs, fg_color="transparent", height=40)
        self.frame_logs_header.pack(fill="x", pady=(0, 10))
        self.frame_logs_header.pack_propagate(False)
        
        self.lbl_logs_header_title = ctk.CTkLabel(
            self.frame_logs_header, text="📊   Консоль логов", 
            text_color=M3_TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold")
        )
        self.lbl_logs_header_title.pack(side="left", padx=5)
        
        # Внутренний контейнер, где будут находиться либо textbox, либо placeholder
        self.frame_logs_container = ctk.CTkFrame(self.frame_logs, fg_color="transparent")
        self.frame_logs_container.pack(fill="both", expand=True)
        
        # Плейсхолдер "Нет логов"
        self.frame_no_logs = ctk.CTkFrame(self.frame_logs_container, fg_color="transparent")
        
        # Иконка документа (Используем крупный эмодзи или текст 📄)
        self.lbl_no_logs_icon = ctk.CTkLabel(
            self.frame_no_logs, text="📄", 
            text_color=M3_TEXT_MUTED,
            font=ctk.CTkFont(size=64)
        )
        self.lbl_no_logs_icon.pack(expand=True, pady=(80, 5))
        
        self.lbl_no_logs_title = ctk.CTkLabel(
            self.frame_no_logs, text="Нет логов", 
            text_color=M3_TEXT,
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold")
        )
        self.lbl_no_logs_title.pack(pady=5)
        
        self.lbl_no_logs_subtitle = ctk.CTkLabel(
            self.frame_no_logs, text="Логи появятся после запуска бота", 
            text_color=M3_TEXT_MUTED,
            font=ctk.CTkFont(family="Segoe UI", size=12)
        )
        self.lbl_no_logs_subtitle.pack(pady=(0, 100))
        
        # Текстовое поле логов (Без рамок, чисто черный фон под стиль Kiro Bot)
        self.textbox_logs = ctk.CTkTextbox(
            self.frame_logs_container, fg_color="#000000", text_color=M3_TEXT, 
            border_color="#000000", border_width=0,
            font=ctk.CTkFont(family="Consolas", size=13), corner_radius=0
        )
        self.textbox_logs.tag_config("red", foreground="#ff5252")       # Красный для ошибок
        self.textbox_logs.tag_config("orange", foreground="#ff9800")    # Оранжевый для предупреждений
        self.textbox_logs.tag_config("green", foreground="#4caf50")     # Зеленый для успехов
        self.textbox_logs.tag_config("white", foreground="#ffffff")     # Белый
        self.textbox_logs.tag_config("gray", foreground="#888888")      # Серый для информации по умолчанию
        # Изначально не запаковываем, update_logs_view_state() сделает это
        
        # Плавающие кнопки в правом нижнем углу (как Share и Trash в Kiro Bot)
        # Кнопка Копирования логов (Segoe MDL2 Assets: Copy = \uE8C8)
        self.btn_copy_logs_floating = ctk.CTkButton(
            self.frame_logs_container, text="\uE8C8", 
            fg_color="#2c2c2e", text_color="#ffffff", 
            hover_color="#3e3e42",
            font=ctk.CTkFont(family="Segoe MDL2 Assets", size=18),
            width=42, height=42, corner_radius=10,
            command=self.copy_logs_to_clipboard
        )
        self.btn_copy_logs_floating.place(relx=0.97, rely=0.86, anchor="se")
        
        # Кнопка Очистки логов (Segoe MDL2 Assets: Delete = \uE74D)
        self.btn_clear_logs_floating = ctk.CTkButton(
            self.frame_logs_container, text="\uE74D", 
            fg_color="#2c2c2e", text_color="#ffffff", 
            hover_color="#3e3e42",
            font=ctk.CTkFont(family="Segoe MDL2 Assets", size=18),
            width=42, height=42, corner_radius=10,
            command=self.clear_logs
        )
        self.btn_clear_logs_floating.place(relx=0.97, rely=0.97, anchor="se")
        
        # Дефолтная активная вкладка
        self.switch_tab("home")

    def update_logs_view_state(self):
        log_content = self.textbox_logs.get("1.0", "end-1c").strip()
        if not log_content:
            self.textbox_logs.pack_forget()
            self.frame_no_logs.pack(fill="both", expand=True)
        else:
            self.frame_no_logs.pack_forget()
            self.textbox_logs.pack(fill="both", expand=True, padx=10, pady=5)
            # Убедимся, что плавающие кнопки поверх textbox
            self.btn_copy_logs_floating.lift()
            self.btn_clear_logs_floating.lift()

    def switch_tab(self, tab_name: str):
        # Переключение визуальных стилей вкладок
        for name, button in self.nav_buttons.items():
            if name == tab_name:
                button.configure(fg_color=M3_PRIMARY, text_color=M3_ON_PRIMARY, hover_color="#e0e0e0")
            else:
                button.configure(fg_color="transparent", text_color=M3_TEXT, hover_color="#121212")
                
        # Прячем все вкладки
        for frame in self.content_frames.values():
            frame.pack_forget()
            
        # Упаковываем текущую вкладку
        self.content_frames[tab_name].pack(fill="both", expand=True, padx=20, pady=20)
        
        # Обновляем состояние логов при переключении на них
        if tab_name == "logs":
            self.update_logs_view_state()

    def toggle_bot_state(self):
        if self.bot_runner.is_running:
            self.bot_runner.stop()
        else:
            token = self.entry_token.get().strip()
            if not token:
                messagebox.showerror("Ошибка", "Заполните поле Telegram Bot Token во вкладке Настройки!")
                self.switch_tab("settings")
                return
            
            self.save_settings_from_ui(silent=True)
            self.btn_toggle_bot_large.configure(state="disabled")
            self.bot_runner.start()

    def update_bot_status(self, status: str):
        def update():
            self.btn_toggle_bot_large.configure(state="normal")
            if status == "RUNNING":
                self.label_status_indicator.configure(text="🟢 Бот активен", text_color="#28a745")
                self.title("Pulse PC [Запущен]")
                self.btn_toggle_bot_large.configure(
                    text="Остановить", 
                    fg_color="#dc3545", 
                    text_color="#ffffff", 
                    hover_color="#c82333"
                )
            else:
                self.label_status_indicator.configure(text="🔴 Бот выключен", text_color="#FF5252")
                self.title("Pulse PC [Остановлен]")
                self.btn_toggle_bot_large.configure(
                    text="Запустить", 
                    fg_color="#28a745", 
                    text_color="#ffffff", 
                    hover_color="#218838"
                )
                # При остановке больше не сворачиваем окно автоматически
                if not self.is_quitting:
                    self.write_log("Бот остановлен.\n")
                    
            if self.tray_icon:
                try:
                    self.tray_icon.update_menu()
                except Exception:
                    pass
        self.after(0, update)

    def restart_bot(self):
        def restart():
            self.write_log("Выполняю перезапуск бота...\n")
            self.toggle_bot_state()  # Останавливаем
            self.after(2000, self.toggle_bot_state)  # Через 2 секунды запускаем
        self.after(0, restart)

    def write_log(self, text: str):
        def append():
            self.append_colored_log(text)
        self.after(0, append)

    def append_colored_log(self, text: str):
        lines = text.splitlines(keepends=True)
        self.textbox_logs.configure(state="normal")
        for line in lines:
            line_strip = line.strip().upper()
            
            # Определяем цвет по содержанию строки
            if any(word in line_strip for word in ["ERROR", "ОШИБКА", "КРИТИЧЕСКАЯ", "FAILED"]):
                tag = "red"
            elif any(word in line_strip for word in ["WARNING", "ПРЕДУПРЕЖДЕНИЕ", "===", "COOLDOWN", "ПРОПУЩЕННЫХ"]):
                tag = "orange"
            elif any(word in line_strip for word in ["УСПЕШНО", "ГОТОВ", "ЗАПУЩЕН", "SUCCESS", "RUNNING", "ИНИЦИАЛИЗИРОВАН", "ПОЛУЧЕН"]):
                tag = "green"
            elif any(word in line_strip for word in ["INFO", "ПОДКЛЮЧЕНИЕ", "ЗАПУСК"]):
                tag = "white"
            else:
                tag = "gray"
                
            self.textbox_logs.insert("end", line, tag)
            
        self.textbox_logs.see("end")
        self.textbox_logs.configure(state="disabled")
        self.update_logs_view_state()

    def auto_start_bot_on_launch(self):
        token = self.entry_token.get().strip()
        if token and token != "your_telegram_bot_token_here" and token.strip():
            self.write_log("Выполняю автозапуск бота на старте...\n")
            self.toggle_bot_state()

    def clear_logs(self):
        self.textbox_logs.configure(state="normal")
        self.textbox_logs.delete("1.0", "end")
        self.textbox_logs.configure(state="disabled")
        self.update_logs_view_state()

    def copy_logs_to_clipboard(self):
        log_content = self.textbox_logs.get("1.0", "end-1c")
        if log_content.strip():
            self.clipboard_clear()
            self.clipboard_append(log_content)
            messagebox.showinfo("Успех", "Логи успешно скопированы в буфер обмена!")
        else:
            messagebox.showwarning("Внимание", "Логи отсутствуют или пусты!")

    # --- Функции Управления Настройками ---
    def load_settings_to_ui(self):
        env_path = os.path.join(config.BASE_DIR, ".env")
        token = ""
        allowed_users = ""
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("BOT_TOKEN="):
                            token = line.split("=", 1)[1]
                        elif line.startswith("ALLOWED_USERS="):
                            allowed_users = line.split("=", 1)[1]
                        elif line.startswith("ADMIN_ID="):
                            allowed_users = line.split("=", 1)[1]
            except Exception as e:
                self.write_log(f"Не удалось загрузить настройки .env: {e}\n")
                
        self.entry_token.delete(0, "end")
        self.entry_token.insert(0, token)
        self.entry_users.delete(0, "end")
        
        # Загружаем из файла .env, если есть, иначе из config
        if allowed_users:
            self.entry_users.insert(0, allowed_users)
        elif hasattr(config, "ALLOWED_USERS_RAW") and getattr(config, "ALLOWED_USERS_RAW"):
            self.entry_users.insert(0, getattr(config, "ALLOWED_USERS_RAW"))
        else:
            self.entry_users.insert(0, getattr(config, "ADMIN_ID_RAW", ""))
            
        # Обновляем состояние переключателя автозагрузки
        if self.check_autostart():
            self.switch_autostart.select()
        else:
            self.switch_autostart.deselect()

    def toggle_autostart_from_ui(self):
        is_enabled = self.switch_autostart.get() == 1
        self.set_autostart(is_enabled)
        state_str = "включена" if is_enabled else "отключена"
        self.write_log(f"Автозагрузка {state_str}.\n")
        
    def check_autostart(self) -> bool:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "PulsePC"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(key, app_name)
            winreg.CloseKey(key)
            return True
        except Exception:
            return False

    def set_autostart(self, enable: bool):
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "PulsePC"
        
        if getattr(sys, 'frozen', False):
            exe_path = f'"{sys.executable}" --minimized'
        else:
            exe_path = f'"{sys.executable}" "{os.path.abspath(__file__)}" --minimized'
            
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
            if enable:
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            self.write_log(f"Ошибка при изменении автозагрузки: {e}\n")

    def save_settings_from_ui(self, silent=False):
        token = self.entry_token.get().strip()
        users_raw = self.entry_users.get().strip()
        
        # Обновляем .env
        env_path = os.path.join(config.BASE_DIR, ".env")
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(f"BOT_TOKEN={token}\n")
                f.write(f"ADMIN_ID={users_raw}\n")
            
            # Обновляем переменные в памяти, чтобы не требовался перезапуск для смены ADMIN_ID
            config.BOT_TOKEN = token
            if users_raw.strip() and users_raw.strip().isdigit():
                config.ADMIN_ID = int(users_raw.strip())
            else:
                config.ADMIN_ID = None
                
            self.write_log("Настройки .env успешно сохранены!\n")
            if not silent:
                messagebox.showinfo("Успех", "Настройки сохранены успешно!")
        except Exception as e:
            self.write_log(f"Ошибка сохранения настроек: {e}\n")
            if not silent:
                messagebox.showerror("Ошибка", f"Не удалось сохранить настройки: {e}")

    # --- Функции Управления Программами ---
    def load_programs_list(self) -> list:
        programs_path = os.path.join(config.BASE_DIR, "programs.json")
        if os.path.exists(programs_path):
            try:
                with open(programs_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                self.write_log(f"Ошибка чтения json программ: {e}\n")
                return []
        return []

    def save_programs_list(self, programs: list):
        programs_path = os.path.join(config.BASE_DIR, "programs.json")
        try:
            with open(programs_path, "w", encoding="utf-8") as f:
                json.dump(programs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.write_log(f"Ошибка сохранения json программ: {e}\n")

    def refresh_programs_list(self):
        # Очищаем виджеты в скролле
        for widget in self.scroll_progs.winfo_children():
            widget.destroy()
            
        programs = self.temp_programs
        self.lbl_programs_count.configure(text=f"({len(programs)}/15)")
        
        # Заголовки
        lbl_h1 = ctk.CTkLabel(self.scroll_progs, text="Название программы", text_color=M3_PRIMARY, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"))
        lbl_h1.grid(row=0, column=0, padx=15, pady=8, sticky="w")
        lbl_h2 = ctk.CTkLabel(self.scroll_progs, text="Имя процесса", text_color=M3_PRIMARY, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"))
        lbl_h2.grid(row=0, column=1, padx=15, pady=8, sticky="w")
        
        for idx, prog in enumerate(programs):
            name = prog.get("name", "")
            process = prog.get("process", "")
            
            # Карточка для строки списка программы (Темная карточка)
            frame_item = ctk.CTkFrame(
                self.scroll_progs, fg_color=M3_CARD_BG, 
                border_color=M3_BORDER, border_width=1, 
                height=45, corner_radius=8
            )
            frame_item.grid(row=idx+1, column=0, columnspan=3, padx=5, pady=4, sticky="ew")
            frame_item.grid_columnconfigure(0, weight=2)
            frame_item.grid_columnconfigure(1, weight=2)
            frame_item.grid_columnconfigure(2, weight=1)
            
            lbl_name = ctk.CTkLabel(frame_item, text=name, text_color=M3_TEXT, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"))
            lbl_name.grid(row=0, column=0, padx=15, pady=10, sticky="w")
            
            lbl_proc = ctk.CTkLabel(frame_item, text=process or "[Не указан]", text_color=M3_TEXT_MUTED, font=ctk.CTkFont(family="Segoe UI", size=12))
            lbl_proc.grid(row=0, column=1, padx=15, pady=10, sticky="w")
            
            btn_del = ctk.CTkButton(
                frame_item, text="Удалить", 
                fg_color=M3_PRIMARY, text_color=M3_ON_PRIMARY, hover_color="#e0e0e0",
                font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
                width=75, height=28, corner_radius=14,
                command=lambda i=idx: self.delete_program(i)
            )
            btn_del.grid(row=0, column=2, padx=15, pady=8, sticky="e")

    def browse_executable(self):
        filepath = filedialog.askopenfilename(
            title="Выберите исполняемый файл",
            filetypes=[("Исполняемые файлы", "*.exe"), ("Все файлы", "*.*")]
        )
        if filepath:
            filepath = os.path.normpath(filepath)
            self.entry_prog_path.delete(0, "end")
            self.entry_prog_path.insert(0, filepath)
            
            filename = os.path.basename(filepath)
            name_without_ext = os.path.splitext(filename)[0]
            
            if not self.entry_prog_name.get().strip():
                self.entry_prog_name.insert(0, name_without_ext.capitalize())

    def add_program_from_ui(self):
        name = self.entry_prog_name.get().strip()
        path = self.entry_prog_path.get().strip()
        
        if not name or not path:
            messagebox.showerror("Ошибка", "Заполните Название и Путь к программе!")
            return
            
        # Лимит добавленных программ (максимум 15)
        if len(self.temp_programs) >= 15:
            messagebox.showwarning("Лимит превышен", "Вы не можете добавить больше 15 программ!")
            return
            
        # Имя процесса автоматически берется из пути к файлу
        process = os.path.basename(path)
        
        self.temp_programs.append({
            "name": name,
            "path": path,
            "process": process
        })
        
        self.entry_prog_name.delete(0, "end")
        self.entry_prog_path.delete(0, "end")
        
        self.refresh_programs_list()
        self.write_log(f"Программа {name} добавлена во временный список. Нажмите «Сохранить список изменений» для записи на диск.\n")

    def delete_program(self, index: int):
        if 0 <= index < len(self.temp_programs):
            deleted = self.temp_programs.pop(index)
            self.refresh_programs_list()
            self.write_log(f"Программа {deleted.get('name')} удалена из временного списка. Нажмите «Сохранить список изменений» для записи на диск.\n")

    def save_programs_from_ui(self):
        self.save_programs_list(self.temp_programs)
        self.write_log("Список программ успешно сохранен на диск (programs.json)!\n")
        messagebox.showinfo("Успех", "Список программ успешно сохранен на диск!")

    # --- Функции Системного Трея (pystray) ---
    def setup_tray(self):
        self.tray_thread = threading.Thread(target=self._run_tray_loop, daemon=True)
        self.tray_thread.start()

    def _run_tray_loop(self):
        icon_png_path = os.path.join(config.BASE_DIR, "icon.png")
        if os.path.exists(icon_png_path):
            img = Image.open(icon_png_path)
        elif os.path.exists(self.icon_path):
            img = Image.open(self.icon_path)
        else:
            img = Image.new("RGBA", (16, 16), color=(255, 255, 255, 255))
            
        def on_open(icon, item):
            self.after(0, self.show_window)
        def on_exit(icon, item):
            self.after(0, self.quit_app)
            
        def get_state_text(item):
            if hasattr(self, 'bot_runner') and self.bot_runner and self.bot_runner.is_running:
                return "Статус: 🟢 Запущен"
            return "Статус: 🔴 Остановлен"

        def get_toggle_text(item):
            if hasattr(self, 'bot_runner') and self.bot_runner and self.bot_runner.is_running:
                return "⏹ Остановить бота"
            return "▶ Запустить бота"

        def on_toggle(icon, item):
            self.after(0, self.toggle_bot_state)
            
        menu = Menu(
            item(get_state_text, lambda icon, item: None),
            item(get_toggle_text, on_toggle),
            item('Открыть панель', on_open, default=True),
            item('Выход', on_exit)
        )
        self.tray_icon = pystray.Icon("Pulse PC", img, "Pulse PC", menu)
        self.tray_icon.run()

    def show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def on_close_event(self):
        self.withdraw()
        self.write_log("Окно свернуто в системный трей.\n")

    def quit_app(self):
        if self.is_quitting:
            return
        self.is_quitting = True
        self.bot_runner.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.destroy()
        sys.exit(0)

if __name__ == "__main__":
    if not acquire_gui_lock():
        import tkinter as tk
        from tkinter import messagebox as tk_messagebox
        root = tk.Tk()
        root.withdraw()
        tk_messagebox.showerror("Ошибка", "Pulse PC Control Panel уже запущена!")
        sys.exit(0)
        
    app = PulsePCApp()
    app.mainloop()
