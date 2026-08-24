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
from typing import Any, Dict, List, Optional

DEFAULT_DIR = os.path.join(os.getcwd(), "data", "sessions")
LIVE_DIR = os.path.join(os.getcwd(), "data", "live")


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
    directory = _dir(directory, "sessions")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "%s.json" % _safe_id(payload["session_id"]))
    if os.path.exists(path):
        raise FileExistsError("Сесія вже збережена: %s" % path)
    _write_atomic(path, payload)
    return path


def load_session(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def list_sessions(directory: Optional[str] = None) -> List[Dict[str, Any]]:
    """Короткі відомості про завершені інтервʼю — для адмінки. Без вмісту реплік."""
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
        items.append({
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
        })
    items.sort(key=lambda item: item.get("started_at") or "", reverse=True)
    return items


# ── стан незавершених ────────────────────────────────────────────────────

def save_live(payload: Dict[str, Any], directory: Optional[str] = None) -> str:
    directory = _dir(directory, "live")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "%s.json" % _safe_id(payload["session_id"]))
    _write_atomic(path, payload)
    return path


def load_live(session_id: str, directory: Optional[str] = None) -> Optional[Dict[str, Any]]:
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
    directory = _dir(directory, "live")
    path = os.path.join(directory, "%s.json" % _safe_id(session_id))
    if os.path.exists(path):
        os.remove(path)
