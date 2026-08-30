# Interview Tool

Voice-based інтерв'юер для якісних досліджень: LLM веде структуроване
інтерв'ю за гайдом (`spaces/<key>/guides/*.json`), респондент відповідає
голосом у браузері, транскрипт зберігається для подальшого аналізу.

Деталі продукту, план і рішення — в `docs/ai/summary.md`,
`docs/ai/architecture.md`, `docs/ai/tasks.md`, `docs/ai/edgecases.md`,
`docs/ai/technical_debt.md`. Установка й запуск — у `README.md`. Тут —
лише орієнтир по структурі репозиторію, щоб одразу було видно, де що
лежить і чому.

## Два живі входи, одне спільне ядро

- **`local/serve.py` / `local/cli.py`** — локальна розробка. `serve.py`
  піднімає `ThreadingHTTPServer` (запускається через `local/start.command`/
  `local/stop.command`, які треба запускати з кореня проєкту), `cli.py` —
  текстовий термінальний канал для швидкої перевірки якості інтерв'ю без
  голосу. Обидва працюють з диском (`local/data/`) і локальними моделями
  (`local/models/`: mlx для LLM, espnet/piper для TTS).
- **`api/index.py`** — Vercel serverless entrypoint (задеплоєна версія).
  Той самий `Handler` з `app/api/server.py`, але сховище — Postgres
  (`STORAGE_BACKEND=postgres`, `app/storage/db.py`), а провайдери LLM/TTS
  підмінюються env-змінними `LLM_PROVIDER_OVERRIDE`/
  `TTS_PROVIDER_OVERRIDE` (`app/providers/registry.py`) — на Vercel
  локальні моделі фізично не запускаються.

Обидва входи ділять один і той самий `app/` без жодних відгалужень —
зміна там впливає одразу на локальну розробку і на деплой.

## Структура

| Шлях | Призначення |
|---|---|
| `app/api/` | HTTP-обробник (`server.py`) і бекенд адмінки (`admin.py`) |
| `app/config/` | Завантаження `.env`, схема/валідація `space.json`/гайдів (`space.py`), резолв конфігів для Vercel (`resolve.py`), банк реплік (`phrases.py`) |
| `app/interview/` | Ядро інтерв'ю: машина станів і фази (`session.py`, `phases.py`), guard проти небажаних реплік, LLM-суддя чеклиста (`judge.py`), деідентифікація PII, збірка промпту, `prompts/*.md` |
| `app/providers/` | По одному файлу на LLM/TTS-провайдера (mlx, anthropic, mock, espnet, piper, azure, say) + `registry.py`, який будує потрібний за конфігом/env |
| `app/storage/` | Диск (`local.py`), Postgres (`db.py`), голосові записи (`voice.py`) — однакові сигнатури для обох бекендів |
| `web/` | Статика: сторінка респондента (`index.html`, `app.js`, `audio.js`, `segments.js`, `styles.css`) і панель дослідника (`admin.html`, `admin.js`, `admin.css`) |
| `public/` | Симлінки на файли з `web/` для статичної роздачі на Vercel |
| `spaces/` | Конфіги досліджень (`space.json` + `guides/`). У git — лише `example/` (референсний фікстур) і `travel/` (реальне дослідження); решта — локальні, гітигноряться |
| `docs/ai/` | Живі документи: план архітектури, продуктовий контекст, задачі, каталог едж-кейсів, технічний борг |
| `tests/` | Юніт-тести (`python3 -m unittest discover -s tests -q`) |
| `api/index.py`, `vercel.json`, `.vercelignore`, `requirements.txt` | Vercel-деплой |
| `local/` | Усе, що потрібне лише локальній розробці — і нічого з цього не входить у Vercel-бандл (`.vercelignore`): `serve.py`, `cli.py`, `start.command`, `stop.command`, `requirements-local.txt`; `bin/` — espnet-воркер (`espnet_worker.py`), офлайн-оцінка LLM-судді (`judge_eval.py`), прогін сценарію без веб-інтерфейсу (`run_interview.py`); `models/`, `data/` — локальні моделі й транскрипти, гітигноряться повністю, існують лише на диску розробника. `start.command`/`stop.command` самі переходять у корінь проєкту (`cd ..`) — запускати можна з будь-якого місця |

## Критерій: що лишається в репозиторії

Файл/тека мають право тут бути, якщо виконується хоч одне:
1. Реально імпортується або викликається з `local/serve.py`, `local/cli.py`
   чи `api/index.py` (напряму або через `app/providers/registry.py`).
2. Використовується тестами (`tests/`).
3. Це документація (`README.md`, `docs/ai/*.md`, цей файл) або конфіг
   деплою (`vercel.json`, `.vercelignore`, `requirements*.txt`).

Усе інше — застарілий прототип, чернетка чи сміття кешів/ОС — не
додається, а якщо з'явилось, прибирається при наступному прибиранні.
