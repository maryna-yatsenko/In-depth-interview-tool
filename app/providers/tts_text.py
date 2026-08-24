"""Підготовка тексту для символьної TTS-моделі.

Модель `uk_UA-ukrainian_tts-medium` — символьна, і її алфавіт містить **лише**
малі українські літери, пунктуацію та комбіновані знаки. Ні цифр, ні латиниці,
ні великих літер.

Наслідок, виміряний 21.08.2026: «Це було у 2019 році» звучить 1,38 с, а те саме
словами — 3,37 с. Число просто зникає. Респондент чує «Це було у році» і не має
жодного способу зрозуміти, що питання було інше. Те саме з латиницею й великими
літерами.

Тому текст нормалізується перед синтезом, а все, що не вкладається в алфавіт,
**повідомляється**, а не викидається молча.
"""

import re
from typing import Dict, List, Tuple

# Апостроф у моделі — звичайний ASCII, а не типографський «ʼ». Це не дрібниця:
# «п'ять» з правильним ASCII читається, з типографським — ні.
APO = "'"

_ONES = ["", "один", "два", "три", "чотири", "п" + APO + "ять", "шість", "сім",
         "вісім", "дев" + APO + "ять"]
_ONES_F = ["", "одна", "дві", "три", "чотири", "п" + APO + "ять", "шість", "сім",
           "вісім", "дев" + APO + "ять"]
_TEENS = ["десять", "одинадцять", "дванадцять", "тринадцять", "чотирнадцять",
          "п" + APO + "ятнадцять", "шістнадцять", "сімнадцять", "вісімнадцять",
          "дев" + APO + "ятнадцять"]
_TENS = ["", "", "двадцять", "тридцять", "сорок", "п" + APO + "ятдесят", "шістдесят",
         "сімдесят", "вісімдесят", "дев" + APO + "яносто"]
_HUNDREDS = ["", "сто", "двісті", "триста", "чотириста", "п" + APO + "ятсот",
             "шістсот", "сімсот", "вісімсот", "дев" + APO + "ятсот"]

# Латиниця → кирилиця. Мета не «правильна транслітерація», а щоб назва
# прозвучала хоч якось, замість зникнути.
_LATIN = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "г",
    "i": "і", "j": "й", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п",
    "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс",
    "y": "и", "z": "з",
}

# Символи, які модель приймає, окрім літер (з конфігу моделі).
_ALLOWED_PUNCT = set(" !',-.:;?—")

# Комбінований знак наголосу — він є в алфавіті моделі, тобто модель НАВЧЕНА
# його читати. Без наголосів вона їх угадує, і частина слів звучить неправильно.
STRESS_MARK = chr(0x301)

_stressifier = None
_stress_state = "unknown"   # unknown | ready | absent


def _get_stressifier():
    """Розставляч наголосів, якщо він встановлений.

    Свідомо необовʼязковий: без нього інструмент працює, просто гірше вимовляє.
    Падати через відсутність поліпшення — гірше за працювати без поліпшення.
    """
    global _stressifier, _stress_state
    if _stress_state != "unknown":
        return _stressifier
    try:
        from ukrainian_word_stress import Disambiguation, Stressifier, StressSymbol

        # Словниковий режим: без stanza й PyTorch. Неоднозначні слова
        # (омографи «за́мок» / «замо́к») лишаються без наголосу — модель угадає
        # сама. Це чесніше за навмання поставлений наголос.
        _stressifier = Stressifier(
            stress_symbol=StressSymbol.CombiningAcuteAccent,
            disambiguation=Disambiguation.Dictionary,
        )
        _stress_state = "ready"
    except Exception:
        _stressifier = None
        _stress_state = "absent"
    return _stressifier


def stress_available() -> bool:
    return _get_stressifier() is not None


def _group(value: int, feminine: bool = False) -> List[str]:
    """Три розряди словами."""
    words = []
    hundreds, rest = divmod(value, 100)
    if hundreds:
        words.append(_HUNDREDS[hundreds])
    if 10 <= rest <= 19:
        words.append(_TEENS[rest - 10])
    else:
        tens, ones = divmod(rest, 10)
        if tens:
            words.append(_TENS[tens])
        if ones:
            words.append((_ONES_F if feminine else _ONES)[ones])
    return words


