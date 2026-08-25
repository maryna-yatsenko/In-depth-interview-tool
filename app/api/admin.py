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

from ..config.space import ConfigError, load_guide, load_space
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


def _trash_dir(root: str) -> str:
    """Поза `root`, щоб `os.listdir(root)` у `list_spaces` не підхопив
    вміст кошика як ще один простір."""
    return os.path.join(os.path.dirname(os.path.normpath(root)), ".trash")


def _space_dir(root: str, space_key: str) -> str:
    """Усе, що в кошику (навіть лише позначене — на Vercel теку бандла не
    прибрати), для звичайних операцій (читання/запис/створення) — як
    неіснуюче. Операції самого кошика (відновити/видалити назавжди) цю
    функцію не викликають — вони працюють із тамбстоуном/теками кошика прямо."""
    key = _check_key(space_key, "інтервʼю")
    if _on_postgres() and store_db.is_space_deleted(key):
        raise AdminError("Інтервʼю '%s' не існує" % space_key, 404)
    path = os.path.join(root, key)
    if os.path.isdir(path):
        return path
    # Простір, створений через адмінку на живому сайті, не має локальної
    # теки взагалі — код деплою незмінний. Існує, якщо для нього є хоч
    # один рядок у config_overrides.
    if _on_postgres() and store_db.list_config_override_paths(space_key):
        return path
    raise AdminError("Інтервʼю '%s' не існує" % space_key, 404)


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
        # Видалений (у кошику чи назавжди) простір ховаємо і тоді, коли він
        # і досі частина коду деплою (`travel`/`example`) — прибрати теку з
        # незмінного бандла на Vercel неможливо, тож ховає саме прапорець.
        # Саме "усі", а не лише кошик: видалене назавжди інакше спливло б знов.
        names -= set(store_db.list_all_deleted_space_keys())
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
        raise AdminError("Інтервʼю '%s' не існує" % space_key, 404)
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
    _check_key(space_key, "інтервʼю")
    target = os.path.join(root, space_key)
    if os.path.isdir(target) or (_on_postgres() and store_db.list_config_override_paths(space_key)):
        raise AdminError("Інтервʼю '%s' уже існує" % space_key, 409)
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


# ── кошик ────────────────────────────────────────────────────────────────
#
# «Видалити» переносить у кошик — оборотно, і саме тому без питань про
# відповіді респондентів: ці дані ніщо тут не чіпає. Питання про них — лише
# на «видалити назавжди», де відкату вже не буде.

def trash_space(root: str, space_key: str) -> Dict[str, Any]:
    _space_dir(root, space_key)  # 404, якщо інтервʼю не існує (або вже в кошику)
    if _on_postgres():
        store_db.mark_space_deleted(space_key)
        return {"ok": True, "key": space_key}

    source = os.path.join(root, space_key)
    trash_dir = _trash_dir(root)
    os.makedirs(trash_dir, exist_ok=True)
    dest = os.path.join(trash_dir, space_key)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.move(source, dest)
    return {"ok": True, "key": space_key}


def list_trash(root: str) -> List[Dict[str, Any]]:
    items = []
    if _on_postgres():
        for entry in store_db.list_deleted_spaces():
            key = entry["key"]
            title = key
            try:
                space = _load_validated_aware(root, key, os.path.join(root, key, "space.json"),
                                              load_space)
                title = space.title
            except (ConfigError, ValueError, OSError):
                pass
            items.append({"key": key, "title": title, "deleted_at": entry["deleted_at"]})
        return items

    trash_dir = _trash_dir(root)
    if not os.path.isdir(trash_dir):
        return []
    for key in sorted(os.listdir(trash_dir)):
        space_path = os.path.join(trash_dir, key, "space.json")
        title = key
        if os.path.isfile(space_path):
            try:
                title = load_space(space_path).title
            except (ConfigError, ValueError, OSError):
                pass
        deleted_at = None
        try:
            deleted_at = os.path.getmtime(os.path.join(trash_dir, key))
        except OSError:
            pass
        items.append({"key": key, "title": title, "deleted_at": deleted_at})
    return items


def restore_space(root: str, space_key: str) -> Dict[str, Any]:
    key = _check_key(space_key, "інтервʼю")
    if _on_postgres():
        if not store_db.is_space_trashed(key):
            raise AdminError("Інтервʼю '%s' немає в кошику" % key, 404)
        store_db.unmark_space_deleted(key)
        return {"ok": True, "key": key}

    source = os.path.join(_trash_dir(root), key)
    if not os.path.isdir(source):
        raise AdminError("Інтервʼю '%s' немає в кошику" % key, 404)
    dest = os.path.join(root, key)
    if os.path.isdir(dest):
        raise AdminError("Інтервʼю '%s' уже існує поза кошиком" % key, 409)
    shutil.move(source, dest)
    return {"ok": True, "key": key}


def purge_space(root: str, space_key: str, delete_sessions: bool = False) -> Dict[str, Any]:
    """Видаляє назавжди — лише з кошика. Конфіг зникає безповоротно; зібрані
    відповіді респондентів — лише якщо про це попросили явно."""
    key = _check_key(space_key, "інтервʼю")
    removed_sessions = 0
    if delete_sessions:
        removed_sessions = store_files.delete_sessions_for_space(key)

    if _on_postgres():
        if not store_db.is_space_trashed(key):
            raise AdminError("Інтервʼю '%s' немає в кошику" % key, 404)
        store_db.delete_config_overrides(key)
        store_db.mark_space_purged(key)
        return {"ok": True, "key": key, "removed_sessions": removed_sessions}

    target = os.path.join(_trash_dir(root), key)
    if not os.path.isdir(target):
        raise AdminError("Інтервʼю '%s' немає в кошику" % key, 404)
    shutil.rmtree(target)
    return {"ok": True, "key": key, "removed_sessions": removed_sessions}


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
        if path == "/api/admin/trash":
            return 200, {"items": list_trash(root)}
    elif method == "POST":
        if path == "/api/admin/space":
            return 200, write_space(root, payload.get("space", ""), payload.get("data") or {})
        if path == "/api/admin/guide":
            return 200, write_guide(root, payload.get("space", ""), payload.get("guide", ""),
                                    payload.get("data") or {})
        if path == "/api/admin/space/new":
            return 200, create_space(root, payload.get("space", ""), payload.get("title", ""))
        if path == "/api/admin/space/delete":
            return 200, trash_space(root, payload.get("space", ""))
        if path == "/api/admin/trash/restore":
            return 200, restore_space(root, payload.get("space", ""))
        if path == "/api/admin/trash/purge":
            return 200, purge_space(root, payload.get("space", ""),
                                    bool(payload.get("delete_sessions")))
    raise AdminError("not found", 404)
