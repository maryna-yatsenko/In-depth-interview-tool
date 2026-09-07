#!/bin/bash
# Запуск інструменту. Двічі клікнути у Finder або виконати ./start.command
#
# Сервер живе незалежно від будь-якої сесії Claude: логи в local/.server.log,
# pid у .server.pid. Зупинити — ./stop.command
cd "$(dirname "$0")/.." || exit 1

SPACE="${1:-spaces/example}"
PORT="${PORT:-8770}"
# Без LLM= провайдер береться з конфігу простору. Раніше тут стояв mock за
# замовчуванням, і він тихо перекривав налаштування — сервер писав «модель: mock»,
# хоч у просторі стояла локальна модель.
LLM="${LLM:-}"
# У теці проєкту, а не в домашній — щоб не залежати від того, де ОС тримає
# логи (на Linux ~/Library/Logs узагалі не існує, і запис у нього мовчки не
# піднімав сервер).
LOG="local/.server.log"
PIDFILE=".server.pid"

open_browser() {
  # macOS має `open`, Linux — `xdg-open`. Якщо немає жодного (Windows/WSL,
  # мінімальний контейнер) — просто нічого не робимо: URL уже надруковано.
  if command -v open >/dev/null 2>&1; then
    open "$1" 2>/dev/null
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$1" 2>/dev/null
  fi
}

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Вже запущено (pid $(cat "$PIDFILE")) → http://127.0.0.1:$PORT"
  open_browser "http://127.0.0.1:$PORT"
  exit 0
fi

# Перший запуск на новій машині: свого .venv ще немає — ставимо сама, а не
# мовчки падаємо на системний Python без anthropic/psycopg2 (справжня модель
# і Vercel-режим тоді просто не працювали б, без жодного пояснення чому).
if [ ! -x ".venv/bin/python" ]; then
  echo "Готую оточення (перший запуск)…"
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi

PY=python3
[ -x ".venv/bin/python" ] && PY=".venv/bin/python"

# Локальна модель лежить у теці проєкту, а не в домашньому кеші.
export HF_HOME="$PWD/local/models/hf"

ARGS=(--space "$SPACE" --port "$PORT" --admin)
[ -n "$LLM" ] && ARGS+=(--llm "$LLM")
echo "Простір: $SPACE | модель: ${LLM:-з конфігу простору} | порт: $PORT"
nohup "$PY" local/serve.py "${ARGS[@]}" >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"
sleep 2

if ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  # Найчастіша причина — порт ще зайнятий попереднім запуском. Кажемо прямо,
  # а не мовчимо з порожнім логом.
  if grep -q "Address already in use" "$LOG" 2>/dev/null; then
    echo "⛔ Порт $PORT ще зайнятий. Виконай ./stop.command і спробуй знову."
  fi
fi

if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "✅ Запущено (pid $(cat "$PIDFILE"))"
  echo "   Респондент: http://127.0.0.1:$PORT"
  echo "   Дослідник:  http://127.0.0.1:$PORT/admin"
  echo "   Логи:       $LOG"
  open_browser "http://127.0.0.1:$PORT"
else
  echo "⛔ Не запустилось. Останні рядки логу:"
  tail -20 "$LOG"
  rm -f "$PIDFILE"
  exit 1
fi
