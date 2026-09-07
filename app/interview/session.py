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

from ..config.space import Guide, SpaceConfig
from ..providers.base import LLMProvider, ProviderError
from . import phases
from . import judge as judging
from .deidentify import Deidentifier
from .prompt_builder import (
    BANK_TURN_SCHEMA,
    DEFAULT_PROMPT_VERSION,
    build_state_block,
    build_system,
)

MAX_GUARD_RETRIES = 2


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

        # Потрібен лише банку (вибір репліки — структурований виклик моделі);
        # для сценарію текст іде дослівно з гайда, модель тут не бере участі.
        self.system = build_system(space, guide, self.prompt_version, bank=bank)
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
            t.ask_if_missed for t in guide.topics
        ) else None
        self.phase_state = phases.PhaseState()
        # ── сценарій vs банк, і різниця між ними принципова ─────────────
        #
        # СЦЕНАРІЙ (гайд дає питання по темах): порядок і текст задає
        # дослідник, темп — людина кнопками «наступне»/«попереднє». Модель
        # не формулює жодного питання: чекліст тут шпаргалка, а не облік.
        #
        # БАНК (`repertoire: bank`, окремий простір без сценарію): модель
        # лише ВИБИРАЄ репліку з набору, записаного людським голосом, — вона
        # теж нічого не формулює сама.
        #
        # Вільного формулювання питань моделлю в цьому інструменті більше
        # немає: усе, що респондент чує, — або дослівний текст гайда, або
        # заздалегідь записана дослідником репліка.
        scripted = self.plan is not None and any(
            topic.ask_if_missed for topic in guide.topics)
        self.script = self.plan.script() if scripted else []
        self.cursor = 0

        # Згода на запис голосу — окреме рішення респондента, не частина згоди
        # на інтервʼю. Голос неможливо деідентифікувати, тому питається прямо.
        self.voice_consent = False
        # ПІБ, як і згода на запис, приходить з екрана згоди до старту гайду —
        # це метадані для дослідника, а не хід сценарію.
        self.respondent_name = ""  # type: str
        # Записи, зроблені на поточну відповідь і ще не прикріплені до ходу.
        self.pending_voice = []      # type: List[str]

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

        # Ні сценарію, ні банку: лишається дослівне відкриття гайда — воно,
        # на відміну від питань по темах, ніколи не потребувало моделі.
        text = "%s\n\n%s" % (self.space.persona.self_intro, self.guide.opening)
        self.turns.append({"role": "interviewer", "text": text, "ts": _now(),
                           "topic_id": self.topic.id})
        return text

    def answer(self, respondent_text: str) -> InterviewerTurn:
        """Респондент відповів — повертаємо наступну репліку інтервʼюера."""
        if self.done:
            raise RuntimeError("Інтервʼю вже завершено")

        clean, masked = self.deidentifier.scrub(respondent_text)
        entry = {"role": "respondent", "text": clean, "ts": _now(),
                 "topic_id": self.current_topic.id,
                 # Фаза, у якій це сказано — досліднику, щоб бачити, де в
                 # розмові що прозвучало.
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

        if self.bank is not None:
            turn = self._ask_bank()
        else:
            # Гайд без сценарію (немає ask_if_missed на жодній темі) і без
            # банку — конфігурація, яку валідатор простору більше не
            # пропускає (app/config/space.py). Якщо це все ж сталось —
            # краще явна помилка тут, ніж мовчазний обрив розмови.
            raise RuntimeError(
                "Простір без сценарію і без банку реплік — немає, як продовжити розмову")
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

    @staticmethod
    def _word_count(text: str) -> int:
        return len(re.findall(r"\w+", text or ""))

    def all_expected_covered(self) -> bool:
        """Чи почули ми все, чого чекали на цьому питанні.

        Порожній чекліст — не «все зараховано»: там просто немає очікувань,
        і кнопку «надіслати» гейтити нічим (див. `web/app.js`).
        """
        items = self.checklist()
        return bool(items) and all(item.get("done") for item in items)

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
        session.respondent_name = data.get("respondent_name") or ""

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
        """Шпаргалка для просторів без плоского сценарію.

        Лишається робочим, бо простір без `ask_if_missed` сценарію не має й
        веде розмову старим шляхом. У «подорожах» цей код не працює: там
        сценарій є. Той самий принцип, що й у `checklist()`: перелік без
        позначок «зараховано» — вирішує людина.
        """
        if self.plan is None:
            return []
        phase = self.phase_state.phase

        if phase == phases.NARRATIVE:
            # `label`, а не `title`: людині показуємо людські слова, а фаховий
            # ярлик карти тем лишається для звітів і транскрипту.
            return [{"text": topic.label, "done": False} for topic in self.guide.topics]
        if phase == phases.WARMUP:
            return [{"text": item, "done": False} for item in (self.guide.opening_expects or [])]
        if phase == phases.TOPICS:
            topic = self.plan.topic_at(self.phase_state.topic_index)
            items = (topic.must_learn or []) if topic is not None else []
            return [{"text": item, "done": False} for item in items]
        if phase == phases.CLOSING:
            index = max(0, self.phase_state.closing_index - 1)
            items = (self.guide.closing_expects[index]
                     if index < len(self.guide.closing_expects) else [])
            return [{"text": item, "done": False} for item in items]
        return []

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
                "section": "Теми",
                "section_index": 0,
                "sections": [{"title": "Теми", "phase": "topics",
                             "total": total, "answered": covered, "current": True}],
                "detail": "тема %d з %d" % (min(covered + 1, total), total),
                "section_fraction": round(covered / float(total), 3),
                "label": "Теми",
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
            # Згода на запис голосу лишається в транскрипті: без неї записи
            # поруч не мають права існувати, і це має бути видно з файлу.
            "voice_consent": self.voice_consent,
            "respondent_name": self.respondent_name,
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
