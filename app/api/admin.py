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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..config.space import DEFAULT_CONSENT_TEXT, DEFAULT_OPENING_TEXT, ConfigError, load_guide, load_space
from ..providers.base import ProviderError
from ..providers.registry import build_llm
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
        entry = {"key": name, "title": name, "guides": [], "error": None, "draft": False, "created_at": None}
        try:
            space = _load_validated_aware(root, name, space_path, load_space)
            entry["title"] = space.title
            entry["languages"] = space.languages
            entry["draft"] = space.draft
            entry["created_at"] = space.created_at
        except (ConfigError, ValueError, OSError) as exc:
            # Зламаний простір показуємо з помилкою, а не ховаємо: інакше
            # дослідник шукатиме, куди зник його конфіг.
            entry["error"] = str(exc)
        if not entry["created_at"]:
            # Запасний варіант для просторів, створених до появи цього поля
            # (або якщо файл фізично відсутній, напр. Postgres-режим — тоді
            # лишається None, дата просто не показується).
            try:
                entry["created_at"] = datetime.fromtimestamp(
                    os.path.getmtime(space_path), tz=timezone.utc
                ).isoformat()
            except OSError:
                pass
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
    # Порядок у лівій панелі — той, який дослідник задав перетягуванням; нові
    # (яких ще немає в порядку) йдуть після впорядкованих, за алфавітом.
    order = read_order(root)
    rank = {key: index for index, key in enumerate(order)}
    items.sort(key=lambda item: rank.get(item["key"], len(rank)))
    return items


def _order_path(root: str) -> str:
    # «_admin» не може бути ключем простору (KEY_RE дозволяє лише a-z0-9 на
    # початку), а без space.json список просторів його пропускає.
    return os.path.join(root, "_admin", "order.json")


def read_order(root: str) -> List[str]:
    raw = _read_bytes(root, "_admin", _order_path(root))
    if not raw:
        return []
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return []
    return [key for key in data if isinstance(key, str)] if isinstance(data, list) else []


def write_order(root: str, order: List[Any]) -> Dict[str, Any]:
    keys = []
    for key in order or []:
        if isinstance(key, str) and KEY_RE.match(key) and key not in keys:
            keys.append(key)
    _write_bytes(root, "_admin", _order_path(root),
                 json.dumps(keys, ensure_ascii=False).encode("utf-8"))
    return {"ok": True, "order": keys}


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
    # Окреме сховище (save_feedback) — не частина самого транскрипту, тому
    # для перегляду в панелі докладаємо його тут, а не в load_session_by_id.
    data = dict(data)
    data["feedback"] = store_files.load_feedback(session_id)
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
    # Поза банком кожна тема мусить мати ask_if_missed — та сама вимога,
    # що й у load_space_dir (app/config/space.py), тут лише для repertoire
    # свіжого зі space.json, а не з уже провалідованого SpaceConfig.
    space_raw = _load_json_aware(root, space_key, os.path.join(space_dir, "space.json")) or {}
    require_scripted = space_raw.get("repertoire", "free") != "bank"
    validator = lambda path: load_guide(path, require_scripted=require_scripted)
    _write_validated(root, space_key, os.path.join(guides_dir, "%s.json" % guide_key),
                      data, validator)
    return {"ok": True, "space": space_key, "guide": guide_key}


# ── аудіо питань (дослідник записує питання власним голосом) ──────────────
#
# НЕ той банк реплік, що в app/config/phrases.py: цей — окремо на кожне
# питання гайда (topic_id), пишеться через _read_bytes/_write_bytes (як і
# guide.json), тому працює однаково локально й на Vercel. Попередня версія
# цієї фічі писала аудіо напряму на диск в обхід цих функцій — на Vercel це
# ламалось (файлова система там незмінна під час роботи), тому й прибрали.

