"""TTS через Azure Speech (REST).

⚠️ **Не перевірено на живому акаунті.** Форма запиту взята з документації
Microsoft (endpoint, заголовки, SSML); ключа для перевірки не було. Перед першим
справжнім інтервʼю прогнати `voices()` — якщо список приїхав, значить доступ і
формат правильні.

Свідомо **не хардкодимо назв голосів**. Реальні імена (для української це
жіночий і чоловічий нейронні голоси) віддає сам сервіс через `voices()` — той
самий принцип, що й у браузерному списку: показуємо те, що є, а не те, що ми
пам'ятаємо.
"""

import json
import urllib.error
import urllib.request
from typing import List, Optional
from xml.sax.saxutils import escape

from .base import ProviderError, TTSProvider

# Підтверджено документацією: WAV, який грає будь-який браузер без конвертації.
DEFAULT_FORMAT = "riff-24khz-16bit-mono-pcm"


class AzureTTS(TTSProvider):
    name = "azure"
    media_type = "audio/wav"

    def __init__(
        self,
        api_key: str,
        region: str,
        voice: Optional[str] = None,
        lang: str = "uk-UA",
        output_format: str = DEFAULT_FORMAT,
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
        timeout: int = 30,
    ):
        if not api_key:
            raise ProviderError("Azure TTS: немає ключа (AZURE_SPEECH_KEY)")
        if not region:
            raise ProviderError("Azure TTS: не вказаний регіон ресурсу")
        self.api_key = api_key
        self.region = region
        self.voice = voice
        self.lang = lang
        self.output_format = output_format
        self.rate = rate
        self.pitch = pitch
        self.timeout = timeout

    # ── ендпоінти ────────────────────────────────────────────────────────

    def _base(self) -> str:
        return "https://%s.tts.speech.microsoft.com/cognitiveservices" % self.region

    def _headers(self) -> dict:
        return {"Ocp-Apim-Subscription-Key": self.api_key}

    # ── синтез ───────────────────────────────────────────────────────────

    def _ssml(self, text: str, voice: str) -> bytes:
        # Екранування обовʼязкове: символ «&» або «<» у репліці інакше зламає
        # весь запит, і це виявиться посеред інтервʼю.
        body = escape(text)
        if self.rate or self.pitch:
            attrs = []
            if self.rate:
                attrs.append('rate="%s"' % escape(self.rate, {'"': "&quot;"}))
            if self.pitch:
                attrs.append('pitch="%s"' % escape(self.pitch, {'"': "&quot;"}))
            body = "<prosody %s>%s</prosody>" % (" ".join(attrs), body)
        ssml = (
            "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='%s'>"
            "<voice name='%s'>%s</voice></speak>"
        ) % (escape(self.lang), escape(voice), body)
        return ssml.encode("utf-8")

    def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        clean = (text or "").strip()
        if not clean:
            return b""
        chosen = voice or self.voice
        if not chosen:
            raise ProviderError(
                "Azure TTS: не вказано голос. Візьми ім'я зі списку `voices()` — "
                "вгадувати назви не варто, вони змінюються між регіонами й тарифами."
            )

        headers = self._headers()
        headers["Content-Type"] = "application/ssml+xml"
        headers["X-Microsoft-OutputFormat"] = self.output_format
        headers["User-Agent"] = "InterviewTool"

        request = urllib.request.Request(
            self._base() + "/v1", data=self._ssml(clean, chosen), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            if exc.code == 401:
                raise ProviderError("Azure TTS: ключ або регіон неправильні (401). %s" % detail)
            if exc.code == 400:
                raise ProviderError(
                    "Azure TTS: сервіс відхилив запит (400) — найчастіше це "
                    "невідома назва голосу. %s" % detail
                )
            if exc.code == 429:
                raise ProviderError("Azure TTS: перевищено ліміт запитів (429). %s" % detail)
            raise ProviderError("Azure TTS: HTTP %d. %s" % (exc.code, detail))
        except urllib.error.URLError as exc:
            raise ProviderError("Azure TTS: немає зв'язку — %s" % exc.reason)

    # ── список голосів ───────────────────────────────────────────────────

    def voices(self, lang_prefix: Optional[str] = None) -> List[dict]:
        """Реальний перелік від сервісу. Це ж і перевірка доступу."""
        request = urllib.request.Request(
            self._base() + "/voices/list", headers=self._headers(), method="GET"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ProviderError("Azure TTS: не вдалося отримати список голосів (HTTP %d)" % exc.code)
        except (urllib.error.URLError, ValueError) as exc:
            raise ProviderError("Azure TTS: не вдалося отримати список голосів — %s" % exc)

        prefix = (lang_prefix or "").lower()
        items = []
        for item in data:
            locale = item.get("Locale") or ""
            if prefix and not locale.lower().startswith(prefix):
                continue
            items.append({
                "name": item.get("ShortName") or item.get("Name"),
                "locale": locale,
                # Стать тут приходить від сервісу — це не наша догадка.
                "gender": item.get("Gender"),
                "display": item.get("LocalName") or item.get("DisplayName"),
            })
        return items
