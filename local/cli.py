#!/usr/bin/env python3
"""Текстовий канал інтервʼю в терміналі — Етап 1.

Навіщо термінал, а не веб: на цьому етапі перевіряється якість інтервʼю, а не
інтерфейс. Веб і голос — Етап 2, і вони не змінять нічого в ядрі.

Запускати з кореня проєкту (шляхи на кшталт `spaces/example` — відносні
до робочої теки, а не до цього файлу):

    python3 local/cli.py --space spaces/example                 # прогін на заглушці
    python3 local/cli.py --space spaces/example --llm anthropic # справжня модель
    python3 local/cli.py --space spaces/example --llm mock --auto  # без участі людини
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.env import has_key, load_env
from app.config.space import ConfigError, load_space_dir
from app.interview.session import Session
from app.providers.base import ProviderError
from app.providers.registry import build_llm
from app.storage.local import save_session

_AUTO_ANSWERS = [
    "Та нормально все, нічого особливого.",
    "Ну я подивився в інтернеті, порівняв кілька варіантів і купив.",
    "Питав у знайомого, він давно катається.",
    "Найскладніше було зрозуміти, який розмір рами мені треба.",
    "Після покупки виявилось, що потрібні були ще й педалі окремо.",
]


def main():
    parser = argparse.ArgumentParser(description="Інтервʼю в терміналі")
    parser.add_argument("--space", required=True, help="тека простору (напр. spaces/example)")
    parser.add_argument("--guide", default=None, help="ключ гайда; за замовчуванням перший")
    parser.add_argument("--llm", default=None, help="mock | anthropic (перекриває конфіг)")
    parser.add_argument("--auto", action="store_true", help="відповідати заготовками, без людини")
    parser.add_argument("--no-save", action="store_true", help="не зберігати транскрипт")
    args = parser.parse_args()

    try:
        space, guide = load_space_dir(args.space, args.guide)
    except (ConfigError, FileNotFoundError) as exc:
        print("⛔ Конфіг: %s" % exc)
        return 2

    load_env()
    if space.draft:
        print("⛔ Простір '%s' — чернетка (draft: true): у ньому ще стоять TODO з шаблону." % space.key)
        print("   Заповни його і прибери draft, інакше респондент почує текст заготовки.")
        return 2

    llm_cfg = dict(space.providers.get("llm", {}) or {})
    if args.llm:
        llm_cfg["provider"] = args.llm
    if llm_cfg.get("provider") == "anthropic" and not has_key():
        print("⛔ Немає ANTHROPIC_API_KEY. Поклади ключ у файл .env у корені проєкту:")
        print("   ANTHROPIC_API_KEY=...")
        print("   (.env уже в .gitignore — у репозиторій не поїде)")
        return 2

    try:
        llm = build_llm(llm_cfg)
    except ProviderError as exc:
        print("⛔ Провайдер: %s" % exc)
        return 2

    session = Session(space, guide, llm)

    print("─" * 72)
    print("Простір: %s | гайд: %s | модель: %s | промпт: %s"
          % (space.key, guide.key, llm.name, session.prompt_version))
    print("Тем: %d | ліміт реплік: %d" % (len(guide.topics), guide.max_turns))
    if space.privacy.consent_text:
        print("\nЗгода: %s" % space.privacy.consent_text)
    print("─" * 72)

    print("\n🎙  %s\n" % session.start())

    auto_i = 0
    while not session.done:
        if args.auto:
            if auto_i >= len(_AUTO_ANSWERS):
                answer = "Більше нічого не згадаю."
            else:
                answer = _AUTO_ANSWERS[auto_i]
            auto_i += 1
            print("👤 %s" % answer)
        else:
            try:
                answer = input("👤 ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n(інтервʼю перервано)")
                break
            if not answer:
                continue
            if answer in (":q", ":quit"):
                break

        try:
            turn = session.answer(answer)
        except ProviderError as exc:
            print("⛔ Модель недоступна: %s" % exc)
            break

        for rejection in turn.guard_rejections:
            print("   ⛔ guard відхилив репліку: %s" % "; ".join(rejection))
        if turn.fallback_used:
            print("   ⚠️  використано нейтральну відступну репліку")
        if turn.override:
            print("   🔒 ядро: %s" % turn.override)

        print("\n🎙  %s\n" % turn.utterance)

    payload = session.to_dict()
    interviewer_turns = len([t for t in payload["turns"] if t["role"] == "interviewer"])
    print("─" * 72)
    print("Реплік інтервʼюера: %d | тем покрито: %d з %d | інцидентів: %d"
          % (interviewer_turns, len(payload["topics_covered"]), len(guide.topics),
             len(payload["incidents"])))

    if not args.no_save:
        path = save_session(payload)
        print("Транскрипт: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
