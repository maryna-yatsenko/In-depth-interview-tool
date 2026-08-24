"""Адмінка дослідника: простори, гайди, транскрипти.

⚠️ Вимкнена за замовчуванням (`serve.py --admin`). Причина не в паранойї: та сама
програма віддає сторінку респондента, і колись її виставлять у зовнішній світ.
Якщо адмінка ввімкнена прапорцем, публічний запуск просто не має її взагалі —
це надійніше за пароль, який колись забудуть поставити.

Правило записи: спершу валідація тим самим завантажувачем, що й у продукційному
шляху, і лише потім заміна файла. Інакше зламаний гайд ляже на диск і завалить
наступне інтервʼю, а не форму.
"""

import json
import os
import re
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from ..config.phrases import KINDS, PhraseError, load_bank, save_bank
from ..config.space import ConfigError, load_guide, load_space
from ..interview import guard
from ..storage import db as store_db
from ..storage import local as store_files

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


def _on_postgres() -> bool:
    """На Vercel код деплою незмінний під час роботи — правки з адмінки не
    можуть лишитись на диску між запитами. Тому там конфіги читаються й
    пишуться через config_overrides у Postgres, а файли в репозиторії
    лишаються лише початковим наповненням (побачити його ще раз можна,
    видаливши відповідний рядок у базі — інтерфейсу для цього поки нема,
    це свідомо відкладено, див. план міграції)."""
    return os.environ.get("STORAGE_BACKEND") == "postgres"


def _rel_path(root: str, space_key: str, path: str) -> str:
    return os.path.relpath(path, os.path.join(root, space_key)).replace(os.sep, "/")


def _read_bytes(root: str, space_key: str, path: str) -> Optional[bytes]:
    """Спершу перевизначення з Postgres (якщо колись редагували на живому
    сайті), інакше — файл із репозиторію. Локально (без STORAGE_BACKEND)
    завжди файл, як і раніше."""
    if _on_postgres():
        content = store_db.get_config_override(space_key, _rel_path(root, space_key, path))
        if content is not None:
            return content
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


def _write_bytes(root: str, space_key: str, path: str, content: bytes) -> None:
    if _on_postgres():
        store_db.put_config_override(space_key, _rel_path(root, space_key, path), content)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(content)
    os.replace(tmp, path)


def _load_json_aware(root: str, space_key: str, path: str):
    """Сирий JSON — байдуже, рядком у Postgres чи файлом у репозиторії.
    Для готових обʼєктів (SpaceConfig/Guide) є _load_validated_aware — тут
    лише те, що адмінка показує назад у формі, без валідації."""
    content = _read_bytes(root, space_key, path)
    if content is None:
        return None
    return json.loads(content.decode("utf-8"))


def _load_validated_aware(root: str, space_key: str, path: str, loader):
    """Те саме, що завантажувач (`load_space`/`load_guide`) робить із
    файлом, — але вміст може лежати в config_overrides, а не на диску.
    Матеріалізуємо у тимчасовий файл, бо самі завантажувачі й тести на них
    свідомо лишились «шлях → дані», без жодної згадки про Postgres."""
    content = _read_bytes(root, space_key, path)
    if content is None:
        raise ConfigError("%s не знайдено" % os.path.basename(path))
    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        return loader(tmp)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


class AdminError(Exception):
    def __init__(self, message: str, status: int = 400):
        Exception.__init__(self, message)
        self.status = status


def _check_key(key: str, what: str) -> str:
    if not key or not KEY_RE.match(key):
        raise AdminError(
            "Недопустимий ключ %s: '%s'. Дозволені малі латинські літери, цифри, дефіс і підкреслення."
            % (what, key)
        )
    return key


def _space_dir(root: str, space_key: str) -> str:
    path = os.path.join(root, _check_key(space_key, "простору"))
    if os.path.isdir(path):
        return path
    # Простір, створений через адмінку на живому сайті, не має локальної
    # теки взагалі — код деплою незмінний. Існує, якщо для нього є хоч
    # один рядок у config_overrides.
    if _on_postgres() and store_db.list_config_override_paths(space_key):
        return path
    raise AdminError("Простору '%s' не існує" % space_key, 404)


def _write_validated(root: str, space_key: str, path: str, data: Dict[str, Any],
                      validator) -> None:
    """Валідація на копії, і тільки потім — заміна файла (локально) або
    рядка в config_overrides (на Vercel). Валідатору однаково потрібен
    справжній файл на диску (він читає його сам), тому тимчасовий файл
    лишається тимчасовим файлом незалежно від бекенду — лише останній крок
    («куди піде вже перевірений вміст») різниться."""
    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        try:
            validator(tmp)
        except ConfigError as exc:
            raise AdminError(str(exc))
        with open(tmp, "rb") as fh:
            content = fh.read()
        _write_bytes(root, space_key, path, content)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)


