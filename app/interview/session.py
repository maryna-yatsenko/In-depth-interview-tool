"""Ядро: стан інтервʼю і жорсткі правила.

Розподіл відповідальності, який тут головний: **модель пропонує, код вирішує.**
Модель може хотіти копати тему нескінченно або завершити, не покривши теми, —
ліміти покриття й переходи форсує код. Промпт просить, ядро гарантує.

Ядро не знає, чи канал голосовий: на вхід текст репліки, на вихід текст
питання. Саме тому голос на Етапі 2 додається без правок у цьому файлі.
"""

import datetime
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config import space as space_config
from ..config.space import Guide, SpaceConfig
from ..providers.base import LLMProvider, ProviderError
from . import guard, phases
from . import judge as judging
from .deidentify import Deidentifier
from .prompt_builder import (
    BANK_TURN_SCHEMA,
    COMPACT_PROMPT_VERSION,
    DEFAULT_PROMPT_VERSION,
    TURN_SCHEMA,
    build_state_block,
    build_system,
    build_system_compact,
)

MAX_GUARD_RETRIES = 2

# Нейтральні відступні репліки: жодного домену, жодної підказки. Використовуються,
# коли модель тричі підряд не змогла сформулювати репліку без порушень.
_FALLBACK_PROBES = [
    "Розкажіть, будь ласка, про останній конкретний випадок.",
    "Що ви зробили далі?",
    "Що сталося потім?",
]


@dataclass
class InterviewerTurn:
    utterance: str
    topic_id: str
    action: str
    coverage_note: str = ""
    guard_rejections: List[List[str]] = field(default_factory=list)
    fallback_used: bool = False
    override: Optional[str] = None
    # Режим банку: яку саме записану репліку вибрано і де її аудіо.
    phrase_id: Optional[str] = None
    audio: Optional[str] = None
    # Звідки взялась репліка: дослівний текст із гайда чи вільне уточнення.
    source: str = ""


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


