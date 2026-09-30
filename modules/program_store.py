"""Common validation for the desktop editor and Telegram menus."""
import re
import os
from pathlib import Path


def executable_process(path):
    target = Path(os.path.expandvars(path))
    if target.suffix.lower() == ".lnk":
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            target = Path(win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(target)).TargetPath)
        except Exception:
            return ""
        finally:
            pythoncom.CoUninitialize()
    return target.name if target.suffix.lower() == ".exe" else ""


def effective_process(program):
    path = program.get("path", "")
    if Path(path).suffix.lower() in (".lnk", ".cmd", ".bat"):
        return executable_process(path)
    return program.get("process") or executable_process(path)


def validate_programs(programs):
    if not isinstance(programs, list):
        raise ValueError("Ожидается список программ с названием и путём.")
    ids = set()
    for program in programs:
        if not isinstance(program, dict) or any(not isinstance(program.get(key), str) or not program[key].strip() for key in ("name", "path")):
            raise ValueError("У каждой программы должны быть название и путь.")
        if "process" in program and not isinstance(program["process"], str):
            raise ValueError("Имя процесса должно быть строкой.")
        if "id" in program:
            key = program["id"]
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", key) or key in ids:
                raise ValueError("ID программ должны быть уникальными: 1–48 букв, цифр, _ или -.")
            ids.add(key)
    return programs