# ── читання ──────────────────────────────────────────────────────────────

def list_spaces(root: str) -> List[Dict[str, Any]]:
    names = set(os.listdir(root)) if os.path.isdir(root) else set()
    if _on_postgres():
        # Простір, створений через адмінку на живому сайті, не лежить у
        # коді деплою взагалі — без цього його не було б видно в переліку.
        names |= set(store_db.list_config_override_spaces())
    if not names:
        return []
    items = []
    for name in sorted(names):
        space_path = os.path.join(root, name, "space.json")
        if _read_bytes(root, name, space_path) is None:
            continue
        entry = {"key": name, "title": name, "guides": [], "error": None, "draft": False}
        try:
            space = _load_validated_aware(root, name, space_path, load_space)
            entry["title"] = space.title
            entry["languages"] = space.languages
            entry["draft"] = space.draft
        except (ConfigError, ValueError, OSError) as exc:
            # Зламаний простір показуємо з помилкою, а не ховаємо: інакше
            # дослідник шукатиме, куди зник його конфіг.
            entry["error"] = str(exc)
        guides_dir = os.path.join(root, name, "guides")
        guide_names = set()
        if os.path.isdir(guides_dir):
            guide_names |= {f[:-5] for f in os.listdir(guides_dir) if f.endswith(".json")}
        if _on_postgres():
            guide_names |= {
                p[len("guides/"):-5] for p in store_db.list_config_override_paths(name)
                if p.startswith("guides/") and p.endswith(".json")
            }
        entry["guides"] = sorted(guide_names)
        items.append(entry)
    return items


def read_space(root: str, space_key: str) -> Dict[str, Any]:
    _space_dir(root, space_key)
    path = os.path.join(root, space_key, "space.json")
    data = _load_json_aware(root, space_key, path)
    if data is None:
        raise AdminError("Простору '%s' не існує" % space_key, 404)
    return data


def read_guide(root: str, space_key: str, guide_key: str) -> Dict[str, Any]:
    _space_dir(root, space_key)
    path = os.path.join(root, space_key, "guides", "%s.json" % _check_key(guide_key, "гайда"))
    data = _load_json_aware(root, space_key, path)
    if data is None:
        raise AdminError("Гайда '%s' не існує" % guide_key, 404)
    return data


def read_transcript(session_id: str) -> Dict[str, Any]:
    data = store_files.load_session_by_id(session_id)
    if data is None:
        raise AdminError("Транскрипт не знайдено", 404)
    return data


# ── запис ────────────────────────────────────────────────────────────────

def write_space(root: str, space_key: str, data: Dict[str, Any]) -> Dict[str, Any]:
    space_dir = _space_dir(root, space_key)
    path = os.path.join(space_dir, "space.json")
    data = dict(data or {})
    data["key"] = space_key
    _write_validated(root, space_key, path, data, load_space)
    return {"ok": True, "key": space_key}


def write_guide(root: str, space_key: str, guide_key: str, data: Dict[str, Any]) -> Dict[str, Any]:
    space_dir = _space_dir(root, space_key)
    guides_dir = os.path.join(space_dir, "guides")
    if not _on_postgres():
        # На Vercel код деплою лише читається — теки там не створюємо, і не
        # треба: config_overrides не має «тек» узагалі, лише шляхи-рядки.
        os.makedirs(guides_dir, exist_ok=True)
    _check_key(guide_key, "гайда")
    data = dict(data or {})
    data["key"] = guide_key
    _write_validated(root, space_key, os.path.join(guides_dir, "%s.json" % guide_key),
                      data, load_guide)
    return {"ok": True, "space": space_key, "guide": guide_key}


def create_space(root: str, space_key: str, title: str, template: str = "example") -> Dict[str, Any]:
    _check_key(space_key, "простору")
    target = os.path.join(root, space_key)
    if os.path.isdir(target) or (_on_postgres() and store_db.list_config_override_paths(space_key)):
        raise AdminError("Простір '%s' уже існує" % space_key, 409)
    source = os.path.join(root, _check_key(template, "шаблону"))
    if not os.path.isdir(source):
        raise AdminError("Шаблон '%s' не знайдено" % template, 404)

    if _on_postgres():
        # Немає shutil.copytree: код деплою на Vercel незмінний під час
        # роботи. Копіюємо вміст шаблону в config_overrides рядок за рядком
        # — читаємо його ще з бандла (це можна), пишемо вже в базу.
        for dirpath, _dirs, files in os.walk(source):
            for filename in files:
                src_path = os.path.join(dirpath, filename)
                rel = _rel_path(root, template, src_path)
                with open(src_path, "rb") as fh:
                    store_db.put_config_override(space_key, rel, fh.read())
    else:
        shutil.copytree(source, target)
    _blank_domain_content(root, space_key, title or space_key)
    return {"ok": True, "key": space_key, "draft": True}


