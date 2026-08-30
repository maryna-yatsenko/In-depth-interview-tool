#!/usr/bin/env python3
"""Довгоживучий процес синтезу ESPnet.

Навіщо окремий процес, а не імпорт у сервері:

1. `ukrainian-tts` тягне за собою PyTorch і ESPnet, і прибиває
   `ukrainian-word-stress` до версії 1.1.0 — це відкатило б наголоси в Piper.
   Тому воно живе в окремому venv (`.venv-espnet`), а спілкуємось через stdin.
2. Завантаження моделі — **20,6 секунди**. Запускати процес на кожну репліку
   означало б платити ці 20 с щоразу; тому процес один і живе далі.

Протокол: рядок JSON на вхід → рядок JSON на вихід.
    {"text": "...", "voice": "tetiana", "stress": "dictionary", "out": "/шлях.wav"}
    {"ok": true, "bytes": 12345}

⚠️ Робоча тека мусить бути текою кешу моделі: у config.yaml моделі шлях до
`feats_stats.npz` **відносний**, і з іншої теки завантаження падає.
"""

import io
import json
import os
import sys


def main():
    cache = os.environ.get("ESPNET_CACHE", ".")
    os.chdir(cache)

    # Уся балаканина ESPnet — у stderr, щоб не забруднити протокол на stdout.
    stdout = sys.stdout
    sys.stdout = sys.stderr

    from ukrainian_tts.tts import TTS  # noqa: E402

    tts = TTS(cache_folder=".", device="cpu")
    stdout.write(json.dumps({"ready": True}) + "\n")
    stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError as exc:
            stdout.write(json.dumps({"error": "невалідний запит: %s" % exc}) + "\n")
            stdout.flush()
            continue

        try:
            buffer = io.BytesIO()
            tts.tts(
                request["text"],
                request.get("voice") or "tetiana",
                request.get("stress") or "dictionary",
                buffer,
            )
            data = buffer.getvalue()
            with open(request["out"], "wb") as fh:
                fh.write(data)
            stdout.write(json.dumps({"ok": True, "bytes": len(data)}) + "\n")
        except Exception as exc:  # синтез однієї фрази не має валити процес
            stdout.write(json.dumps({"error": "%s: %s" % (type(exc).__name__, exc)}) + "\n")
        stdout.flush()


if __name__ == "__main__":
    main()
