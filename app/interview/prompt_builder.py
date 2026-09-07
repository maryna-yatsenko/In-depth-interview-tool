"""Складання системного промпту: стабільне ядро + доменний конфіг.

Порядок частин не випадковий. Стабільне (файл промпту + простір + гайд) — на
початку; змінне (стан покриття) — окремим блоком, який іде в розмову, а не в
системний промпт. Це дає prompt caching шанс працювати: змінюваний хвіст не
має інвалідувати незмінний початок.
"""

import os
from typing import Any, Dict, List

from ..config.space import Guide, SpaceConfig

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")
DEFAULT_PROMPT_VERSION = "interviewer.v1"

BANK_TURN_SCHEMA = {
    "type": "object",
    "properties": {
        # Модель не пише текст, вона вибирає id репліки з переглянутого
        # людиною набору.
        "phrase_id": {"type": "string"},
        "topic_id": {"type": "string"},
        "action": {"type": "string", "enum": ["probe", "next_topic", "wrap_up"]},
        "coverage_note": {"type": "string"},
    },
    "required": ["phrase_id", "topic_id", "action", "coverage_note"],
    "additionalProperties": False,
}


def load_prompt(version: str = DEFAULT_PROMPT_VERSION) -> str:
    path = os.path.join(PROMPTS_DIR, "%s.md" % version)
    if not os.path.exists(path):
        raise FileNotFoundError("Немає версії промпту '%s' (%s)" % (version, path))
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


BANK_RULES = """
---

# Репертуар: ти НЕ формулюєш питання, ти їх ВИБИРАЄШ

Твої репліки записані людським голосом заздалегідь. Тому замість тексту ти
називаєш `phrase_id` — ідентифікатор репліки зі списку нижче. Нічого поза цим
списком сказати неможливо.

Що це змінює для тебе:

- **Вибирай найдоречніше з наявного.** Ідеального питання під цю відповідь може
  не бути — тоді бери найближче за змістом, а не найзагальніше.
- **Не повторюй ту саму репліку двічі підряд**, якщо респондент уже на неї
  відповів: візьми іншу з тієї ж теми або уточнення.
- Правила методології вище лишаються чинними: вони визначають, **яку** репліку
  доречно вибрати і коли переходити далі.
- `coverage_note` пиши як завжди — це службове поле, воно не озвучується.
"""


def build_repertoire(bank, guide) -> str:
    """Список доступних реплік із їхніми id — те, з чого модель вибирає."""
    lines = ["\n## Доступні репліки\n"]

    opening = bank.opening
    if opening:
        lines.append("**Відкриття** (вимовляється автоматично на старті): `%s`\n" % opening.id)

    for topic in guide.topics:
        items = bank.for_topic(topic.id)
        lines.append("\n### Тема «%s» (`%s`)\n" % (topic.title, topic.id))
        if items:
            for phrase in items:
                lines.append("- `%s` — «%s»\n" % (phrase.id, phrase.text))
        else:
            lines.append("- (записаних питань немає — користуйся загальними уточненнями)\n")

    probes = bank.probes
    if probes:
        lines.append("\n### Загальні уточнення (доречні в будь-якій темі)\n")
        for phrase in probes:
            lines.append("- `%s` — «%s»\n" % (phrase.id, phrase.text))

    closing = bank.closing
    if closing:
        lines.append("\n**Завершення** (для `wrap_up`): `%s`\n" % closing.id)
    return "".join(lines)


def build_system(
    space: SpaceConfig,
    guide: Guide,
    version: str = DEFAULT_PROMPT_VERSION,
    bank=None,
) -> str:
    """Стабільна частина: методологія + (банк реплік, якщо є) + простір + гайд."""
    parts = [load_prompt(version)]
    if bank is not None:
        # У режимі банку правила каналу не потрібні: текст не синтезується.
        parts.append(BANK_RULES)
        parts.append(build_repertoire(bank, guide))
    parts.append("\n\n---\n\n# Цей простір\n")

    parts.append("**Мова інтервʼю:** %s. " % ", ".join(space.languages))
    if len(space.languages) > 1:
        parts.append(
            "Якщо респондент перейшов на іншу мову зі списку — продовжуй тією, "
            "якою говорить він. Не переучуй людину посеред розмови.\n"
        )
    else:
        parts.append("\n")

    parts.append("**Як ти представляєшся:** %s\n" % space.persona.self_intro)

    parts.append("\n---\n\n# Гайд\n\n**Мета дослідження:** %s\n\n" % guide.goal)
    for i, topic in enumerate(guide.topics, 1):
        parts.append("## %d. %s (`%s`)\n" % (i, topic.title, topic.id))
        if topic.must_learn:
            parts.append("Треба зʼясувати:\n")
            for item in topic.must_learn:
                parts.append("- %s\n" % item)
        parts.append("Ліміт уточнень: %d.\n\n" % topic.max_probes)

    if guide.closing:
        parts.append("**Коли завершуєш** (`wrap_up`), скажи приблизно так: %s\n" % guide.closing)

    return "".join(parts)


def build_state_block(state: Dict[str, Any]) -> str:
    """Змінна частина: де ми зараз. Окремим повідомленням, не в системному промпті."""
    lines = ["[СЛУЖБОВИЙ СТАН — респондент цього не бачить]"]
    lines.append("Поточна тема: %s (`%s`)." % (state["topic_title"], state["topic_id"]))
    lines.append("Уточнень у цій темі: %d з %d." % (state["probes_used"], state["probes_max"]))
    lines.append("Реплік усього: %d з %d." % (state["turns"], state["max_turns"]))

    if state.get("covered"):
        lines.append("Уже покрито: %s." % ", ".join(state["covered"]))
    remaining = state.get("remaining") or []
    lines.append("Ще не торкались: %s." % (", ".join(remaining) if remaining else "нічого не лишилось"))

    if state["probes_used"] >= state["probes_max"]:
        lines.append(
            "⚠️ Ліміт уточнень у цій темі вичерпано — наступною реплікою переходь далі "
            "(`next_topic`) або завершуй (`wrap_up`)."
        )
    if not remaining and state["probes_used"] >= 1:
        lines.append("⚠️ Теми покриті. Завершуй (`wrap_up`), без резюме й висновків.")

    if state.get("guard_feedback"):
        lines.append(
            "⛔ Попередню репліку відхилено автоматичною перевіркою: %s. "
            "Переформулюй: коротке відкрите питання про конкретний випадок, без оцінок і підказок."
            % "; ".join(state["guard_feedback"])
        )
    return "\n".join(lines)
