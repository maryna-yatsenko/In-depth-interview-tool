#!/bin/bash
# Зупинка інструменту.
cd "$(dirname "$0")/.." || exit 1
PIDFILE=".server.pid"

if [ -f "$PIDFILE" ]; then
  PID="$(cat "$PIDFILE")"
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    # Чекаємо фактичного завершення: інакше наступний start упирається в
    # ще зайнятий порт («Address already in use») і тихо не піднімається.
    for _ in $(seq 1 40); do
      kill -0 "$PID" 2>/dev/null || break
      sleep 0.25
    done
    if kill -0 "$PID" 2>/dev/null; then
      kill -9 "$PID" 2>/dev/null
      echo "Зупинено примусово (pid $PID)"
    else
      echo "Зупинено (pid $PID)"
    fi
  else
    echo "Процес $PID уже не живий"
  fi
  rm -f "$PIDFILE"
else
  echo "Файла .server.pid немає — можливо, сервер запускали вручну."
  pgrep -fl "local/serve.py" || echo "Запущених серверів не знайдено."
fi