def _plural(value: int, one: str, few: str, many: str) -> str:
    mod10, mod100 = value % 10, value % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not (12 <= mod100 <= 14):
        return few
    return many


def number_to_words(value: int) -> str:
    """Кардинальне число словами, у називному відмінку.

    Відмінок свідомо не узгоджується з контекстом: зробити це правильно можна
    лише знаючи речення, і це робота моделі, яка формулює питання (див. промпт
    інтервʼюера — там є пряме правило писати числа словами). Тут — запобіжник,
    щоб число прозвучало хоч так, а не зникло.
    """
    if value < 0:
        return "мінус " + number_to_words(-value)
    if value == 0:
        return "нуль"

    words = []
    millions, rest = divmod(value, 1000000)
    if millions:
        words += _group(millions)
        words.append(_plural(millions, "мільйон", "мільйони", "мільйонів"))

    thousands, rest = divmod(rest, 1000)
    if thousands:
        words += _group(thousands, feminine=True)
        words.append(_plural(thousands, "тисяча", "тисячі", "тисяч"))

    if rest:
        words += _group(rest)
    return " ".join(w for w in words if w)


# «15 000», «1 250 000» — пробіл (звичайний або нерозривний) як розділювач
# тисяч. Без цього «15 000» розпадається на «п'ятнадцять» і «нуль».
# Провідна цифра не нуль: справжні числа не пишуть як «067», а телефони — так.
# Один символ у шаблоні відсікає хибне склеювання «067 123» у «шістдесят сім тисяч».
_THOUSAND_SEP = re.compile(r"(?<!\d)([1-9]\d{0,2})((?:[ \u00A0\u202F]\d{3})+)(?!\d)")


def _join_thousand_groups(text: str) -> str:
    def repl(match):
        return match.group(1) + re.sub(r"[ \u00A0\u202F]", "", match.group(2))
    return _THOUSAND_SEP.sub(repl, text)


def _expand_numbers(text: str) -> str:
    text = _join_thousand_groups(text)

    def repl(match):
        raw = match.group(0)
        try:
            return " " + number_to_words(int(raw)) + " "
        except ValueError:
            return raw
    # Спершу довгі числа, потім решта — інакше «2019» розпадеться на частини.
    return re.sub(r"\d+", repl, text)


def _transliterate(text: str) -> str:
    out = []
    for ch in text:
        low = ch.lower()
        out.append(_LATIN.get(low, ch) if low in _LATIN else ch)
    return "".join(out)


def normalize(text: str, add_stress: bool = False) -> Tuple[str, Dict[str, List[str]]]:
    """Повертає (готовий текст, звіт про зміни).

    Звіт — не для краси: якщо в питання потрапило щось, чого модель не знає,
    дослідник має це побачити в транскрипті, а не гадати, чому респондент
    відповів не на те.

    Порядок кроків не випадковий: числа розкриваються ДО наголосів (щоб
    «дві тисячі» теж отримали наголос), наголоси ставляться ДО зниження
    регістру (словник шукає нормальні словоформи), а відкидання невідомих
    символів — останнім, і знак наголосу в дозволених.
    """
    report = {"numbers": [], "latin": [], "dropped": [], "stressed": False}
    if not text:
        return "", report

    report["numbers"] = re.findall(r"\d+", text)
    report["latin"] = re.findall(r"[A-Za-z]+", text)

    result = _expand_numbers(text)
    result = _transliterate(result)

    if add_stress:
        stressifier = _get_stressifier()
        if stressifier is not None:
            try:
                result = stressifier(result)
                report["stressed"] = True
            except Exception:
                # Розставляч спіткнувся на конкретній фразі — не привід
                # ламати інтервʼю, просто читаємо без наголосів.
                report["stressed"] = False

    result = result.lower()
    # Типографські апострофи й лапки — на ті, які модель знає.
    result = (result.replace("ʼ", APO).replace("’", APO)
                    .replace("“", "").replace("”", "")
                    .replace("«", "").replace("»", "")
                    .replace("–", "—").replace("…", "."))

    kept = []
    for ch in result:
        if ch in _ALLOWED_PUNCT or ("а" <= ch <= "я") or ch in "ґєіїь́̆̈":
            kept.append(ch)
        elif ch.isspace():
            kept.append(" ")
        else:
            report["dropped"].append(ch)
    result = re.sub(r"\s+", " ", "".join(kept)).strip()
    return result, report
