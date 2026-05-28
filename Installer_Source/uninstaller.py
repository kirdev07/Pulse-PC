import os
import sys
import time
import shutil
import subprocess
import threading
import ctypes
import webbrowser
import customtkinter as ctk

# Цвета в стиле Kiro Bot
M3_BG = "#000000"
M3_CARD_BG = "#161616"
M3_INPUT_BG = "#090909"
M3_BORDER = "#1f1f1f"
M3_PRIMARY = "#ffffff"  # Белый для прогресс бара
M3_ON_PRIMARY = "#000000"
M3_TEXT = "#ffffff"
M3_TEXT_MUTED = "#888888"

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class UninstallerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("Удаление Pulse PC")
        self.geometry("600x400")
        self.resizable(False, False)
        self.configure(fg_color=M3_BG)
        
        self.after(10, self.apply_dark_titlebar)
        
        # Получаем пути
        self.app_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        
        # Иконка
        self.meipass = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        self.icon_path = os.path.join(self.meipass, "icon.ico")
        if os.path.exists(self.icon_path):
            try:
                self.iconbitmap(self.icon_path)
            except Exception:
                pass
                
        self.setup_ui()
        
    def apply_dark_titlebar(self):
        try:
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            if hwnd:
                rendering = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(rendering), ctypes.sizeof(rendering))
                color = ctypes.c_int(0x00000000) 
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))
                text_color = ctypes.c_int(0x00FFFFFF) 
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text_color), ctypes.sizeof(text_color))
        except Exception:
            pass
            
    def setup_ui(self):
        # Header
        self.frame_header = ctk.CTkFrame(self, fg_color="transparent", height=80)
        self.frame_header.pack(fill="x", pady=20)
        
        self.lbl_title = ctk.CTkLabel(
            self.frame_header, text="Удаление Pulse PC", 
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
        
        self.lbl_warning = ctk.CTkLabel(
            self.frame_content, text="Вы уверены, что хотите удалить Pulse PC?", 
            text_color=M3_TEXT, font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            justify="center"
        )
        self.lbl_warning.pack(pady=(30, 15))
        
        self.var_keep_settings = ctk.BooleanVar(value=False)
        self.chk_keep_settings = ctk.CTkCheckBox(
            self.frame_content, text="Сохранить файлы настроек (config, files)", 
            variable=self.var_keep_settings, text_color=M3_TEXT,
            fg_color=M3_PRIMARY, checkmark_color=M3_ON_PRIMARY, hover_color="#e0e0e0",
            font=ctk.CTkFont(family="Segoe UI", size=13)
        )
        self.chk_keep_settings.pack(pady=(0, 20))
        
        # Progress
        self.progressbar = ctk.CTkProgressBar(self.frame_content, progress_color=M3_PRIMARY, fg_color=M3_INPUT_BG, height=8)
        self.progressbar.pack(fill="x", padx=20, pady=(10, 5))
        self.progressbar.set(0)
        self.progressbar.pack_forget()
        
        self.lbl_status = ctk.CTkLabel(self.frame_content, text="", text_color=M3_TEXT_MUTED, font=ctk.CTkFont(size=12))
        self.lbl_status.pack()
        
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
        
        self.btn_uninstall = ctk.CTkButton(
            self.frame_bottom, text="Удалить", 
            fg_color="#ff5252", text_color="#ffffff", hover_color="#d32f2f",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            height=40, corner_radius=20, command=self.start_uninstallation
        )
        self.btn_uninstall.pack(side="right")
        
        self.btn_cancel = ctk.CTkButton(
            self.frame_bottom, text="Отмена", 
            fg_color="transparent", text_color=M3_TEXT, hover_color=M3_CARD_BG, border_width=1, border_color=M3_BORDER,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            height=40, corner_radius=20, command=self.destroy
        )
        self.btn_cancel.pack(side="right", padx=(0, 10))

    def delete_shortcuts(self):
        try:
            # Рабочий стол
            desktop = os.path.join(os.environ["USERPROFILE"], "Desktop", "Pulse PC.lnk")
            if os.path.exists(desktop):
                os.remove(desktop)
                
            # Автозагрузка
            startup = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "Pulse PC.lnk")
            if os.path.exists(startup):
                os.remove(startup)
        except Exception as e:
            pass

    def start_uninstallation(self):
        self.btn_uninstall.configure(state="disabled")
        self.btn_cancel.configure(state="disabled")
        self.chk_keep_settings.configure(state="disabled")
        
        self.progressbar.pack(fill="x", padx=20, pady=(10, 5), before=self.lbl_status)
        
        threading.Thread(target=self._uninstall_process, daemon=True).start()
        
    def _uninstall_process(self):
        try:
            self.lbl_status.configure(text="Остановка процесса Pulse PC...")
            self.progressbar.set(0.1)
            time.sleep(1)
            
            # 1. Завершаем процесс Pulse PC
            subprocess.run(["taskkill", "/F", "/IM", "Pulse PC.exe"], capture_output=True)
            self.progressbar.set(0.3)
            time.sleep(1)
            
            self.lbl_status.configure(text="Удаление ярлыков...")
            self.progressbar.set(0.5)
            # 2. Удаляем ярлыки
            self.delete_shortcuts()
            time.sleep(1)
            
            self.lbl_status.configure(text="Подготовка к очистке файлов...")
            self.progressbar.set(0.8)
            time.sleep(1)
            
            keep_settings = self.var_keep_settings.get()
            
            # 3. Подготавливаем самоуничтожение директории
            temp_bat = os.path.join(os.environ["TEMP"], "pulse_uninstall.bat")
            with open(temp_bat, "w") as f:
                f.write("@echo off\n")
                f.write(":loop\n")
                f.write('tasklist | find /i "Uninstall.exe" >nul\n')
                f.write("if %errorlevel% equ 0 (\n")
                f.write("    ping 127.0.0.1 -n 2 > nul\n")
                f.write("    goto loop\n")
                f.write(")\n")
                f.write("ping 127.0.0.1 -n 2 > nul\n")
                
                if keep_settings:
                    # Удаляем только экзешник, иконки и прочий мусор, кроме config и files
                    f.write(f'del /f /q "{os.path.join(self.app_dir, "Pulse PC.exe")}" 2>nul\n')
                    f.write(f'del /f /q "{os.path.join(self.app_dir, "gui.lock")}" 2>nul\n')
                    f.write(f'del /f /q "{os.path.join(self.app_dir, "bot.lock")}" 2>nul\n')
                    f.write(f'del /f /q "{os.path.join(self.app_dir, "last_start.txt")}" 2>nul\n')
                    f.write(f'rmdir /s /q "{os.path.join(self.app_dir, "image")}" 2>nul\n')
                    # Сам деинсталлятор в папке тоже удаляем
                    f.write(f'del /f /q "{os.path.join(self.app_dir, "Uninstall.exe")}" 2>nul\n')
                else:
                    # Удаляем всю папку программы
                    f.write(f'rmdir /s /q "{self.app_dir}"\n')
                    
                f.write('del "%~f0"\n') # Удаляем сам батник
            
            self.progressbar.set(1.0)
            self.lbl_status.configure(text="Готово!")
            time.sleep(1)
            
            # Запускаем батник через cmd /c
            subprocess.Popen(["cmd.exe", "/c", temp_bat], creationflags=subprocess.CREATE_NO_WINDOW)
            
            # Закрываем деинсталлятор
            self.after(100, self.destroy)
            
        except Exception as e:
            self.lbl_status.configure(text=f"Ошибка: {e}", text_color="#ff5252")
            self.btn_cancel.configure(state="normal", text="Закрыть")

if __name__ == "__main__":
    app = UninstallerApp()
    app.mainloop()
