"""Фази інтервʼю за гайдом: розігрів → вільна розповідь → карта тем → підсумок.

Чому це окремий рушій, а не робота моделі.

Професійний гайд — це не список питань, а **сценарій із різними режимами**:
спершу людину просять розповісти все саме, і інтервʼюер тільки тримає розмову
(«ага», «і що далі»); потім по карті тем добирають прогалини, і для кожної теми є
два різні формулювання — якщо тему не згадали взагалі й якщо згадали побіжно;
а на узагальненнях («завжди», «якось так») працює драбина заглиблення.

Усе це — **рішення дослідника, зафіксовані в гайді**. Віддавати їх моделі означало
б замінити перевірені формулювання згенерованими. Тому рушій веде сценарій, а
модель викликається лише там, де потрібне вільне уточнення під конкретну
відповідь.

Побічний і важливий наслідок: більшість реплік інтервʼюера — це дослівні тексти
з гайда, тому якість майже не залежить від того, наскільки сильна модель.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Фази
WARMUP = "warmup"
NARRATIVE = "narrative"
TOPICS = "topics"
CLOSING = "closing"

# Що робити наступним ходом
FIXED = "fixed"        # дослівний текст із гайда
PROBE = "probe"        # вільне уточнення — тут потрібна модель
HOLD = "hold"          # інтервʼюер МОВЧИТЬ, людина продовжує розповідь
WRAP_UP = "wrap_up"

SHORT_ANSWER_WORDS = 6
# Скільки вільних уточнень модель може дати в одній темі. Гайд їх не просить
# зовсім: у нього є рівень 1, рівень 2 «до конкретики» і драбина заглиблення.
# Один — це запас на випадок, коли відповідь пішла в бік, якого гайд не передбачив.
MAX_MODEL_PROBES_PER_TOPIC = 1
# Скільки разів доперепитуємо в розігріві, якщо людина не назвала того, що
# просив гайд («куди їздили · з ким · скільки вас було»). Два — щоб у гіршому
# випадку закрити всі три пункти й не перетворити дворозмовний розігрів на
# допит. Гайд дає цій фазі дві хвилини.
MAX_OPENING_PROBES = 2
# У підсумку — одне доуточнення на питання. Це кінець розмови, людина втомлена.
MAX_CLOSING_PROBES_PER_QUESTION = 1


@dataclass
class Action:
    kind: str
    text: str = ""
    topic_id: str = ""
    label: str = ""            # для транскрипту: звідки взялась репліка
    advance_topic: bool = False
    # Про що саме питати вільним уточненням: незакритий пункт `must_learn`
    # поточної теми. Без цього модель питає «щось по темі», а нам треба
    # закрити конкретну прогалину, яку записав дослідник.
    focus: str = ""


@dataclass
class PhaseState:
    phase: str = WARMUP
    narrative_count: int = 0
    topic_index: int = 0
    topic_asked: Dict[str, int] = field(default_factory=dict)
    topic_entered: Dict[str, bool] = field(default_factory=dict)
    # Чи вже вжито рівень 2 у темі. Він працює двояко: як відкриття теми, якщо
    # її вже згадували в розповіді, і як хід «до конкретики», якщо відповідь на
    # рівень 1 виявилась тонкою. Другого гайд і хоче.
    topic_level2: Dict[str, bool] = field(default_factory=dict)
    topic_probes: Dict[str, int] = field(default_factory=dict)
    # Які пункти `must_learn` уже закриті: {topic_id: [індекси]}. Це і є
    # відповідь на питання «чи дізналися все, що потрібно».
    topic_items_done: Dict[str, List[int]] = field(default_factory=dict)
    closing_index: int = 0
    deepening_index: int = 0
    hold_index: int = 0
    # Зараховане в розігріві (`opening_expects`) і в підсумку
    # (`closing_expects` окремо для кожного питання). Раніше галочки жили лише
    # в темах, і в цих двох фазах чекліст стояв порожній назавжди.
    opening_items_done: List[int] = field(default_factory=list)
    closing_items_done: Dict[int, List[int]] = field(default_factory=dict)
    # Скільки разів уже доперепитували в цих фазах. Без обліку доуточнення
    # зациклилось би на пункті, якого людина просто не знає.
    opening_probes: int = 0
    closing_probes: Dict[int, int] = field(default_factory=dict)
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
            "topic_level2": dict(self.topic_level2),
            "topic_probes": dict(self.topic_probes),
            "topic_items_done": {k: list(v) for k, v in self.topic_items_done.items()},
            "closing_index": self.closing_index,
            "deepening_index": self.deepening_index,
            "hold_index": self.hold_index,
            "opening_items_done": list(self.opening_items_done),
            "closing_items_done": {str(k): list(v) for k, v
                                   in self.closing_items_done.items()},
            "opening_probes": self.opening_probes,
            "closing_probes": {str(k): v for k, v in self.closing_probes.items()},
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
            topic_level2=dict(data.get("topic_level2") or {}),
            topic_probes=dict(data.get("topic_probes") or {}),
            topic_items_done={k: list(v) for k, v in
                              (data.get("topic_items_done") or {}).items()},
            closing_index=int(data.get("closing_index", 0)),
            deepening_index=int(data.get("deepening_index", 0)),
            hold_index=int(data.get("hold_index", 0)),
            opening_items_done=[int(i) for i in (data.get("opening_items_done") or [])],
            # Ключі приходять із JSON рядками — вертаємо в int, бо всередині це
            # індекс питання підсумку.
            closing_items_done={int(k): [int(i) for i in v] for k, v in
                                (data.get("closing_items_done") or {}).items()},
            opening_probes=int(data.get("opening_probes", 0)),
            closing_probes={int(k): int(v) for k, v in
                            (data.get("closing_probes") or {}).items()},
            covered_in_narrative=list(data.get("covered_in_narrative") or []),
            narrative_checked=list(data.get("narrative_checked") or []),
        )


def gap_question(item: str) -> str:
    """Питання про пункт, якого не почули — з формулювання дослідника.

    Дослівно, без моделі. Пункти в гайді написані як «те, що ми хочемо
    дізнатися» («з ким», «скільки вас було»), тому «А <пункт>?» дає осмислене
    питання само собою.

    Модель тут пробували: на «скільки вас було» вона спитала «Що ви робили
    там?», а на порожню відповідь — переказала початкове питання. Формулювання
    дослідника точніше за будь-яке, що вона згенерує, і його не треба
    перевіряти guard-ом — як і всі інші дослівні репліки гайда.
    """
    text = (item or "").strip().rstrip("?.!,;: ")
    if not text:
        return ""
    if len(text) > 1:
        text = text[0].lower() + text[1:]
    return "А %s?" % text


def open_expectations(items, done) -> List[int]:
    """Індекси того, чого ще не почули. Один помічник на розігрів і підсумок."""
    marked = set(done or [])
    return [index for index in range(len(items or [])) if index not in marked]


def is_short(answer: str) -> bool:
    return len(re.findall(r"\w+", answer or "")) <= SHORT_ANSWER_WORDS


def generalizes(answer: str, markers: List[str]) -> bool:
    low = (answer or "").lower()
    return any(marker in low for marker in (markers or []))


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


def open_items(topic, state: PhaseState) -> List[int]:
    """Індекси пунктів `must_learn`, які ще не закриті."""
    done = set(state.topic_items_done.get(topic.id, []))
    return [i for i in range(len(topic.must_learn or [])) if i not in done]


def focus_item(topic, state: PhaseState) -> str:
    """Наступна прогалина, яку треба закрити в цій темі."""
    remaining = open_items(topic, state)
    if not remaining:
        return ""
    return topic.must_learn[remaining[0]]


PHASE_LABELS = {
    WARMUP: "Початок",
    NARRATIVE: "Ваша розповідь",
    TOPICS: "Уточнення",
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
            # Рівень 1 і рівень 2 — обидва в переліку. Раніше рівень 2 давався
            # лише «якщо згадав побіжно», і вирішувала це модель. Тепер обидва
            # стоять по порядку, а зайве людина просто пропускає кнопкою.
            for level, text in (("1", topic.ask_if_missed), ("2", topic.ask_for_detail)):
                if not text:
                    continue
                items.append({
                    "id": "%s/%s" % (topic.id, level), "text": text,
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
            items.append({"phase": TOPICS, "title": "Уточнення"})
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

    def _hold(self, state: PhaseState) -> Action:
        """У фазі розповіді інтервʼюер не говорить нічого.

        У гайді тут стоять «ага» й «і що далі» — але це репліки живої розмови,
        де вони звучать паралельно з мовленням людини. У покроковому інтерфейсі
        вони перетворюються на окреме питання «Ага.», і це виглядає дивно й
        збиває: людина думає, що її про щось спитали.

        Тому тримання — це відсутність репліки. Питання лишається на екрані,
        людина просто продовжує додавати до розповіді.
        """
        state.hold_index += 1
        return Action(kind=HOLD, label="narrative-hold")

    # ── головне ──────────────────────────────────────────────────────────

    def next_action(self, state: PhaseState, last_answer: str,
                    narrative_text: str = "") -> Action:
        """Що інтервʼюер робить після цієї відповіді."""

        # ── розігрів: доперепитати прогалину, далі запит на розповідь ──
        if state.phase == WARMUP:
            # Чекліст обіцяє «хочемо почути» — і раніше рушій цю обіцянку не
            # виконував: людина казала «В Карпати їздили», один пункт із трьох,
            # а інтервʼюер ішов далі. Куди, з ким і скільки — це рамка, у якій
            # читається вся решта розмови; без неї транскрипт незрозумілий.
            gaps = open_expectations(self.guide.opening_expects,
                                     state.opening_items_done)
            if gaps and state.opening_probes < MAX_OPENING_PROBES:
                # Питаємо про ОДИН пункт за раз, і щоразу про інший: інакше
                # людина, яка справді не знає відповіді, чула б те саме двічі.
                index = gaps[state.opening_probes % len(gaps)]
                state.opening_probes += 1
                text = gap_question(self.guide.opening_expects[index])
                if text:
                    return Action(kind=FIXED, text=text, label="opening-gap")
            if self.guide.narrative_prompt:
                state.phase = NARRATIVE
                return Action(kind=FIXED, text=self.guide.narrative_prompt,
                              label="narrative-prompt")
            state.phase = TOPICS
            return self._enter_topic(state, narrative_text)

        # ── вільна розповідь: тільки тримаємо ──
        if state.phase == NARRATIVE:
            state.narrative_count += 1
            exhausted = state.narrative_count >= max(1, self.guide.narrative_turns)
            # Дві короткі відповіді підряд означають, що людина договорила —
            # тримати далі означало б тиснути на порожнє.
            ran_dry = is_short(last_answer) and state.narrative_count >= 2
            # Почули всі теми — розповідь себе вичерпала. Раніше цей перехід
            # робила кнопка «Я все розповіла»; вона дублювала «Надіслати
            # відповідь», тому перехід став наслідком повного чекліста.
            #
            # Поріг ходів обовʼязковий: локальна модель зараховує тему за
            # легкою згадкою (TD-21), і без порога пара таких зарахувань
            # обривала б вільну розповідь на другій хвилині — а гайд дає їй
            # 20-25 хвилин і вважає найціннішою частиною.
            floor = max(3, max(1, self.guide.narrative_turns) // 3)
            told_all = (bool(self.guide.topics)
                        and state.narrative_count >= floor
                        and len(set(state.covered_in_narrative)) >= len(self.guide.topics))
            if exhausted or ran_dry or told_all:
                state.phase = TOPICS
                # Покриття визначається ПО ХОДУ розповіді (див. Session), тому
                # тут лише добираємо те, що не встигли перевірити.
                pending = [t for t in self.guide.topics
                           if t.id not in state.narrative_checked]
                if pending:
                    found = self.detect_coverage(narrative_text, pending)
                    for tid in found:
                        if tid not in state.covered_in_narrative:
                            state.covered_in_narrative.append(tid)
                    state.narrative_checked += [t.id for t in pending]
                return self._enter_topic(state, narrative_text)
            return self._hold(state)

        # ── карта тем ──
        if state.phase == TOPICS:
            topic = self.topic_at(state.topic_index)
            if topic is None:
                state.phase = CLOSING
                return self.next_action(state, last_answer, narrative_text)

            asked = state.topic_asked.get(topic.id, 0)

            # Драбина заглиблення має пріоритет: узагальнення треба довести до
            # конкретики, і формулювання для цього задав дослідник.
            if self.guide.deepening and generalizes(last_answer, self.guide.generalization_markers):
                if state.deepening_index < len(self.guide.deepening):
                    text = self.guide.deepening[state.deepening_index]
                    state.deepening_index += 1
                    state.topic_asked[topic.id] = asked + 1
                    return Action(kind=FIXED, text=text, topic_id=topic.id,
                                  label="deepening")

            state.deepening_index = 0

            probes_used = state.topic_probes.get(topic.id, 0)
            level2_used = state.topic_level2.get(topic.id, False)
            gaps = open_items(topic, state)

            # Тема закрита за змістом — переходимо, навіть якщо ліміт питань
            # ще лишився. Витрачати ходи на закриту тему означало б забирати
            # їх у наступної.
            if topic.must_learn and not gaps:
                if state.topic_index + 1 < len(self.guide.topics):
                    state.topic_index += 1
                    return self._enter_topic(state, narrative_text)
                state.phase = CLOSING
                return self.next_action(state, last_answer, narrative_text)

            # Рівень 2 як хід «до конкретики»: відповідь на рівень 1 була тонкою,
            # а формулювання для доведення до конкретики дослідник уже написав.
            if not level2_used and topic.ask_for_detail:
                state.topic_level2[topic.id] = True
                state.topic_asked[topic.id] = asked + 1
                return Action(kind=FIXED, text=topic.ask_for_detail,
                              topic_id=topic.id, label="topic-level2")

            if asked >= topic.max_probes or probes_used >= MAX_MODEL_PROBES_PER_TOPIC:
                if state.topic_index + 1 < len(self.guide.topics):
                    state.topic_index += 1
                    return self._enter_topic(state, narrative_text)
                state.phase = CLOSING
                return self.next_action(state, last_answer, narrative_text)

            state.topic_asked[topic.id] = asked + 1
            state.topic_probes[topic.id] = probes_used + 1
            # Уточнення націлене на конкретну незакриту прогалину, а не «щось
            # по темі»: саме це й означає «дізнатися все, що нам потрібно».
            return Action(kind=PROBE, topic_id=topic.id, label="probe",
                          focus=focus_item(topic, state))

        # ── підсумок ──
        if state.phase == CLOSING:
            questions = self.guide.closing_questions or []
            # Спершу — чи почули те, чого чекали від ПОПЕРЕДНЬОГО питання
            # підсумку. Тут теж стояв чекліст, який ні на що не впливав.
            asked_index = state.closing_index - 1
            if asked_index >= 0 and asked_index < len(self.guide.closing_expects):
                expects = self.guide.closing_expects[asked_index]
                gaps = open_expectations(
                    expects, state.closing_items_done.get(asked_index))
                used = state.closing_probes.get(asked_index, 0)
                if gaps and used < MAX_CLOSING_PROBES_PER_QUESTION:
                    state.closing_probes[asked_index] = used + 1
                    text = gap_question(expects[gaps[0]])
                    if text:
                        return Action(kind=FIXED, text=text, label="closing-gap")
            if state.closing_index < len(questions):
                text = questions[state.closing_index]
                state.closing_index += 1
                return Action(kind=FIXED, text=text, label="closing-question")
            return Action(kind=WRAP_UP, text=self.guide.closing, label="closing")

        return Action(kind=WRAP_UP, text=self.guide.closing, label="closing")

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

    def _enter_topic(self, state: PhaseState, narrative_text: str) -> Action:
        """Перше питання в темі: рівень 1 або рівень 2 — залежно від розповіді."""
        topic = self.topic_at(state.topic_index)
        if topic is None:
            state.phase = CLOSING
            return Action(kind=WRAP_UP, text=self.guide.closing, label="closing")

        state.topic_entered[topic.id] = True
        state.topic_asked[topic.id] = state.topic_asked.get(topic.id, 0) + 1

        covered = topic.id in state.covered_in_narrative
        if covered and topic.ask_for_detail:
            state.topic_level2[topic.id] = True
            return Action(kind=FIXED, text=topic.ask_for_detail, topic_id=topic.id,
                          label="topic-level2")
        if topic.ask_if_missed:
            return Action(kind=FIXED, text=topic.ask_if_missed, topic_id=topic.id,
                          label="topic-level1")
        # Гайд без готових формулювань — питання формулює модель.
        return Action(kind=PROBE, topic_id=topic.id, label="probe")
