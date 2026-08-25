# -*- coding: utf-8 -*-
"""Тонка обгортка над `load_space_dir` — лише для серверного входу.

`app/config/space.py` лишається чистими функціями «шлях → дані» і
використовується без змін і локально (`cli.py`, тести), і тут. Уся різниця
для Vercel — де саме шукати той шлях, ПЕРШ ніж віддати його
`load_space_dir`: спершу перевизначення з адмінки (Postgres), і лише якщо
його немає — файли, що приїхали разом із кодом.

Код деплою на Vercel незмінний під час роботи, тому перевизначення
матеріалізуються у `/tmp` — єдине місце, куди там можна писати.
"""

import os
import shutil
import tempfile
from typing import Optional, Tuple

from ..config.space import Guide, SpaceConfig, load_space_dir
from ..storage import db as store_db


def _on_postgres() -> bool:
    return os.environ.get("STORAGE_BACKEND") == "postgres"


def resolve_space_dir(root: str, space_key: str) -> str:
    """Повертає шлях, який можна віддати `load_space_dir` без жодних змін
    у ній самій: або теку деплою (як завжди), або матеріалізовану в /tmp
    копію того, що дослідник відредагував через адмінку на живому сайті.

    Перевизначень може бути лише на частину файлів (дослідник зберіг лише
    гайд, а `space.json` ніколи не редагував) — тому першим кроком копіюємо
    весь бандл цілком, і лише потім перезаписуємо зверху ті шляхи, для яких
    є рядок у Postgres. Матеріалізувати тільки перевизначені файли означало
    б лишити в /tmp дірку там, де `load_space_dir` чекає на файл із бандла.
    """
    bundled = os.path.join(root, space_key)
    if not _on_postgres():
        return bundled

    paths = store_db.list_config_override_paths(space_key)
    if not paths:
        # Простір ніхто не редагував на живому сайті — файли з деплою й є
        # чинним конфігом.
        return bundled

    tmp_root = os.path.join(tempfile.gettempdir(), "spaces", space_key)
    if os.path.isdir(bundled):
        shutil.copytree(bundled, tmp_root, dirs_exist_ok=True)
    for rel in paths:
        content = store_db.get_config_override(space_key, rel)
        if content is None:
            continue
        dest = os.path.join(tmp_root, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(content)
    return tmp_root


def load_resolved_space(root: str, space_key: str,
                         guide_key: Optional[str] = None) -> Tuple[SpaceConfig, Guide]:
    """Те, що `api/index.py` викликає на холодному старті замість прямого
    `load_space_dir(space_dir)`."""
    return load_space_dir(resolve_space_dir(root, space_key), guide_key)
