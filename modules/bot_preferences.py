"""Validated, atomic preferences shared by Telegram and the desktop editor."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading

import config

LOCK = threading.RLock()
FAVORITE_ACTIONS = {
    "sys_screenshot": "Скриншот", "menu_files": "Файлы", "sys_info": "Состояние ПК",
    "media_play": "Пауза / воспроизведение", "media_mute": "Звук",
    "menu_windows": "Окна", "menu_power": "Таймер выключения", "menu_history": "История файлов",
}
DEFAULTS = {
    "device_name": "", "greeting": "Ваш компьютер — под рукой.",
    "show_device": True, "show_time": True, "show_programs": True, "show_tips": True,
    "favorites": [], "scenarios": [],
    "alerts": {"enabled": False, "cpu_enabled": True, "cpu_percent": 90,
               "cpu_seconds": 60, "disk_enabled": True, "disk_free_gb": 5,
               "interval_seconds": 10, "cooldown_minutes": 15, "processes": []},
}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pulse-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def validate_preferences(value):
    if not isinstance(value, dict):
        raise ValueError("Настройки бота должны быть объектом JSON.")
    result = deepcopy(DEFAULTS)
    result.update(value)
    for key, limit in (("device_name", 80), ("greeting", 300)):
        if not isinstance(result[key], str) or len(result[key]) > limit:
            raise ValueError(f"Поле {key}: максимум {limit} символов.")
    for key in ("show_device", "show_time", "show_programs", "show_tips"):
        if type(result[key]) is not bool:
            raise ValueError(f"Поле {key} должно быть переключателем.")
    favorites = result["favorites"]
    if not isinstance(favorites, list) or len(favorites) > 6 or len(set(map(str, favorites))) != len(favorites):
        raise ValueError("Выберите до 6 разных избранных действий.")
    for item in favorites:
        if not isinstance(item, str) or not (item in FAVORITE_ACTIONS or (item.startswith("program:") and 0 < len(item[8:]) <= 48)):
            raise ValueError("Неизвестное избранное действие.")
    scenarios = result["scenarios"]
    if not isinstance(scenarios, list) or len(scenarios) > 20:
        raise ValueError("Можно сохранить до 20 сценариев.")
    ids = set()
    for item in scenarios:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].isalnum() or len(item["id"]) > 32 or item["id"] in ids:
            raise ValueError("Некорректный ID сценария.")
        ids.add(item["id"])
        if not isinstance(item.get("name"), str) or not 1 <= len(item["name"].strip()) <= 50:
            raise ValueError("Назовите сценарий: до 50 символов.")
        programs = item.get("program_ids")
        if not isinstance(programs, list) or not 1 <= len(programs) <= 15 or any(not isinstance(key, str) or not key or len(key) > 48 for key in programs) or len(set(programs)) != len(programs):
            raise ValueError("Выберите от 1 до 15 разных программ для сценария.")
    alerts = value.get("alerts", {})
    if not isinstance(alerts, dict):
        raise ValueError("Некорректные настройки уведомлений.")
    result["alerts"] = {**DEFAULTS["alerts"], **alerts}
    alerts = result["alerts"]
    for key in ("enabled", "cpu_enabled", "disk_enabled"):
        if type(alerts[key]) is not bool:
            raise ValueError("Некорректный переключатель уведомлений.")
    for key, low, high in (("cpu_percent", 1, 100), ("cpu_seconds", 10, 3600),
                           ("disk_free_gb", 1, 1000), ("interval_seconds", 5, 300), ("cooldown_minutes", 1, 1440)):
        if type(alerts[key]) is not int or not low <= alerts[key] <= high:
            raise ValueError(f"Параметр {key}: допустимо {low}–{high}.")
    if not isinstance(alerts["processes"], list) or len(alerts["processes"]) > 20 or any(not isinstance(p, str) or not p.strip() or len(p) > 100 or any(c in p for c in '/\\') for p in alerts["processes"]):
        raise ValueError("Укажите до 20 имён процессов, например obs64.exe.")
    return result


def load_preferences():
    with LOCK:
        path = Path(config.BASE_DIR) / "bot_options.json"
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return validate_preferences(value)


def save_preferences(value):
    validated = validate_preferences(value)
    with LOCK:
        # A malformed existing file must never be silently overwritten.
        current = load_preferences()
        current.update(validated)
        atomic_json(Path(config.BASE_DIR) / "bot_options.json", current)

