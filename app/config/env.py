"""Читання .env — щоб ключ жив у теці проєкту, а не в ~/.zshrc.

Свідомо без залежностей і свідомо мінімально. Значення ключів ніде не логуються
і не друкуються: у вивід іде тільки факт «встановлено / не встановлено».
"""

import os

DEFAULT_PATH = os.path.join(os.getcwd(), ".env")


def load_env(path: str = DEFAULT_PATH) -> int:
    """Підхоплює KEY=VALUE з .env, не перетираючи вже задані змінні середовища.

    Повертає кількість підхоплених змінних. Файла немає — 0, це не помилка.
    """
    if not os.path.exists(path):
        return 0
    loaded = 0
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
                loaded += 1
    return loaded


def has_key(name: str = "ANTHROPIC_API_KEY") -> bool:
    return bool(os.environ.get(name))
