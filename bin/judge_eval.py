#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Мірка для оцінювача: наскільки правильно він зараховує пункти чекліста.

Без цієї мірки «стало краще» — це відчуття. Тут це число.

    .venv/bin/python bin/judge_eval.py                # поточний промпт
    .venv/bin/python bin/judge_eval.py --prompt quote # промпт із цитатою
    .venv/bin/python bin/judge_eval.py --model mlx-community/gemma-3-12b-it-4bit

Що показує:
  точність     — скільки випадків із еталону вгадано;
  хибне «так»  — зарахував те, чого не було (це те, що ламає довіру: людина
                 бачить галочку там, де нічого не казала);
  хибне «ні»   — не зарахував сказане (людина повторює те саме, і кнопка
                 «надіслати» лишається закритою).

Еталон розмічений людиною: tests/data/judge_cases.json.
"""

import argparse
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES = os.path.join(ROOT, "tests", "data", "judge_cases.json")


# ── промпти, які порівнюємо ──────────────────────────────────────────────

def prompt_plain(answer, item):
    """Те, що працює зараз."""
    return (
        "Ось усе, що розповів респондент:\n\n%s\n\n"
        "Чи є у цій розповіді ось це: «%s»?\n"
        "Відповідай ОДНИМ словом: так або ні." % (answer, item)
    )


def prompt_strict(answer, item):
    """Те саме, але з прямою вказівкою не домислювати."""
    return (
        "ВІДПОВІДЬ РЕСПОНДЕНТА:\n%s\n\n"
        "ПИТАННЯ: чи сказав респондент саме це — «%s»?\n\n"
        "Правила:\n"
        "— «так» лише якщо це прямо сказано у відповіді;\n"
        "— близька за темою відповідь — це «ні»;\n"
        "— якщо сумніваєшся — «ні».\n\n"
        "Відповідай ОДНИМ словом: так або ні." % (answer, item)
    )


def prompt_quote(answer, item):
    """Просимо цитату. Цитату можна перевірити рядковим порівнянням —
    саме це й перетворює судження моделі на факт, який можна звірити."""
    return (
        "ВІДПОВІДЬ РЕСПОНДЕНТА:\n%s\n\n"
        "ПИТАННЯ: чи сказав респондент саме це — «%s»?\n\n"
        "Якщо так — виведи ДОСЛІВНО фрагмент відповіді, який це підтверджує, "
        "і більше нічого.\n"
        "Якщо ні — виведи одне слово: ні.\n"
        "Близька за темою відповідь, якої тут насправді немає, — це «ні»."
        % (answer, item)
    )


def prompt_learn(answer, item):
    """Те, що працює в застосунку. НЕ копія: імпорт із app/interview/judge.py.

    Копія тут була б найгіршим варіантом — вона тихо розійшлась би з робочим
    кодом, і число з цієї мірки перестало б щось означати.
    """
    from app.interview.judge import item_question
    return item_question(answer, item)


def prompt_extract(answer, item):
    """Не судження, а витяг: слабкій моделі легше переказати сказане, ніж
    вирішити абстрактне «чи є». Порожній витяг і є «ні»."""
    return (
        "ВІДПОВІДЬ РЕСПОНДЕНТА:\n%s\n\n"
        "Що саме сказано у цій відповіді про «%s»?\n"
        "Перекажи це коротко своїми словами.\n"
        "Якщо про це не сказано нічого — напиши рівно: НЕ СКАЗАНО."
        % (answer, item)
    )


def prompt_learn2(answer, item):
    """`learn` плюс два уточнення проти помилок, які лишились після нього:
    заперечна відповідь — це теж відповідь («в план не залазили» закриває
    пункт «чи відкривали план»), і конкретний випадок закриває пункт про
    конкретний випадок."""
    return (
        "ВІДПОВІДЬ РЕСПОНДЕНТА:\n%s\n\n"
        "Чи можна з цієї відповіді дізнатися: %s?\n\n"
        "Врахуй:\n"
        "— заперечення теж є відповіддю («не робили», «нічого не було»);\n"
        "— розказаний конкретний випадок закриває питання про випадок;\n"
        "— якщо про це у відповіді нічого немає — «ні».\n\n"
        "Відповідай ОДНИМ словом: так або ні." % (answer, item)
    )


def prompt_criterion(answer, item, counts_if=None):
    """Пункт як питання + критерій зарахування.

    Гіпотеза: хибні «так» беруться не з моделі, а з форми пункта. Ярлик
    «домовленість про витрати» ловить усе, що поруч («грошей вистачило»);
    критерій «сказано, за що хто платить» ловити цього не може.
    """
    if not counts_if:
        return prompt_learn(answer, item)
    from app.interview.judge import item_question
    return item_question(answer, item, counts_if)


PROMPTS = {"plain": prompt_plain, "strict": prompt_strict, "quote": prompt_quote,
           "learn": prompt_learn, "extract": prompt_extract, "learn2": prompt_learn2,
           "criterion": prompt_criterion}


def parse_extract(reply):
    """«Не сказано» в будь-якому написанні означає, що пункт відкритий."""
    low = normalize(reply)
    if not low:
        return False, "порожньо"
    for marker in ("не сказано", "не сказан", "нічого не сказано", "не згадано",
                   "не вказано", "не зазначено", "немає інформації"):
        if marker in low:
            return False, "не сказано"
    return True, reply.strip().replace("\n", " ")[:44]


# ── читання відповіді моделі ─────────────────────────────────────────────

def parse_yes_no(reply):
    low = (reply or "").strip().lower().lstrip("*_-• ")
    return low.startswith("так")


def normalize(text):
    """Для звіряння цитати: без регістру, без пунктуації, один пробіл."""
    keep = []
    for ch in (text or "").lower():
        keep.append(ch if (ch.isalnum() or ch.isspace()) else " ")
    return " ".join("".join(keep).split())


def parse_quote(reply, answer, min_words=3):
    """«Так» лише якщо цитата справді є у відповіді.

    Це головний важіль проти хибних «так»: модель мусить показати, ДЕ вона це
    побачила, а ми перевіряємо рядком. Вигадану цитату видно одразу.
    """
    text = (reply or "").strip().strip('«»"\'')
    if not text:
        return False, "порожньо"
    if normalize(text).startswith("ні"):
        return False, "сказала «ні»"
    words = normalize(text).split()
    if len(words) < min_words:
        return False, "цитата коротка: %r" % text
    hay = normalize(answer)
    # Довгі цитати модель любить обрізати або склеювати — звіряємо найдовше
    # вікно, яке справді є у відповіді.
    for size in range(len(words), min_words - 1, -1):
        for start in range(0, len(words) - size + 1):
            piece = " ".join(words[start:start + size])
            if piece in hay:
                return True, "цитата збіглась (%d сл.)" % size
    return False, "цитати немає у відповіді: %r" % text[:60]


# ── прогін ───────────────────────────────────────────────────────────────

def build_llm(model):
    from app.providers.llm_mlx import MlxLLM
    return MlxLLM(model_path=model) if model else MlxLLM()


def run(kind, llm, cases, verbose, criteria=None, learn=None):
    criteria = criteria or {}
    learn = learn or {}
    build = PROMPTS[kind]
    stats = {"total": 0, "ok": 0, "false_yes": 0, "false_no": 0, "by_kind": {}}
    misses = []
    started = time.time()

    for case in cases:
        if kind == "criterion":
            # Питання до моделі може бути повнішим за підпис у чеклісті:
            # респондент читає ярлик, модель отримує питання.
            asked = learn.get(case["item"], case["item"])
            instruction = build(case["answer"], asked, criteria.get(case["item"]))
        else:
            instruction = build(case["answer"], case["item"])
        reply = llm.respond_text(
            "Ти відповідаєш стисло й точно.",
            [{"role": "user", "content": instruction}])

        if kind == "quote":
            got, why = parse_quote(reply, case["answer"])
        elif kind == "extract":
            got, why = parse_extract(reply)
        else:
            got, why = parse_yes_no(reply), reply.strip()[:40]

        want = bool(case["expected"])
        stats["total"] += 1
        bucket = stats["by_kind"].setdefault(case["kind"], {"total": 0, "ok": 0})
        bucket["total"] += 1
        if got == want:
            stats["ok"] += 1
            bucket["ok"] += 1
        else:
            if got and not want:
                stats["false_yes"] += 1
            else:
                stats["false_no"] += 1
            misses.append((case, got, why))

        if verbose:
            print("  %s %-5s %-46s %s" % (
                "✓" if got == want else "✗", case["kind"],
                case["item"][:44], why))

    stats["seconds"] = round(time.time() - started, 1)
    return stats, misses


def report(name, stats, misses):
    total = stats["total"] or 1
    print("\n── %s ──" % name)
    print("точність:     %d/%d (%.0f%%)   за %s с"
          % (stats["ok"], stats["total"], 100.0 * stats["ok"] / total, stats["seconds"]))
    print("хибне «так»:  %d   (зарахував те, чого не було)" % stats["false_yes"])
    print("хибне «ні»:   %d   (не зарахував сказане)" % stats["false_no"])
    for kind in ("hit", "miss", "near"):
        b = stats["by_kind"].get(kind)
        if b:
            print("  %-5s %d/%d" % (kind, b["ok"], b["total"]))
    if misses:
        print("  помилки:")
        for case, got, why in misses:
            print("    [%s] «%s» ← %r → %s (%s)"
                  % (case["kind"], case["item"][:34], case["answer"][:44],
                     "так" if got else "ні", why))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="all",
                    choices=["all"] + list(PROMPTS))
    ap.add_argument("--model", default=None,
                    help="інша модель MLX, напр. mlx-community/gemma-3-12b-it-4bit")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--items-only", action="store_true",
                    help="без випадків для фази розповіді")
    args = ap.parse_args()

    data = json.load(io.open(CASES, encoding="utf-8"))
    cases = data["cases"]
    print("еталон: %d випадків (%s)"
          % (len(cases), ", ".join("%s×%d" % (k, sum(1 for c in cases if c["kind"] == k))
                                   for k in ("hit", "miss", "near"))))
    llm = build_llm(args.model)
    print("модель: %s" % getattr(llm, "model_path", "?"))

    kinds = list(PROMPTS) if args.prompt == "all" else [args.prompt]
    topics = data.get("topic_cases") or []
    for kind in kinds:
        stats, misses = run(kind, llm, cases, args.verbose,
                            data.get("criteria"), data.get("learn"))
        report("%s · пункти" % kind, stats, misses)
        holdout = data.get("holdout_cases") or []
        if holdout:
            hstats, hmisses = run(kind, llm, holdout, args.verbose,
                                  data.get("criteria"), data.get("learn"))
            report("%s · КОНТРОЛЬНИЙ (не бачив налаштування)" % kind, hstats, hmisses)
        if topics and not args.items_only:
            tstats, tmisses = run(kind, llm, topics, args.verbose,
                                  data.get("criteria"), data.get("learn"))
            report("%s · теми розповіді" % kind, tstats, tmisses)


if __name__ == "__main__":
    main()
