"""Банк реплік: інтервʼюер говорить записаним людським голосом.

Чому це методологічно сильніше за синтез, а не просто приємніше на слух:
модель більше не формулює питання, вона **вибирає** з набору, який людина
переглянула й записала. Отже всі респонденти чують буквально однакові
формулювання — та сама однаковість, за якою ми ганялись через `noise_scale`,
тільки справжня. І навідне питання не може виникнути за побудовою: у банку його
немає.

Ціна названа прямо: інтервʼюер не поставить точно підігнаного під відповідь
питання, якого немає в банку. Він вибере найближче.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

KINDS = ("opening", "closing", "topic", "probe")


class PhraseError(ValueError):
    """Банк неповний або суперечливий. Краще впасти на старті."""


@dataclass
class Phrase:
    id: str
    kind: str
    text: str
    audio: Optional[str] = None
    topic_id: Optional[str] = None

    @property
    def recorded(self) -> bool:
        return bool(self.audio)


@dataclass
class PhraseBank:
    phrases: List[Phrase] = field(default_factory=list)
    audio_dir: str = ""

    # ── доступ ───────────────────────────────────────────────────────────

    def by_id(self, phrase_id: str) -> Optional[Phrase]:
        for phrase in self.phrases:
            if phrase.id == phrase_id:
                return phrase
        return None

    def of_kind(self, kind: str) -> List[Phrase]:
        return [p for p in self.phrases if p.kind == kind]

    def for_topic(self, topic_id: str) -> List[Phrase]:
        return [p for p in self.phrases if p.kind == "topic" and p.topic_id == topic_id]

    @property
    def opening(self) -> Optional[Phrase]:
        items = self.of_kind("opening")
        return items[0] if items else None

    @property
    def closing(self) -> Optional[Phrase]:
        items = self.of_kind("closing")
        return items[0] if items else None

    @property
    def probes(self) -> List[Phrase]:
        return self.of_kind("probe")

    def recorded_only(self) -> "PhraseBank":
        return PhraseBank([p for p in self.phrases if p.recorded], self.audio_dir)

    def audio_path(self, phrase: Phrase) -> Optional[str]:
        if not phrase.audio:
            return None
        return os.path.join(self.audio_dir, phrase.audio)

    # ── придатність ──────────────────────────────────────────────────────

    def missing_for_interview(self, topic_ids: List[str]) -> List[str]:
        """Чого не хватає, щоб провести інтервʼю **лише** банком.

        Повертає перелік людською мовою, а не булеве значення: дослідник має
        бачити, що саме дозаписати, а не «банк неповний».
        """
        gaps = []
        recorded = self.recorded_only()

        if not recorded.opening:
            gaps.append("немає записаного відкриття")
        if not recorded.closing:
            gaps.append("немає записаного завершення")
        if not recorded.probes:
            gaps.append("немає жодного записаного уточнення")

        for topic_id in topic_ids:
            if not recorded.for_topic(topic_id):
                gaps.append("немає жодного записаного питання до теми «%s»" % topic_id)

        unrecorded = [p.id for p in self.phrases if not p.recorded]
        if unrecorded:
            gaps.append("не записані: %s" % ", ".join(unrecorded[:8]))
        return gaps


def load_bank(space_dir: str) -> PhraseBank:
    """Читає `phrases.json` простору. Немає файла — порожній банк, не помилка."""
    path = os.path.join(space_dir, "phrases.json")
    audio_dir = os.path.join(space_dir, "audio")
    if not os.path.isfile(path):
        return PhraseBank([], audio_dir)

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    seen = set()
    phrases = []
    for raw in data.get("phrases", []):
        pid = (raw.get("id") or "").strip()
        if not pid:
            raise PhraseError("phrases.json: репліка без id")
        if pid in seen:
            raise PhraseError("phrases.json: дубльований id репліки «%s»" % pid)
        seen.add(pid)

        kind = raw.get("kind")
        if kind not in KINDS:
            raise PhraseError(
                "phrases.json: репліка «%s» має невідомий kind «%s». Допустимі: %s."
                % (pid, kind, ", ".join(KINDS))
            )
        text = (raw.get("text") or "").strip()
        if not text:
            raise PhraseError("phrases.json: репліка «%s» без тексту" % pid)
        if kind == "topic" and not raw.get("topic_id"):
            raise PhraseError("phrases.json: репліка «%s» типу topic без topic_id" % pid)

        audio = raw.get("audio") or None
        if audio:
            # Ім'я файла йде у шлях, тому жодних переходів по тецях.
            if os.path.basename(audio) != audio:
                raise PhraseError("phrases.json: недопустиме ім'я файла «%s»" % audio)
            if not os.path.isfile(os.path.join(audio_dir, audio)):
                # Не помилка: запис могли видалити руками. Репліка просто
                # вважається незаписаною, і це видно в панелі.
                audio = None

        phrases.append(Phrase(id=pid, kind=kind, text=text, audio=audio,
                              topic_id=raw.get("topic_id")))
    return PhraseBank(phrases, audio_dir)


def save_bank(space_dir: str, phrases: List[Dict[str, Any]]) -> None:
    path = os.path.join(space_dir, "phrases.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "phrases": phrases}, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
