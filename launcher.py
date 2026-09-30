"""Pulse PC launcher: no .exe, only Python.

It finds (or creates) a virtual environment next to the project, installs the
packages from requirements.txt once, and starts the panel without a console.

  PulsePC.pyw                       double-click: prepare if needed, then start
  python launcher.py --install      prepare everything + Desktop shortcut
  python launcher.py --autostart on|off
  python launcher.py --check        print what is ready and what is missing
"""
import hashlib
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / "requirements.txt"
ENV_NAMES = (".venv", ".qt-venv")          # .qt-venv: environment from older installs
STAMP_NAME = "pulsepc-requirements.sha256"
CHECK_IMPORTS = "PySide6, aiogram, aiohttp, dotenv, psutil, pyautogui, win32gui, win32com, mss, PIL"
OPTIONAL = ROOT / "requirements-optional.txt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MIN_PYTHON = (3, 10)


class SetupError(Exception):
    pass


# ---------- helpers ----------

def env_python(env, windowless=False):
    return env / "Scripts" / ("pythonw.exe" if windowless else "python.exe")


def requirements_hash():
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def runs(python, *args, timeout=90):
    try:
        done = subprocess.run([str(python), *args], capture_output=True, text=True, timeout=timeout,
                              creationflags=NO_WINDOW, cwd=ROOT)
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def env_ready(env):
    """Quick check: the stamp matches; otherwise verify the imports once and re-stamp."""
    python = env_python(env)
    if not python.exists() or not runs(python, "--version", timeout=20):
        return False
    stamp = env / STAMP_NAME
    if stamp.exists() and stamp.read_text(encoding="utf-8").strip() == requirements_hash():
        return True
    if runs(python, "-c", f"import {CHECK_IMPORTS}"):
        stamp.write_text(requirements_hash(), encoding="utf-8")
        return True
    return False


def find_ready_env():
    for name in ENV_NAMES:
        env = ROOT / name
        if env.exists() and env_ready(env):
            return env
    return None


def check_python():
    if sys.version_info < MIN_PYTHON:
        raise SetupError(f"Нужен Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} или новее, сейчас "
                         f"{sys.version_info.major}.{sys.version_info.minor}. Скачайте: https://www.python.org/downloads/")
    if struct.calcsize("P") * 8 != 64:
        raise SetupError("Нужен 64-битный Python (для PySide6). Скачайте 64-bit на https://www.python.org/downloads/")