_AUDIO_EXT_BY_MIME = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
}
_AUDIO_MIME_BY_EXT = {
    ".webm": "audio/webm", ".ogg": "audio/ogg", ".m4a": "audio/mp4",
    ".wav": "audio/wav", ".mp3": "audio/mpeg",
}


def _topic_audio_path(root: str, space_key: str, guide_key: str, topic_id: str, ext: str) -> str:
    return os.path.join(root, space_key, "audio", guide_key, topic_id + ext)


def save_topic_audio(root: str, space_key: str, guide_key: str, topic_id: str,
                      content_type: str, data: bytes) -> Dict[str, Any]:
    _space_dir(root, space_key)
    _check_key(guide_key, "гайда")
    _check_key(topic_id, "теми")
    mime = (content_type or "").split(";")[0].strip().lower()
    ext = _AUDIO_EXT_BY_MIME.get(mime)
    if not ext:
        raise AdminError("Непідтримуваний формат запису: %s" % (content_type or "?"), 400)
    if not data:
        raise AdminError("Порожній запис", 400)
    # Прибираємо попередній файл з іншим розширенням — переזапис міг
    # трапитись іншим браузером/форматом мікрофона.
    for other_ext in _AUDIO_MIME_BY_EXT:
        if other_ext == ext:
            continue
        old_path = _topic_audio_path(root, space_key, guide_key, topic_id, other_ext)
        if _on_postgres():
            store_db.delete_config_override(space_key, _rel_path(root, space_key, old_path))
        elif os.path.isfile(old_path):
            os.remove(old_path)
    path = _topic_audio_path(root, space_key, guide_key, topic_id, ext)
    _write_bytes(root, space_key, path, data)
    return {"ok": True}


def read_topic_audio(root: str, space_key: str, guide_key: str,
                      topic_id: str) -> Optional[Tuple[bytes, str]]:
    """(байти, mime) або None, якщо для цього питання ще нема запису."""
    _check_key(space_key, "інтервʼю")
    _check_key(guide_key, "гайда")
    _check_key(topic_id, "теми")
    for ext, mime in _AUDIO_MIME_BY_EXT.items():
        path = _topic_audio_path(root, space_key, guide_key, topic_id, ext)
        content = _read_bytes(root, space_key, path)
        if content is not None:
            return content, mime
    return None


def topic_audio_exists(root: str, space_key: str, guide_key: str, topic_id: str) -> bool:
    """Легша перевірка для гарячого шляху інтервʼю (/api/step на кожен крок) —
    локально без читання самих байтів; на Postgres той самий _read_bytes,
    бо там і так одна вибірка рядка."""
    _check_key(space_key, "інтервʼю")
    _check_key(guide_key, "гайда")
    _check_key(topic_id, "теми")
    for ext in _AUDIO_MIME_BY_EXT:
        path = _topic_audio_path(root, space_key, guide_key, topic_id, ext)
        if _on_postgres():
            if store_db.get_config_override(space_key, _rel_path(root, space_key, path)) is not None:
                return True
        elif os.path.isfile(path):
            return True
    return False


def delete_topic_audio(root: str, space_key: str, guide_key: str, topic_id: str) -> Dict[str, Any]:
    _check_key(guide_key, "гайда")
    _check_key(topic_id, "теми")
    removed = False
    for ext in _AUDIO_MIME_BY_EXT:
        path = _topic_audio_path(root, space_key, guide_key, topic_id, ext)
        if _on_postgres():
            if store_db.get_config_override(space_key, _rel_path(root, space_key, path)) is not None:
                store_db.delete_config_override(space_key, _rel_path(root, space_key, path))
                removed = True
        elif os.path.isfile(path):
            os.remove(path)
            removed = True
    return {"ok": True, "removed": removed}


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


