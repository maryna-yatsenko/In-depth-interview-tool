"""Локальне сховище: завершені транскрипти і стан незавершених інтервʼю.

Три теки з різними правилами, і різниця тут принципова:

- `local/data/sessions/` — **завершені транскрипти**, JSON. Первинні дані
  дослідження: пишуться один раз, перезапис заборонений.
- `local/data/live/` — **стан незавершених** інтервʼю. Перезаписується після
  кожної репліки, видаляється після завершення. Це закриває TD-5: перезапуск
  сервера більше не губить розмову, і респондент може продовжити по тому
  самому посиланню.
- `local/data/responses/` — те саме, що й `sessions/`, але розкладено по
  теках для людини, а не для коду: одна тека на респондента, у ній — одна
  тека на кожне питання з `питання.txt`/`відповідь.txt`. Похідне (JSON у
  `sessions/` лишається єдиним джерелом істини), тому цю теку можна вільно
  чистити й перегенеровувати — вона просто зручніша для ручного перегляду.
"""

import json
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from . import db as _db
from . import voice as _voice

DEFAULT_DIR = os.path.join(os.getcwd(), "local", "data", "sessions")
LIVE_DIR = os.path.join(os.getcwd(), "local", "data", "live")


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

def _slug(text: str, limit: int = 40) -> str:
    """Питання — у назву теки: лишаємо літери/цифри/пробіли, пробіли — в дефіси."""
    cleaned = "".join(ch for ch in (text or "").strip() if ch.isalnum() or ch in " -")
    return "-".join(cleaned.split())[:limit].strip("-") or "питання"


def _qa_pairs(turns: List[Dict[str, Any]]) -> List[Tuple[str, Optional[str]]]:
    """Репліки — плаский список `interviewer`/`respondent` по черзі. Пара —
    питання інтервʼюера і відповідь одразу після нього (якщо респондент
    ще не встиг відповісти — там `None`, а не вигадана відповідь)."""
    pairs = []
    i, n = 0, len(turns)
    while i < n:
        if turns[i].get("role") == "interviewer":
            question = turns[i].get("text", "")
            answer = None
            if i + 1 < n and turns[i + 1].get("role") == "respondent":
                answer = turns[i + 1].get("text", "")
                i += 2
            else:
                i += 1
            pairs.append((question, answer))
        else:
            i += 1
    return pairs


def _respondent_folder(payload: Dict[str, Any]) -> str:
    started = (payload.get("started_at") or "").replace("-", "").replace(":", "").replace("T", "-")
    short_id = _safe_id(payload["session_id"])[:6]
    return "%s_%s" % (started or "невідомо-коли", short_id)


def _export_responses(payload: Dict[str, Any], sessions_dir: str) -> None:
    """Похідна, читабельна копія `sessions/` — не джерело істини, тому без
    атомарного запису й без заборони перезапису: просто розкладає те саме
    по теках, щоб можна було відкрити Finder і подивитись, а не парсити JSON.

    Тека — сусідня з тим, куди щойно ліг сам JSON (`sessions_dir`), а не
    окрема глобальна константа: `DEFAULT_DIR` тести підміняють на тимчасову
    теку (`test_api.py`), і якщо рахувати звідси, а не від власної незалежної
    змінної, підміна сама поширюється й сюди — без цього кожен такий тест
    писав би читабельний розклад у справжню теку проєкту, а не в пісочницю.
    """
    folder = os.path.join(os.path.dirname(sessions_dir), "responses", _respondent_folder(payload))
    for idx, (question, answer) in enumerate(_qa_pairs(payload.get("turns") or []), start=1):
        qdir = os.path.join(folder, "%02d-%s" % (idx, _slug(question)))
        os.makedirs(qdir, exist_ok=True)
        with open(os.path.join(qdir, "питання.txt"), "w", encoding="utf-8") as fh:
            fh.write(question or "")
        with open(os.path.join(qdir, "відповідь.txt"), "w", encoding="utf-8") as fh:
            fh.write("(без відповіді)" if answer is None else answer)


def save_session(payload: Dict[str, Any], directory: Optional[str] = None) -> str:
    if _on_postgres():
        return _db.save_session(payload)
    directory = _dir(directory, "sessions")
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "%s.json" % _safe_id(payload["session_id"]))
    if os.path.exists(path):
        raise FileExistsError("Сесія вже збережена: %s" % path)
    _write_atomic(path, payload)
    _export_responses(payload, directory)
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
