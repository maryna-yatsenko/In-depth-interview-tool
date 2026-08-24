"""TTS через Piper — локальна нейронна модель.

Навіщо він тут головний: системний голос macOS («Леся») — старий синтез, і
жодне крутіння швидкості чи паузи його не виправить. Проблема в моделі, а не в
обгортці. Piper — це VITS-модель, яка працює на CPU офлайн, безкоштовно й без
акаунта, і українська модель `uk_UA-ukrainian_tts-medium` має три голоси
(`lada`, `mykyta`, `tetiana` — тобто є і чоловічий).

Побічна властивість, важлива для корпоративного контура: **нічого не покидає
машину.** Ні тексту питань, ні голосу. Порівняй із браузерним розпізнаванням
(TD-6), яке відправляє аудіо респондента вендору браузера.

Модель береться з локального файла; звідки він узявся — справа встановлення,
а не коду. Шлях і голос задаються в конфізі простору.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import List, Optional

from .base import ProviderError, TTSProvider
from .tts_text import normalize


def _find_piper() -> Optional[str]:
    """Шукати поруч із поточним інтерпретатором, а не лише в PATH.

    Сервер запускається як `.venv/bin/python serve.py`, і теки `.venv/bin` у
    PATH при цьому немає — `shutil.which` бінарник не знайшов би, хоча він
    установлений у тому самому venv.
    """
    beside = os.path.join(os.path.dirname(sys.executable), "piper")
    if os.path.isfile(beside) and os.access(beside, os.X_OK):
        return beside
    return shutil.which("piper")


class PiperTTS(TTSProvider):
    name = "piper"
    media_type = "audio/wav"

    def __init__(
        self,
        model_path: str,
        voice: Optional[str] = None,
        binary: Optional[str] = None,
        length_scale: Optional[float] = None,
        sentence_silence: Optional[float] = None,
        noise_scale: Optional[float] = None,
        noise_w_scale: Optional[float] = None,
        add_stress: bool = True,
        timeout: int = 120,
    ):
        self.binary = binary or _find_piper()
        if not self.binary:
            raise ProviderError(
                "Piper не встановлений (немає команди `piper`). Встановлення — "
                "разова дія, див. README → «Приємний голос»."
            )
        if not model_path or not os.path.isfile(model_path):
            raise ProviderError("Не знайдено файл моделі Piper: %s" % model_path)

        self.model_path = model_path
        self.config_path = model_path + ".json"
        # length_scale > 1 — повільніше. Це не «швидкість читання» рушія, а
        # параметр самої моделі, тому звучить природніше за пост-обробку.
        self.length_scale = length_scale
        # Пауза після кожного речення — робить сама модель. Це чистіше за
        # різання тексту на куски збоку: рушій знає, де межа речення, і
        # інтонація не скидається посеред фрази.
        self.sentence_silence = sentence_silence
        # Шум генератора VITS. Це не декор: за типових значень той самий текст
        # звучить по-різному від разу до разу — виміряно 0,94 с розкиду
        # тривалості на трьох реченнях. Нуль дає байт-у-байт однакове аудіо,
        # але й пласкішу інтонацію. Компроміс обирає людина, не код.
        self.noise_scale = noise_scale
        self.noise_w_scale = noise_w_scale
        self.timeout = timeout
        # Наголоси: модель навчена їх читати, тому за замовчуванням ставимо.
        self.add_stress = add_stress
        # Звіт про останню нормалізацію: що саме довелось перетворити.
        self.last_report = {}
        self._speakers = self._read_speakers()
        self.voice = voice
        if voice:
            self._require_known_voice(voice)

    # ── голоси моделі ────────────────────────────────────────────────────

    def _read_speakers(self) -> dict:
        """Мапа «ім'я → id» із конфігу моделі. Нічого не вигадуємо: якщо модель
        односпікерна, мапа порожня, і параметр голосу просто не застосовується."""
        if not os.path.isfile(self.config_path):
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                config = json.load(fh)
        except (OSError, ValueError):
            return {}
        mapping = config.get("speaker_id_map") or {}
        return {str(name): int(index) for name, index in mapping.items()}

    def _require_known_voice(self, name: str) -> None:
        if not self._speakers:
            raise ProviderError(
                "Модель %s односпікерна — голос '%s' їй задати нельзя."
                % (os.path.basename(self.model_path), name)
            )
        if name not in self._speakers:
            raise ProviderError(
                "Голос '%s' у моделі відсутній. Доступні: %s."
                % (name, ", ".join(sorted(self._speakers)))
            )

    def voices(self) -> List[dict]:
        model = os.path.basename(self.model_path)
        if not self._speakers:
            return [{"name": model, "locale": "", "id": 0}]
        return [
            {"name": name, "locale": self._locale(), "id": index}
            for name, index in sorted(self._speakers.items(), key=lambda pair: pair[1])
        ]

    def _locale(self) -> str:
        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                config = json.load(fh)
            return (config.get("language") or {}).get("code", "")
        except (OSError, ValueError):
            return ""

    # ── синтез ───────────────────────────────────────────────────────────

    def build_command(self, output_path: str, voice: Optional[str] = None) -> List[str]:
        """Команда для piper. Винесено окремо, щоб її перевіряв тест.

        Модель нестабільна (див. noise_scale), тому перевіряти передачу
        параметрів через довжину аудіо неможливо — розкид тривалості перекриває
        будь-який ефект. Перевіряємо те, що справді контролюємо: сам виклик.
        """
        command = [self.binary, "--model", self.model_path, "--output_file", output_path]
        if voice and self._speakers:
            command += ["--speaker", str(self._speakers[voice])]
        if self.length_scale:
            command += ["--length_scale", str(self.length_scale)]
        if self.sentence_silence is not None:
            command += ["--sentence_silence", str(self.sentence_silence)]
        if self.noise_scale is not None:
            command += ["--noise_scale", str(self.noise_scale)]
        if self.noise_w_scale is not None:
            command += ["--noise_w_scale", str(self.noise_w_scale)]
        return command

    def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        # Модель символьна: цифри, латиниця й великі літери в її алфавіті
        # відсутні і зникають БЕЗ помилки. Нормалізація тут обовʼязкова, а не
        # опційна — інакше респондент чує «Це було у році» замість «у 2019 році».
        clean, self.last_report = normalize(text, add_stress=self.add_stress)
        if not clean:
            return b""

        chosen = voice or self.voice
        if chosen:
            self._require_known_voice(chosen)

        handle, path = tempfile.mkstemp(suffix=".wav")
        os.close(handle)
        try:
            command = self.build_command(path, chosen)
            try:
                result = subprocess.run(
                    command,
                    input=clean.encode("utf-8"),
                    capture_output=True,
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired:
                raise ProviderError("Piper не відповів за %d секунд" % self.timeout)

            if result.returncode != 0:
                raise ProviderError(
                    "Piper завершився з помилкою: %s"
                    % (result.stderr or b"").decode("utf-8", "replace")[:300]
                )
            if not os.path.exists(path) or os.path.getsize(path) == 0:
                raise ProviderError("Piper не створив аудіо (порожній файл)")

            with open(path, "rb") as fh:
                return fh.read()
        finally:
            if os.path.exists(path):
                os.remove(path)