def _blank_domain_content(root: str, space_key: str, title: str) -> None:
    """Структуру шаблону лишаємо, доменний зміст — прибираємо.

    Інакше новий простір «Онбординг» вітає респондента розповіддю про
    велосипеди з прикладу — і це виявляється вже після інтервʼю.
    """
    space_path = os.path.join(root, space_key, "space.json")
    data = _load_json_aware(root, space_key, space_path) or {}
    data["key"] = space_key
    data["title"] = title
    data["draft"] = True
    data.pop("_comment", None)
    data["persona"] = dict(data.get("persona") or {})
    data["persona"]["self_intro"] = "TODO: як інтервʼюер представляється респонденту"
    data["domain_vocabulary"] = []
    privacy = dict(data.get("privacy") or {})
    privacy["never_ask_about"] = []
    privacy["deidentify"] = False
    privacy["consent_text"] = "TODO: текст згоди"
    data["privacy"] = privacy
    data["report_sections"] = []
    branding = dict(data.get("branding") or {})
    branding["page_title"] = title
    data["branding"] = branding
    _write_validated(root, space_key, space_path, data, load_space)

    guides_dir = os.path.join(root, space_key, "guides")
    if _on_postgres():
        guide_names = sorted(
            os.path.basename(p) for p in store_db.list_config_override_paths(space_key)
            if p.startswith("guides/") and p.endswith(".json")
        )
    else:
        guide_names = sorted(n for n in os.listdir(guides_dir) if n.endswith(".json"))
    for name in guide_names:
        path = os.path.join(guides_dir, name)
        guide = _load_json_aware(root, space_key, path) or {}
        guide.pop("_comment", None)
        guide["goal"] = "TODO: що саме треба зрозуміти"
        guide["opening"] = "TODO: перше питання — однакове для всіх респондентів"
        guide["closing"] = "TODO: подяка без резюме"
        guide["topics"] = [{
            "id": "topic-1",
            "title": "TODO: назва теми",
            "must_learn": ["TODO: що треба зʼясувати"],
            "max_probes": 4,
        }]
        _write_validated(root, space_key, path, guide, load_guide)


# ── банк реплік ──────────────────────────────────────────────────────────
#
# ⚠️ Свідомо лишається лише на локальному диску — не Postgres-aware, як усе
# вище. `repertoire: "bank"` не використовує жоден задеплоєний простір
# (обидва — "free"), тож на Vercel цей розділ функціонально недоступний,
# доки хтось не захоче саме банк реплік у хмарі. Тоді і варто перенести.

AUDIO_EXT = {
    "audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".mp4",
    "audio/x-m4a": ".m4a", "audio/wav": ".wav", "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
}


def read_phrases(root: str, space_key: str) -> Dict[str, Any]:
    """Банк для панелі: що записано, чого не хватає, і де формулювання підозріле.

    Перевірка формулювань тут не для краси. Банк — це і є методологія: якщо в
    ньому лежить навідне питання, воно піде всім респондентам однаково. Дешевше
    побачити це під час запису, ніж у транскриптах.
    """
    space_dir = _space_dir(root, space_key)
    bank = load_bank(space_dir)
    guide_key = None
    guides_dir = os.path.join(space_dir, "guides")
    if os.path.isdir(guides_dir):
        files = sorted(f for f in os.listdir(guides_dir) if f.endswith(".json"))
        guide_key = files[0][:-5] if files else None

    topic_ids = []
    if guide_key:
        try:
            guide = load_guide(os.path.join(guides_dir, "%s.json" % guide_key))
            topic_ids = [t.id for t in guide.topics]
        except ConfigError:
            topic_ids = []

    items = []
    for phrase in bank.phrases:
        items.append({
            "id": phrase.id,
            "kind": phrase.kind,
            "text": phrase.text,
            "topic_id": phrase.topic_id,
            "recorded": phrase.recorded,
            "audio": phrase.audio,
            "warnings": guard.check(phrase.text),
        })
    return {
        "phrases": items,
        "gaps": bank.missing_for_interview(topic_ids),
        "topics": topic_ids,
        "kinds": list(KINDS),
    }


