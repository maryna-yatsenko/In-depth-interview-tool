"""HTTP-шар: віддає сторінку респондента і проводить інтервʼю по кроках.

Стандартна бібліотека, без фреймворку: ендпоінтів небагато, а зайва залежність у
внутрішньому інструменті — це те, що через рік ніхто не оновить.

Правило з architecture.md: цей шар не містить логіки інтервʼю. Він приймає
відповідь, віддає її в ядро і повертає наступну репліку.
"""

import json
import os
import posixpath
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from ..config.phrases import PhraseError, load_bank
from ..config import space as space_module
from ..config.space import ConfigError, Guide, SpaceConfig, load_space
from ..interview.session import Session
from ..providers.base import ProviderError
from ..providers.registry import build_llm, build_tts
from ..storage import local as store_files
from ..storage import voice as voice_files
from . import admin as admin_api

WEB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "web"
)

# Фраза для прослуховування голосу в панелі. Свідомо стала: див. _admin_preview.
PREVIEW_TEXT = ("Розкажіть, будь ласка, про останній конкретний випадок, "
                "коли це сталося. Що ви зробили далі?")

# Формати, у яких браузери віддають запис із мікрофона.
_AUDIO_MIME = {
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".mp4": "audio/mp4",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
}

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


class TtsHolder:
    """Обгортка над провайдером озвучення, щоб його можна було замінити наживо.

    Провайдер збирається зі збереженого конфігу простору. Коли дослідник
    перемикає провайдера в панелі, сервер перезбирає його тут — інакше
    доводилось би перезапускати сервер, а це рве live-сесії респондентів.
    """

    def __init__(self, provider=None):
        self.current = provider
        self._lock = threading.Lock()

    def swap(self, provider):
        with self._lock:
            old = self.current
            self.current = provider
        # Довгоживучий процес попереднього провайдера треба зупинити, інакше
        # він тримає модель у памʼяті до кінця життя сервера.
        if old is not None and hasattr(old, "stop") and old is not provider:
            try:
                old.stop()
            except Exception:
                pass


