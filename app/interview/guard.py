"""Guard — код, який перевіряє репліку інтервʼюера ПЕРЕД тим, як її почує людина.

Навіщо, якщо є промпт. Промпт — це прохання; guard — це гарантія. Модель
схильна погоджуватися і підхоплювати формулювання, і робить це тим охочіше,
чим довша розмова. Без цієї перевірки заявлена мета «менше впливу на
респондента» лишається декларацією.

Правила тут — методологічні, не доменні: жодного нашого домену, лексика домену
приходить із конфігу простору.
"""

import re
from typing import Dict, List, Optional, Set

# Оцінки й погоджування. Саме вони вчать респондента, яка відповідь «правильна».
_EVALUATIVE = [
    "ви праві", "ви маєте рацію", "маєте рацію", "саме так", "погоджуюсь",
    "погоджуюся", "згоден", "згодна", "чудово", "прекрасно", "дуже цікаво",
    "це важливо", "розумію вас", "я вас розумію", "справді незручно",
    "вы правы", "согласен", "согласна", "именно так", "отлично",
    "очень интересно", "понимаю вас",
]

# Навідні та докірливі конструкції.
_LEADING = [
    (r"\bа якби\b", "гіпотетичне питання"),
    (r"\bякби у вас\b", "гіпотетичне питання"),
    (r"\bуявіть\b", "гіпотетичне питання"),
    (r"\bпредставьте\b", "гіпотетичне питання"),
    (r"чому ви не ", "докір замість питання"),
    (r"почему вы не ", "докір замість питання"),
    (r"вам не вистача", "навідне питання"),
    (r"вам не хватает", "навідне питання"),
    (r"чи не здається", "навідне питання"),
    (r"тобто вам (важлив|потрібн|не вистача)", "вкладання слів у вуста"),
    (r"більшість (користувачів|людей|респондентів)", "згадка про інших людей"),
    # Прислівник між словами ламає перевірку підстрокою («ви АБСОЛЮТНО праві»),
    # тому погоджування ловимо ще й шаблоном.
    (r"\bви\s+(\w+\s+){0,2}прав[іи]\b", "погоджування з респондентом"),
    (r"\bмаєте\s+(\w+\s+){0,2}рацію\b", "погоджування з респондентом"),
    (r"\bвы\s+(\w+\s+){0,2}прав[ыи]\b", "погоджування з респондентом"),
    (r"большинство (пользователей|людей)", "згадка про інших людей"),
]

MAX_CHARS = 320


def check(
    utterance: str,
    domain_vocabulary: Optional[List[str]] = None,
    respondent_words: Optional[Set[str]] = None,
    require_spoken_form: bool = False,
    require_question: bool = False,
) -> List[str]:
    """Повертає список порушень. Порожній список = репліку можна говорити."""
    problems = []
    low = utterance.lower().strip()

    if not low:
        problems.append("порожня репліка")
        return problems

    # Вільне уточнення мусить бути питанням. Слабка модель охоче віддає
    # «Добре.» або «Зрозуміло.» — це не уточнення, а filler, і за методологією
    # це ще й оцінка. Дослівні репліки гайда цю перевірку не проходять і не
    # мусять: там є і «Ага», і «Слухаю», і вони там доречні.
    if require_question and "?" not in utterance:
        problems.append("це не питання — вільне уточнення мусить бути питанням")

    if utterance.count("?") > 1:
        problems.append("більше одного питання в репліці")

    if len(utterance) > MAX_CHARS:
        problems.append("репліка задовга (%d символів, ліміт %d) — інтервʼюер говорить замість респондента"
                        % (len(utterance), MAX_CHARS))

    for phrase in _EVALUATIVE:
        if phrase in low:
            problems.append("оцінка або погоджування: «%s»" % phrase)

    for pattern, label in _LEADING:
        if re.search(pattern, low):
            problems.append("%s: спрацював шаблон /%s/" % (label, pattern))

    # Канал озвучення: символьна модель губить цифри й латиницю без помилки.
    # Промпт про це просить — guard це гарантує, бо тиха діра в питанні
    # виявиться вже після інтервʼю.
    if require_spoken_form:
        digits = re.findall(r"\d+", utterance)
        if digits:
            problems.append(
                "цифри в репліці (%s) — синтез їх не вимовить, потрібні слова"
                % ", ".join(digits[:3])
            )
        latin = re.findall(r"[A-Za-z]{2,}", utterance)
        if latin:
            problems.append(
                "латиниця в репліці (%s) — синтез її не вимовить"
                % ", ".join(latin[:3])
            )

    # Правило 4 промпту: сутність першим називає респондент, не інтервʼюер.
    # Це єдина перевірка, що залежить від конфігу простору, — і вона там і живе.
    for term in (domain_vocabulary or []):
        t = term.lower()
        if t in low and (not respondent_words or t not in respondent_words):
            problems.append(
                "термін домену «%s» названий інтервʼюером першим — далі буде чути власне відлуння" % term
            )

    return problems


def _normalize_for_compare(text: str) -> Set[str]:
    words = re.findall(r"[а-яіїєґa-z]+", (text or "").lower())
    return set(words)


def repetition_problem(utterance: str, turns: List[Dict[str, str]],
                       threshold: float = 0.8) -> Optional[str]:
    """Чи це вже питали.

    Респондент уже відповів на це питання; повторити його — сказати людині, що
    її не слухали. Слабкі моделі роблять це особливо охоче: зачіпаються за опис
    теми й повертають ту саму фразу щоходу.

    Порівнюємо не рядки, а набори слів: «Що стало поштовхом купити велосипед?» і
    «Що стало поштовхом, щоб ви купили велосипед?» — те саме питання.
    """
    words = _normalize_for_compare(utterance)
    if len(words) < 3:
        return None
    for turn in turns:
        if turn.get("role") != "interviewer":
            continue
        previous = _normalize_for_compare(turn.get("text", ""))
        if not previous:
            continue
        overlap = len(words & previous) / float(len(words | previous))
        if overlap >= threshold:
            return "це питання вже ставилось («%s»)" % turn["text"][:60]
    return None


def respondent_vocabulary(turns: List[Dict[str, str]]) -> Set[str]:
    """Що вже вимовив сам респондент — у нижньому регістрі, для перевірки вище."""
    said = set()
    for turn in turns:
        if turn.get("role") == "respondent":
            said.add(turn.get("text", "").lower())
    return said


def term_used_by_respondent(term: str, turns: List[Dict[str, str]]) -> bool:
    t = term.lower()
    return any(t in turn.get("text", "").lower() for turn in turns if turn.get("role") == "respondent")


def check_turn(
    utterance: str,
    domain_vocabulary: List[str],
    turns: List[Dict[str, str]],
    require_spoken_form: bool = False,
    require_question: bool = False,
) -> List[str]:
    """Зручна обгортка: сама зʼясовує, які терміни респондент уже вживав,
    і чи це питання вже звучало."""
    already = {t.lower() for t in (domain_vocabulary or []) if term_used_by_respondent(t, turns)}
    problems = check(utterance, domain_vocabulary, already, require_spoken_form,
                     require_question)
    repeated = repetition_problem(utterance, turns)
    if repeated:
        problems.append(repeated)
    return problems