def write_phrases(root: str, space_key: str, phrases: List[Dict[str, Any]]) -> Dict[str, Any]:
    space_dir = _space_dir(root, space_key)
    existing = {p.id: p.audio for p in load_bank(space_dir).phrases}

    cleaned = []
    seen = set()
    for raw in phrases or []:
        pid = (raw.get("id") or "").strip()
        if not pid or not KEY_RE.match(pid):
            raise AdminError("Недопустимий id репліки: «%s»" % pid)
        if pid in seen:
            raise AdminError("Дубльований id репліки: «%s»" % pid)
        seen.add(pid)
        if raw.get("kind") not in KINDS:
            raise AdminError("Репліка «%s»: невідомий тип" % pid)
        if not (raw.get("text") or "").strip():
            raise AdminError("Репліка «%s» без тексту" % pid)
        item = {"id": pid, "kind": raw["kind"], "text": raw["text"].strip()}
        if raw.get("topic_id"):
            item["topic_id"] = raw["topic_id"]
        # Запис прив'язаний до id: перейменування id губить аудіо, і це
        # видно одразу в панелі, а не при першому інтервʼю.
        if existing.get(pid):
            item["audio"] = existing[pid]
        cleaned.append(item)

    save_bank(space_dir, cleaned)
    return {"ok": True, "count": len(cleaned)}


def save_phrase_audio(root: str, space_key: str, phrase_id: str,
                      content_type: str, data: bytes) -> Dict[str, Any]:
    if not data:
        raise AdminError("Порожній запис")
    if len(data) > 20 * 1024 * 1024:
        raise AdminError("Запис завеликий (більше 20 МБ)")
    ext = AUDIO_EXT.get((content_type or "").split(";")[0].strip().lower())
    if not ext:
        raise AdminError("Невідомий формат аудіо: %s" % content_type)

    space_dir = _space_dir(root, space_key)
    _check_key(phrase_id, "репліки")
    bank = load_bank(space_dir)
    phrase = bank.by_id(phrase_id)
    if phrase is None:
        raise AdminError("Репліки «%s» немає в банку" % phrase_id, 404)

    audio_dir = os.path.join(space_dir, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    filename = "%s%s" % (phrase_id, ext)
    with open(os.path.join(audio_dir, filename), "wb") as fh:
        fh.write(data)

    # Старий запис іншого формату прибираємо, щоб не лишався сирота.
    for other in os.listdir(audio_dir):
        if other != filename and os.path.splitext(other)[0] == phrase_id:
            os.remove(os.path.join(audio_dir, other))

    items = []
    for item in bank.phrases:
        entry = {"id": item.id, "kind": item.kind, "text": item.text}
        if item.topic_id:
            entry["topic_id"] = item.topic_id
        entry["audio"] = filename if item.id == phrase_id else item.audio
        if not entry["audio"]:
            entry.pop("audio")
        items.append(entry)
    save_bank(space_dir, items)
    return {"ok": True, "id": phrase_id, "audio": filename, "bytes": len(data)}


def delete_phrase_audio(root: str, space_key: str, phrase_id: str) -> Dict[str, Any]:
    space_dir = _space_dir(root, space_key)
    _check_key(phrase_id, "репліки")
    bank = load_bank(space_dir)
    audio_dir = os.path.join(space_dir, "audio")
    if os.path.isdir(audio_dir):
        for other in os.listdir(audio_dir):
            if os.path.splitext(other)[0] == phrase_id:
                os.remove(os.path.join(audio_dir, other))

    items = []
    for item in bank.phrases:
        entry = {"id": item.id, "kind": item.kind, "text": item.text}
        if item.topic_id:
            entry["topic_id"] = item.topic_id
        if item.audio and item.id != phrase_id:
            entry["audio"] = item.audio
        items.append(entry)
    save_bank(space_dir, items)
    return {"ok": True, "id": phrase_id}


# ── маршрутизація ────────────────────────────────────────────────────────

def handle(method: str, path: str, query: Dict[str, str], payload: Dict[str, Any],
           root: str) -> Tuple[int, Dict[str, Any]]:
    """Повертає (статус, тіло). Винятки AdminError ловить викликач."""
    if method == "GET":
        if path == "/api/admin/spaces":
            return 200, {"items": list_spaces(root), "root": root}
        if path == "/api/admin/space":
            return 200, read_space(root, query.get("space", ""))
        if path == "/api/admin/guide":
            return 200, read_guide(root, query.get("space", ""), query.get("guide", ""))
        if path == "/api/admin/transcript":
            return 200, read_transcript(query.get("id", ""))
        if path == "/api/admin/phrases":
            return 200, read_phrases(root, query.get("space", ""))
    elif method == "POST":
        if path == "/api/admin/space":
            return 200, write_space(root, payload.get("space", ""), payload.get("data") or {})
        if path == "/api/admin/guide":
            return 200, write_guide(root, payload.get("space", ""), payload.get("guide", ""),
                                    payload.get("data") or {})
        if path == "/api/admin/space/new":
            return 200, create_space(root, payload.get("space", ""), payload.get("title", ""))
        if path == "/api/admin/phrases":
            return 200, write_phrases(root, payload.get("space", ""), payload.get("phrases") or [])
        if path == "/api/admin/phrase/audio/delete":
            return 200, delete_phrase_audio(root, payload.get("space", ""), payload.get("id", ""))
    raise AdminError("not found", 404)