class Session:
    def __init__(
        self,
        space: SpaceConfig,
        guide: Guide,
        llm: LLMProvider,
        prompt_version: str = DEFAULT_PROMPT_VERSION,
        session_id: Optional[str] = None,
        bank=None,
    ):
        # Банк передається лише коли простір у режимі "bank" І банк придатний.
        # Вирішує це викликач (сервер), бо саме він може віддати зрозумілу
        # помилку досліднику, а не респонденту посеред розмови.
        self.bank = bank
        self.space = space
        self.guide = guide
        self.llm = llm
        self.prompt_version = prompt_version
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.started_at = _now()
        self.finished_at = None  # type: Optional[str]

        # Провайдер без структурованого виводу отримує скорочений промпт:
        # повний коштує йому вп'ятеро більше часу на кожну репліку.
        self.structured = getattr(llm, "supports_structured", True)
        if not self.structured and prompt_version == DEFAULT_PROMPT_VERSION:
            self.prompt_version = COMPACT_PROMPT_VERSION
        self.system = (build_system(space, guide, self.prompt_version, bank=bank)
                       if self.structured else None)
        # На вході, не при збереженні: інакше персональні дані спершу поїдуть
        # у вендора моделі, а «вичистимо» ми потім лише файл.
        self.deidentifier = Deidentifier.from_space(space)
        self.turns = []              # type: List[Dict[str, str]]
        self.topic_index = 0
        self.probes = {t.id: 0 for t in guide.topics}
        self.coverage = {t.id: [] for t in guide.topics}
        self.incidents = []          # type: List[Dict[str, Any]]
        self.done = False

        # Сценарій гайда: фази, рівні питань, драбина заглиблення. Ведеться
        # рушієм, а не моделлю — це рішення дослідника, зафіксовані в гайді.
        self.plan = phases.Plan(guide, self._detect_coverage) if guide.narrative_prompt or any(
            t.ask_if_missed or t.ask_for_detail for t in guide.topics
        ) else None
        self.phase_state = phases.PhaseState()
        # ── два режими, і різниця між ними принципова ──────────────────
        #
        # СЦЕНАРІЙ (гайд дає питання по темах): порядок задає дослідник, темп —
        # людина кнопками «наступне»/«попереднє». Модель не вирішує нічого:
        # чекліст тут шпаргалка, а не облік. Так працює простір «подорожі».
        #
        # ВІЛЬНИЙ РЕЖИМ (гайд питань не дає, лише теми й мету): питання
        # формулює модель, і тоді їй потрібне відстеження прогалин — інакше
        # вона не знає, про що питати далі. Так працює простір «example».
        #
        # Обидва лишаються, бо це різні інструменти. Судження моделі про «чи
        # можна далі» живе тільки у вільному режимі, де без нього не обійтись.
        scripted = self.plan is not None and any(
            topic.ask_if_missed or topic.ask_for_detail for topic in guide.topics)
        self.script = self.plan.script() if scripted else []
        self.cursor = 0

        # Чернетка: що людина вже проговорила на ЦЬОМУ питанні, але ще не
        # надіслала. Тримається окремо від стану рушія навмисно — «Сказати
        # заново» мусить прибирати галочки разом із текстом, інакше рушій
        # вважав би пункт закритим, а в транскрипті не було б нічого.
        # Згода на запис голосу — окреме рішення респондента, не частина згоди
        # на інтервʼю. Голос неможливо деідентифікувати, тому питається прямо.
        self.voice_consent = False
        # Записи, зроблені на поточну відповідь і ще не прикріплені до ходу.
        self.pending_voice = []      # type: List[str]

        self.draft_text = ""
        self.draft_done = []         # type: List[Any]
        # Що вже перевірили САМЕ для цього тексту. Текст виріс — перевіряємо
        # знову (людина щойно догово́рила те, чого бракувало); той самий текст
        # двічі не питаємо.
        self.draft_checked = []      # type: List[Any]
        self.draft_checked_text = ""
        # Звідки починати наступний прогін. За один прогін перевіряємо не всі
        # пункти, а наступні по колу: інакше десять тем розповіді коштували б
        # десятків секунд на кожну паузу в мовленні.
        self.draft_cursor = 0

    # ── стан ─────────────────────────────────────────────────────────────

    @property
    def topic(self):
        if self.topic_index >= len(self.guide.topics):
            return self.guide.topics[-1]
        return self.guide.topics[self.topic_index]

    @property
    def current_topic(self):
        """Тема, у якій розмова насправді зараз.

        `self.topic` дивиться на `topic_index` — старе поле, яке в режимі
        сценарію не рухається взагалі (той самий корінь, що й у бага з
        прогресом «Тема 1 з 10» назавжди). Через нього кожна відповідь у
        транскрипті підписувалась першою темою, і оцінка, звужена до «цієї ж
        теми», не знаходила НІЧОГО: закрилось 3 пункти з 20 замість 19.
        """
        if self.plan is not None and self.phase_state.phase == phases.TOPICS:
            topic = self.plan.topic_at(self.phase_state.topic_index)
            if topic is not None:
                return topic
        return self.topic

    @property
    def remaining_topics(self) -> List[str]:
        return [t.id for t in self.guide.topics[self.topic_index + 1:]]

    @property
    def covered_topics(self) -> List[str]:
        return [t.id for t in self.guide.topics[: self.topic_index]]

    def _state(self, guard_feedback: Optional[List[str]] = None) -> Dict[str, Any]:
        return {
            "topic_id": self.topic.id,
            "topic_title": self.topic.title,
            "probes_used": self.probes[self.topic.id],
            "probes_max": self.topic.max_probes,
            "turns": len([t for t in self.turns if t["role"] == "interviewer"]),
            "max_turns": self.guide.max_turns,
            "covered": self.covered_topics,
            "remaining": self.remaining_topics,
            "guard_feedback": guard_feedback or [],
        }

    # ── хід інтервʼю ─────────────────────────────────────────────────────

    # ── навігація сценарієм ──────────────────────────────────────────────

    def current_question(self) -> Dict[str, Any]:
        """Питання, на якому людина зараз."""
        if not self.script:
            return {}
        index = max(0, min(self.cursor, len(self.script) - 1))
        return self.script[index]

    def answers_for_current(self) -> List[str]:
        """Що людина вже сказала на поточне питання.

        Повернувшись назад, вона мусить бачити свою відповідь, а не порожнє
        поле: інакше «попереднє питання» виглядає як «почати заново».
        """
        question_id = (self.current_question() or {}).get("id")
        if not question_id:
            return []
        return [turn["text"] for turn in self.turns
                if turn.get("role") == "respondent"
                and turn.get("question_id") == question_id]

    def finish(self) -> str:
        """Завершення розмови. Прощання дослівне з гайда."""
        text = self.guide.closing or "Дякую за розмову."
        self.turns.append({"role": "interviewer", "text": text, "ts": _now(),
                           "question_id": "closing/final", "source": "closing"})
        self.done = True
        self.finished_at = _now()
        return text

    def go(self, delta: int) -> Dict[str, Any]:
        """Крок сценарієм. Повертає нове питання.

        Межі жорсткі: назад далі першого питання й уперед далі останнього не
        йдемо. Завершує інтервʼю окрема дія, а не «переліз через край» —
        випадково завершити розмову людина не має.
        """
        if not self.script:
            return {}
        self.cursor = max(0, min(self.cursor + delta, len(self.script) - 1))
        question = self.current_question()
        self.phase_state.phase = question.get("section", phases.WARMUP)
        return question

    def at_start(self) -> bool:
        return self.cursor <= 0

    def at_end(self) -> bool:
        return not self.script or self.cursor >= len(self.script) - 1

    def answered_current(self) -> bool:
        """Чи є відповідь на поточне питання.

        «Наступне» вмикається лише після відповіді: інакше людина проклацає
        інтервʼю, не сказавши нічого, і в даних лишиться порожньо.
        """
        question_id = (self.current_question() or {}).get("id")
        if not question_id:
            return False
        return any(turn.get("role") == "respondent"
                   and turn.get("question_id") == question_id
                   for turn in self.turns)

    def show_current(self) -> str:
        """Текст поточного питання; у транскрипт воно потрапляє один раз.

        Навігація туди-сюди не має плодити дублікати: питання в транскрипті —
        це «його поставили», а не «його показали вдруге».
        """
        question = self.current_question()
        if not question:
            return ""
        already = any(turn.get("role") == "interviewer"
                      and turn.get("question_id") == question["id"]
                      for turn in self.turns)
        text = question["text"]
        if self.cursor == 0 and self.space.persona.self_intro:
            # Відкриття несе рамку всієї розмови — воно однакове для всіх.
            text = "%s\n\n%s" % (self.space.persona.self_intro, text)
        if not already:
            self.turns.append({
                "role": "interviewer", "text": text, "ts": _now(),
                "question_id": question["id"],
                "topic_id": question.get("topic_id", ""),
                "phase": question.get("section", ""),
                "source": question["id"],
            })
        return text

    def start(self) -> str:
        """Перша репліка. Відкриття не віддаємо моделі: воно задає рамку всієї
        розмови і має бути однаковим для всіх респондентів."""
        if self.script:
            self.cursor = 0
            self.phase_state.phase = self.script[0].get("section", phases.WARMUP)
            return self.show_current()
        if self.bank is not None:
            phrase = self.bank.opening
            text = phrase.text
            entry = {"role": "interviewer", "text": text, "ts": _now(),
                     "topic_id": self.topic.id, "phrase_id": phrase.id,
                     "audio": phrase.audio}
            self.turns.append(entry)
            return text

        opening = self.guide.opening or _FALLBACK_PROBES[0]
        text = "%s\n\n%s" % (self.space.persona.self_intro, opening)
        self.turns.append({"role": "interviewer", "text": text, "ts": _now(),
                           "topic_id": self.topic.id})
        return text

    def answer(self, respondent_text: str,
               finish_narrative: bool = False) -> InterviewerTurn:
        """Респондент відповів — повертаємо наступну репліку інтервʼюера.

        `finish_narrative` — людина сказала «я все розповіла». Без цієї дії
        фаза розповіді триває, поки не вичерпаються ходи або поки людина двічі
        не відповість коротко, і виглядає це як «нічого не відбувається».
        """
        if self.done:
            raise RuntimeError("Інтервʼю вже завершено")

        # Чернетку закриваємо тут: далі рушій дасть інше питання, і галочки,
        # зароблені на попередньому, до нього не стосуються. Саме зарахування
        # відповіді робить `_resolve_items` — уже в стані рушія, надовго.
        self.reset_draft()

        clean, masked = self.deidentifier.scrub(respondent_text)
        entry = {"role": "respondent", "text": clean, "ts": _now(),
                 "topic_id": self.current_topic.id,
                 # Фаза, у якій це сказано. Потрібна оцінювачу, щоб не
                 # зараховувати тему чужою відповіддю (див. `_said_for_topic`),
                 # і досліднику — щоб бачити, де в розмові що прозвучало.
                 "phase": self.phase_state.phase if self.plan else ""}
        if self.pending_voice:
            # Записи цієї відповіді — у сам хід: дослідник мусить бачити, який
            # файл до якої репліки належить, а не купу файлів окремо.
            entry["voice"] = list(self.pending_voice)
            self.pending_voice = []
        if masked:
            # Слід у транскрипті: дослідник має бачити, що інструмент прибрав,
            # інакше маскування не відрізнити від збою розпізнавання.
            entry["masked"] = masked
            self.incidents.append({"kind": "deidentified", "rules": masked, "ts": _now()})
        self.turns.append(entry)

        if self.script:
            # Сценарій веде людина: відповідь записується, наступний крок —
            # окрема її дія. Модель тут не вирішує нічого.
            question = self.current_question()
            entry["question_id"] = question.get("id", "")
            entry["topic_id"] = question.get("topic_id", "") or entry.get("topic_id", "")
            entry["phase"] = question.get("section", "")
            return InterviewerTurn(utterance="", action="recorded",
                                   topic_id=entry["topic_id"], source="recorded")

        if self.plan is not None:
            if finish_narrative and self.phase_state.phase == phases.NARRATIVE:
                # Достатньо позначити ходи вичерпаними: рушій сам перейде далі
                # і сам визначить покриття тем за всією розповіддю.
                self.phase_state.narrative_count = max(
                    self.phase_state.narrative_count, self.guide.narrative_turns)
            turn = self._ask_planned(clean)
        elif self.bank is not None:
            turn = self._ask_bank()
        elif self.structured:
            turn = self._ask_llm()
        else:
            turn = self._ask_text()
        turn = self._enforce(turn)

        # Порожня репліка — це мовчання інтервʼюера у фазі розповіді. Писати
        # його в транскрипт означало б плодити порожні ходи.
        if turn.utterance:
            entry = {"role": "interviewer", "text": turn.utterance, "ts": _now(),
                     "topic_id": turn.topic_id}
            if turn.source:
                entry["source"] = turn.source
            if turn.phrase_id:
                entry["phrase_id"] = turn.phrase_id
                entry["audio"] = turn.audio
            self.turns.append(entry)
        if turn.action == "wrap_up":
            self.done = True
            self.finished_at = _now()
        return turn

    # ── звернення до моделі + guard ───────────────────────────────────────

    def _messages(self, guard_feedback: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        msgs = []
        for t in self.turns:
            role = "assistant" if t["role"] == "interviewer" else "user"
            msgs.append({"role": role, "content": t["text"]})

        state = build_state_block(self._state(guard_feedback))
        if getattr(self.llm, "supports_system_turns", False):
            # Службовий стан окремим system-повідомленням: не ламає кеш
            # стабільного префікса і не виглядає як слова респондента.
            msgs.append({"role": "system", "content": state})
        else:
            # Провайдер не вміє system посеред розмови — доклеюємо до останньої
            # реплики респондента з явним розділювачем.
            if msgs and msgs[-1]["role"] == "user":
                msgs[-1] = {"role": "user", "content": "%s\n\n%s" % (msgs[-1]["content"], state)}
            else:
                msgs.append({"role": "user", "content": state})
        return msgs

    def _detect_coverage(self, narrative_text: str, topics) -> Optional[List[str]]:
        """Питаємо модель по кожній темі окремо: «так» чи «ні».

        Спершу було одне питання зі списком і проханням назвати номери — слабка
        модель відповідала «майже всі» (9 тем із 10 при трьох реально
        розказаних). Переоцінка тут гірша за недооцінку: питання рівня 2
        припускає, що тему вже згадували, і на непочату тему звучить як
        «розкажіть про той випадок» без жодного випадку.

        Питання «так/ні» про одну тему модель тримає надійно. Це 10 викликів
        один раз після розповіді — респондент чекає один раз.
        """
        if not narrative_text.strip():
            return []

        covered = []
        for topic in topics:
            what = topic.goal or topic.title
            said_yes = judging.ask(
                self.llm, judging.topic_question(narrative_text, topic.title, what))
            if said_yes is None:
                return None
            if said_yes:
                covered.append(topic.id)

        self.incidents.append({"kind": "coverage_detected", "topics": covered, "ts": _now()})
        return covered

    def _narrative_text(self) -> str:
        """Усе, що респондент сказав у фазі вільної розповіді.

        Потрібне, щоб визначити, які теми вже прозвучали — і не питати вдруге
        (правило гайда «позначати подумки, що вже прозвучало»).
        """
        return " ".join(t["text"] for t in self.turns if t["role"] == "respondent")

    # Скільком пунктам максимум даємо оцінку за один хід. Кожен пункт — окремий
    # виклик моделі, тому межа є; але одна відповідь часто закриває два пункти
    # («Оля запропонувала за місяць до поїздки»), і не побачити цього означало б
    # питати про вже сказане.
    MAX_ITEM_CHECKS_PER_TURN = 3

    # Скільком темам за один хід розповіді даємо оцінку «чи вже звучала». Так
    # перевірка розтягується по ходах, а не стає десятисекундною паузою в мить,
    # коли людина натиснула «Я все розповіла».
    MAX_TOPIC_CHECKS_PER_TURN = 3

    # ОДИН пункт за виклик — і це про швидкість, а не про економію.
    #
    # Оцінка одного пункта коштує ~1,3 с, і майже все це — обробка промпту, а не
    # генерація (кап токенів нічого не змінює: зміряно 80 → 3 токени, різниці
    # немає). Коли за один запит оцінювались три пункти, перша галочка
    # зʼявлялась через ~4 с. Тепер відповідь повертається після першого пункта,
    # клієнт одразу малює його й питає наступний — галочки проступають одна за
    # одною, замість того щоб чекати всі разом.
    MAX_DRAFT_CHECKS_PER_CALL = 1

    def _scan_narrative(self) -> None:
        """Поступово зʼясовує, які теми вже прозвучали у розповіді.

        Побічний і головний ефект: чекліст у фазі розповіді заповнюється
        галочками **по ходу**, тому людина бачить, про що вже розповіла і про
        що ми ще чекаємо почути.
        """
        if self.plan is None or self.phase_state.phase != phases.NARRATIVE:
            return
        pending = [topic for topic in self.guide.topics
                   if topic.id not in self.phase_state.narrative_checked]
        if not pending:
            return
        said = self._narrative_text()
        if not said.strip():
            return

        batch = pending[: self.MAX_TOPIC_CHECKS_PER_TURN]
        found = self._detect_coverage(said, batch)
        if found is None:
            return
        for topic in batch:
            self.phase_state.narrative_checked.append(topic.id)
        for tid in found:
            if tid not in self.phase_state.covered_in_narrative:
                self.phase_state.covered_in_narrative.append(tid)

    def _said_for_topic(self, topic) -> str:
        """Текст, у якому взагалі має сенс шукати пункти ЦІЄЇ теми.

        Не «все, що людина сказала». Спостережено на повному прогоні: відповіді
        на теми «Розподіл внеску» й «Гроші» закрили пункти тем «Розбіжна
        інформація», «Розбіжність поглядів» і «Поведінка на місці» — і рушій не
        спитав про них узагалі. Три теми дослідження зникли молча.

        Береться:
        — вільна розповідь і розігрів: там людина розповідає про все підряд, і
          саме там пункт будь-якої теми може законно прозвучати;
        — відповіді в межах цієї ж теми: рівень 1, рівень 2, уточнення.

        Відповіді на ІНШІ теми — ні. Оцінювач надто щедрий (TD-31), і саме тут
        його щедрість коштує найдорожче: не зайвого питання, а втраченої теми.
        """
        parts = []
        for turn in self.turns:
            if turn.get("role") != "respondent":
                continue
            phase = turn.get("phase")
            if phase in (phases.WARMUP, phases.NARRATIVE, "", None):
                parts.append(turn["text"])
            elif turn.get("topic_id") == topic.id:
                parts.append(turn["text"])
        return " ".join(parts)

    def _resolve_phase_items(self, last_answer: str) -> None:
        """Оцінка очікуваного в розігріві й підсумку.

        Окремо від `_resolve_items` (теми) з двох причин. По-перше, порядок:
        тут оцінка потрібна до вибору ходу, там — після. По-друге, обсяг: пункти
        розігріву й підсумку належать одному конкретному питанню, тому й
        перевіряються проти відповіді на нього, а не проти всієї розмови.
        """
        if self.plan is None:
            return
        if self.phase_state.phase not in (phases.WARMUP, phases.CLOSING):
            return
        items, done = self._expectation()
        if not items:
            return
        gaps = phases.open_expectations(items, done)
        said = (last_answer or "").strip()
        if not gaps or not said:
            return
        for index in gaps[: self.MAX_ITEM_CHECKS_PER_TURN]:
            if not self._developed_enough(said, items[index]):
                continue
            if self._item_covered(said, items[index]):
                if index not in done:
                    done.append(index)
                    self.incidents.append({
                        "kind": "item_closed", "phase": self.phase_state.phase,
                        "item": items[index], "ts": _now(),
                    })

    def _resolve_items(self, last_answer: str) -> None:
        """Що з очікуваного ми вже почули.

        Перевіряємо проти розповіді й проти відповідей у цій же темі, а не
        проти однієї останньої репліки: пункт, що прозвучав у вільній розповіді,
        не має лишатись відкритим. Але й не проти всього підряд — див.
        `_said_for_topic`.
        """
        if self.phase_state.phase != phases.TOPICS:
            return
        topic = self.plan.topic_at(self.phase_state.topic_index)
        if topic is None or not topic.must_learn:
            return
        gaps = phases.open_items(topic, self.phase_state)
        if not gaps:
            return

        self._resolve_items_for(topic)

    def _resolve_items_for(self, topic) -> None:
        """Оцінка пунктів КОНКРЕТНОЇ теми. Окремо, бо цього просять двоє:
        звичайний хід і повернення до раніше відповіданого питання."""
        gaps = phases.open_items(topic, self.phase_state)
        if not gaps:
            return
        said = self._said_for_topic(topic)
        if not said.strip():
            return

        for index in gaps[: self.MAX_ITEM_CHECKS_PER_TURN]:
            item = topic.must_learn[index]
            if not self._developed_enough(said, item, topic):
                # Коротка відповідь лишає пункт відкритим — рушій перепитає.
                continue
            closed = self._item_covered(said, item)
            if closed is None:
                # Не змогли оцінити — пункт лишається відкритим. Зайве уточнення
                # дешевше за прогалину в даних.
                continue

            if closed:
                done = self.phase_state.topic_items_done.setdefault(topic.id, [])
                if index not in done:
                    done.append(index)
                    self.incidents.append({
                        "kind": "item_closed", "topic_id": topic.id,
                        "item": item, "ts": _now(),
                    })

    @staticmethod
    def _word_count(text: str) -> int:
        return len(re.findall(r"\w+", text or ""))

    def _developed_enough(self, said: str, item: str, topic=None) -> bool:
        """Чи відповідь достатньо розгорнута, щоб зараховувати цей пункт.

        Перевірка ДО моделі й дешева. Сенс не в тому, щоб не довіряти
        оцінювачу, а в тому, що «Оля.» — це не відповідь на «хто запропонував
        поїхати»: людина назвала слово, а не розповіла. Для дослідження таке
        зарахування гірше за відкритий пункт, бо в транскрипті лишається слово,
        з якого нічого не видно.

        Дві межі:
        — спільна нижня (`MIN_WORDS_TO_CREDIT`): одне-два слова не зараховують
          нічого й ніколи;
        — власна межа пункта (`needs_words` із гайда) — для пунктів, що просять
          розповідь, а не факт. «Нас було шість» повна відповідь на «скільки вас
          було», і завищена межа тут лише плодила б зайві питання.
        """
        count = self._word_count(said)
        if count < space_config.MIN_WORDS_TO_CREDIT:
            return False
        needed = 0
        if topic is not None:
            needed = (topic.needs_words or {}).get(item, 0)
        return count >= needed

    def _item_covered(self, said: str, item: str):
        """Чи можна дізнатися «item» зі сказаного. None — оцінити не вдалося.

        Формулювання живе в `judge.py` разом із числами, які воно дало на
        еталоні: те, що міряють, і те, що працює, мусить бути одним кодом.
        """
        return judging.ask(self.llm, judging.item_question(said, item))

    def _expectation(self):
        """Чого чекаємо на ЦЬОМУ питанні: (перелік, список зарахованих індексів).

        Одне джерело для чекліста, живої перевірки й кнопки «надіслати»: коли
        вони питали різні місця, кнопка розблоковувалась не тоді, коли галочки
        ставали повними. Список зарахованих повертається **той самий об'єкт**
        зі стану — у нього дописують.

        Фаза розповіді сюди не входить: там очікуване — теми гайда, і вони
        зараховуються за id, а не за індексом (див. `checklist`).
        """
        phase = self.phase_state.phase
        if phase == phases.WARMUP:
            return list(self.guide.opening_expects), self.phase_state.opening_items_done
        if phase == phases.TOPICS:
            topic = self.plan.topic_at(self.phase_state.topic_index) if self.plan else None
            if topic is None or not topic.must_learn:
                return [], []
            return list(topic.must_learn), self.phase_state.topic_items_done.setdefault(
                topic.id, [])
        if phase == phases.CLOSING:
            index = max(0, self.phase_state.closing_index - 1)
            if index < len(self.guide.closing_expects):
                return (list(self.guide.closing_expects[index]),
                        self.phase_state.closing_items_done.setdefault(index, []))
        return [], []

    def reset_draft(self) -> None:
        """Людина сказала заново — галочки чернетки йдуть разом із текстом."""
        self.draft_text = ""
        self.draft_done = []
        self.draft_cursor = 0
        self.draft_checked = []
        self.draft_checked_text = ""

    def evaluate_draft(self, text: str) -> Dict[str, Any]:
        """Живе зарахування: людина ще говорить, галочки вже ставляться.

        Не пише в транскрипт і не рухає рушій: це чернетка. Перевіряються лише
        пункти, ще не зараховані, і не більше `MAX_DRAFT_CHECKS_PER_CALL` за
        виклик — решта дочекається наступної паузи в мовленні.
        """
        text = (text or "").strip()
        # Позначки лишаються, поки в тексті лишається те, за що їх поставили.
        #
        # Спершу тут стояла перевірка на префікс — і вона скидала все, щойно
        # людина правила початок фрази або обривала слово: «Їздили в Карпа»
        # знімало обидві зароблені галочки. Для людини це виглядало як «я це
        # сказала, а воно забуло». Тепер міряємо перетин слів: правка й дописування
        # позначок не чіпають, а «стерла все і сказала інше» — чіпає.
        if not text or not self._same_answer(self.draft_text, text):
            self.draft_done = []
            self.draft_cursor = 0
        if text != self.draft_checked_text:
            # Текст інший — попередні «ні» більше не про нього.
            self.draft_checked = []
            self.draft_checked_text = text
        self.draft_text = text

        # Судимо ТІЛЬКИ те, що людина говорить зараз, а не все інтервʼю.
        # Спершу я додавав до чернетки всі попередні відповіді — і галочка
        # зʼявлялась на слові, що не мало до пункта стосунку: її насправді
        # спричинив старий текст. Живий відгук мусить бути причинно чесним:
        # галочка = «оце, що ви щойно сказали».
        #
        # Зараховане з попередніх ходів не губиться: воно вже в стані рушія
        # (`_resolve_items` після надсилання) і показується як `done`.
        if text:
            if self.phase_state.phase == phases.NARRATIVE:
                self._evaluate_draft_narrative(text)
            else:
                self._evaluate_draft_items(text)

        return {
            "checklist": self.checklist(),
            "all_covered": self.all_expected_covered(),
            # Чи лишились непроверені пункти для ЦЬОГО тексту. Клієнт бачить
            # `more` і одразу питає наступний, не чекаючи нової паузи в мовленні.
            "more": self._draft_has_more(),
        }

    # Скільки слів попередньої чернетки мусить лишитись, щоб вважати, що це та
    # сама відповідь. Дві третини: людина може переписати фразу, але якщо від
    # неї лишилась третина — це вже інша відповідь.
    SAME_ANSWER_RATIO = 0.66

    @staticmethod
    def _same_answer(before: str, after: str) -> bool:
        """Чи це та сама відповідь, лише доповнена або виправлена."""
        old_words = re.findall(r"\w+", (before or "").lower())
        if not old_words:
            return True
        new_words = set(re.findall(r"\w+", (after or "").lower()))
        kept = sum(1 for word in old_words if word in new_words)
        return kept >= len(old_words) * Session.SAME_ANSWER_RATIO

    def _draft_pending(self):
        """Пункти, які ще можна перевірити для поточного тексту чернетки."""
        if self.phase_state.phase == phases.NARRATIVE:
            covered = set(self.phase_state.covered_in_narrative) | set(self.draft_done)
            return [t.id for t in self.guide.topics
                    if t.id not in covered and t.id not in self.draft_checked]
        items, done = self._expectation()
        return [i for i in range(len(items))
                if i not in done and i not in self.draft_done
                and i not in self.draft_checked]

    def _draft_has_more(self) -> bool:
        return bool(self.draft_text) and bool(self._draft_pending())

    def _evaluate_draft_items(self, full: str) -> None:
        items, done = self._expectation()
        topic = (self.plan.topic_at(self.phase_state.topic_index)
                 if self.plan is not None and self.phase_state.phase == phases.TOPICS
                 else None)
        pending = self._draft_pending()
        for index in self._draft_batch(pending):
            self.draft_checked.append(index)
            # Та сама межа, що й після надсилання: галочка не має зʼявлятись на
            # одному слові, а потім зникати, коли рушій її не підтвердить.
            if not self._developed_enough(full, items[index], topic):
                continue
            if self._item_covered(full, items[index]):
                self.draft_done.append(index)

    def _draft_batch(self, pending):
        """Кого перевіряємо цього прогону: наступних по колу.

        Кешувати «цього не почули» не можна: людина говорить далі, і саме та
        фраза, якої бракувало, звучить наступною. Спостережено — дописаний текст
        не закривав пункти, бо їх один раз перевірили й більше не питали.
        """
        if not pending:
            self.draft_cursor = 0
            return []
        start = self.draft_cursor % len(pending)
        order = pending[start:] + pending[:start]
        batch = order[: self.MAX_DRAFT_CHECKS_PER_CALL]
        self.draft_cursor = start + len(batch)
        return batch

    def _evaluate_draft_narrative(self, full: str) -> None:
        pending_ids = self._draft_pending()
        pending = [t for t in self.guide.topics if t.id in pending_ids]
        batch = [pending[i] for i in self._draft_batch(list(range(len(pending))))]
        if not batch:
            return
        for topic in batch:
            self.draft_checked.append(topic.id)
        found = self._detect_coverage(full, batch)
        if found is None:
            return
        for topic in batch:
            if topic.id in found and topic.id not in self.draft_done:
                self.draft_done.append(topic.id)

    def all_expected_covered(self) -> bool:
        """Чи почули ми все, чого чекали на цьому питанні.

        Порожній чекліст — не «все зараховано»: там просто немає очікувань,
        і кнопку «надіслати» гейтити нічим (див. `web/app.js`).
        """
        items = self.checklist()
        return bool(items) and all(item.get("done") for item in items)

    def _ask_planned(self, last_answer: str) -> InterviewerTurn:
        """Хід за сценарієм гайда.

        Дослівні репліки гайда йдуть як є — їх не перевіряє guard і не
        переформулює модель: це формулювання дослідника, вони вже вивірені.
        Модель викликається лише там, де сценарій просить вільне уточнення.
        """
        # У фазі розповіді — сканування по ходу; у темах — оцінка пунктів.
        self._scan_narrative()
        # Розігрів і підсумок оцінюємо ДО вибору ходу — і це не деталь: рішення
        # «доперепитати чи йти далі» залежить саме від того, чи почули ми
        # очікуване від питання, на яке людина щойно відповіла. У темах
        # навпаки: там оцінка мусить бути ПІСЛЯ (див. коментар нижче).
        self._resolve_phase_items(last_answer)
        action = self.plan.next_action(self.phase_state, last_answer,
                                       self._narrative_text())
        # Оцінюємо ПІСЛЯ вибору ходу, а не до нього. На ході, який переводить із
        # розповіді в теми, фаза ще була «розповідь», і оцінка виходила одразу —
        # тому пункти, що прозвучали в розповіді, лишались відкритими, а чекліст
        # показував нулі там, де людина вже все сказала.
        self._resolve_items(last_answer)

        # Перевибір ходу тут стояв: якщо оцінка закривала тему до того, як
        # звучало вже вибране питання рівня 1/2, воно ставало зайвим. Код
        # прибраний, бо в цій гілці таких питань більше не буває: гайд із
        # питаннями по темах іде сценарним режимом, де темп задає людина, а
        # тут лишились тільки простори, де питання формулює модель.

        if action.kind == phases.WRAP_UP:
            return InterviewerTurn(
                utterance=action.text or self.guide.closing,
                topic_id=action.topic_id or self.topic.id,
                action="wrap_up",
                source=action.label,
            )

        if action.kind == phases.HOLD:
            # Інтервʼюер мовчить: репліки немає, і в транскрипт вона не йде.
            return InterviewerTurn(
                utterance="",
                topic_id=action.topic_id or self.topic.id,
                action="hold",
                source=action.label,
            )

        if action.kind == phases.FIXED:
            return InterviewerTurn(
                utterance=action.text,
                topic_id=action.topic_id or self.topic.id,
                action="probe",
                source=action.label,
            )

        # Вільне уточнення: тут потрібна модель.
        turn = (self._ask_text(focus=action.focus) if not self.structured
                else self._ask_llm())
        turn.topic_id = action.topic_id or turn.topic_id
        turn.action = "probe"
        turn.source = action.label
        return turn

    def _ask_text(self, focus: str = "") -> InterviewerTurn:
        """Шлях для моделей без структурованого виводу.

        Модель дає лише текст питання. `action` тут завжди "probe": рішення про
        перехід до наступної теми й про завершення ухвалює `_enforce` за
        лімітами — воно робило це й раніше, просто тепер це єдине джерело
        рішень, а не підстраховка.
        """
        rejections = []
        feedback = None
        for _ in range(MAX_GUARD_RETRIES + 1):
            system = build_system_compact(self.space, self.guide, self.topic,
                                          self.prompt_version)
            if focus:
                # Прогалина, яку записав дослідник. Без цього модель питає
                # «щось по темі», а нам треба закрити саме це.
                system += ("\n\n**СПИТАЙ САМЕ ПРО ЦЕ:** %s\n"
                           "Сформулюй питання так, щоб респондент розповів саме це, "
                           "спираючись на його останню відповідь." % focus)
            if feedback:
                system += ("\n\n⛔ Попередню репліку відхилено: %s. Переформулюй: "
                           "коротке відкрите питання про конкретний випадок."
                           % "; ".join(feedback))
            utterance = self.llm.respond_text(system, self._plain_messages())
            problems = guard.check_turn(
                utterance, self.space.domain_vocabulary, self.turns,
                require_spoken_form=self.space.requires_spoken_form,
            )
            if not problems:
                return InterviewerTurn(
                    utterance=utterance,
                    topic_id=self.topic.id,
                    action="probe",
                    guard_rejections=rejections,
                )
            rejections.append(problems)
            feedback = problems
            self.incidents.append({"kind": "guard_rejection", "utterance": utterance,
                                   "problems": problems, "ts": _now()})

        idx = len([i for i in self.incidents if i["kind"] == "guard_fallback"])
        self.incidents.append({"kind": "guard_fallback", "ts": _now()})
        return InterviewerTurn(
            utterance=_FALLBACK_PROBES[idx % len(_FALLBACK_PROBES)],
            topic_id=self.topic.id,
            action="probe",
            guard_rejections=rejections,
            fallback_used=True,
        )

    def _plain_messages(self) -> List[Dict[str, Any]]:
        """Розмова без службового блоку: він потрібен лише для рішень моделі,
        а їх тут ухвалює ядро."""
        return [
            {"role": "assistant" if t["role"] == "interviewer" else "user",
             "content": t["text"]}
            for t in self.turns
        ]

    def _ask_bank(self) -> InterviewerTurn:
        """Модель вибирає id репліки. Перевіряємо, що такий існує й записаний.

        Guard тут майже не потрібен: банк переглянула людина, навідних питань у
        ньому немає за побудовою. Лишається перевірка самого вибору — модель
        може назвати id, якого немає.
        """
        rejections = []
        feedback = None
        recent = [t.get("phrase_id") for t in self.turns[-4:] if t.get("phrase_id")]

        for _ in range(MAX_GUARD_RETRIES + 1):
            data = self.llm.respond_json(
                system=self.system,
                messages=self._messages(feedback),
                schema=BANK_TURN_SCHEMA,
            )
            phrase_id = (data.get("phrase_id") or "").strip()
            phrase = self.bank.by_id(phrase_id)

            problems = []
            if phrase is None:
                problems.append("репліки «%s» у банку немає" % phrase_id)
            elif not phrase.recorded:
                problems.append("репліка «%s» ще не записана голосом" % phrase_id)
            elif phrase.kind == "opening":
                problems.append("відкриття вимовляється лише на старті")
            elif phrase_id in recent[-1:]:
                problems.append("ця сама репліка щойно звучала — вибери іншу")

            if not problems:
                return InterviewerTurn(
                    utterance=phrase.text,
                    topic_id=data.get("topic_id") or self.topic.id,
                    action=data.get("action") or "probe",
                    coverage_note=data.get("coverage_note", ""),
                    guard_rejections=rejections,
                    phrase_id=phrase.id,
                    audio=phrase.audio,
                )
            rejections.append(problems)
            feedback = problems
            self.incidents.append({"kind": "bank_rejection", "phrase_id": phrase_id,
                                   "problems": problems, "ts": _now()})

        # Модель тричі не змогла вибрати — беремо загальне уточнення самі.
        fallback = self._fallback_phrase(recent)
        self.incidents.append({"kind": "bank_fallback", "phrase_id": fallback.id, "ts": _now()})
        return InterviewerTurn(
            utterance=fallback.text,
            topic_id=self.topic.id,
            action="probe",
            guard_rejections=rejections,
            fallback_used=True,
            phrase_id=fallback.id,
            audio=fallback.audio,
        )

    def _fallback_phrase(self, recent: List[str]):
        """Найбезпечніший вибір: записане загальне уточнення, якого щойно не було."""
        probes = [p for p in self.bank.probes if p.recorded]
        fresh = [p for p in probes if p.id not in recent]
        pool = fresh or probes
        if not pool:
            # Такого не має бути: придатність банку перевіряється до старту.
            raise RuntimeError("У банку немає записаних уточнень")
        return pool[len(self.incidents) % len(pool)]

    def _ask_llm(self) -> InterviewerTurn:
        rejections = []
        feedback = None
        for attempt in range(MAX_GUARD_RETRIES + 1):
            data = self.llm.respond_json(
                system=self.system,
                messages=self._messages(feedback),
                schema=TURN_SCHEMA,
            )
            utterance = (data.get("utterance") or "").strip()
            problems = guard.check_turn(
                utterance,
                self.space.domain_vocabulary,
                self.turns,
                require_spoken_form=self.space.requires_spoken_form,
                require_question=True,
            )
            if not problems:
                return InterviewerTurn(
                    utterance=utterance,
                    topic_id=data.get("topic_id") or self.topic.id,
                    action=data.get("action") or "probe",
                    coverage_note=data.get("coverage_note", ""),
                    guard_rejections=rejections,
                )
            rejections.append(problems)
            feedback = problems
            self.incidents.append({
                "kind": "guard_rejection",
                "attempt": attempt + 1,
                "utterance": utterance,
                "problems": problems,
                "ts": _now(),
            })

        # Модель не змогла — не пускаємо в інтервʼю зіпсовану репліку.
        idx = len([i for i in self.incidents if i["kind"] == "guard_fallback"])
        self.incidents.append({"kind": "guard_fallback", "ts": _now()})
        return InterviewerTurn(
            utterance=_FALLBACK_PROBES[idx % len(_FALLBACK_PROBES)],
            topic_id=self.topic.id,
            action="probe",
            guard_rejections=rejections,
            fallback_used=True,
        )

    # ── жорсткі правила ──────────────────────────────────────────────────

    def _enforce(self, turn: InterviewerTurn) -> InterviewerTurn:
        # За сценарієм гайда переходи й ліміти веде рушій фаз: він знає про
        # розповідь, рівні питань і драбину заглиблення, чого _enforce не знає.
        if self.plan is not None:
            interviewer_turns = len([t for t in self.turns if t["role"] == "interviewer"])
            if interviewer_turns >= self.guide.max_turns and turn.action != "wrap_up":
                turn.action = "wrap_up"
                turn.override = "ліміт реплік (%d) — завершення форсовано" % self.guide.max_turns
                if self.guide.closing:
                    turn.utterance = self.guide.closing
                self.incidents.append({"kind": "override", "detail": turn.override, "ts": _now()})
            return turn

        if turn.coverage_note:
            self.coverage[self.topic.id].append(turn.coverage_note)

        interviewer_turns = len([t for t in self.turns if t["role"] == "interviewer"])

        # 1. Ліміт реплік — понад усе.
        if interviewer_turns >= self.guide.max_turns:
            if turn.action != "wrap_up":
                turn.override = "ліміт реплік (%d) — завершення форсовано" % self.guide.max_turns
            turn.action = "wrap_up"
            return self._finalize(turn)

        # 2. Ліміт уточнень у темі: модель хоче копати, код не дає.
        if turn.action == "probe":
            if self.probes[self.topic.id] >= self.topic.max_probes:
                if self.remaining_topics:
                    turn.override = ("ліміт уточнень теми '%s' (%d) — перехід форсовано"
                                     % (self.topic.id, self.topic.max_probes))
                    turn.action = "next_topic"
                else:
                    turn.override = "теми покриті й ліміт уточнень вичерпано — завершення форсовано"
                    turn.action = "wrap_up"
            else:
                self.probes[self.topic.id] += 1

        # 3. Перехід до наступної теми.
        if turn.action == "next_topic":
            if self.remaining_topics:
                self.topic_index += 1
                self.probes[self.topic.id] += 1
            else:
                turn.override = "тем більше немає — завершення форсовано"
                turn.action = "wrap_up"

        # 4. Модель хоче завершити, а теми не покриті — не даємо.
        elif turn.action == "wrap_up" and self.remaining_topics:
            turn.override = ("спроба завершити з непокритими темами (%s) — відхилено"
                             % ", ".join(self.remaining_topics))
            turn.action = "next_topic"
            self.topic_index += 1
            self.probes[self.topic.id] += 1

        return self._finalize(turn)

    def _finalize(self, turn: InterviewerTurn) -> InterviewerTurn:
        """Єдина точка виходу з _enforce. Раніше тут був другий `return`, і гілка
        ліміту реплік його обходила — інтервʼю закінчувалось питанням у повітрі."""
        # Якщо завершення форсоване, репліка моделі — це ще одне питання, і
        # закінчувати ним інтервʼю не можна.
        if turn.action == "wrap_up":
            if self.bank is not None and self.bank.closing:
                closing = self.bank.closing
                turn.utterance = closing.text
                turn.phrase_id = closing.id
                turn.audio = closing.audio
            elif turn.override and self.guide.closing:
                turn.utterance = self.guide.closing

        if turn.override:
            self.incidents.append({"kind": "override", "detail": turn.override, "ts": _now()})
        return turn

    # ── видача ───────────────────────────────────────────────────────────

    @classmethod
    def from_dict(
        cls,
        space: SpaceConfig,
        guide: Guide,
        llm: LLMProvider,
        data: Dict[str, Any],
    ) -> "Session":
        """Відновлення незавершеного інтервʼю.

        Гайд і промпт беруться з поточних файлів, а не з транскрипту: якщо їх
        змінили посеред хвилі, це видно в `prompt_version` збереженої сесії —
        і краще впасти на розбіжності, ніж тихо змішати дві методології.
        """
        if data.get("guide") != guide.key:
            raise ValueError(
                "Сесія належить гайду '%s', а завантажений '%s'" % (data.get("guide"), guide.key)
            )

        session = cls(space, guide, llm, session_id=data["session_id"])

        # Порівнюємо з тим, що дав би ЦЕЙ провайдер зараз, а не з фіксованою
        # версією за замовчуванням. Раніше було навпаки — і resume завжди падав
        # для локальної моделі: MLX не дає структурованого виводу, тому їй
        # призначається `interviewer.compact`, а перевірка звіряла це з
        # `interviewer.v1` і незмінно кидала виняток. Тобто відновлення сесії
        # для «подорожей» після перезапуску сервера НЕ ПРАЦЮВАЛО ЖОДНОГО РАЗУ —
        # спіймано лише зараз, при написанні тесту на курсор.
        saved_version = data.get("prompt_version")
        if saved_version and saved_version != session.prompt_version:
            raise ValueError(
                "Сесія записана промптом '%s', а поточний — '%s'. Дозбирати її "
                "новою методологією нельзя: це змішає дані двох різних інтервʼю."
                % (saved_version, session.prompt_version)
            )
        session.started_at = data.get("started_at") or session.started_at
        session.turns = list(data.get("turns") or [])
        session.incidents = list(data.get("incidents") or [])
        session.done = bool(data.get("completed"))
        session.finished_at = data.get("finished_at")

        session.voice_consent = bool(data.get("voice_consent"))

        state = data.get("state") or {}
        session.pending_voice = [str(x) for x in (state.get("pending_voice") or [])]
        session.phase_state = phases.PhaseState.from_dict(state.get("phase"))
        session.topic_index = min(int(state.get("topic_index", 0)), len(guide.topics) - 1)

        if session.script:
            if "cursor" in state:
                session.cursor = max(0, min(int(state["cursor"]), len(session.script) - 1))
            else:
                # Сесії, збережені до появи "cursor": відновлюємо з останнього
                # питання в транскрипті, а не з нуля.
                last_qid = next(
                    (t.get("question_id") for t in reversed(session.turns)
                     if t.get("role") == "interviewer" and t.get("question_id")), None)
                if last_qid:
                    ids = [q["id"] for q in session.script]
                    if last_qid in ids:
                        session.cursor = ids.index(last_qid)
        saved_probes = state.get("probes") or {}
        for topic in guide.topics:
            session.probes[topic.id] = int(saved_probes.get(topic.id, 0))
        saved_coverage = data.get("coverage") or {}
        for topic in guide.topics:
            session.coverage[topic.id] = list(saved_coverage.get(topic.id) or [])
        return session

    def _open_items_report(self) -> Dict[str, List[str]]:
        if self.plan is None:
            return {}
        report = {}
        for topic in self.guide.topics:
            gaps = phases.open_items(topic, self.phase_state)
            if gaps:
                report[topic.id] = [topic.must_learn[i] for i in gaps]
        return report

    def history(self) -> List[Dict[str, Any]]:
        """Питання й відповіді, які вже прозвучали.

        Потрібна не для краси: людина згадує щось про раніше поставлене питання
        вже посеред іншої теми, і без можливості повернутись ця деталь
        втрачається назавжди. У модерованому інтервʼю дослідник просто повернувся
        б до теми — тут це мусить бути кнопкою.
        """
        # Те саме «про що варто сказати», що й на активному питанні, — тут
        # воно статичне (лежить у самому пункті сценарію), тому дістати його
        # для БУДЬ-ЯКОГО вже поставленого питання можна без current_question.
        expects_by_id = {q["id"]: q.get("expects") or [] for q in self.script}
        groups = {}
        order = []
        current = None
        for index, turn in enumerate(self.turns):
            if turn["role"] == "interviewer":
                current = index
                groups[index] = {
                    "index": index,
                    "question": turn.get("text", ""),
                    "topic_id": turn.get("topic_id", ""),
                    "source": turn.get("source", ""),
                    # Людина дописує деталь — і мусить бачити, чого від неї
                    # чекали на цьому питанні, а не лише сам його текст.
                    "expects": expects_by_id.get(turn.get("question_id", ""), []),
                    "answers": [],
                }
                order.append(index)
                continue
            # Доповнення фізично лежить у кінці транскрипту (він тільки на
            # дописування), але належить тому питанню, до якого його додали.
            # Групувати послідовно тут не можна: доповнення показувалось би під
            # останнім питанням — спостережено.
            added_to = turn.get("added_to")
            target = added_to if isinstance(added_to, int) and added_to in groups else current
            if target is None:
                continue
            groups[target]["answers"].append({
                "text": turn.get("text", ""),
                "added": added_to is not None,
                "ts": turn.get("ts", ""),
                # Записи цієї відповіді: людина мусить мати змогу переслухати
                # їх і тут, а не лише поки питання ще поточне.
                "voice": turn.get("voice", []),
            })
        return [groups[index] for index in order]

    def append_to_answer(
        self, index: int, text: str, voice: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Дописує сказане до питання, на яке вже відповідали.

        Транскрипт лишається **тільки на дописування**: попередня репліка не
        переписується, нова стає окремим ходом із позначкою `added_to`. Дослідник
        мусить бачити, що це згадали пізніше, а не сказали одразу — це різні
        дані про людську память.

        Сценарій не рухається: людина повернулась додати деталь, а не почати
        тему заново.

        `voice` приходить явно від клієнта (імена кліпів із `/api/voice`), а
        не з `self.pending_voice`: людина могла відкрити «Раніше сказане»
        просто зупинивши запис на поточному питанні — і той запис ще чекає
        свого `answer()`. Якби доповнення забирало спільний pending_voice,
        воно вкрало б чужий запис.
        """
        if not (0 <= index < len(self.turns)) or self.turns[index]["role"] != "interviewer":
            raise ValueError("Немає такого питання")
        clean, masked = self.deidentifier.scrub(text)
        if not clean.strip():
            raise ValueError("Порожнє доповнення")

        asked = self.turns[index]
        entry = {
            "role": "respondent", "text": clean, "ts": _now(),
            "topic_id": asked.get("topic_id", ""),
            "phase": asked.get("phase") or self.phase_state.phase,
            # Той самий question_id, що й у питання: без цього доповнення не
            # бачили ні `answers_for_current`, ні `answered_current`, ні підрахунок
            # глибини відповіді — воно існувало лише у транскрипті й в історії.
            "question_id": asked.get("question_id", ""),
            # Позначка «це доповнення до питання №», а не нова відповідь.
            "added_to": index,
        }
        if voice:
            entry["voice"] = [str(name) for name in voice]
        if masked:
            entry["masked"] = masked
            self.incidents.append({"kind": "deidentified", "rules": masked, "ts": _now()})
        self.turns.append(entry)
        self.incidents.append({
            "kind": "answer_extended", "turn": index,
            "topic_id": entry["topic_id"], "ts": _now(),
        })

        # Пункти тієї теми могли щойно закритись — переоцінюємо саме її.
        topic = next((t for t in self.guide.topics if t.id == entry["topic_id"]), None)
        if topic is not None and topic.must_learn:
            self._resolve_items_for(topic)
        return {"turn": entry, "topic_id": entry["topic_id"]}

    def answer_depth_stats(self) -> Dict[str, Any]:
        """Скільки питань має відповідь і наскільки вони розгорнуті.

        Не гейт і не умова — просто інформація для екрана підсумку: людина
        бачить, наскільки докладними вийшли її відповіді, а не вгадує.
        """
        respondent_turns = [t for t in self.turns if t.get("role") == "respondent"]
        if self.script:
            words_by_question = {}
            for turn in respondent_turns:
                qid = turn.get("question_id")
                if not qid:
                    continue
                words_by_question[qid] = (
                    words_by_question.get(qid, 0) + self._word_count(turn.get("text", "")))
            answered = len(words_by_question)
            total = len(self.script)
            avg = (sum(words_by_question.values()) / float(answered)) if answered else 0.0
            return {"answered": answered, "total": total, "avg_words": round(avg, 1)}
        # Вільний режим: питання не мають стабільних ідентифікаторів — рахуємо
        # по ходах, а не по темах.
        if not respondent_turns:
            return {"answered": 0, "total": 0, "avg_words": 0.0}
        total_words = sum(self._word_count(t.get("text", "")) for t in respondent_turns)
        avg = total_words / float(len(respondent_turns))
        return {"answered": len(respondent_turns), "total": len(respondent_turns),
                "avg_words": round(avg, 1)}

    def _section_progress(self) -> List[Dict[str, Any]]:
        """Розділи з кількістю питань і відповідей у кожному.

        Це і є сходинковий прогрес: кожен розділ показує, скільки в ньому
        питань і скільки з них уже мають відповідь — а не позицію курсора,
        яка раніше плуталась із «зроблено».
        """
        if not self.script:
            return []
        current_phase = self.current_question().get("section", phases.WARMUP)
        answered_ids = {t.get("question_id") for t in self.turns
                        if t.get("role") == "respondent" and t.get("question_id")}
        out = []
        for sec in self.plan.sections():
            items_in = [q for q in self.script if q["section"] == sec["phase"]]
            answered = len([q for q in items_in if q["id"] in answered_ids])
            out.append({
                "title": sec["title"], "phase": sec["phase"],
                "total": len(items_in), "answered": answered,
                "current": sec["phase"] == current_phase,
            })
        return out

    def checklist(self) -> List[Dict[str, Any]]:
        """Шпаргалка: що ми сподіваємось почути на цьому питанні.

        Без позначок «зараховано». Позначки ставила модель, і робила це з
        точністю 64-71 % (`app/interview/judge.py`): вона зараховувала сказане
        поруч і не зараховувала сказане прямо. Галочка, якій не можна вірити,
        гірша за її відсутність — вона обіцяє облік, якого немає.

        Тепер це просто перелік того, про що варто сказати. Вирішує людина.
        """
        if self.script:
            question = self.current_question()
            return [{"text": item, "done": False}
                    for item in (question.get("expects") or [])]
        return self._legacy_checklist()

    def _legacy_checklist(self) -> List[Dict[str, Any]]:
        """Старий чекліст із позначками — для просторів без плоского сценарію.

        Лишається робочим, бо простір без `ask_if_missed`/`ask_for_detail`
        сценарію не має й веде розмову старим шляхом. У «подорожах» цей код не
        працює: там сценарій є.
        """
        if self.plan is None:
            return []
        phase = self.phase_state.phase

        if phase == phases.NARRATIVE:
            covered = set(self.phase_state.covered_in_narrative) | set(self.draft_done)
            # `label`, а не `title`: людині показуємо людські слова, а фаховий
            # ярлик карти тем лишається для звітів і транскрипту.
            return [{"text": topic.label, "done": topic.id in covered}
                    for topic in self.guide.topics]

        items, done = self._expectation()
        marked = set(done) | set(self.draft_done)
        return [{"text": item, "done": index in marked}
                for index, item in enumerate(items)]

    def progress_info(self) -> Dict[str, Any]:
        if self.script:
            question = self.current_question()
            section_list = self._section_progress()
            current_index = next(
                (i for i, s in enumerate(section_list) if s["current"]), 0)
            detail = "питання %d з %d" % (self.cursor + 1, len(self.script))
            if question.get("topic_title"):
                detail += " · %s" % question["topic_title"]
            return {
                "phase": question.get("section", phases.WARMUP),
                # Розділи — кроки, не суцільна смуга: кожен несе власні
                # total/answered, а не позицію курсора (T-91/T-92).
                "sections": section_list,
                "section_index": current_index,
                "section": section_list[current_index]["title"] if section_list else "",
                "detail": detail,
                "label": section_list[current_index]["title"] if section_list else "",
                "fraction": round((self.cursor + 1) / float(max(1, len(self.script))), 3),
                "asked": self.cursor + 1,
                "topic_index": self.phase_state.topic_index,
                "topics_total": len(self.guide.topics),
                # Навігація: клієнт малює кнопки за цими прапорцями.
                "at_start": self.at_start(),
                "at_end": self.at_end(),
                "answered": self.answered_current(),
                # Судження зникло з навігації — тут воно лишається як
                # інформація на прощання, не як умова.
                "depth": self.answer_depth_stats(),
                "scripted": True,
            }
        return self._legacy_progress()

    def _legacy_progress(self) -> Dict[str, Any]:
        """Прогрес для клієнта: підпис фази й частка, а не номер теми.

        Для просторів без сценарію (`example`): нема плоского переліку питань,
        тому нема й дискретних кроків — розділ рахує тему, а не питання.
        """
        asked = len([t for t in self.turns if t["role"] == "interviewer"])
        if self.plan is None:
            total = len(self.guide.topics) or 1
            covered = len(self.covered_topics)
            info = {
                "phase": "topics",
                "section": "Уточнення",
                "section_index": 0,
                "sections": [{"title": "Уточнення", "phase": "topics",
                             "total": total, "answered": covered, "current": True}],
                "detail": "тема %d з %d" % (min(covered + 1, total), total),
                "section_fraction": round(covered / float(total), 3),
                "label": "Уточнення",
                "fraction": round(covered / float(total), 3),
                "asked": asked,
                "topic_index": self.topic_index,
                "topics_total": total,
            }
        else:
            info = self.plan.progress(self.phase_state, asked)
            # Ті самі назви, але вже словниками: клієнт малює кроки одним кодом
            # для обох режимів, без розгалуження на «старий»/«новий» формат.
            info["sections"] = [
                {"title": title, "phase": "", "total": 0, "answered": 0,
                 "current": title == info.get("section")}
                for title in (info.get("sections") or [])
            ]
        # Немає плоского сценарію — немає й навігації кнопками: людину веде
        # модель, а не курсор. Клієнт за цим прапорцем ховає «наступне»/«назад».
        info["scripted"] = False
        info["depth"] = self.answer_depth_stats()
        return info

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "space": self.space.key,
            "guide": self.guide.key,
            "prompt_version": self.prompt_version,
            "llm_provider": self.llm.name,
            "repertoire": "bank" if self.bank is not None else "free",
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "completed": self.done,
            "turns": self.turns,
            "coverage": self.coverage,
            # Що так і не зʼясували: прямий матеріал для «Нотаток для себе».
            "open_items": self._open_items_report(),
            # Згода на запис голосу лишається в транскрипті: без неї записи
            # поруч не мають права існувати, і це має бути видно з файлу.
            "voice_consent": self.voice_consent,
            # Стан, без якого сесію не відновити після перезапуску (TD-5).
            "state": {"topic_index": self.topic_index, "probes": self.probes,
                      "phase": self.phase_state.to_dict(),
                      "pending_voice": list(self.pending_voice),
                      # Без цього /api/resume «забував», на якому питанні
                      # стояла людина: сесія відновлювалась курсором 0, і
                      # чекліст, навігація та «сказане раніше» показували
                      # перше питання замість поточного. Спостережено при
                      # написанні прогресу по кроках.
                      "cursor": self.cursor},
            "topics_covered": self.covered_topics + ([self.topic.id] if self.done else []),
            "incidents": self.incidents,
        }
