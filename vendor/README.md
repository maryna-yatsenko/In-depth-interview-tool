# vendor/

Сторонній код, вкопійований у репозиторій напряму (а не встановлений через
`pip`), бо `requirements.txt` не вміє `--no-deps` для одного рядка.

## ukrainian_word_stress

[ukrainian-word-stress](https://pypi.org/project/ukrainian-word-stress/)
2.1.0, ліцензія MIT (див. `LICENSE` у цій теці). У словниковому режимі
(`Disambiguation.Dictionary`, саме той, що використовує цей проєкт) пакет
не потребує `stanza`/PyTorch — `import stanza` в `stressify_.py` лежить
усередині функції, а не на рівні модуля, тому не виконується, якщо ця гілка
коду не викликається. Але `pip install ukrainian-word-stress` все одно тягне
`stanza` як жорстку залежність з `install_requires` — а разом з нею й
PyTorch (~2 ГБ), що зробило б Vercel-бандл непридатним.

Локально це обходять разовим `pip install --no-deps` (див. README.md), але
`requirements.txt`, який один командою `pip install -r requirements.txt`
ставить усе для Vercel, такої гнучкості на рівні одного рядка не має. Тому
для деплою пакет лежить тут уже готовим файлом — той самий код, без кроку
встановлення, який намагався б заодно поставити й stanza.

Оновлення: перевстановити локально з `--no-deps`, скопіювати наново з
`site-packages/ukrainian_word_stress`.
