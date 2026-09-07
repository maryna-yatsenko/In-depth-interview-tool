# -*- coding: utf-8 -*-
"""Оцінювач: чи згадав респондент тему у вільній розповіді.

Лишилось одне питання до моделі — `topic_question` — і те, тільки щоб не
питати вдруге про тему, яка вже прозвучала в розповіді. Рушій більше не
судить, чи розкрита тема достатньо: жодних додаткових питань понад дослівний
текст гайда він не ставить (історію калібрування колишнього пооб'єктного
оцінювача див. у `docs/ai/technical_debt.md`, TD-36).
"""

from typing import Optional


# ── формулювання ─────────────────────────────────────────────────────────

def topic_question(narrative: str, title: str, goal: str) -> str:
    """Чи згадав респондент тему у вільній розповіді.

    Тут «так» означає саме «згадав»: це лише щоб не питати вдруге про те, що
    вже прозвучало — рушій більше не ставить жодного додаткового питання на
    тему понад те, що дослідник написав у гайді. Тому й чекліст у фазі
    розповіді підписаний «Про що вже згадали», а не «Хочемо почути».
    """
    return (
        "РОЗПОВІДЬ РЕСПОНДЕНТА:\n%s\n\n"
        "Чи можна з цієї розповіді дізнатися: «%s» (%s)?\n\n"
        "Якщо про це у розповіді нічого немає — «ні».\n"
        "Відповідай ОДНИМ словом: так або ні." % (narrative, title, goal)
    )


SYSTEM = "Відповідай одним словом: так або ні."

# Схема для провайдерів зі структурованим виводом.
YES_NO_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string", "enum": ["так", "ні"]}},
    "required": ["answer"],
    "additionalProperties": False,
}


def parse_yes_no(reply: str) -> bool:
    return (reply or "").strip().lower().lstrip("*_-• ").startswith("так")


def ask(llm, instruction: str) -> Optional[bool]:
    """Одне запитання до моделі. None — оцінити не вдалося.

    None і «ні» тут різні речі: «ні» лишає пункт відкритим свідомо, а None
    означає, що ми не знаємо, і вирішувати за цим не можна.
    """
    try:
        if getattr(llm, "supports_structured", True):
            data = llm.respond_json(
                system="Ти відповідаєш лише «так» або «ні».",
                messages=[{"role": "user", "content": instruction}],
                schema=YES_NO_SCHEMA,
            )
            return (data.get("answer") or "").strip().lower().startswith("так")
        return parse_yes_no(llm.respond_text(
            SYSTEM, [{"role": "user", "content": instruction}]))
    except Exception:
        return None
