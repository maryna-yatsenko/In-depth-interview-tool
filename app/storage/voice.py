# -*- coding: utf-8 -*-
"""Записи голосу респондента: файли на диску, поруч із транскриптом.

Окремий модуль, бо правила тут інші, ніж у транскриптів, і жорсткіші.

**Голос неможливо деідентифікувати.** Текст ми чистимо на вході (`deidentify`):
телефон, пошта, довгі числа стають масками. З аудіо так не вийде — імʼя,
вимовлене вголос, лишається в записі назавжди, і сам голос теж є персональними
даними. Тому:

- запис ведеться **лише за прямою згодою** респондента, окремою від згоди на
  інтервʼю (`interface.record_voice` у просторі + галочка на екрані згоди);
- «Сказати заново» **видаляє** файл, а не позначає його як скасований: людина
  сказала «цього не було», отже цього не має бути й на диску;
- розмір одного файлу обмежений, щоб помилка в браузері не залила диск.

Розкладка: `data/voice/<session_id>/<номер>.<розширення>`.
"""

import os
from typing import List, Optional

VOICE_DIR = os.path.join(os.getcwd(), "data", "voice")

# 25 МБ на один запис. Opus у браузері дає ~20 кБ/с, тобто це приблизно 20
# хвилин безперервного мовлення на ОДНУ відповідь — межа не тисне на людину,
# але й не дає зламаному клієнту залити диск.
MAX_CLIP_BYTES = 25 * 1024 * 1024

# Що приймаємо. Браузери дають різне: Chrome — webm/opus, Safari — mp4/aac.
_EXTENSIONS = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}

_SAFE = set("abcdefghijklmnopqrstuvwxyz0123456789")


class VoiceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _safe_id(session_id: str) -> str:
    cleaned = "".join(ch for ch in (session_id or "").lower() if ch in _SAFE)
    if not cleaned or cleaned != (session_id or "").lower():
        raise VoiceError("Недопустимий ідентифікатор сесії")
    return cleaned


def extension_for(content_type: str) -> str:
    """Розширення за типом. Параметри (`;codecs=opus`) відкидаємо."""
    base = (content_type or "").split(";")[0].strip().lower()
    if base not in _EXTENSIONS:
        raise VoiceError("Непідтримуваний тип аудіо: %r" % (content_type or ""))
    return _EXTENSIONS[base]


def session_dir(session_id: str, root: Optional[str] = None) -> str:
    return os.path.join(root or VOICE_DIR, _safe_id(session_id))


def save_clip(session_id: str, data: bytes, content_type: str,
              root: Optional[str] = None) -> str:
    """Зберігає один запис і повертає його імʼя файлу.

    Номер беремо з кількості вже наявних файлів: імена мусять бути стабільними,
    бо на них посилається транскрипт.
    """
    if not data:
        raise VoiceError("Порожній запис")
    if len(data) > MAX_CLIP_BYTES:
        raise VoiceError("Запис завеликий: %d байтів (межа %d)"
                         % (len(data), MAX_CLIP_BYTES), status=413)
    ext = extension_for(content_type)
    directory = session_dir(session_id, root)
    os.makedirs(directory, exist_ok=True)
    number = len(os.listdir(directory)) + 1
    name = "%03d%s" % (number, ext)
    path = os.path.join(directory, name)
    # Тимчасовий файл + перейменування: обірваний аплоуд не лишає півзапису,
    # на який уже посилається транскрипт.
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)
    return name


def clip_path(session_id: str, name: str, root: Optional[str] = None) -> str:
    """Шлях до запису з перевіркою, що імʼя не виводить за межі теки."""
    safe = os.path.basename(name or "")
    if not safe or safe.startswith(".") or safe != name:
        raise VoiceError("Недопустиме імʼя файлу")
    directory = session_dir(session_id, root)
    path = os.path.join(directory, safe)
    if not os.path.abspath(path).startswith(os.path.abspath(directory)):
        raise VoiceError("Недопустимий шлях")
    return path


def read_clip(session_id: str, name: str, root: Optional[str] = None) -> bytes:
    path = clip_path(session_id, name, root)
    if not os.path.isfile(path):
        raise VoiceError("Запис не знайдено", status=404)
    with open(path, "rb") as fh:
        return fh.read()


def delete_clips(session_id: str, names: List[str],
                 root: Optional[str] = None) -> int:
    """Видаляє записи. «Сказати заново» мусить прибирати їх із диска."""
    removed = 0
    for name in names or []:
        try:
            path = clip_path(session_id, name, root)
        except VoiceError:
            continue
        if os.path.isfile(path):
            os.remove(path)
            removed += 1
    return removed


def list_clips(session_id: str, root: Optional[str] = None) -> List[str]:
    directory = session_dir(session_id, root)
    if not os.path.isdir(directory):
        return []
    return sorted(name for name in os.listdir(directory)
                  if not name.endswith(".part"))
