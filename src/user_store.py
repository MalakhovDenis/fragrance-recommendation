import json
import os
import re

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "users.json")


def _load() -> dict:
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_profile_id(telegram_id: int) -> str | None:
    return _load().get(str(telegram_id))


def set_profile_id(telegram_id: int, profile_id: str):
    data = _load()
    data[str(telegram_id)] = profile_id
    _save(data)


def extract_profile_id(text: str) -> str | None:
    """Извлекает ID профиля из URL вида https://www.fragrantica.ru/chlen/462653."""
    m = re.search(r"/chlen/(\d+)", text)
    if m:
        return m.group(1)
    # Просто число
    m = re.match(r"^\s*(\d{4,8})\s*$", text)
    if m:
        return m.group(1)
    return None
