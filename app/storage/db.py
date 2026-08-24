# -*- coding: utf-8 -*-
"""Postgres-шар зберігання — лише коли `STORAGE_BACKEND=postgres`.

Не для локальної розробки: там `local.py`/`voice.py` й далі працюють із
диском напряму, як і завжди. Це існує тільки для задеплоєної версії
(Vercel), де файлова система не переживає між запитами — диск там не
джерело істини, ним просто немає.

Підключення — одне на викоик, без пулу: на Hobby-тарифі й з одним-двома
одночасними респондентами це прийнятний компроміс для першої версії. Якщо
з'явиться помітна кількість одночасних з'єднань — тут і буде видно
(помилки пулу провайдера), і тоді додати пул (`psycopg2.pool` або пулер
самого провайдера Postgres).

Функції тут повторюють за формою те, що вже робить `local.py`/`voice.py`
на диску, — той самий виняток (`FileExistsError`), той самий `None` для
відсутнього. Викликачі (`SessionStore`, `admin.py`) про це не знають:
для них це просто інша реалізація тих самих функцій.
"""

import json
import os
from typing import Any, Dict, List, Optional

_SCHEMA_READY = False
_SAFE = set("abcdefghijklmnopqrstuvwxyz0123456789")


def _safe_id(session_id: str) -> str:
    """Той самий фільтр, що й у local.py/voice.py — навмисно окремий, щоб
    db.py не тягнув імпорт назад у local.py й не створював цикл."""
    cleaned = "".join(ch for ch in (session_id or "").lower() if ch in _SAFE)
    if not cleaned or cleaned != (session_id or "").lower():
        raise ValueError("Недопустимий ідентифікатор сесії")
    return cleaned


def _dsn() -> str:
    dsn = (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
           or os.environ.get("POSTGRES_PRISMA_URL"))
    if not dsn:
        raise RuntimeError(
            "STORAGE_BACKEND=postgres, але рядок з'єднання не знайдено "
            "(DATABASE_URL / POSTGRES_URL) — перевір змінні середовища проєкту."
        )
    return dsn


def _connect():
    import psycopg2
    return psycopg2.connect(_dsn())


def ensure_schema() -> None:
    """Таблиці створюються самі при першому зверненні — без окремого кроку
    міграції для такого маленького інструменту."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS live_sessions (
                    id TEXT PRIMARY KEY,
                    data JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS finished_sessions (
                    id TEXT PRIMARY KEY,
                    data JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS voice_clips (
                    session_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    data BYTEA NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (session_id, name)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS config_overrides (
                    space_key TEXT NOT NULL,
                    path TEXT NOT NULL,
                    content BYTEA NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (space_key, path)
                )
            """)
        conn.commit()
    _SCHEMA_READY = True


# ── завершені транскрипти ────────────────────────────────────────────────

def save_session(payload: Dict[str, Any]) -> str:
    ensure_schema()
    session_id = _safe_id(payload["session_id"])
    body = json.dumps(payload, ensure_ascii=False)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO finished_sessions (id, data) VALUES (%s, %s) "
                "ON CONFLICT (id) DO NOTHING",
                (session_id, body),
            )
            if cur.rowcount == 0:
                conn.rollback()
                raise FileExistsError("Сесія вже збережена: %s" % session_id)
        conn.commit()
    return session_id


