#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Повний прогін інтервʼю по HTTP із заготовленими відповідями.

Навіщо: перевірити наживо те, що інакше перевіряється тільки очима — чи
інтервʼюер справді не питає зайвого, коли людина відповіла повно, і чи питає,
коли відповідь тонка.

    .venv/bin/python local/bin/run_interview.py --out звіт.md
    .venv/bin/python local/bin/run_interview.py --thin idea   # тонкі відповіді на тему

Відповіді підібрані під теми гайда «подорожі компанією»: кожна закриває обидва
пункти `must_learn`. Тема обирається за підписом фази, який віддає сервер.
"""

import argparse
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8770"

# Розгорнуті відповіді: кожна свідомо містить обидва пункти теми.
FULL = {
    "Виникнення ідеї":
        "Запропонувала Оля — кинула в наш чат посилання на будинок у Ворохті й "
        "написала «їдемо?». Від того повідомлення до першого завдатку минуло "
        "буквально два дні: наступного вечора вже скидались по тисячі.",
    "Де жила інформація":
        "Квитки лежали в мене в пошті, обговорення все в телеграмі, а бюджет "
        "Андрій вів в окремій гугл-таблиці. Усе було в різних місцях, в одному "
        "не лежало нічого — і саме це найбільше бісило.",
    "Групові рішення":
        "Механіка була проста: хтось кидав варіант у чат, і якщо за годину ніхто "
        "не заперечив — вважалось, що згода є. Останнє таке рішення: вибирали між "
        "двома будинками, Оля скинула обидва посилання, ми проголосували емодзі, "
        "і за півгодини вона забронювала дешевший.",
    "Розбіжна інформація":
        "Було: я була впевнена, що виїзд у пʼятницю о шостій, а Андрій усім "
        "казав, що о восьмій. Помітила Марта, коли зводила список, хто кого "
        "забирає — вона перепитала в чаті, і ми з Андрієм побачили, що в нього "
        "стара версія. Виправили тим, що закріпили правильний час у чаті.",
    "Розподіл внеску":
        "По факту тягнула Оля — вона і житло, і маршрут, і нагадування. Я взяла "
        "на себе їжу, Андрій — таблицю витрат, а решта троє не робили нічого, "
        "хоч на словах усі були «за». Останній тиждень перед виїздом Оля щодня "
        "щось дописувала в чат, я закупалась, Андрій рахував.",
    "Розбіжність поглядів":
        "Посварились через бюджет: Андрій хотів будинок дорожче, з сауною, а Оля "
        "казала, що це вдвічі дорожче за сенс. Почалось із його повідомлення "
        "«давайте вже нормально відпочинемо», закінчилось тим, що взяли дешевший "
        "варіант, а Андрій два дні дувся, потім відпустило.",
    "Гроші":
        "Домовились так: житло скидаємо порівну, а їжу — хто скільки зʼїв, тому "
        "чеки фотографували. Сам розрахунок відбувся вже після повернення: Андрій "
        "звів усе в таблицю, скинув, кому скільки, і двоє перераховували, бо "
        "забули про бензин.",
    "Поведінка на місці":
        "На місці в план ніхто не залазив — усе трималось у голові й у розмові. "
        "Один раз я таки відкрила таблицю: шукала, на яку годину в нас "
        "заброньована сауна. Знайшла не одразу, бо це був окремий аркуш, і я "
        "хвилини три гортала.",
    "Термінові пошуки на місці":
        "Коли приїхали, треба була точна адреса будинку — я шукала її в пошті, "
        "гортала листи з бронюванням просто на морозі. Пішло хвилин десять, бо "
        "лист був не в основній папці, а в промоакціях.",
    "Після поїздки":
        "Фото залишились у спільному альбомі, його зробила Марта. Таблиця з "
        "витратами десь загубилась — Андрій казав, що вона в нього, але потім не "
        "знайшов. Якби зараз захотіла щось згадати, пішла б у чат: там усе "
        "лежить, просто перемішане з мемами.",
}

WARMUP = ("Останнього разу ми їздили в Карпати, у Ворохту. Були друзі з "
          "університету, нас шість людей, на чотири дні в лютому.")

# Коротка розповідь: тоді теми НЕ виглядають згаданими, і рушій питає про них
# сам. Потрібно, щоб побачити роботу карти тем, а не лише пропуски.
NARRATIVE_SHORT = [
    "Та поїхали й поїхали, нормально все було.",
    "Та все, більше нічого не пригадаю.",
]

NARRATIVE = [
    "Почалось усе з Олі: вона в грудні кинула в чат посилання на будинок і "
    "написала «їдемо?». За два дні ми вже скидались на завдаток. Далі місяць "
    "нічого не відбувалось, а потім за тиждень до виїзду почалась паніка: "
    "виявилось, що ніхто не подумав про дорогу.",
    "У самій поїздці все було нормально, крім першого вечора — ми годину "
    "шукали адресу, бо вона була в пошті, а не в чаті. Потім я готувала, "
    "Андрій рахував витрати, Оля всіх організовувала. Посварились один раз "
    "через бюджет, але швидко відпустило.",
    "Та все, більше нічого не пригадаю.",
]

CLOSING = [
    "Найбільше часу забрало те, що мало бути простим — звести докупи, хто коли "
    "приїжджає. Це три дні листування в чаті, хоч мало бути п'ять хвилин.",
    "Муляло, що інформація лежала в чотирьох місцях. Щоразу, коли треба було "
    "щось перевірити, я не знала, куди дивитись першим.",
    "Мабуть, ще важливо, що ніхто з нас не хотів бути головним — Оля стала "
    "організатором не тому, що хотіла, а тому, що більше нікому.",
]

THIN = "Та не пам'ятаю вже, давно було."


def post(path, payload):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def topic_of(label):
    """Тема з деталі прогресу: «питання 4 з 25 · Як виникла ідея поїздки»."""
    if "·" in (label or ""):
        return label.split("·")[-1].strip()
    return ""


def pick_answer(data, thin_topic, narrative_index, closing_index,
                short_narrative=False):
    progress = data.get("progress") or {}
    # Тема тепер у деталі прогресу, а не в підписі розділу.
    label = progress.get("detail", "")
    phase = progress.get("phase", "")
    if phase == "warmup":
        return WARMUP, "розігрів"
    if phase == "narrative":
        source = NARRATIVE_SHORT if short_narrative else NARRATIVE
        idx = min(narrative_index, len(source) - 1)
        return source[idx], "розповідь"
    if phase == "closing":
        idx = min(closing_index, len(CLOSING) - 1)
        return CLOSING[idx], "підсумок"
    topic = topic_of(label)
    if thin_topic and thin_topic.lower() in topic.lower():
        return THIN, topic
    return FULL.get(topic, "Розкажу так: усе робили разом, нічого особливого."), topic


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="куди писати звіт (markdown)")
    ap.add_argument("--thin", default="", help="тема, на яку відповідати тонко")
    ap.add_argument("--limit", type=int, default=70)
    ap.add_argument("--short-narrative", action="store_true",
                    help="коротка вільна розповідь — щоб рушій питав про теми сам")
    args = ap.parse_args()

    status, started = post("/api/start", {})
    if status != 200:
        print("не вдалося почати:", started)
        return 1
    sid = started["session_id"]
    print("сесія:", sid)

    steps = []
    data = started
    narrative_index = 0
    closing_index = 0
    started_at = time.time()

    for step in range(args.limit):
        progress = data.get("progress") or {}
        if data.get("hold"):
            # Інтервʼюер мовчить: питання лишається тим самим.
            question = "(тримає розповідь — питання те саме)"
        else:
            question = data.get("utterance", "")
        answer, where = pick_answer(data, args.thin, narrative_index,
                                    closing_index, args.short_narrative)
        if progress.get("phase") == "narrative":
            narrative_index += 1
        if progress.get("phase") == "closing":
            closing_index += 1

        checklist = data.get("checklist") or []
        steps.append({
            "n": step + 1,
            "phase": progress.get("phase", ""),
            "label": progress.get("label", ""),
            "where": where,
            "question": question,
            "answer": answer,
            "asked": progress.get("asked"),
            "max_questions": progress.get("max_questions"),
            "checklist": [(c["text"], c["done"]) for c in checklist],
            "hold": bool(data.get("hold")),
        })
        print("%2d. [%s] %s" % (step + 1, progress.get("phase", "?"),
                                (question or "")[:66].replace("\n", " ")))

        # Відповідь лише записується; крок сценарієм — окрема дія, як у людини.
        status, data = post("/api/answer", {"session_id": sid, "text": answer})
        if status != 200:
            print("помилка (відповідь):", data)
            break
        status, data = post("/api/step", {"session_id": sid, "delta": 1})
        if status != 200:
            print("помилка (крок):", data)
            break
        if data.get("done"):
            steps.append({
                "n": len(steps) + 1, "phase": "done", "label": "Завершення",
                "where": "фінал", "question": data.get("utterance", ""),
                "answer": "", "asked": (data.get("progress") or {}).get("asked"),
                "max_questions": (data.get("progress") or {}).get("max_questions"),
                "checklist": [], "hold": False,
            })
            print("завершено на кроці", len(steps))
            break

    elapsed = round(time.time() - started_at)
    report = build_report(sid, steps, elapsed, args.thin)
    if args.out:
        io.open(args.out, "w", encoding="utf-8").write(report)
        print("звіт:", args.out)
    else:
        print(report)
    return 0


def build_report(sid, steps, elapsed, thin):
    lines = []
    add = lines.append
    add("# Повний прогін інтервʼю")
    add("")
    add("Сесія `%s` · %d кроків · %d с · локальна модель gemma-3-4b" % (sid, len(steps), elapsed))
    if thin:
        add("")
        add("Відповіді на тему «%s» — навмисно тонкі, щоб побачити уточнення." % thin)
    add("")

    # Скільки питань пішло на кожну тему — це і є відповідь на «чи не питає зайвого».
    per_topic = {}
    for step in steps:
        if step["phase"] != "topics":
            continue
        topic = topic_of(step["label"]) or step["where"]
        per_topic.setdefault(topic, 0)
        per_topic[topic] += 1

    add("## Скільки питань пішло на тему")
    add("")
    add("| Тема | Питань |")
    add("|---|---|")
    for topic, count in per_topic.items():
        add("| %s | %d |" % (topic, count))
    add("")

    add("## Хід розмови")
    add("")
    for step in steps:
        head = "**%d.** %s" % (step["n"], step["label"] or step["phase"])
        if step["asked"]:
            head += " · питання %s з %s" % (step["asked"], step["max_questions"])
        add(head)
        add("")
        if step["hold"]:
            add("> *(інтервʼюер мовчить — питання лишається тим самим)*")
        else:
            add("> " + (step["question"] or "").replace("\n", "\n> "))
        add("")
        if step["checklist"]:
            done = sum(1 for _, ok in step["checklist"] if ok)
            add("Хочемо почути (%d з %d): %s" % (
                done, len(step["checklist"]),
                ", ".join(("**%s** ✓" % t) if ok else t for t, ok in step["checklist"])))
            add("")
        if step["answer"]:
            add("— " + step["answer"])
            add("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
