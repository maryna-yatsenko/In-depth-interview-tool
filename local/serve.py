#!/usr/bin/env python3
"""Веб-канал інтервʼю: сторінка респондента + голос у браузері.

Запускати з кореня проєкту (шляхи на кшталт `spaces/example` — відносні
до робочої теки, а не до цього файлу):

    python3 local/serve.py --space spaces/example                # заглушка, без витрат
    .venv/bin/python local/serve.py --space spaces/example --llm anthropic
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.server import serve
from app.config.env import has_key, load_env
from app.config.space import ConfigError, load_space_dir


def main():
    parser = argparse.ArgumentParser(description="Веб-сервер інтервʼю")
    parser.add_argument("--space", required=True)
    parser.add_argument("--guide", default=None)
    parser.add_argument("--llm", default=None, help="mock | mlx | anthropic")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--admin", action="store_true",
                        help="увімкнути адмінку дослідника на /admin (за замовчуванням її немає)")
    args = parser.parse_args()

    try:
        space, guide = load_space_dir(args.space, args.guide)
    except (ConfigError, FileNotFoundError) as exc:
        print("⛔ Конфіг: %s" % exc)
        return 2

    load_env()
    llm_cfg = dict(space.providers.get("llm", {}) or {})
    if args.llm:
        llm_cfg["provider"] = args.llm
    if llm_cfg.get("provider") == "anthropic" and not has_key():
        print("⛔ Немає ANTHROPIC_API_KEY (поклади у .env). Або запусти з --llm mock.")
        return 2

    # Корінь просторів — батьківська тека обраного простору.
    admin_root = os.path.abspath(os.path.join(args.space, os.pardir)) if args.admin else None

    httpd = serve(space, guide, llm_cfg, args.port, admin_root,
                  space_dir=os.path.abspath(args.space))
    print("Простір: %s | гайд: %s | модель: %s" % (space.key, guide.key, llm_cfg.get("provider")))
    print("Голос: stt=%s (питання — текстом і, де записано, живим голосом дослідника)"
          % (space.providers.get("stt") or {}).get("provider"))
    print("\n  Респондент:  http://127.0.0.1:%d" % args.port)
    if admin_root:
        print("  Дослідник:   http://127.0.0.1:%d/admin" % args.port)
    else:
        print("  (адмінка вимкнена — запусти з --admin)")
    print("")
    print("Ctrl+C — зупинити")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nзупинено")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