def duplicate_space(root: str, source_key: str) -> Dict[str, Any]:
    """Копія дослідження з усім вмістом (простір, гайди, записи питань) —
    як чернетка. Зібрані відповіді респондентів не копіюються."""
    source_key = _check_key(source_key, "інтервʼю")
    source = os.path.join(root, source_key)
    if not os.path.isdir(source) and not (_on_postgres() and store_db.list_config_override_paths(source_key)):
        raise AdminError("Інтервʼю '%s' не знайдено" % source_key, 404)

    def taken(key: str) -> bool:
        return (os.path.isdir(os.path.join(root, key))
                or os.path.isdir(os.path.join(_trash_dir(root), key))
                or (_on_postgres() and (bool(store_db.list_config_override_paths(key))
                                        or key in set(store_db.list_all_deleted_space_keys()))))

    base = source_key[:32].rstrip("-_") + "-copy"
    new_key, n = base, 1
    while taken(new_key):
        n += 1
        new_key = "%s-%d" % (base, n)
    target = os.path.join(root, new_key)

    if _on_postgres():
        # Спершу файли з бандла, потім перевизначення з бази (вони перекривають).
        if os.path.isdir(source):
            for dirpath, _dirs, files in os.walk(source):
                for filename in files:
                    src_path = os.path.join(dirpath, filename)
                    with open(src_path, "rb") as fh:
                        store_db.put_config_override(
                            new_key, _rel_path(root, source_key, src_path), fh.read())
        for rel in store_db.list_config_override_paths(source_key):
            content = store_db.get_config_override(source_key, rel)
            if content is not None:
                store_db.put_config_override(new_key, rel, content)
    else:
        shutil.copytree(source, target)

    space_path = os.path.join(root, new_key, "space.json")
    data = _load_json_aware(root, new_key, space_path) or {}
    title = "%s (копія)" % (data.get("title") or source_key)
    data["key"] = new_key
    data["title"] = title
    data["draft"] = True
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    branding = dict(data.get("branding") or {})
    branding["page_title"] = title
    data["branding"] = branding
    _write_validated(root, new_key, space_path, data, load_space)
    return {"ok": True, "key": new_key, "title": title}


# ── автопокращення формулювань питань ─────────────────────────────────────
#
# Питання, яке дослідниця завантажила файлом, приводимо до практик якісних
# досліджень: відкрите, нейтральне, про один випадок, про реальний досвід,
# простими словами. Змісту не вигадуємо: якщо відповідь моделі підозріла
# (порожня, задовга, не про те) — лишається оригінал.

_IMPROVE_SYSTEM = (
    "Ти допомагаєш дослідниці привести питання глибинного інтервʼю до найкращих практик "
    "якісних користувацьких досліджень. Перепиши питання, яке надішле користувач, так, щоб воно:\n"
    "- було відкритим (починалось із «Розкажіть…», «Як…», «Що…», «Коли…», «Чому…»), без відповіді «так/ні»;\n"
    "- було нейтральним: без підказки відповіді, оцінок і наведення;\n"
    "- питало про одну річ: якщо в питанні дві, залиш головну;\n"
    "- питало про реальний минулий досвід («як було востаннє»), а не про гіпотетичне «що б ви зробили»;\n"
    "- було простим, розмовним, до 20 слів, без жаргону;\n"
    "- зберігало зміст і тему оригіналу, нічого не вигадувало; мова — українська.\n"
    "Якщо питання вже добре, поверни його без змін. "
    "Відповідай ЛИШЕ одним переписаним питанням, без пояснень, лапок і нумерації."
)

_improve_llm_cache = {}


def _improve_llm(cfg: Dict[str, Any]):
    """Провайдер збираємо один раз і тримаємо: локальна модель важка в памʼяті."""
    config = dict(cfg or {})
    # Питання коротке, але українські слова «дорогі» в токенах — дефолтних 80 мало.
    config["max_tokens"] = max(int(config.get("max_tokens", 80)), 160)
    key = json.dumps(config, sort_keys=True) + os.environ.get("LLM_PROVIDER_OVERRIDE", "")
    if key not in _improve_llm_cache:
        _improve_llm_cache[key] = build_llm(config)
    return _improve_llm_cache[key]


