#!/bin/bash
# Запуск інструменту. Двічі клікнути у Finder або виконати ./start.command
#
# Сервер живе незалежно від будь-якої сесії Claude: логи в ~/Library/Logs,
# pid у .server.pid. Зупинити — ./stop.command
cd "$(dirname "$0")" || exit 1

SPACE="${1:-spaces/example}"
PORT="${PORT:-8770}"
# Без LLM= провайдер береться з конфігу простору. Раніше тут стояв mock за
# замовчуванням, і він тихо перекривав налаштування — сервер писав «модель: mock»,
# хоч у просторі стояла локальна модель.
LLM="${LLM:-}"
LOG="$HOME/Library/Logs/interview-tool.log"
PIDFILE=".server.pid"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Вже запущено (pid $(cat "$PIDFILE")) → http://127.0.0.1:$PORT"
  open "http://127.0.0.1:$PORT" 2>/dev/null
  exit 0
fi

PY=python3
[ -x ".venv/bin/python" ] && PY=".venv/bin/python"

# Локальна модель лежить у теці проєкту, а не в домашньому кеші.
export HF_HOME="$PWD/models/hf"

ARGS=(--space "$SPACE" --port "$PORT" --admin)
[ -n "$LLM" ] && ARGS+=(--llm "$LLM")
echo "Простір: $SPACE | модель: ${LLM:-з конфігу простору} | порт: $PORT"
nohup "$PY" serve.py "${ARGS[@]}" >> "$LOG" 2>&1 &
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
  open "http://127.0.0.1:$PORT" 2>/dev/null
else
  echo "⛔ Не запустилось. Останні рядки логу:"
  tail -20 "$LOG"
  rm -f "$PIDFILE"
  exit 1
fi