def load_session_by_id(session_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    session_id = _safe_id(session_id)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT data FROM finished_sessions WHERE id = %s", (session_id,))
            row = cur.fetchone()
    return row[0] if row else None


def list_finished_sessions() -> List[Dict[str, Any]]:
    """Повні payload-и завершених сесій — підсумок будує та сама логіка,
    що й для диска (`local.py::list_sessions`), лише джерело інше."""
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT data FROM finished_sessions")
            rows = cur.fetchall()
    return [row[0] for row in rows]


# ── стан незавершених ────────────────────────────────────────────────────

def save_live(payload: Dict[str, Any]) -> str:
    ensure_schema()
    session_id = _safe_id(payload["session_id"])
    body = json.dumps(payload, ensure_ascii=False)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO live_sessions (id, data, updated_at) VALUES (%s, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()",
                (session_id, body),
            )
        conn.commit()
    return session_id


def load_live(session_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    session_id = _safe_id(session_id)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT data FROM live_sessions WHERE id = %s", (session_id,))
            row = cur.fetchone()
    return row[0] if row else None


def drop_live(session_id: str) -> None:
    ensure_schema()
    session_id = _safe_id(session_id)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM live_sessions WHERE id = %s", (session_id,))
        conn.commit()


# ── голосові записи ───────────────────────────────────────────────────────

def save_voice_clip(session_id: str, name: str, content_type: str, data: bytes) -> None:
    ensure_schema()
    session_id = _safe_id(session_id)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO voice_clips (session_id, name, content_type, data) "
                "VALUES (%s, %s, %s, %s)",
                (session_id, name, content_type, data),
            )
        conn.commit()


def next_voice_clip_number(session_id: str) -> int:
    """Номер наступного запису — під advisory-локом на ідентифікатор сесії,
    щоб два майже одночасні аплоуди (той самий респондент) не отримали
    однаковий номер. Лишається чинним лише на час транзакції."""
    ensure_schema()
    session_id = _safe_id(session_id)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (session_id,))
            cur.execute("SELECT COUNT(*) FROM voice_clips WHERE session_id = %s", (session_id,))
            count = cur.fetchone()[0]
        conn.commit()
    return count + 1


def read_voice_clip(session_id: str, name: str) -> Optional[bytes]:
    ensure_schema()
    session_id = _safe_id(session_id)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT data FROM voice_clips WHERE session_id = %s AND name = %s",
                (session_id, name),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return bytes(row[0])


def delete_voice_clips(session_id: str, names: List[str]) -> int:
    ensure_schema()
    session_id = _safe_id(session_id)
    if not names:
        return 0
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM voice_clips WHERE session_id = %s AND name = ANY(%s)",
                (session_id, list(names)),
            )
            removed = cur.rowcount
        conn.commit()
    return removed


def list_voice_clips(session_id: str) -> List[str]:
    ensure_schema()
    session_id = _safe_id(session_id)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name FROM voice_clips WHERE session_id = %s ORDER BY name",
                (session_id,),
            )
            rows = cur.fetchall()
    return [row[0] for row in rows]


# ── перевизначення конфігів (адмінка на живому сайті) ────────────────────

def get_config_override(space_key: str, path: str) -> Optional[bytes]:
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content FROM config_overrides WHERE space_key = %s AND path = %s",
                (space_key, path),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return bytes(row[0])


def put_config_override(space_key: str, path: str, content: bytes) -> None:
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO config_overrides (space_key, path, content, updated_at) "
                "VALUES (%s, %s, %s, now()) "
                "ON CONFLICT (space_key, path) DO UPDATE "
                "SET content = EXCLUDED.content, updated_at = now()",
                (space_key, path, content),
            )
        conn.commit()


def list_config_override_spaces() -> List[str]:
    """Ключі просторів, які існують ЛИШЕ в базі — новий простір, створений
    через адмінку на живому сайті, не з'явиться на диску деплою (той
    незмінний під час роботи), тож без цього списку список просторів
    показував би тільки те, що приїхало разом із кодом."""
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT space_key FROM config_overrides ORDER BY space_key")
            rows = cur.fetchall()
    return [row[0] for row in rows]


def list_config_override_paths(space_key: str) -> List[str]:
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT path FROM config_overrides WHERE space_key = %s ORDER BY path",
                (space_key,),
            )
            rows = cur.fetchall()
    return [row[0] for row in rows]


def delete_config_override(space_key: str, path: str) -> None:
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM config_overrides WHERE space_key = %s AND path = %s",
                (space_key, path),
            )
        conn.commit()
