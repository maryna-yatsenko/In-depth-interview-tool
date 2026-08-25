"""Локальне сховище: завершені транскрипти і стан незавершених інтервʼю.

Дві теки з різними правилами, і різниця тут принципова:

- `data/sessions/` — **завершені транскрипти**. Первинні дані дослідження:
  пишуться один раз, перезапис заборонений.
- `data/live/` — **стан незавершених** інтервʼю. Перезаписується після кожної
  репліки, видаляється після завершення. Це закриває TD-5: перезапуск сервера
  більше не губить розмову, і респондент може продовжити по тому самому посиланню.
"""

import json
import os
import shutil
from typing import Any, Dict, List, Optional

from . import db as _db
from . import voice as _voice

DEFAULT_DIR = os.path.join(os.getcwd(), "data", "sessions")
LIVE_DIR = os.path.join(os.getcwd(), "data", "live")


def _on_postgres() -> bool:
    """Задеплоєна версія (Vercel) не має файлової системи, яка переживає між
    запитами — там `STORAGE_BACKEND=postgres` перемикає ці самі функції на
    app/storage/db.py. Локально змінна не задана, і нижче нічого не змінюється."""
    return os.environ.get("STORAGE_BACKEND") == "postgres"


def _dir(directory: Optional[str], fallback_name: str) -> str:
    """Теку беремо на момент виклику, а не на момент import.

    Значення за замовчуванням в аргументі функції прив'язалось би один раз при
    завантаженні модуля — і тести (та будь-яка зміна робочої теки) працювали б
    не там, де очікується.
    """
    if directory:
        return directory
    return DEFAULT_DIR if fallback_name == "sessions" else LIVE_DIR

_SAFE = set("abcdefghijklmnopqrstuvwxyz0123456789")


def _safe_id(session_id: str) -> str:
    """Ідентифікатор іде в шлях, тому все, що не hex, — відкидаємо."""
    cleaned = "".join(ch for ch in (session_id or "").lower() if ch in _SAFE)
    if not cleaned or cleaned != (session_id or "").lower():
        raise ValueError("Недопустимий ідентифікатор сесії")
    return cleaned


def _write_atomic(path: str, payload: Dict[str, Any]) -> None:
    """Через тимчасовий файл: обрив посеред запису не має псувати попередній стан."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ── завершені транскрипти ────────────────────────────────────────────────

def save_session(payload: Dict[str, Any], directory: Optional[str] = None) -> str:
    if _on_postgres():
        return _db.save_session(payload)
    directory = _dir(directory, "sessions")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "%s.json" % _safe_id(payload["session_id"]))
    if os.path.exists(path):
        raise FileExistsError("Сесія вже збережена: %s" % path)
    _write_atomic(path, payload)
    return path


def load_session(path: str) -> Dict[str, Any]:
    """Приймає шлях до файлу — лишається робочим лише для локального диска.
    На Postgres дані немає сенсу адресувати шляхом, тому там — load_session_by_id."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_session_by_id(session_id: str) -> Optional[Dict[str, Any]]:
    """На відміну від load_session (шлях), тут — саме ідентифікатор, з
    тим самим _safe_id, що й скрізь. Працює на обох бекендах."""
    if _on_postgres():
        return _db.load_session_by_id(session_id)
    path = os.path.join(_dir(None, "sessions"), "%s.json" % _safe_id(session_id))
    if not os.path.isfile(path):
        return None
    return load_session(path)


def _summarize(data: Dict[str, Any]) -> Dict[str, Any]:
    """Короткі відомості про одне завершене інтервʼю — без вмісту реплік."""
    return {
        "session_id": data.get("session_id"),
        "space": data.get("space"),
        "guide": data.get("guide"),
        "prompt_version": data.get("prompt_version"),
        "started_at": data.get("started_at"),
        "finished_at": data.get("finished_at"),
        "completed": data.get("completed"),
        "turns": len(data.get("turns") or []),
        "topics_covered": len(data.get("topics_covered") or []),
        "incidents": len(data.get("incidents") or []),
        # Записи голосу — щоб дослідник бачив, які інтервʼю можна
        # переслухати, не відкриваючи файл транскрипту.
        "voice_consent": bool(data.get("voice_consent")),
        "voice": [name for turn in (data.get("turns") or [])
                  for name in (turn.get("voice") or [])],
    }


def list_sessions(directory: Optional[str] = None) -> List[Dict[str, Any]]:
    """Короткі відомості про завершені інтервʼю — для адмінки. Без вмісту реплік."""
    if _on_postgres():
        items = [_summarize(data) for data in _db.list_finished_sessions()]
        items.sort(key=lambda item: item.get("started_at") or "", reverse=True)
        return items
    directory = _dir(directory, "sessions")
    if not os.path.isdir(directory):
        return []
    items = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        try:
            data = load_session(os.path.join(directory, name))
        except (ValueError, OSError):
            continue
        items.append(_summarize(data))
    items.sort(key=lambda item: item.get("started_at") or "", reverse=True)
    return items


# ── стан незавершених ────────────────────────────────────────────────────

def save_live(payload: Dict[str, Any], directory: Optional[str] = None) -> str:
    if _on_postgres():
        return _db.save_live(payload)
    directory = _dir(directory, "live")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "%s.json" % _safe_id(payload["session_id"]))
    _write_atomic(path, payload)
    return path


def load_live(session_id: str, directory: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if _on_postgres():
        return _db.load_live(session_id)
    directory = _dir(directory, "live")
    path = os.path.join(directory, "%s.json" % _safe_id(session_id))
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError:
        # Битий файл не має валити сервер: для респондента це «почніть спочатку».
        return None


def drop_live(session_id: str, directory: Optional[str] = None) -> None:
    if _on_postgres():
        _db.drop_live(session_id)
        return
    directory = _dir(directory, "live")
    path = os.path.join(directory, "%s.json" % _safe_id(session_id))
    if os.path.exists(path):
        os.remove(path)


# ── видалення (адмінка: дослідник видаляє інтервʼю разом із даними) ───────

def delete_sessions_for_space(space_key: str) -> int:
    """Прибирає завершені й незавершені сесії цього простору разом із
    голосовими записами. Повертає кількість видалених завершених сесій —
    для підтвердження в панелі."""
    if _on_postgres():
        return _db.delete_sessions_for_space(space_key)

    session_ids = []
    removed = 0

    finished_dir = _dir(None, "sessions")
    if os.path.isdir(finished_dir):
        for name in list(os.listdir(finished_dir)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(finished_dir, name)
            try:
                data = load_session(path)
            except ValueError:
                continue
            if data.get("space") != space_key:
                continue
            session_ids.append(data.get("session_id") or name[:-5])
            os.remove(path)
            removed += 1

    live_dir = _dir(None, "live")
    if os.path.isdir(live_dir):
        for name in list(os.listdir(live_dir)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(live_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except ValueError:
                continue
            if data.get("space") != space_key:
                continue
            session_ids.append(data.get("session_id") or name[:-5])
            os.remove(path)

    for session_id in session_ids:
        directory = _voice.session_dir(session_id)
        if os.path.isdir(directory):
            shutil.rmtree(directory, ignore_errors=True)

    return removed