class SessionStore:
    """Живі сесії: памʼять як кеш, файл як істина.

    Раніше стан жив тільки в памʼяті процесу, і перезапуск сервера губив
    розмову на 12-й хвилині (TD-5). Тепер після кожної репліки стан пишеться на
    диск, а `get` умів відновити сесію, якої в памʼяті вже немає.
    """

    def __init__(self, space: SpaceConfig, guide: Guide, llm_cfg: Dict[str, Any],
                 bank_provider=None):
        self._items = {}  # type: Dict[str, Session]
        self._lock = threading.Lock()
        self._space = space
        self._guide = guide
        self._llm_cfg = llm_cfg
        # ОДНА модель на процес, спільна для всіх сесій.
        #
        # Раніше `build_llm` викликався на кожен старт і кожне відновлення — а
        # для локальної моделі це означало ще 3,2 ГБ у памʼяті. Кілька сесій, і
        # 16 ГБ закінчувались: процес убивала система, сторінка отримувала
        # «Failed to fetch» посеред інтервʼю. Спостережено двічі за один день.
        self._llm = None
        # Банк читається на кожну сесію: дослідник може дозаписати репліку, і
        # наступний респондент мусить її почути без перезапуску сервера.
        self._bank_provider = bank_provider

    def _bank(self):
        if self._space.repertoire != "bank" or self._bank_provider is None:
            return None
        return self._bank_provider()

    def _llm_shared(self):
        """Ліниво й один раз. Провайдер сам відповідає за одночасні запити
        (`MlxLLM` тримає замок на генерації)."""
        with self._lock:
            if self._llm is None:
                self._llm = build_llm(self._llm_cfg)
            return self._llm

    def new(self) -> Session:
        session = Session(self._space, self._guide, self._llm_shared(),
                          bank=self._bank())
        with self._lock:
            self._items[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session:
        with self._lock:
            if session_id in self._items:
                return self._items[session_id]

        try:
            data = store_files.load_live(session_id)
        except ValueError:
            raise KeyError(session_id)
        if not data:
            raise KeyError(session_id)

        session = Session.from_dict(self._space, self._guide, self._llm_shared(), data)
        session.bank = self._bank()
        with self._lock:
            self._items[session.session_id] = session
        return session

    def persist(self, session: Session) -> None:
        store_files.save_live(session.to_dict())

    def finish(self, session: Session) -> Optional[str]:
        """Завершений транскрипт — у сховище, живий стан — прибрати."""
        path = None
        try:
            path = store_files.save_session(session.to_dict())
        except FileExistsError:
            path = None
        store_files.drop_live(session.session_id)
        with self._lock:
            self._items.pop(session.session_id, None)
        return path


def _preview_audio(tts, data: Dict[str, Any]) -> bytes:
    """Синтез фрази для прослуховування, з тимчасовими налаштуваннями.

    Провайдер не пересобирається: підмінюємо поля на час одного виклику і
    повертаємо як було. Інакше превʼю могло б тихо змінити налаштування живого
    інтервʼю, яке зараз іде в іншій вкладці.
    """
    voice = data.get("voice") or None
    tunable = ("length_scale", "sentence_silence", "noise_scale", "noise_w_scale", "add_stress")
    saved = {}
    try:
        for field in tunable:
            if field in data and hasattr(tts, field):
                saved[field] = getattr(tts, field)
                value = data[field]
                if value in ("", None):
                    setattr(tts, field, None if field != "add_stress" else False)
                else:
                    setattr(tts, field, bool(value) if field == "add_stress" else float(value))
        return tts.synthesize(PREVIEW_TEXT, voice=voice)
    finally:
        for field, value in saved.items():
            setattr(tts, field, value)


def make_handler(
    space: SpaceConfig,
    guide: Guide,
    llm_cfg: Dict[str, Any],
    store: SessionStore,
    admin_root: Optional[str] = None,
    tts=None,
    bank_provider=None,
):
    """`admin_root` = None означає, що адмінки в цьому запуску немає взагалі
    (не «є, але закрита»). Див. app/api/admin.py про причину."""
    class Handler(BaseHTTPRequestHandler):
        server_version = "InterviewTool"

        def log_message(self, fmt, *args):
            # Технічний лог без вмісту реплік — правило з architecture.md.
            print("[web] %s" % (fmt % args))

        # ── видача ───────────────────────────────────────────────────────
        def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, rel_path: str) -> None:
            # Захист від виходу за межі web/: шлях нормалізуємо і перевіряємо.
            safe = posixpath.normpath("/" + rel_path).lstrip("/")
            full = os.path.join(WEB_DIR, safe)
            if not os.path.abspath(full).startswith(os.path.abspath(WEB_DIR)) or not os.path.isfile(full):
                self._send_json({"error": "not found"}, 404)
                return
            with open(full, "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", _MIME.get(os.path.splitext(full)[1], "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return {}

        # ── маршрути ─────────────────────────────────────────────────────
        # ── адмінка ──────────────────────────────────────────────────────
        def _try_admin(self, method: str, path: str, payload: Dict[str, Any]) -> bool:
            if not path.startswith("/api/admin"):
                return False
            if not admin_root:
                self._send_json({"error": "адмінка вимкнена (запусти з --admin)"}, 404)
                return True
            parsed = urllib.parse.urlparse(self.path)
            query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            try:
                status, body = admin_api.handle(method, path, query, payload, admin_root)
            except admin_api.AdminError as exc:
                self._send_json({"error": str(exc)}, exc.status)
            except (OSError, ValueError) as exc:
                self._send_json({"error": str(exc)}, 400)
            else:
                self._send_json(body, status)
            return True

        def _reload_tts(self):
            """Перезібрати провайдера озвучення зі збереженого конфігу простору."""
            if not admin_root:
                self._send_json({"error": "адмінка вимкнена"}, 404)
                return
            try:
                fresh_space = load_space(os.path.join(admin_root, space.key, "space.json"))
            except (ConfigError, OSError) as exc:
                self._send_json({"error": "конфіг простору: %s" % exc}, 400)
                return
            try:
                provider = build_tts(dict(fresh_space.providers.get("tts", {}) or {}))
            except ProviderError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            tts.swap(provider)
            # Оновлюємо й сам простір, щоб озвучення й правила каналу не розійшлись.
            space.providers = fresh_space.providers
            self._send_json({
                "provider": provider.name if provider else "browser",
                "voices": provider.voices() if provider else [],
            })

        def _send_phrase_audio(self, phrase_id: str):
            """Аудіо шукається за id репліки, а не за іменем файла.

            Так у шлях не потрапляє нічого з запиту: ім'я файла беремо з банку,
            а не від клієнта.
            """
            try:
                bank = bank_provider()
            except PhraseError as exc:
                self._send_json({"error": str(exc)}, 500)
                return
            phrase = bank.by_id((phrase_id or "").strip())
            if phrase is None or not phrase.recorded:
                self._send_json({"error": "запису немає"}, 404)
                return
            full = bank.audio_path(phrase)
            if not full or not os.path.isfile(full):
                self._send_json({"error": "файл запису відсутній"}, 404)
                return
            with open(full, "rb") as fh:
                data = fh.read()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                _AUDIO_MIME.get(os.path.splitext(full)[1].lower(), "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path.startswith("/audio/"):
                self._send_phrase_audio(path[len("/audio/"):])
                return
            if path.startswith("/voice/"):
                self._send_voice(path[len("/voice/"):])
                return
            if path == "/api/tts/voices":
                # Реальні голоси провайдера — щоб панель показувала те, що є.
                if tts.current is None:
                    self._send_json({"provider": "browser", "items": []})
                    return
                try:
                    self._send_json({"provider": tts.current.name, "items": tts.current.voices()})
                except ProviderError as exc:
                    self._send_json(
                        {"provider": tts.current.name, "items": [], "error": str(exc)}, 200)
                return
            if self._try_admin("GET", path, {}):
                return
            if path == "/admin":
                if not admin_root:
                    self._send_json({"error": "адмінка вимкнена (запусти з --admin)"}, 404)
                    return
                self._send_file("admin.html")
            elif path in ("/", "/index.html"):
                self._send_file("index.html")
            elif path == "/api/space":
                self._send_json(self._space_payload())
            elif path == "/api/sessions":
                self._send_json({"items": store_files.list_sessions()})
            else:
                self._send_file(path.lstrip("/"))

        def _speak(self, data: Dict[str, Any]):
            """Озвучення на сервері.

            ⚠️ Свідомо БЕЗ параметра тексту. Озвучується лише останнє питання
            цієї ж сесії. Якби текст приймався з запиту, ендпоінт став би
            безкоштовним TTS-проксі для будь-кого, хто його знайшов — а платить
            за символи власник ключа.
            """
            if tts.current is None:
                self._send_json({"error": "серверне озвучення не налаштоване"}, 404)
                return
            try:
                session = store.get(data.get("session_id") or "")
            except (KeyError, ValueError):
                self._send_json({"error": "сесію не знайдено"}, 404)
                return

            text = next(
                (turn["text"] for turn in reversed(session.turns) if turn["role"] == "interviewer"),
                "",
            )
            if not text:
                self._send_json({"error": "нема чого озвучувати"}, 409)
                return

            try:
                audio = tts.current.synthesize(text)
            except ProviderError as exc:
                # Не змогли озвучити — не привід валити інтервʼю: клієнт
                # покаже питання текстом.
                self._send_json({"error": str(exc), "fallback": "text"}, 503)
                return

            self.send_response(200)
            self.send_header("Content-Type", getattr(tts, "media_type", "audio/wav"))
            self.send_header("Content-Length", str(len(audio)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(audio)

        def _admin_preview(self, data: Dict[str, Any]):
            """Прослуховування голосу в панелі.

            Текст **фіксований** і заданий у коді. Голос обирається, текст — ні:
            інакше це знову безкоштовний синтез чого завгодно, тільки тепер за
            адресою адмінки.
            """
            if not admin_root:
                self._send_json({"error": "адмінка вимкнена"}, 404)
                return
            if tts is None:
                self._send_json({"error": "серверне озвучення не налаштоване"}, 404)
                return
            # Налаштування звучання приймаємо — щоб дослідник чув те, що
            # накрутив, ще до збереження. Текст лишається фіксованим: саме він,
            # а не параметри, був би тут дірою для безкоштовного синтезу.
            try:
                audio = _preview_audio(tts.current, data)
            except ProviderError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            self.send_response(200)
            self.send_header("Content-Type", getattr(tts.current, "media_type", "audio/wav"))
            self.send_header("Content-Length", str(len(audio)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(audio)

        def do_POST(self):
            path = self.path.split("?")[0]
            if path == "/api/voice":
                # Так само бінарне тіло: _read_json спожив би аудіо й розібрав
                # його як зламаний JSON.
                self._upload_voice()
                return
            payload = self._read_json()
            if path == "/api/admin/tts/preview":
                self._admin_preview(payload)
                return
            if path == "/api/admin/tts/reload":
                self._reload_tts()
                return
            if self._try_admin("POST", path, payload):
                return
            if path == "/api/start":
                self._start(payload)
            elif path == "/api/resume":
                self._resume(payload)
            elif path == "/api/answer":
                self._answer(payload)
            elif path == "/api/draft":
                self._draft(payload)
            elif path == "/api/step":
                self._step(payload)
            elif path == "/api/finish":
                self._finish(payload)
            elif path == "/api/history":
                self._history(payload)
            elif path == "/api/append":
                self._append(payload)
            elif path == "/api/speak":
                self._speak(payload)
            else:
                self._send_json({"error": "not found"}, 404)

        # ── обробники ────────────────────────────────────────────────────
        def _space_payload(self) -> Dict[str, Any]:
            """Те, що клієнту треба знати. Ключів провайдерів тут немає й бути не може."""
            return {
                "key": "%s/%s" % (space.key, guide.key),
                "title": space.branding.get("page_title") or space.title,
                "accent": space.branding.get("accent", "#3a3a3a"),
                "consent_text": space.privacy.consent_text,
                "languages": space.languages,
                "voice": {
                    "stt": (space.providers.get("stt") or {}).get("provider", "none"),
                    "tts": (space.providers.get("tts") or {}).get("provider", "none"),
                },
                "interface": {
                    "mode": space.interface.get("mode", "text"),
                    # Голос на вимогу — типова поведінка: питання первинно текстом.
                    "autoplay": bool(space.interface.get("autoplay", False)),
                    # Очікуваний обсяг відповіді. Це підказка, не поріг:
                    # коротка відповідь валідна, інтервʼюер попросить розкрити.
                    "expected_words": int(space.interface.get("expected_words", 15)),
                    # Чи взагалі пропонувати запис голосу. Сама згода — окреме
                    # рішення респондента на екрані згоди.
                    "record_voice": bool(space.interface.get("record_voice", False)),
                    # Нижче цього не зараховуємо нічого. Клієнт мусить це знати,
                    # щоб сказати людині, чому нічого не зарахувалось, а не
                    # лишати її гадати.
                    "min_words_to_credit": space_module.MIN_WORDS_TO_CREDIT,
                },
                "repertoire": space.repertoire,
                # Тільки параметри звучання. Ключі провайдерів у клієнт не їдуть
                # ніколи — за це є тест (test_space_payload_has_no_secrets).
                "tts": {
                    k: v for k, v in (space.providers.get("tts") or {}).items()
                    if k in ("voice", "rate", "pitch", "gap")
                },
                "topics_total": len(guide.topics),
            }

        def _checklist(self, session: Session):
            try:
                return session.checklist()
            except Exception:
                return []

        def _all_covered(self, session: Session) -> bool:
            try:
                return session.all_expected_covered()
            except Exception:
                return False

        def _progress(self, session: Session) -> Dict[str, Any]:
            info = session.progress_info()
            # Старі поля лишаємо для сумісності зі збереженими сесіями.
            info["covered"] = len(session.covered_topics)
            info["total"] = len(guide.topics)
            return info

        def _audio_url(self, phrase_id: Optional[str]) -> Optional[str]:
            return ("/audio/%s" % phrase_id) if phrase_id else None

        def _bank_gaps(self) -> list:
            if space.repertoire != "bank":
                return []
            try:
                bank = bank_provider()
            except PhraseError as exc:
                return [str(exc)]
            return bank.missing_for_interview([t.id for t in guide.topics])

        def _start(self, data: Optional[Dict[str, Any]] = None):
            gaps = self._bank_gaps()
            if gaps:
                # Респондент не має дізнатись про це посеред розмови, тому
                # перевірка стоїть до старту й називає, чого саме не хватає.
                self._send_json({
                    "error": "Банк реплік неповний, інтервʼю не почнеться.",
                    "gaps": gaps,
                }, 409)
                return
            if space.draft:
                self._send_json({
                    "error": "Простір '%s' — чернетка: він ще не заповнений. "
                             "Заповни його в панелі дослідника і познач як готовий."
                             % space.key
                }, 409)
                return
            try:
                session = store.new()
            except ProviderError as exc:
                self._send_json({"error": str(exc)}, 503)
                return
            # Згода на запис голосу приходить із екрана згоди. Простір може
            # запис не пропонувати взагалі — тоді згоди немає й бути не може.
            session.voice_consent = bool(
                space.interface.get("record_voice", False)
                and (data or {}).get("record_voice"))
            utterance = session.start()
            store.persist(session)
            last = session.turns[-1]
            self._send_json({
                "session_id": session.session_id,
                "utterance": utterance,
                "audio_url": self._audio_url(last.get("phrase_id")),
                "source": "opening",
                "phase": session.phase_state.phase if session.plan else "",
                "checklist": self._checklist(session),
                "all_covered": self._all_covered(session),
                # Записи поточної відповіді: людина мусить мати змогу
                # переслухати їх навіть після перезавантаження сторінки.
                "voice": list(session.pending_voice),
                "done": False,
                "progress": self._progress(session),
                "voice_consent": session.voice_consent,
            })

        def _resume(self, data: Dict[str, Any]):
            """Повернення по тому самому посиланню — сценарій із edgecases.md."""
            try:
                session = store.get(data.get("session_id") or "")
            except (KeyError, ValueError):
                self._send_json({"error": "незавершеного інтервʼю не знайдено"}, 404)
                return
            except Exception as exc:  # розбіжність методології — теж не 500
                self._send_json({"error": str(exc)}, 409)
                return
            if session.done:
                self._send_json({"error": "інтервʼю вже завершено"}, 409)
                return

            last_turn = next(
                (t for t in reversed(session.turns) if t["role"] == "interviewer"), {})
            last = last_turn.get("text", "")
            answered = len([t for t in session.turns if t["role"] == "respondent"])
            self._send_json({
                "session_id": session.session_id,
                "utterance": last,
                "audio_url": self._audio_url(last_turn.get("phrase_id")),
                "source": last_turn.get("source", ""),
                "phase": session.phase_state.phase if session.plan else "",
                "checklist": self._checklist(session),
                "all_covered": self._all_covered(session),
                # Записи поточної відповіді: людина мусить мати змогу
                # переслухати їх навіть після перезавантаження сторінки.
                "voice": list(session.pending_voice),
                "answered": answered,
                "done": False,
                "progress": self._progress(session),
                # Згода живе в сесії: після перезавантаження сторінки запис
                # продовжується тільки якщо людина погодилась тоді.
                "voice_consent": session.voice_consent,
                # Раніше цього поля тут не було: після /api/resume курсор
                # відновлювався правильно (див. Session.from_dict), а текст
                # уже даної відповіді — ні, і людина бачила порожнє поле замість
                # свого. Той самий сенс, що й у /api/step.
                "said": session.answers_for_current(),
            })

        def _upload_voice(self):
            """Запис голосу респондента. Приходить одразу, як людина договорила.

            Одразу, а не разом із відповіддю, з двох причин: запис переживе
            закриту сторінку, і респондент може його переслухати з сервера, а не
            лише з памʼяті браузера. «Сказати заново» його видаляє.
            """
            parsed = urllib.parse.urlparse(self.path)
            query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            session_id = query.get("session_id", "")
            try:
                session = store.get(session_id)
            except (KeyError, ValueError):
                self._send_json({"error": "сесію не знайдено"}, 404)
                return
            # Дві умови, і обидві обовʼязкові: простір це дозволяє І людина
            # погодилась. Без другої запис голосу був би зроблений потай.
            if not space.interface.get("record_voice", False):
                self._send_json({"error": "запис голосу вимкнений у просторі"}, 403)
                return
            if not getattr(session, "voice_consent", False):
                self._send_json({"error": "респондент не дав згоди на запис"}, 403)
                return

            length = int(self.headers.get("Content-Length") or 0)
            if length > voice_files.MAX_CLIP_BYTES:
                # Не читаємо тіло взагалі: інакше завеликий запис усе одно
                # проїхав би через памʼять.
                self._send_json({"error": "запис завеликий"}, 413)
                return
            data = self.rfile.read(length) if length else b""
            try:
                name = voice_files.save_clip(
                    session_id, data, self.headers.get("Content-Type", ""))
            except voice_files.VoiceError as exc:
                self._send_json({"error": str(exc)}, exc.status)
                return
            except OSError as exc:
                self._send_json({"error": "не вдалося зберегти запис: %s" % exc}, 500)
                return

            session.pending_voice.append(name)
            store.persist(session)
            self._send_json({"clip": name, "url": "/voice/%s/%s" % (session.session_id, name),
                             "pending": list(session.pending_voice)})

        def _send_voice(self, rel: str):
            """Віддача запису — для дослідника в панелі й для переслухування."""
            parts = [p for p in rel.split("/") if p]
            if len(parts) != 2:
                self._send_json({"error": "not found"}, 404)
                return
            try:
                data = voice_files.read_clip(parts[0], parts[1])
            except voice_files.VoiceError as exc:
                self._send_json({"error": str(exc)}, exc.status)
                return
            ext = os.path.splitext(parts[1])[1].lower()
            mime = {".webm": "audio/webm", ".ogg": "audio/ogg", ".m4a": "audio/mp4",
                    ".mp3": "audio/mpeg", ".wav": "audio/wav"}.get(ext, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _draft(self, data: Dict[str, Any]):
            """Жива перевірка: людина ще говорить, а галочки вже ставляться.

            Транскрипт не чіпається — це чернетка. `reset` приходить, коли
            людина сказала заново: галочки мусять зникнути разом із текстом.
            """
            session_id = data.get("session_id") or ""
            try:
                session = store.get(session_id)
            except (KeyError, ValueError):
                self._send_json({"error": "сесію не знайдено"}, 404)
                return
            if session.done:
                self._send_json({"error": "інтервʼю вже завершено"}, 409)
                return

            if data.get("reset"):
                # Людина сказала «цього не було» — отже цього не має бути й на
                # диску. Позначки «скасовано» тут недостатньо: це її голос.
                if session.pending_voice:
                    voice_files.delete_clips(session.session_id, session.pending_voice)
                    session.pending_voice = []
                session.reset_draft()
                self._send_json({
                    "checklist": self._checklist(session),
                    "all_covered": self._all_covered(session),
                # Записи поточної відповіді: людина мусить мати змогу
                # переслухати їх навіть після перезавантаження сторінки.
                "voice": list(session.pending_voice),
                })
                return

            try:
                result = session.evaluate_draft(data.get("text") or "")
            except ProviderError as exc:
                # Живу перевірку можна не зробити: галочки просто зʼявляться
                # після надсилання. Обривати через це відповідь не будемо.
                self._send_json({"error": "модель недоступна: %s" % exc,
                                 "retryable": True}, 503)
                return
            # Записи поточної відповіді: щоб «Мій голос» працював і після
            # перезавантаження сторінки, коли blob-и в браузері вже зникли.
            result["voice"] = list(session.pending_voice)
            self._send_json(result)

        def _step(self, data: Dict[str, Any]):
            """Крок сценарієм: наступне або попереднє питання.

            Темп задає людина, а не модель. Раніше перехід залежав від того, чи
            «зарахувала» модель сказане, — а вона робила це з точністю 64-71 %.
            """
            try:
                session = store.get(data.get("session_id") or "")
            except (KeyError, ValueError):
                self._send_json({"error": "сесію не знайдено"}, 404)
                return
            if session.done:
                self._send_json({"error": "інтервʼю вже завершено"}, 409)
                return
            try:
                delta = int(data.get("delta", 1))
            except (TypeError, ValueError):
                delta = 1
            # Уперед — лише після відповіді: інакше людина проклацає інтервʼю,
            # і в даних лишиться порожньо. Назад — завжди.
            if delta > 0 and not session.answered_current():
                self._send_json({"error": "спершу відповідь на це питання"}, 409)
                return

            # Досягнення останнього питання більше НЕ завершує інтервʼю саме тут:
            # клієнт спершу показує підсумок (скільки відповіли, наскільки
            # розгорнуто) і дає повернутись доповнити щось. Завершує окрема дія
            # — POST /api/finish, після явного підтвердження людиною.
            session.go(delta)
            utterance = session.show_current()
            store.persist(session)
            self._send_json({
                "utterance": utterance,
                "audio_url": None,
                "source": (session.current_question() or {}).get("id", ""),
                "phase": session.phase_state.phase,
                "checklist": self._checklist(session),
                "done": False,
                "progress": self._progress(session),
                "voice": list(session.pending_voice),
                # Текст, який людина вже сказала на це питання: повернувшись
                # назад, вона мусить бачити свою відповідь, а не порожнє поле.
                "said": session.answers_for_current(),
            })

        def _finish(self, data: Dict[str, Any]):
            """Явне завершення. Окрема дія від кроку сценарієм.

            Раніше клік «наступне» на останньому питанні одразу завершував
            розмову. Тепер між останньою відповіддю й фактичним фіналом стоїть
            екран підсумку (людина бачить, скільки відповіла і як розгорнуто, і
            може повернутись щось дописати) — фінал стається лише тут.
            """
            try:
                session = store.get(data.get("session_id") or "")
            except (KeyError, ValueError):
                self._send_json({"error": "сесію не знайдено"}, 404)
                return
            if session.done:
                self._send_json({"error": "інтервʼю вже завершено"}, 409)
                return
            depth = session.answer_depth_stats()
            utterance = session.finish()
            payload = {"utterance": utterance, "done": True, "depth": depth}
            saved = store.finish(session)
            if saved:
                payload["saved_to"] = saved
            self._send_json(payload)

        def _history(self, data: Dict[str, Any]):
            """Що вже питали й що людина відповіла — щоб можна було повернутись."""
            try:
                session = store.get(data.get("session_id") or "")
            except (KeyError, ValueError):
                self._send_json({"error": "сесію не знайдено"}, 404)
                return
            self._send_json({"items": session.history()})

        def _append(self, data: Dict[str, Any]):
            """Доповнення до питання, на яке вже відповідали.

            Сценарій не рухається: людина повернулась додати деталь. Транскрипт
            лишається тільки на дописування — попередня репліка не переписується.
            """
            try:
                session = store.get(data.get("session_id") or "")
            except (KeyError, ValueError):
                self._send_json({"error": "сесію не знайдено"}, 404)
                return
            if session.done:
                self._send_json({"error": "інтервʼю вже завершено"}, 409)
                return
            try:
                index = int(data.get("index", -1))
            except (TypeError, ValueError):
                self._send_json({"error": "невірний номер питання"}, 400)
                return
            voice = data.get("voice")
            voice = [str(v) for v in voice] if isinstance(voice, list) else None
            try:
                session.append_to_answer(index, data.get("text") or "", voice=voice)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            except ProviderError as exc:
                self._send_json({"error": "модель недоступна: %s" % exc,
                                 "retryable": True}, 503)
                return
            store.persist(session)
            self._send_json({
                "items": session.history(),
                # Чекліст ПОТОЧНОГО питання: доповнення могло закрити пункт,
                # і людина мусить це побачити одразу.
                "checklist": self._checklist(session),
                "all_covered": self._all_covered(session),
                "progress": self._progress(session),
            })

        def _answer(self, data: Dict[str, Any]):
            session_id = data.get("session_id") or ""
            text = (data.get("text") or "").strip()
            if not text:
                self._send_json({"error": "порожня відповідь"}, 400)
                return
            try:
                session = store.get(session_id)
            except (KeyError, ValueError):
                self._send_json({"error": "сесію не знайдено"}, 404)
                return
            if session.done:
                self._send_json({"error": "інтервʼю вже завершено"}, 409)
                return

            try:
                turn = session.answer(
                    text, finish_narrative=bool(data.get("finish_narrative")))
            except ProviderError as exc:
                # Деградація, а не обрив: респондент, який дійшов до 12-ї хвилини,
                # не має втратити все (architecture.md → Правила взаємодії).
                # Стан на диску лишається таким, як до цієї репліки, — можна повторити.
                self._send_json({"error": "модель недоступна: %s" % exc, "retryable": True}, 503)
                return

            if turn.action == "recorded":
                # Сценарієм веде людина: відповідь записана, наступний крок —
                # її кнопка. Питання тут не змінюється.
                store.persist(session)
                self._send_json({
                    "recorded": True,
                    "checklist": self._checklist(session),
                    "progress": self._progress(session),
                    "voice": list(session.pending_voice),
                    "said": session.answers_for_current(),
                    "done": False,
                })
                return

            payload = {
                "utterance": turn.utterance,
                # Тримання розповіді: інтервʼюер нічого не сказав. Клієнт лишає
                # питання на місці й запрошує продовжувати.
                "hold": turn.action == "hold",
                "audio_url": self._audio_url(turn.phrase_id),
                # Звідки репліка: клієнт мусить показувати тримання розповіді
                # («Ага», «І що далі?») інакше, ніж питання — у реальній розмові
                # це бурмотіння, поки людина продовжує говорити.
                "source": turn.source or "",
                "phase": session.phase_state.phase if session.plan else "",
                "checklist": self._checklist(session),
                "all_covered": self._all_covered(session),
                # Записи поточної відповіді: людина мусить мати змогу
                # переслухати їх навіть після перезавантаження сторінки.
                "voice": list(session.pending_voice),
                "done": session.done,
                "progress": self._progress(session),
            }
            if session.done:
                saved = store.finish(session)
                if saved:
                    payload["saved_to"] = saved
            else:
                store.persist(session)
            self._send_json(payload)

    return Handler


def serve(
    space: SpaceConfig,
    guide: Guide,
    llm_cfg: Dict[str, Any],
    port: int = 8770,
    admin_root: Optional[str] = None,
    tts=None,
    space_dir: Optional[str] = None,
):
    # Банк читається з диска на кожен запит: дослідник дозаписує репліки в
    # панелі, і наступний респондент мусить їх почути без перезапуску.
    root = space_dir or (os.path.join(admin_root, space.key) if admin_root else None)
    bank_provider = (lambda: load_bank(root)) if root else (lambda: load_bank("."))

    store = SessionStore(space, guide, llm_cfg, bank_provider)
    holder = tts if isinstance(tts, TtsHolder) else TtsHolder(tts)
    handler = make_handler(space, guide, llm_cfg, store, admin_root, holder, bank_provider)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    return httpd