def _stems(text: str) -> set:
    return {w[:5] for w in re.findall(r"[\w']+", text.lower()) if len(w) > 3}


def _accept_rewrite(original: str, rewritten: str) -> str:
    """Відповідь моделі — лише якщо схожа на переписане питання, а не на що завгодно."""
    text = (rewritten or "").strip().strip('"“”«»').strip()
    text = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", text)
    if not text or len(text) > max(220, 2 * len(original)):
        return original
    if not _stems(original) & _stems(text):
        return original
    if not text.endswith("?"):
        text = text.rstrip(".! ") + "?"
    return text[0].upper() + text[1:]


def improve_questions(root: str, space_key: str, questions: List[Any]) -> Dict[str, Any]:
    _space_dir(root, space_key)
    texts = [q.strip()[:600] for q in (questions or []) if isinstance(q, str) and q.strip()][:20]
    if not texts:
        raise AdminError("Немає питань для покращення")
    space_raw = _load_json_aware(root, space_key, os.path.join(root, space_key, "space.json")) or {}
    cfg = (space_raw.get("providers") or {}).get("llm") or {}
    try:
        llm = _improve_llm(cfg)
    except (ProviderError, ImportError) as exc:
        raise AdminError("Модель недоступна: %s" % exc, 503)
    if getattr(llm, "name", "") == "mock":
        raise AdminError("Модель недоступна: підключена лише заглушка", 503)
    items = []
    for text in texts:
        try:
            raw = llm.respond_text(_IMPROVE_SYSTEM, [{"role": "user", "content": text}])
        except ProviderError as exc:
            raise AdminError("Модель недоступна: %s" % exc, 503)
        improved = _accept_rewrite(text, raw)
        items.append({"original": text, "text": improved, "changed": improved != text})
    return {"ok": True, "items": items}


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
    # Проставляється лише тут, один раз при створенні — на відміну від
    # mtime файлу, не зсувається при подальших редагуваннях через адмінку.
    data["created_at"] = datetime.now(timezone.utc).isoformat()
    data.pop("_comment", None)
    data["persona"] = dict(data.get("persona") or {})
    data["persona"]["self_intro"] = "TODO: як інтервʼюер представляється респонденту"
    privacy = dict(data.get("privacy") or {})
    privacy["deidentify"] = False
    privacy["consent_text"] = DEFAULT_CONSENT_TEXT
    data["privacy"] = privacy
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
        guide["opening"] = DEFAULT_OPENING_TEXT
        guide["closing"] = "TODO: подяка без резюме"
        guide["topics"] = [{
            "id": "topic-1",
            "title": "TODO: назва теми",
            "must_learn": ["TODO: що треба зʼясувати"],
            "max_probes": 4,
            "ask_if_missed": "TODO: питання, якщо тему взагалі не згадали",
        }]
        validator = lambda p: load_guide(p, require_scripted=True)
        _write_validated(root, space_key, path, guide, validator)


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
        if path == "/api/admin/space/duplicate":
            return 200, duplicate_space(root, payload.get("space", ""))
        if path == "/api/admin/improve-questions":
            return 200, improve_questions(root, payload.get("space", ""), payload.get("questions") or [])
        if path == "/api/admin/spaces/order":
            return 200, write_order(root, payload.get("order") or [])
        if path == "/api/admin/space/delete":
            return 200, trash_space(root, payload.get("space", ""))
        if path == "/api/admin/trash/restore":
            return 200, restore_space(root, payload.get("space", ""))
        if path == "/api/admin/trash/purge":
            return 200, purge_space(root, payload.get("space", ""),
                                    bool(payload.get("delete_sessions")))
        if path == "/api/admin/topic-audio/delete":
            return 200, delete_topic_audio(root, payload.get("space", ""),
                                           payload.get("guide", ""), payload.get("topic", ""))
    raise AdminError("not found", 404)
