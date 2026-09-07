"""Фази інтервʼю за гайдом: розігрів → вільна розповідь → карта тем → підсумок.

Чому це окремий рушій, а не робота моделі.

Професійний гайд — це не список питань, а **сценарій із різними режимами**:
спершу людину просять розповісти все саме, і інтервʼюер тільки тримає розмову
(«ага», «і що далі»); потім по карті тем — по одному дослівному питанню на
кожну. Респондент рухається сценарієм сам, кнопками «наступне»/«попереднє»
(`Session.go`) — рушій нижче лише будує цей плаский перелік
(`Plan.script`) і визначає, які теми вже прозвучали у вільній розповіді, щоб
не питати про них ще раз (`Plan.detect_coverage`).

Усе це — **рішення дослідника, зафіксовані в гайді**. Інтервʼюер не ставить
жодних додаткових питань понад те, що дослідник написав: ні другого,
доводжувального формулювання, ні реакції на узагальнення респондента — лише
дослівний текст гайда, по одному питанню на тему.

Побічний і важливий наслідок: усі репліки інтервʼюера — це дослівні тексти
з гайда, тому якість не залежить від того, наскільки сильна модель.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Фази
WARMUP = "warmup"
NARRATIVE = "narrative"
TOPICS = "topics"
CLOSING = "closing"


@dataclass
class PhaseState:
    phase: str = WARMUP
    narrative_count: int = 0
    topic_index: int = 0
    topic_asked: Dict[str, int] = field(default_factory=dict)
    topic_entered: Dict[str, bool] = field(default_factory=dict)
    closing_index: int = 0
    hold_index: int = 0
    covered_in_narrative: List[str] = field(default_factory=list)
    # Теми, про які вже питали модель під час розповіді (і «так», і «ні»), щоб
    # не питати про них знову кожного ходу. Це те, що прибирає довгу паузу в
    # кінці розповіді: перевірка розтягується по ходах.
    narrative_checked: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "narrative_count": self.narrative_count,
            "topic_index": self.topic_index,
            "topic_asked": dict(self.topic_asked),
            "topic_entered": dict(self.topic_entered),
            "closing_index": self.closing_index,
            "hold_index": self.hold_index,
            "covered_in_narrative": list(self.covered_in_narrative),
            "narrative_checked": list(self.narrative_checked),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "PhaseState":
        data = data or {}
        return cls(
            phase=data.get("phase", WARMUP),
            narrative_count=int(data.get("narrative_count", 0)),
            topic_index=int(data.get("topic_index", 0)),
            topic_asked=dict(data.get("topic_asked") or {}),
            topic_entered=dict(data.get("topic_entered") or {}),
            closing_index=int(data.get("closing_index", 0)),
            hold_index=int(data.get("hold_index", 0)),
            covered_in_narrative=list(data.get("covered_in_narrative") or []),
            narrative_checked=list(data.get("narrative_checked") or []),
        )


def mentioned_in_text(topic, text: str) -> bool:
    """Груба лексична перевірка: чи звучала тема у вільній розповіді.

    Свідомо груба й свідомо консервативна: беремо значущі слова з назви теми та
    з `must_learn` і вважаємо тему згаданою лише при кількох збігах. Помилитись
    у бік «не згадували» дешевше: тоді прозвучить питання рівня 1, і респондент
    просто повторить — це незручно. Помилка в інший бік гірша: тему пропустять.
    """
    low = (text or "").lower()
    words = set()
    for source in [topic.title] + list(topic.must_learn or []):
        for word in re.findall(r"[а-яіїєґ]{5,}", source.lower()):
            words.add(word[:6])          # грубе відкидання закінчень
    if not words:
        return False
    hits = sum(1 for stem in words if stem in low)
    return hits >= 2


PHASE_LABELS = {
    WARMUP: "Початок",
    NARRATIVE: "Ваша розповідь",
    TOPICS: "Теми",
    CLOSING: "Підсумок",
}


class Plan:
    """Рушій сценарію. Не тримає стану — стан живе в сесії."""

    def __init__(self, guide, coverage_detector=None):
        self.guide = guide
        # Функція, яка за текстом розповіді каже, які теми вже прозвучали.
        # Модель робить це помітно краще за лексичну перевірку, але лексична
        # лишається запобіжником: без неї падіння моделі означало б, що всі теми
        # питаються рівнем 1, тобто вдруге.
        self.coverage_detector = coverage_detector

    # ── службове ─────────────────────────────────────────────────────────

    def script(self) -> List[Dict[str, Any]]:
        """Інтервʼю як плоский перелік питань — по порядку гайда.

        Чому плоский, а не машина станів із оцінкою: рішення «чи можна далі»
        більше не ухвалює модель. Воно трималось на судженні точністю 64-71 %
        (див. `app/interview/judge.py`), і на такому судженні тримати людину на
        питанні неправильно. Тепер порядок задає гайд, а темп — сама людина
        кнопками «наступне» й «попереднє».

        Чекліст лишається, але як **шпаргалка**: ось що ми сподіваємось почути.
        Не протокол, не умова, не замок.
        """
        items = []
        if self.guide.opening:
            items.append({
                "id": "opening", "text": self.guide.opening,
                "section": WARMUP, "topic_id": "",
                "expects": list(self.guide.opening_expects or []),
            })
        if self.guide.narrative_prompt:
            items.append({
                "id": "narrative", "text": self.guide.narrative_prompt,
                "section": NARRATIVE, "topic_id": "",
                # У вільній розповіді шпаргалка — усі теми гайда: людина бачить,
                # про що взагалі йтиметься, і розповідає повніше.
                "expects": [topic.label for topic in self.guide.topics],
            })
        for topic in self.guide.topics:
            # Одне питання на тему — саме те, що дослідник написав як
            # `ask_if_missed`. Інтервʼюер більше не ставить другого,
            # доводжувального питання: рушій не задає жодних уточнень понад
            # дослівний текст гайда.
            if not topic.ask_if_missed:
                continue
            items.append({
                "id": "%s/1" % topic.id, "text": topic.ask_if_missed,
                "section": TOPICS, "topic_id": topic.id,
                "topic_title": topic.label,
                "expects": list(topic.must_learn or []),
            })
        for index, question in enumerate(self.guide.closing_questions or []):
            items.append({
                "id": "closing/%d" % index, "text": question,
                "section": CLOSING, "topic_id": "",
                "expects": list(self.guide.closing_expects[index])
                if index < len(self.guide.closing_expects) else [],
            })
        return items

    def sections(self) -> List[Dict[str, str]]:
        """Розділи інтервʼю — його справжня структура, а не лічильник питань.

        Чотири, і кожен існує лише якщо гайд його задав: у просторі без вільної
        розповіді розділу «Ваша розповідь» немає взагалі.
        """
        items = [{"phase": WARMUP, "title": "Початок"}]
        if self.guide.narrative_prompt:
            # «Розповідь», не «Ваша розповідь»: на телефоні довгий підпис
            # обрізався трьома точками в пройденому розділі.
            items.append({"phase": NARRATIVE, "title": "Розповідь"})
        if self.guide.topics:
            items.append({"phase": TOPICS, "title": "Теми"})
        if self.guide.closing_questions:
            items.append({"phase": CLOSING, "title": "Підсумок"})
        return items

    def progress(self, state: PhaseState, asked: int) -> Dict[str, Any]:
        """Прогрес розділами, а не числом питань.

        Чому не «питання 4 з 60»: 60 — це межа гайда, а не план. Реальне
        інтервʼю виходить на 15-24 питання, тому «з 60» одночасно пугає й
        неправда. Людині потрібна структура: де я в розмові й що буде далі.

        Чому пішла «частина 1» у розповіді: вона нічого не означала. Номер ходу
        всередині вільної розповіді — це наша внутрішня механіка, а питання «а
        буде частина 2?» на нього немає відповіді, бо частин стільки, скільки
        людина захоче говорити. Рух у цій фазі показує чекліст тем — там видно,
        про що вже згадали.
        """
        topics = self.guide.topics
        total_topics = len(topics)
        sections = self.sections()
        phases_order = [item["phase"] for item in sections]
        index = phases_order.index(state.phase) if state.phase in phases_order else 0

        # Деталь усередині розділу — тільки там, де є що рахувати чесно.
        detail = ""
        inner = 0.0
        if state.phase == WARMUP:
            inner = 0.5
        elif state.phase == NARRATIVE:
            planned = max(1, self.guide.narrative_turns)
            inner = min(1.0, state.narrative_count / float(planned))
            detail = "розповідайте, скільки потрібно"
        elif state.phase == TOPICS and total_topics:
            shown = min(state.topic_index + 1, total_topics)
            detail = "тема %d з %d" % (shown, total_topics)
            topic = self.topic_at(state.topic_index)
            if topic is not None:
                # Підпис бачить респондент — отже людські слова, не ярлик карти.
                detail += " · %s" % topic.label
            inner = min(1.0, state.topic_index / float(total_topics))
        elif state.phase == CLOSING:
            questions = self.guide.closing_questions or []
            if questions:
                shown = min(state.closing_index + 1, len(questions))
                detail = "питання %d з %d" % (shown, len(questions))
                inner = min(1.0, state.closing_index / float(len(questions)))

        return {
            "phase": state.phase,
            # Назва розділу окремо від деталі: підпис і уточнення читаються
            # по-різному й показуються в різних місцях.
            "section": sections[index]["title"] if sections else "",
            "section_index": index,
            "sections": [item["title"] for item in sections],
            "detail": detail,
            # Заповнення ПОТОЧНОГО розділу, не всього інтервʼю. Суцільна смуга
            # на всю розмову не давала розуміння: вона рухалась на відсоток і
            # ні про що не говорила.
            "section_fraction": round(min(1.0, max(0.0, inner)), 3),
            # Лишається для дослідника й сумісності зі збереженими сесіями.
            "label": sections[index]["title"] if sections else "",
            "fraction": round(min(1.0, (index + inner) / max(1, len(sections))), 3),
            "asked": asked,
            "topic_index": state.topic_index,
            "topics_total": total_topics,
        }

    def topic_at(self, index: int):
        topics = self.guide.topics
        if not topics:
            return None
        return topics[min(index, len(topics) - 1)]

    def detect_coverage(self, narrative_text: str, topics=None) -> List[str]:
        """Які теми вже прозвучали у вільній розповіді.

        Правило гайда: «позначати подумки, що вже прозвучало — щоб не питати
        вдруге». Спершу питаємо модель; якщо вона не відповіла або відповіла
        незрозуміло — лексичний запобіжник.
        """
        if not (narrative_text or "").strip():
            return []
        subset = topics if topics is not None else self.guide.topics
        if self.coverage_detector is not None:
            try:
                found = self.coverage_detector(narrative_text, subset)
            except Exception:
                found = None
            if found is not None:
                known = {t.id for t in self.guide.topics}
                return [tid for tid in found if tid in known]
        return [t.id for t in subset if mentioned_in_text(t, narrative_text)]

