"""Конфіг простору — уся доменна специфіка інструменту.

Правило з docs/ai/architecture.md: у коді немає жодного домену. Ні мови за
замовчуванням, ні лексики, ні брендингу, ні схеми звіту. Тест на дефект:
чи можна провести інтервʼю про вибір велосипеда, не торкаючись жодного .py?

Формат — JSON, а не YAML/TOML: нуль залежностей, і адмінка все одно
генеруватиме його машинно.
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ConfigError(ValueError):
    """Конфіг неповний або суперечливий. Краще впасти на старті, ніж посеред інтервʼю."""


@dataclass
class Persona:
    """Хто саме питає. Тон — конфіг, а не риса коду."""

    self_intro: str                      # як інтервʼюер представляється
    address: str = "ви"                  # "ви" / "ти"
    tone: str = "нейтральний, стриманий"


@dataclass
class Privacy:
    """Що не питати і що вичищати. Для кожного простору своє."""

    never_ask_about: List[str] = field(default_factory=list)
    deidentify: bool = False
    consent_text: str = ""
    # Доменні шаблони маскування: формати реєстрових кодів, номерів справ тощо.
    # Задає людина, яка ці формати знає. Код їх не вигадує (див. deidentify.py).
    patterns: List[Dict[str, str]] = field(default_factory=list)
    use_builtin_patterns: bool = True


@dataclass
class SpaceConfig:
    key: str
    title: str
    languages: List[str]                 # мови інтервʼю, перша — основна
    persona: Persona
    privacy: Privacy
    domain_vocabulary: List[str] = field(default_factory=list)
    branding: Dict[str, Any] = field(default_factory=dict)
    report_sections: List[str] = field(default_factory=list)
    providers: Dict[str, Any] = field(default_factory=dict)
    # Режим інтерфейсу респондента: "voice" (лише голос, без поля введення)
    # або "text". Резерв у текст лишається завжди — коли мікрофона немає,
    # людину не можна заводити в тупик.
    interface: Dict[str, Any] = field(default_factory=dict)
    # Репертуар інтервʼюера: "free" — модель формулює питання сама;
    # "bank" — вибирає з набору реплік, записаних людським голосом.
    # Банк методологічно чистіший (усі чують однакові формулювання й навідне
    # питання не може виникнути за побудовою), але менш гнучкий.
    repertoire: str = "free"
    # Чернетка = простір створений із шаблону і ще не заповнений. Інтервʼю з
    # такого простору не стартує: інакше реальному респонденту дістанеться
    # текст заготовки, і це виявиться вже після розмови.
    draft: bool = False

    @property
    def primary_language(self) -> str:
        return self.languages[0]

    @property
    def requires_spoken_form(self) -> bool:
        """Чи мусить інтервʼюер писати числа словами й без латиниці.

        Символьні TTS-моделі (Piper) не мають у алфавіті ні цифр, ні латиниці —
        вони зникають без помилки. Це властивість каналу, не методології, тому
        визначається провайдером озвучення, а не окремим полем у конфізі.
        """
        return (self.providers.get("tts") or {}).get("provider") == "piper"


@dataclass
class Topic:
    id: str
    # Назва для ДОСЛІДНИКА: те, як тема зветься в гайді й у звітах. Її видно в
    # транскрипті, у панелі й у нотатках — вона мусить збігатися з паперовим
    # гайдом, тому тут лишається фахова мова («Розбіжна інформація»).
    title: str
    must_learn: List[str] = field(default_factory=list)   # що треба зʼясувати
    # Скільки слів мусить мати відповідь, щоб пункт можна було зарахувати:
    # {текст пункта: мінімум слів}. Заповнюється лише для пунктів, які просять
    # РОЗПОВІДЬ, а не факт.
    #
    # Різниця тут не косметична. «Нас було шість» — три слова й повна відповідь
    # на «скільки вас було». «Та посварились» — три слова й порожнеча на
    # «випадок, коли ви не погоджувались»: немає ні з чого почалось, ні чим
    # закінчилось. Одна межа на всі пункти неминуче або пропускає порожнє, або
    # відкидає повне — тому межу задає сам пункт у гайді.
    needs_words: Dict[str, int] = field(default_factory=dict)
    max_probes: int = 4                                   # ліміт уточнень (жорсткий)
    # Двоуровнева структура з реальних гайдів: рівень 1 — якщо тему не згадали
    # взагалі; рівень 2 — якщо згадали побіжно і треба довести до конкретики.
    # Це не те саме, що «ще одне уточнення»: у гайда під це різні формулювання.
    ask_if_missed: str = ""
    ask_for_detail: str = ""
    goal: str = ""

    @property
    def label(self) -> str:
        """Як тему називати людині. Дослідницький ярлик — лише для звітів."""
        return self.shown_as or self.title

    # Назва для РЕСПОНДЕНТА. Фахові ярлики карти тем людині не читаються:
    # «Розбіжна інформація» й «Розбіжність поглядів» для неї виглядають однаково
    # й не означають нічого. Порожнє поле — показуємо `title`.
    shown_as: str = ""


@dataclass
class Guide:
    key: str
    goal: str
    topics: List[Topic]
    max_turns: int = 40
    opening: str = ""
    closing: str = ""
    # Фаза вільної розповіді: інтервʼюер НЕ питає, а тільки тримає розмову
    # короткими репліками. У професійних гайдах це окрема частина на 20–25 хв,
    # і найцінніше часто звучить саме там.
    narrative_prompt: str = ""
    narrative_turns: int = 0
    narrative_holds: List[str] = field(default_factory=list)
    # Питання підсумку: ставляться в кінці, після карти тем. Кожне може мати
    # свій перелік очікуваного — так чекліст є на КОЖНОМУ питанні, а не лише
    # в темах.
    closing_questions: List[str] = field(default_factory=list)
    closing_expects: List[List[str]] = field(default_factory=list)
    opening_expects: List[str] = field(default_factory=list)
    # Правило заглиблення: коли респондент узагальнює («завжди», «якось так»),
    # інтервʼюер веде його до конкретики фіксованими сходинками. У гайдах це
    # окреме правило «тримати в голові на всі теми».
    deepening: List[str] = field(default_factory=list)
    generalization_markers: List[str] = field(default_factory=list)


def _require(data: Dict[str, Any], keys: List[str], where: str) -> None:
    missing = [k for k in keys if not data.get(k)]
    if missing:
        raise ConfigError("%s: не заповнені обовʼязкові поля: %s" % (where, ", ".join(missing)))


def load_space(path: str) -> SpaceConfig:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    _require(data, ["key", "title", "languages", "persona"], "space.json")
    if not isinstance(data["languages"], list) or not data["languages"]:
        raise ConfigError("space.json: languages має бути непорожнім списком")

    persona_raw = data["persona"]
    _require(persona_raw, ["self_intro"], "space.json → persona")

    privacy_raw = data.get("privacy", {})
    privacy = Privacy(
        never_ask_about=privacy_raw.get("never_ask_about", []),
        deidentify=bool(privacy_raw.get("deidentify", False)),
        consent_text=privacy_raw.get("consent_text", ""),
        patterns=privacy_raw.get("patterns", []),
        use_builtin_patterns=bool(privacy_raw.get("use_builtin_patterns", True)),
    )
    for rule in privacy.patterns:
        if not rule.get("pattern"):
            raise ConfigError("space.json → privacy.patterns: правило без поля 'pattern'")
        try:
            re.compile(rule["pattern"])
        except re.error as exc:
            # Впасти тут, а не посеред інтервʼю на першій репліці респондента.
            raise ConfigError(
                "space.json → privacy.patterns: шаблон '%s' не компілюється: %s"
                % (rule.get("name") or rule["pattern"], exc)
            )
    if privacy.deidentify and not privacy.use_builtin_patterns and not privacy.patterns:
        raise ConfigError(
            "space.json → privacy: deidentify=true, вбудовані шаблони вимкнені, "
            "власних немає — маскування нічого не робитиме, але вигляд захисту створює"
        )
    if privacy.deidentify and not privacy.never_ask_about:
        # Не блокуємо, але це майже завжди помилка конфігу.
        raise ConfigError(
            "space.json → privacy: deidentify=true, але never_ask_about порожній — "
            "вичищати транскрипт, не сказавши інтервʼюеру, чого не питати, — це лікувати симптом"
        )

    repertoire = data.get("repertoire", "free")
    if repertoire not in ("free", "bank"):
        raise ConfigError(
            "space.json → repertoire: '%s' невідомий. Допустимі: free, bank." % repertoire
        )

    interface = data.get("interface", {}) or {}
    mode = interface.get("mode", "text")
    if mode not in ("voice", "text"):
        raise ConfigError(
            "space.json → interface.mode: '%s' невідомий. Допустимі: voice, text." % mode
        )
    if "autoplay" in interface and not isinstance(interface["autoplay"], bool):
        raise ConfigError("space.json → interface.autoplay: очікується true або false")
    # Запис голосу — вимкнений, поки простір не попросить прямо. Голос
    # неможливо деідентифікувати (див. app/storage/voice.py), тому типове
    # значення тут «ні», а не «так».
    if "record_voice" in interface and not isinstance(interface["record_voice"], bool):
        raise ConfigError("space.json → interface.record_voice: очікується true або false")
    expected = interface.get("expected_words", 15)
    if not isinstance(expected, int) or expected < 1:
        raise ConfigError(
            "space.json → interface.expected_words: очікується ціле число більше нуля"
        )
    if mode == "voice" and (data.get("providers", {}).get("stt", {}) or {}).get("provider") in (None, "none"):
        raise ConfigError(
            "space.json: interface.mode='voice', але провайдер stt не заданий — "
            "голосовий режим без розпізнавання дасть екран, на якому нічого не можна сказати"
        )

    return SpaceConfig(
        key=data["key"],
        title=data["title"],
        languages=data["languages"],
        persona=Persona(
            self_intro=persona_raw["self_intro"],
            address=persona_raw.get("address", "ви"),
            tone=persona_raw.get("tone", "нейтральний, стриманий"),
        ),
        privacy=privacy,
        domain_vocabulary=data.get("domain_vocabulary", []),
        branding=data.get("branding", {}),
        report_sections=data.get("report_sections", []),
        providers=data.get("providers", {}),
        interface=interface,
        repertoire=repertoire,
        draft=bool(data.get("draft", False)),
    )


# Скільки слів вимагати за замовчуванням від пункта, позначеного як розповідь.
# Приблизно два речення: менше — це ще не випадок, а згадка про випадок.
DEFAULT_DETAIL_WORDS = 12

# Нижче цього не зараховуємо НІЧОГО, хоч би що сказала модель. Одне-два слова —
# це не відповідь, а слово: «Оля.», «Так.», «Було.»
MIN_WORDS_TO_CREDIT = 3


def _item_text(item) -> str:
    """Пункт `must_learn` — або рядок, або обʼєкт із вимогою до обсягу."""
    if isinstance(item, dict):
        text = item.get("text") or item.get("learn") or ""
        if not text:
            raise ConfigError("Пункт must_learn без тексту: %r" % (item,))
        return text
    return str(item)


def _item_requirements(items) -> Dict[str, int]:
    """{текст пункта: мінімум слів} — лише для пунктів, що просять розповідь."""
    out = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        text = _item_text(item)
        if item.get("needs_detail"):
            words = int(item.get("min_words", DEFAULT_DETAIL_WORDS))
            if words < 1:
                raise ConfigError(
                    "min_words для пункта «%s» мусить бути більше нуля" % text)
            out[text] = words
    return out


def load_guide(path: str) -> Guide:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    _require(data, ["key", "goal", "topics"], os.path.basename(path))
    if not isinstance(data["topics"], list) or not data["topics"]:
        raise ConfigError("%s: topics має бути непорожнім списком" % os.path.basename(path))

    topics = []
    seen = set()
    for raw in data["topics"]:
        _require(raw, ["id", "title"], "topic")
        if raw["id"] in seen:
            raise ConfigError("Дубльований id теми: %s" % raw["id"])
        seen.add(raw["id"])
        topics.append(
            Topic(
                id=raw["id"],
                title=raw["title"],
                must_learn=[_item_text(x) for x in raw.get("must_learn", [])],
                needs_words=_item_requirements(raw.get("must_learn", [])),
                max_probes=int(raw.get("max_probes", 4)),
                ask_if_missed=raw.get("ask_if_missed", ""),
                ask_for_detail=raw.get("ask_for_detail", ""),
                goal=raw.get("goal", ""),
                shown_as=raw.get("shown_as", ""),
            )
        )

    narrative = data.get("narrative") or {}
    if narrative and not narrative.get("prompt"):
        raise ConfigError(
            "%s → narrative: є блок, але немає `prompt` — фаза розповіді без "
            "запиту на розповідь не має сенсу" % os.path.basename(path)
        )

    # Підсумкові питання приймаємо і рядками, і обʼєктами {text, expects}:
    # старі гайди лишаються валідними.
    closing_raw = data.get("closing_questions", []) or []
    closing_texts, closing_expects = [], []
    for item in closing_raw:
        if isinstance(item, dict):
            if not (item.get("text") or "").strip():
                raise ConfigError("%s → closing_questions: питання без тексту"
                                  % os.path.basename(path))
            closing_texts.append(item["text"].strip())
            closing_expects.append(list(item.get("expects") or []))
        else:
            closing_texts.append(str(item))
            closing_expects.append([])

    return Guide(
        key=data["key"],
        goal=data["goal"],
        topics=topics,
        max_turns=int(data.get("max_turns", 40)),
        opening=data.get("opening", ""),
        closing=data.get("closing", ""),
        narrative_prompt=narrative.get("prompt", ""),
        narrative_turns=int(narrative.get("turns", 0)),
        narrative_holds=narrative.get("holds", []),
        closing_questions=closing_texts,
        closing_expects=closing_expects,
        opening_expects=data.get("opening_expects", []),
        deepening=data.get("deepening", []),
        generalization_markers=data.get("generalization_markers", []),
    )


def load_space_dir(space_dir: str, guide_key: Optional[str] = None):
    """Повертає (SpaceConfig, Guide). Гайд — перший за алфавітом, якщо не вказаний."""
    space = load_space(os.path.join(space_dir, "space.json"))
    guides_dir = os.path.join(space_dir, "guides")
    if not os.path.isdir(guides_dir):
        raise ConfigError("У просторі '%s' немає теки guides/" % space_dir)
    files = sorted(f for f in os.listdir(guides_dir) if f.endswith(".json"))
    if not files:
        raise ConfigError("У просторі '%s' немає жодного гайда" % space_dir)
    if guide_key:
        target = "%s.json" % guide_key
        if target not in files:
            raise ConfigError(
                "Гайд '%s' не знайдено. Доступні: %s"
                % (guide_key, ", ".join(f[:-5] for f in files))
            )
    else:
        target = files[0]
    return space, load_guide(os.path.join(guides_dir, target))
