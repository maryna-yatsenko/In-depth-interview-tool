"""TTS через Piper — локальна нейронна модель.

Навіщо він тут головний: системний голос macOS («Леся») — старий синтез, і
жодне крутіння швидкості чи паузи його не виправить. Проблема в моделі, а не в
обгортці. Piper — це VITS-модель, яка працює на CPU офлайн, безкоштовно й без
акаунта, і українська модель `uk_UA-ukrainian_tts-medium` має три голоси
(`lada`, `mykyta`, `tetiana` — тобто є і чоловічий).

Побічна властивість, важлива для корпоративного контура: **нічого не покидає
машину.** Ні тексту питань, ні голосу. Порівняй із браузерним розпізнаванням
(TD-6), яке відправляє аудіо респондента вендору браузера.

Синтез — через Python API пакета `piper` (`PiperVoice`/`SynthesisConfig`), не
через окремий бінарник `piper` командного рядка. Так було раніше (subprocess +
пошук бінарника поруч з інтерпретатором чи в PATH) — і саме це впало на
Vercel: `pip install` кладе пакет, але не гарантує, що консольний скрипт
опиниться там, де його шукає `shutil.which`/сусідство з `sys.executable` в
серверлес-рантаймі. Прямий виклик Python-класу цієї проблеми не має в
принципі — це той самий процес, а не окремий, якого треба ще знайти.

Модель береться з локального файла; звідки він узявся — справа встановлення,
а не коду. Шлях і голос задаються в конфізі простору.
"""

import io
import json
import os
import wave
from typing import List, Optional

from .base import ProviderError, TTSProvider
from .tts_text import normalize

try:
    from piper import PiperVoice, SynthesisConfig
except ImportError:
    PiperVoice = None
    SynthesisConfig = None


class PiperTTS(TTSProvider):
    name = "piper"
    media_type = "audio/wav"

    def __init__(
        self,
        model_path: str,
        voice: Optional[str] = None,
        length_scale: Optional[float] = None,
        sentence_silence: Optional[float] = None,
        noise_scale: Optional[float] = None,
        noise_w_scale: Optional[float] = None,
        add_stress: bool = True,
    ):
        if PiperVoice is None:
            raise ProviderError(
                "Пакет `piper` не встановлений. Встановлення — разова дія, "
                "див. README → «Приємний голос»."
            )
        if not model_path or not os.path.isfile(model_path):
            raise ProviderError("Не знайдено файл моделі Piper: %s" % model_path)

        self.model_path = model_path
        self.config_path = model_path + ".json"
        self._voice = PiperVoice.load(model_path, config_path=self.config_path)
        # length_scale > 1 — повільніше. Це не «швидкість читання» рушія, а
        # параметр самої моделі, тому звучить природніше за пост-обробку.
        self.length_scale = length_scale
        # Пауза між реченнями — рушій моделі її не знає (одна модель = одна
        # цілісна фраза), тому вставляємо тишу самі, між шматками по реченнях.
        self.sentence_silence = sentence_silence
        # Шум генератора VITS. Це не декор: за типових значень той самий текст
        # звучить по-різному від разу до разу — виміряно 0,94 с розкиду
        # тривалості на трьох реченнях. Нуль дає байт-у-байт однакове аудіо,
        # але й пласкішу інтонацію. Компроміс обирає людина, не код.
        self.noise_scale = noise_scale
        self.noise_w_scale = noise_w_scale
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
        """Мапа «ім'я → id» із конфігу моделі, який уже завантажив PiperVoice —
        нічого не вигадуємо: якщо модель односпікерна, мапа порожня."""
        mapping = getattr(self._voice.config, "speaker_id_map", None) or {}
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
        # `PiperConfig` (розібраний PiperVoice.load) не носить це поле — воно
        # лише в сирому JSON моделі, тому читаємо файл конфігу напряму.
        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                raw_config = json.load(fh)
        except (OSError, ValueError):
            return ""
        return (raw_config.get("language") or {}).get("code", "")

    # ── синтез ───────────────────────────────────────────────────────────

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

        syn_config = SynthesisConfig(
            speaker_id=self._speakers.get(chosen) if chosen else None,
            length_scale=self.length_scale,
            noise_scale=self.noise_scale,
            noise_w_scale=self.noise_w_scale,
        )

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            first_chunk = True
            silence_frames = b""
            for chunk in self._voice.synthesize(clean, syn_config=syn_config):
                if first_chunk:
                    wav_file.setframerate(chunk.sample_rate)
                    wav_file.setsampwidth(chunk.sample_width)
                    wav_file.setnchannels(chunk.sample_channels)
                    if self.sentence_silence:
                        n_samples = int(chunk.sample_rate * self.sentence_silence)
                        silence_frames = b"\x00\x00" * n_samples
                    first_chunk = False
                elif silence_frames:
                    wav_file.writeframes(silence_frames)
                wav_file.writeframes(chunk.audio_int16_bytes)

        if first_chunk:
            # Жодного шматка не прийшло (наприклад, після нормалізації лишились
            # самі символи поза алфавітом моделі) — порожнє аудіо, не помилка.
            return b""
        return buf.getvalue()
