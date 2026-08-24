"""TTS через ukrainian-tts (ESPnet): пʼять українських голосів локально.

Компроміс, названий вголос. Голоси інші й, можливо, приємніші, але **синтез у
~10 разів повільніший за Piper**: заміряно 1,1–4,6 с на коротке питання і
10,9–14,5 с на довге відкриття, проти 1,3 с у Piper на те саме довге.

Тому тут дві речі, без яких це було б непридатне для живої розмови:

1. **Модель живе в довгоживучому процесі** (`bin/espnet_worker.py`).
   Завантаження — 20,6 с; платити їх на кожну репліку неможливо.
2. **Кеш аудіо на диску.** Відкриття й закриття гайда та відступні репліки
   фіксовані — їх достатньо синтезувати один раз. Живий синтез лишається лише
   для динамічних уточнень, а вони короткі.
"""

import hashlib
import json
import os
import subprocess
import threading
from typing import List, Optional

from .base import ProviderError, TTSProvider
from .tts_text import normalize

VOICES = [
    {"name": "tetiana", "locale": "uk_UA", "gender": "Female"},
    {"name": "lada", "locale": "uk_UA", "gender": "Female"},
    {"name": "mykyta", "locale": "uk_UA", "gender": "Male"},
    {"name": "dmytro", "locale": "uk_UA", "gender": "Male"},
    {"name": "oleksa", "locale": "uk_UA", "gender": "Male"},
]
_NAMES = {item["name"] for item in VOICES}


class EspnetTTS(TTSProvider):
    name = "espnet"
    media_type = "audio/wav"

    def __init__(
        self,
        python_path: str,
        worker_path: str,
        cache_folder: str,
        audio_cache: str,
        voice: Optional[str] = None,
        stress: str = "dictionary",
        start_timeout: int = 180,
        synth_timeout: int = 120,
    ):
        for path, label in ((python_path, "інтерпретатор"), (worker_path, "воркер")):
            if not os.path.isfile(path):
                raise ProviderError("ESPnet: не знайдено %s: %s" % (label, path))
        if not os.path.isdir(cache_folder):
            raise ProviderError("ESPnet: немає теки моделі: %s" % cache_folder)
        if voice and voice not in _NAMES:
            raise ProviderError(
                "Голос '%s' невідомий. Доступні: %s." % (voice, ", ".join(sorted(_NAMES)))
            )

        self.python_path = os.path.abspath(python_path)
        self.worker_path = os.path.abspath(worker_path)
        self.cache_folder = os.path.abspath(cache_folder)
        self.audio_cache = os.path.abspath(audio_cache)
        self.voice = voice or "tetiana"
        self.stress = stress
        self.start_timeout = start_timeout
        self.synth_timeout = synth_timeout

        os.makedirs(self.audio_cache, exist_ok=True)
        self._process = None
        self._lock = threading.Lock()

    # ── процес ───────────────────────────────────────────────────────────

    def _ensure_worker(self):
        if self._process is not None and self._process.poll() is None:
            return self._process

        env = dict(os.environ)
        env["ESPNET_CACHE"] = self.cache_folder
        self._process = subprocess.Popen(
            [self.python_path, self.worker_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, cwd=self.cache_folder,
        )
        # Перший рядок — сигнал готовності. До нього модель ще вантажиться.
        line = self._process.stdout.readline()
        if not line:
            raise ProviderError("ESPnet: воркер не запустився (модель не завантажилась)")
        try:
            payload = json.loads(line.decode("utf-8"))
        except ValueError:
            raise ProviderError("ESPnet: воркер відповів не JSON-ом")
        if not payload.get("ready"):
            raise ProviderError("ESPnet: воркер не готовий: %s" % payload.get("error"))
        return self._process

    def stop(self):
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                try:
                    self._process.stdin.close()
                    self._process.wait(timeout=10)
                except Exception:
                    self._process.kill()
            self._process = None

    # ── кеш ──────────────────────────────────────────────────────────────

    def _cache_path(self, text: str, voice: str) -> str:
        key = hashlib.sha256(
            ("%s|%s|%s" % (voice, self.stress, text)).encode("utf-8")
        ).hexdigest()[:32]
        return os.path.join(self.audio_cache, "%s.wav" % key)

    # ── синтез ───────────────────────────────────────────────────────────

    def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        clean, self.last_report = normalize(text, add_stress=False)
        if not clean:
            return b""

        chosen = voice or self.voice
        if chosen not in _NAMES:
            raise ProviderError(
                "Голос '%s' невідомий. Доступні: %s." % (chosen, ", ".join(sorted(_NAMES)))
            )

        path = self._cache_path(clean, chosen)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            with open(path, "rb") as fh:
                return fh.read()

        with self._lock:
            process = self._ensure_worker()
            request = json.dumps(
                {"text": clean, "voice": chosen, "stress": self.stress, "out": path},
                ensure_ascii=False,
            )
            try:
                process.stdin.write((request + "\n").encode("utf-8"))
                process.stdin.flush()
                line = process.stdout.readline()
            except (BrokenPipeError, OSError) as exc:
                self._process = None
                raise ProviderError("ESPnet: воркер обірвався — %s" % exc)

        if not line:
            self._process = None
            raise ProviderError("ESPnet: воркер не відповів")
        payload = json.loads(line.decode("utf-8"))
        if payload.get("error"):
            raise ProviderError("ESPnet: %s" % payload["error"])

        with open(path, "rb") as fh:
            return fh.read()

    def prewarm(self, phrases: List[str], voice: Optional[str] = None) -> int:
        """Синтезувати наперед те, що відомо заздалегідь.

        Відкриття й закриття гайда однакові для всіх респондентів, і саме вони
        найдовші. Без цього перший респондент чекав би 12 секунд тишу.
        """
        done = 0
        for phrase in phrases:
            if not phrase:
                continue
            try:
                self.synthesize(phrase, voice)
                done += 1
            except ProviderError:
                break
        return done

    def voices(self) -> List[dict]:
        return list(VOICES)
