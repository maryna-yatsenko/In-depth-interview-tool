"""TTS через системний `say` (macOS).

Навіщо він, якщо голос той самий, що в браузері: він **перевіряє весь серверний
шлях озвучення** — синтез на сервері, передача аудіо, відтворення в браузері —
за нуль грошей і без жодного акаунта. Коли з'явиться платний провайдер, зміниться
один файл, а не архітектура.

Якості це не додає: `say` бере ті самі системні голоси. Додає воно готовий
конвеєр.
"""

import os
import shutil
import subprocess
import tempfile
from typing import List, Optional

from .base import ProviderError, TTSProvider


class SayTTS(TTSProvider):
    name = "say"
    media_type = "audio/wav"

    def __init__(self, voice: Optional[str] = None, rate_wpm: Optional[int] = None):
        self.binary = shutil.which("say")
        if not self.binary:
            raise ProviderError("Команди `say` немає — цей провайдер тільки для macOS")
        self.voice = voice or None
        # `say` міряє швидкість у словах на хвилину, а не множником. Типова
        # мова — близько 175; трохи повільніше звучить спокійніше.
        self.rate_wpm = rate_wpm or 170

    def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        clean = (text or "").strip()
        if not clean:
            return b""

        chosen = voice or self.voice
        if chosen:
            self._require_known_voice(chosen)

        handle, path = tempfile.mkstemp(suffix=".wav")
        os.close(handle)
        try:
            command = [self.binary, "-o", path, "--file-format=WAVE",
                       "--data-format=LEI16@22050", "-r", str(self.rate_wpm)]
            if chosen:
                command += ["-v", chosen]
            # Текст передаємо аргументом після «--», щоб репліка, яка починається
            # з дефіса, не була прочитана як прапорець.
            command += ["--", clean]
            try:
                subprocess.run(command, check=True, capture_output=True, timeout=60)
            except subprocess.CalledProcessError as exc:
                raise ProviderError(
                    "`say` не зміг озвучити: %s" % (exc.stderr or b"").decode("utf-8", "replace")
                )
            except subprocess.TimeoutExpired:
                raise ProviderError("`say` не відповів за 60 секунд")

            with open(path, "rb") as fh:
                return fh.read()
        finally:
            if os.path.exists(path):
                os.remove(path)

    def _require_known_voice(self, name: str) -> None:
        """`say` при невідомому імені голосу НЕ падає, а тихо бере типовий.

        Це найгірший вид збою: дослідник обрав голос, отримав інший і не
        дізнався про це. Тому перевіряємо ім'я самі й падаємо гучно.

        Окремо варто знати: імена голосів у `say` і в браузері **різні** для того
        самого голосу — `say` знає «Lesya», браузер показує «Леся». Це різні рушії,
        тому ім'я голосу належить провайдеру, а не простору взагалі.
        """
        known = [item["name"] for item in self.voices()]
        if not known:
            return  # список не дістався — не блокуємо синтез через це
        if name not in known:
            matches = [n for n in known if n.lower().startswith(name.lower()[:3])]
            hint = (" Схоже на: %s." % ", ".join(matches[:5])) if matches else ""
            raise ProviderError(
                "Голос '%s' системі невідомий, а `say` у такому разі тихо бере типовий."
                "%s Доступні імена — у панелі дослідника." % (name, hint)
            )

    def voices(self) -> List[dict]:
        """Реальні системні голоси: [{"name": "Lesya", "locale": "uk_UA"}, …]."""
        try:
            out = subprocess.run([self.binary, "-v", "?"], capture_output=True,
                                 timeout=15, check=True).stdout
        except (subprocess.SubprocessError, OSError):
            return []
        items = []
        for line in out.decode("utf-8", "replace").splitlines():
            # Формат рядка: "Lesya               uk_UA    # Привіт! Мене звуть Леся."
            head = line.split("#")[0].strip()
            if not head:
                continue
            bits = head.rsplit(None, 1)
            if len(bits) != 2:
                continue
            name, locale = bits[0].strip(), bits[1].strip()
            if name and locale:
                items.append({"name": name, "locale": locale})
        return items
