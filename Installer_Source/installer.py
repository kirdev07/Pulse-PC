import os
import sys
import time
import shutil
import subprocess
import threading
import ctypes
import webbrowser
from tkinter import filedialog
import customtkinter as ctk

# Цвета в стиле Kiro Bot
M3_BG = "#000000"
M3_CARD_BG = "#161616"
M3_INPUT_BG = "#090909"
M3_BORDER = "#1f1f1f"
M3_PRIMARY = "#ffffff"
M3_ON_PRIMARY = "#000000"
M3_TEXT = "#ffffff"
M3_TEXT_MUTED = "#888888"

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class InstallerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Установка Pulse PC")
        self.geometry("600x400")
        self.resizable(False, False)
        self.configure(fg_color=M3_BG)
        
        self.after(10, self.apply_dark_titlebar)
        
        # Получаем пути
        self.meipass = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        self.icon_path = os.path.join(self.meipass, "icon.ico")
        if os.path.exists(self.icon_path):
            try:
                self.iconbitmap(self.icon_path)
            except Exception:
                pass
                
        # Путь по умолчанию
        appdata_local = os.environ.get('LOCALAPPDATA', os.path.join(os.environ.get('USERPROFILE', ''), 'AppData', 'Local'))
        self.default_install_path = os.path.join(appdata_local, "Pulse_PC")
        
        self.setup_ui()
        
    def apply_dark_titlebar(self):
        try:
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            if hwnd:
                # Темный режим окна
                rendering = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(rendering), ctypes.sizeof(rendering))
                # Черный цвет заголовка
                color = ctypes.c_int(0x00000000) 
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))
                # Белый текст заголовка
                text_color = ctypes.c_int(0x00FFFFFF) 
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text_color), ctypes.sizeof(text_color))
        except Exception:
            pass
            
    def browse_path(self):
        selected_dir = filedialog.askdirectory(initialdir=self.entry_path.get())
        if selected_dir:
            self.entry_path.delete(0, 'end')
            self.entry_path.insert(0, os.path.join(selected_dir, "Pulse_PC").replace("/", "\\"))
        
    def setup_ui(self):
        # Header
        self.frame_header = ctk.CTkFrame(self, fg_color="transparent", height=80)
        self.frame_header.pack(fill="x", pady=20)
        
        self.lbl_title = ctk.CTkLabel(
            self.frame_header, text="Установка Pulse PC", 
            text_color=M3_TEXT, font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold")
        )
        self.lbl_title.pack()
        
        self.lbl_subtitle = ctk.CTkLabel(
            self.frame_header, text="Удаленное управление ПК через Telegram", 
            text_color=M3_TEXT_MUTED, font=ctk.CTkFont(family="Segoe UI", size=13)
        )
        self.lbl_subtitle.pack()
        
        # Main Content
        self.frame_content = ctk.CTkFrame(self, fg_color=M3_CARD_BG, corner_radius=12, border_width=1, border_color=M3_BORDER)
        self.frame_content.pack(fill="both", expand=True, padx=30, pady=(0, 20))
        
        # Path selection
        self.lbl_path = ctk.CTkLabel(
            self.frame_content, text="Путь установки:", 
            text_color=M3_TEXT, font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        )
        self.lbl_path.pack(anchor="w", padx=20, pady=(20, 5))
        
        self.frame_path_input = ctk.CTkFrame(self.frame_content, fg_color="transparent")
        self.frame_path_input.pack(fill="x", padx=20)
        
        self.entry_path = ctk.CTkEntry(
            self.frame_path_input, fg_color=M3_INPUT_BG, border_color=M3_BORDER, text_color=M3_TEXT,
            height=35, corner_radius=8
        )
        self.entry_path.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.entry_path.insert(0, self.default_install_path)
        
        self.btn_browse = ctk.CTkButton(
            self.frame_path_input, text="Обзор", 
            fg_color=M3_PRIMARY, text_color=M3_ON_PRIMARY, hover_color="#e0e0e0",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            width=80, height=35, corner_radius=8, command=self.browse_path
        )
        self.btn_browse.pack(side="right")
        
        # Checkboxes
        self.var_shortcut = ctk.BooleanVar(value=True)
        self.chk_shortcut = ctk.CTkCheckBox(
            self.frame_content, text="Создать ярлык на Рабочем столе", 
            variable=self.var_shortcut, text_color=M3_TEXT,
            fg_color=M3_PRIMARY, checkmark_color=M3_ON_PRIMARY, hover_color="#e0e0e0",
            font=ctk.CTkFont(family="Segoe UI", size=12)
        )
        self.chk_shortcut.pack(anchor="w", padx=20, pady=(15, 0))
        
        self.var_autorun = ctk.BooleanVar(value=True)
        self.chk_autorun = ctk.CTkCheckBox(
            self.frame_content, text="Добавить в автозагрузку (запуск при старте Windows)", 
            variable=self.var_autorun, text_color=M3_TEXT,
            fg_color=M3_PRIMARY, checkmark_color=M3_ON_PRIMARY, hover_color="#e0e0e0",
            font=ctk.CTkFont(family="Segoe UI", size=12)
        )
        self.chk_autorun.pack(anchor="w", padx=20, pady=(10, 0))
        
        # Progress
        self.progressbar = ctk.CTkProgressBar(self.frame_content, progress_color=M3_PRIMARY, fg_color=M3_INPUT_BG, height=8)
        self.progressbar.pack(fill="x", padx=20, pady=(20, 5))
        self.progressbar.set(0)
        self.progressbar.pack_forget()
        
        self.lbl_status = ctk.CTkLabel(self.frame_content, text="", text_color=M3_TEXT_MUTED, font=ctk.CTkFont(size=11))
        self.lbl_status.pack(anchor="w", padx=20)
        
        # Bottom bar
        self.frame_bottom = ctk.CTkFrame(self, fg_color="transparent", height=50)
        self.frame_bottom.pack(fill="x", padx=30, pady=(0, 20))
        
        # Socials
        self.frame_socials = ctk.CTkFrame(self.frame_bottom, fg_color="transparent")
        self.frame_socials.pack(side="left")
        
        self.lbl_author = ctk.CTkLabel(
            self.frame_socials, text="Автор: KirDev", 
            text_color=M3_TEXT_MUTED, font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold")
        )
        self.lbl_author.pack(side="top", anchor="w", pady=(0, 2))
        
        self.frame_links = ctk.CTkFrame(self.frame_socials, fg_color="transparent")
        self.frame_links.pack(side="top", anchor="w")
        
        self.btn_vk = ctk.CTkButton(
            self.frame_links, text="VK", 
            fg_color="#2787F5", text_color="#ffffff", hover_color="#2274d6",
            width=50, height=24, corner_radius=12,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            command=lambda: webbrowser.open("https://vk.com/kirdev_07")
        )
        self.btn_vk.pack(side="left", padx=(0, 5))
        
        self.btn_tg = ctk.CTkButton(
            self.frame_links, text="Telegram", 
            fg_color="#24A1DE", text_color="#ffffff", hover_color="#1f8bbf",
            width=65, height=24, corner_radius=12,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            command=lambda: webbrowser.open("https://web.telegram.org/k/#@kirdev_studio")
        )
        self.btn_tg.pack(side="left")
        
        self.btn_install = ctk.CTkButton(
            self.frame_bottom, text="Установить", 
            fg_color=M3_PRIMARY, text_color=M3_ON_PRIMARY, hover_color="#e0e0e0",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            height=40, corner_radius=20, command=self.start_installation
        )
        self.btn_install.pack(side="right")
        
        self.btn_cancel = ctk.CTkButton(
            self.frame_bottom, text="Отмена", 
            fg_color="transparent", text_color=M3_TEXT, hover_color=M3_CARD_BG, border_width=1, border_color=M3_BORDER,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            height=40, corner_radius=20, command=self.destroy
        )
        self.btn_cancel.pack(side="right", padx=(0, 10))

    def create_shortcut(self, target_exe, name, add_to_desktop=True, add_to_startup=False):
        try:
            # Используем VBScript для создания ярлыка (работает без внешних библиотек)
            vbs_script = os.path.join(os.environ["TEMP"], "create_shortcut.vbs")
            
            paths = []
            if add_to_desktop:
                desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
                paths.append(os.path.join(desktop, f"{name}.lnk"))
                
            if add_to_startup:
                startup = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
                paths.append(os.path.join(startup, f"{name}.lnk"))
                
            if not paths:
                return
                
            with open(vbs_script, "w", encoding="utf-8") as f:
                f.write('Set oWS = WScript.CreateObject("WScript.Shell")\n')
                for path in paths:
                    f.write(f'sLinkFile = "{path}"\n')
                    f.write('Set oLink = oWS.CreateShortcut(sLinkFile)\n')
                    f.write(f'oLink.TargetPath = "{target_exe}"\n')
                    f.write(f'oLink.WorkingDirectory = "{os.path.dirname(target_exe)}"\n')
                    f.write('oLink.Save\n')
                    
            subprocess.run(["cscript.exe", "//Nologo", vbs_script], creationflags=subprocess.CREATE_NO_WINDOW)
            os.remove(vbs_script)
        except Exception as e:
            print(f"Error creating shortcut: {e}")

    def start_installation(self):
        install_path = self.entry_path.get().strip()
        if not install_path:
            return
            
        self.btn_install.configure(state="disabled")
        self.btn_cancel.configure(state="disabled")
        self.entry_path.configure(state="disabled")
        self.chk_shortcut.configure(state="disabled")
        self.chk_autorun.configure(state="disabled")
        
        self.progressbar.pack(fill="x", padx=20, pady=(10, 5), before=self.lbl_status)
        
        threading.Thread(target=self._install_process, args=(install_path,), daemon=True).start()
        
    def _install_process(self, install_path):
        try:
            self.lbl_status.configure(text="Создание директорий...")
            self.progressbar.set(0.1)
            time.sleep(0.5)
            
            os.makedirs(install_path, exist_ok=True)
            
            # Копируем Pulse_PC из вшитых данных (MEIPASS)
            source_pulse_dir = os.path.join(self.meipass, "Pulse_PC")
            
            self.lbl_status.configure(text="Копирование файлов...")
            self.progressbar.set(0.4)
            
            if os.path.exists(source_pulse_dir):
                # Копируем содержимое Pulse_PC в папку установки
                for item in os.listdir(source_pulse_dir):
                    s = os.path.join(source_pulse_dir, item)
                    d = os.path.join(install_path, item)
                    if os.path.isdir(s):
                        shutil.copytree(s, d, dirs_exist_ok=True)
                    else:
                        shutil.copy2(s, d)
            
            target_exe = os.path.join(install_path, "Pulse PC.exe")
            
            self.progressbar.set(0.8)
            
            if self.var_shortcut.get() or self.var_autorun.get():
                self.lbl_status.configure(text="Создание ярлыков...")
                self.create_shortcut(target_exe, "Pulse PC", self.var_shortcut.get(), self.var_autorun.get())
                time.sleep(0.5)
                
            self.progressbar.set(1.0)
            self.lbl_status.configure(text="Установка завершена успешно!")
            
            self.after(500, lambda: self.finish_installation(target_exe))
            
        except Exception as e:
            self.lbl_status.configure(text=f"Ошибка: {e}", text_color="#ff5252")
            self.btn_cancel.configure(state="normal", text="Закрыть")
            
    def finish_installation(self, target_exe):
        self.btn_install.configure(text="Запустить", state="normal", command=lambda: self.run_and_exit(target_exe))
        self.btn_cancel.configure(text="Готово", state="normal", command=self.destroy)
        
    def run_and_exit(self, target_exe):
        try:
            subprocess.Popen([target_exe], cwd=os.path.dirname(target_exe))
        except Exception:
            pass
        self.destroy()

if __name__ == "__main__":
    app = InstallerApp()
    app.mainloop()
