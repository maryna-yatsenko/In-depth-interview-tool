"""Деідентифікація реплік респондента.

**Момент застосування — на вході, а не при збереженні.** Якщо вичищати транскрипт
перед записом на диск, персональні дані спершу все одно поїдуть у вендора моделі.
Тому маскування стоїть між «людина сказала» і «текст пішов далі»: ні модель, ні
файл сирого тексту не бачать.

**Ціна цього рішення, названа вголос:** замаскований фрагмент не відновити. Якщо
шаблон спрацював помилково (наприклад, число в замовленні виглядає як код), у
транскрипті лишиться `[ЧИСЛО]`, і дослідник не дізнається, що там було. Тому
кожне спрацювання логується (що саме за шаблон і скільки разів), а самі шаблони
вимикаються в конфізі простору.

⚠️ **Доменні шаблони тут НЕ вигадуються.** Вбудовані — лише нейтральні й
перевіряємі (пошта, посилання, довгі послідовності цифр). Формати конкретних
реєстрових кодів і номерів справ задаються в конфізі простору людиною, яка їх
знає. Вигаданий «правильний» формат гірший за відсутній: він створює відчуття
захисту там, де його немає.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

# Нейтральні шаблони: не залежать від домену й мови дослідження.
BUILTIN_PATTERNS = [
    {
        "name": "email",
        "pattern": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "replacement": "[ПОШТА]",
    },
    {
        "name": "url",
        "pattern": r"https?://\S+",
        "replacement": "[ПОСИЛАННЯ]",
    },
    {
        "name": "phone_formatted",
        # Дужки або дефіси — сильні ознаки телефону: +38 (067) 123-45-67, 067-123-45-67.
        # ПРОБІЛ такою ознакою НЕ вважається, і це не недогляд: «у 2019 2020 2021
        # роках» — це ряд чисел, розділених пробілами, і колишній шаблон з'їдав його
        # як телефон. Втратити роки, які назвав респондент, гірше, ніж не замаскувати
        # телефон, записаний пробілами. Локальні формати з пробілами — у конфіг
        # простору, там їх задає людина, яка знає свою локаль.
        "pattern": r"(?<!\d)\+?\d{0,3}[\s\-]?\(\d{2,4}\)[\s\-]?\d{2,4}(?:[\s\-]?\d{2,4}){1,3}(?!\d)"
                   r"|(?<!\d)\+?\d{2,4}(?:-\d{2,4}){2,4}(?!\d)",
        "replacement": "[ТЕЛЕФОН]",
    },
    {
        "name": "long_digits",
        # 8+ цифр підряд: реєстровий код, рахунок, картка — або таки телефон.
        # Замінник свідомо нейтральний: ми ловимо форму, а не сутність, і не
        # вдаємо, що знаємо, що це саме було.
        "pattern": r"(?<!\d)\d{8,}(?!\d)",
        "replacement": "[ЧИСЛО]",
    },
]


class Deidentifier:
    """Збирається з конфігу простору. Вимкнений — не робить нічого."""

    def __init__(
        self,
        enabled: bool = False,
        extra_patterns: Optional[List[Dict[str, str]]] = None,
        use_builtin: bool = True,
    ):
        self.enabled = enabled
        self.rules = []  # type: List[Tuple[str, Any, str]]
        if not enabled:
            return

        # Шаблони простору йдуть ПЕРШИМИ: вони конкретніші за вбудовані, і якщо
        # людина описала формат свого домену, він мусить спрацювати раніше, ніж
        # загальний «8+ цифр» з'їсть його під виглядом [ЧИСЛО].
        for raw in (extra_patterns or []):
            name = (raw.get("name") or "").strip() or "custom"
            pattern = raw.get("pattern") or ""
            if not pattern:
                continue
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    "Шаблон деідентифікації '%s' не компілюється: %s" % (name, exc)
                )
            self.rules.append((name, compiled, raw.get("replacement") or "[ПРИХОВАНО]"))

        if use_builtin:
            for item in BUILTIN_PATTERNS:
                self.rules.append((item["name"], re.compile(item["pattern"]), item["replacement"]))

    @classmethod
    def from_space(cls, space) -> "Deidentifier":
        privacy = space.privacy
        return cls(
            enabled=privacy.deidentify,
            extra_patterns=getattr(privacy, "patterns", None),
            use_builtin=getattr(privacy, "use_builtin_patterns", True),
        )

    def scrub(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Повертає (замаскований текст, перелік спрацювань).

        Перелік — не для звіту, а для аудиту: дослідник має бачити, що саме
        інструмент прибрав, інакше маскування не відрізнити від збою.
        """
        if not self.enabled or not text:
            return text, []

        hits = []
        result = text
        for name, compiled, replacement in self.rules:
            found = compiled.findall(result)
            if not found:
                continue
            result = compiled.sub(replacement, result)
            hits.append({"rule": name, "count": len(found)})
        return result, hits