def stream(command, log):
    """Run a command and pass its output lines to log()."""
    process = subprocess.Popen([str(c) for c in command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", cwd=ROOT, creationflags=NO_WINDOW)
    tail = []
    for line in process.stdout:
        line = line.rstrip()
        if line:
            tail.append(line)
            log(line)
    if process.wait() != 0:
        raise SetupError("Команда завершилась с ошибкой:\n" + "\n".join(tail[-12:]))


# ---------- setup ----------

def pip_install(python, requirements, log):
    """pip install -r ...; on locked-down PCs (no write access to the pip cache) retry without cache."""
    base = [python, "-m", "pip", "install", "--disable-pip-version-check", "--prefer-binary"]
    try:
        stream(base + ["-r", requirements], log)
    except SetupError as exc:
        text = str(exc).lower()
        if "permission denied" not in text and "errno 13" not in text and "access is denied" not in text:
            raise
        log("Нет доступа к кэшу pip, повторяю установку без кэша…")
        stream(base + ["--no-cache-dir", "-r", requirements], log)


def prepare(log=print):
    """Return a ready environment, creating it and installing packages when needed."""
    env = find_ready_env()
    if env:
        return env
    check_python()
    if not REQUIREMENTS.exists():
        raise SetupError("Не найден requirements.txt рядом с программой.")
    env = ROOT / ".venv"
    if env.exists() and not runs(env_python(env), "--version", timeout=20):
        log("Старое окружение повреждено, создаю заново…")
        shutil.rmtree(env, ignore_errors=True)
    if not env.exists():
        log("Создаю окружение Python (.venv)…")
        stream([sys.executable, "-m", "venv", env], log)
    python = env_python(env)
    log("Устанавливаю пакеты (первый раз это несколько минут)…")
    stream([python, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"], lambda _: None)
    pip_install(python, REQUIREMENTS, log)
    if OPTIONAL.exists():
        try:
            pip_install(python, OPTIONAL, log)
        except SetupError:
            log("Необязательные пакеты не поставились: «что играет» из других программ недоступно. Остальное работает.")
    if not runs(python, "-c", f"import {CHECK_IMPORTS}"):
        raise SetupError("Пакеты установлены, но программа не импортируется. Смотрите install.log.")
    (env / STAMP_NAME).write_text(requirements_hash(), encoding="utf-8")
    log("Готово.")
    return env


def start(env, extra_args=()):
    """Start the panel detached from this process, without a console window."""
    python = env_python(env, windowless=True)
    if not python.exists():
        python = env_python(env)
    flags = NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    with open(ROOT / "launcher.log", "w", encoding="utf-8") as log:   # output of the app, to diagnose failed starts
        subprocess.Popen([str(python), str(ROOT / "gui.py"), *extra_args], cwd=ROOT, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log)


# ---------- shortcut and autostart ----------

def launcher_command(extra=""):
    """pythonw + PulsePC.pyw of the interpreter that runs this script (self-healing entry point)."""
    base = Path(sys.base_prefix) / "pythonw.exe"
    interpreter = base if base.exists() else Path(sys.executable)
    return f'"{interpreter}" "{ROOT / "PulsePC.pyw"}"' + (f" {extra}" if extra else ""), interpreter


def create_shortcut(folder=None):
    """Shortcut «Pulse PC» on the Desktop (or in `folder`)."""
    _, interpreter = launcher_command()
    desktop = Path(os.path.expandvars(r"%USERPROFILE%\Desktop"))
    if folder is not None:
        desktop = Path(folder)
    else:
        try:
            result = subprocess.run(["powershell", "-NoProfile", "-Command",
                                     "[Environment]::GetFolderPath('Desktop')"], capture_output=True, text=True,
                                    creationflags=NO_WINDOW)
            if result.stdout.strip():
                desktop = Path(result.stdout.strip())
        except OSError:
            pass
    target = desktop / "Pulse PC.lnk"
    icon = ROOT / "image" / "icon.ico"
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:PULSE_LNK);"
        "$s.TargetPath=$env:PULSE_TARGET;$s.Arguments=$env:PULSE_ARGS;$s.WorkingDirectory=$env:PULSE_DIR;"
        "$s.IconLocation=$env:PULSE_ICON;$s.Description='Pulse PC';$s.Save()"
    )
    env = dict(os.environ, PULSE_LNK=str(target), PULSE_TARGET=str(interpreter), PULSE_ARGS=f'"{ROOT / "PulsePC.pyw"}"',
               PULSE_DIR=str(ROOT), PULSE_ICON=str(icon))
    done = subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env, capture_output=True, text=True,
                          creationflags=NO_WINDOW)
    if done.returncode != 0 or not target.exists():
        raise SetupError("Не удалось создать ярлык: " + (done.stderr.strip() or "неизвестная ошибка"))
    return target


def set_autostart(enable):
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        if enable:
            command, _ = launcher_command("--minimized")
            winreg.SetValueEx(key, "PulsePC", 0, winreg.REG_SZ, command)
        else:
            for name in ("PulsePC", "PulsePC_Bot"):
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass


# ---------- command line ----------

def main(argv):
    args = set(argv)
    try:
        if "--autostart" in args:
            set_autostart("off" not in args)
            print("Автозагрузка " + ("выключена." if "off" in args else "включена."))
            return 0
        if "--check" in args:
            env = find_ready_env()
            print("Окружение:", env if env else "не готово (запустите install.bat)")
            return 0 if env else 1
        env = prepare(print)
        if "--install" in args:
            if "--no-shortcut" not in args:
                print("Ярлык на рабочем столе:", create_shortcut())
            print("\nУстановка завершена. Запуск: ярлык «Pulse PC» на рабочем столе или файл PulsePC.pyw.")
            return 0
        start(env, [a for a in argv if a in ("--minimized", "-m")])
        return 0
    except SetupError as exc:
        print("\nОШИБКА:", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
