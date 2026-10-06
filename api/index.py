# -*- coding: utf-8 -*-
"""Вхідна точка Vercel — той самий Handler, що й у serve.py, лише без
ThreadingHTTPServer/serve_forever: Vercel сам викликає `handler` на кожен
запит, тримати сокет самим не потрібно (і не можна).

Усе нижче виконується один раз на холодний старт контейнера — так само, як
serve.py будує store/handler один раз перед тим, як пірнути в
`serve_forever()`. Тепле повторне використання того самого контейнера між
запитами — оптимізація самого Vercel, коду тут для цього не треба.

`vercel.json` заводить усі шляхи сюди через rewrites — цей файл не знає,
що там `/api/answer`, а що `/voice/<id>/<file>`: усю маршрутизацію робить
`Handler`, як і раніше.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.server import SessionStore, make_handler
from app.config.env import load_env
from app.config.phrases import load_bank
from app.config.resolve import load_resolved_space

load_env()

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPACES_ROOT = os.path.join(_ROOT, "spaces")
# Один спільний гайд, а не окрема копія під хмару (рішення з плану міграції)
# — тож і тут той самий ключ, що й у ./start.command spaces/travel.
_SPACE_KEY = os.environ.get("SPACE_KEY", "travel")

space, guide = load_resolved_space(_SPACES_ROOT, _SPACE_KEY)

llm_cfg = dict(space.providers.get("llm", {}) or {})

_space_dir = os.path.join(_SPACES_ROOT, _SPACE_KEY)
bank_provider = lambda: load_bank(_space_dir)  # noqa: E731 — те саме, що robить serve.py

store = SessionStore(space, guide, llm_cfg, bank_provider)

# Адмінка на Vercel — повна, не лише перегляд транскриптів (рішення з плану
# міграції). Корінь той самий, що дає list_spaces/create_space побачити й
# бандл, і простори, створені лише в Postgres.
admin_root = _SPACES_ROOT

# Vercel шукає в файлі САМЕ `class handler(...):` статично (без виконання
# коду) — присвоєння `handler = make_handler(...)` цьому не відповідає, хоч
# і працює однаково в Python. Тому клас, що успадковує результат фабрики.
# SURFACE=respondent|admin ділить деплой на два окремі сайти (два проєкти Vercel з одного коду);
# без змінної — як раніше, один сайт з обома частинами.
_SURFACE = os.environ.get("SURFACE", "all")
_Handler = make_handler(space, guide, llm_cfg, store, admin_root, bank_provider, _SURFACE)


class handler(_Handler):
    pass
