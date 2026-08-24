/* Відповідь як шматки з походженням.
 *
 * Окремий файл із ЧИСТИМИ функціями — і це не стиль, а необхідність: голосовий
 * шлях неможливо перевірити в браузерній панелі, бо доступ до мікрофона там
 * заблокований. Логіку, від якої залежить «сказане голосом ≠ набране текстом»,
 * треба перевіряти тестами, а тестувати можна лише те, що не сидить у замиканні
 * разом зі станом сторінки.
 *
 * Шматок: {text, source: "voice"|"typed", clip: індекс запису або null}.
 */
var ITSegments = (function () {
  "use strict";

  function text(list) {
    return (list || [])
      .map(function (part) { return part.text; })
      .join(" ")
      .replace(/\s+/g, " ")
      .trim();
  }

  /* Додає сказане. Сусідні шматки того самого походження й того самого запису
     зливаються: інакше кожне слово диктування стало б окремим шматком, і
     підсвітка під час прослуховування сипалась би на порожні вузли. */
  function push(list, chunk, source, clip) {
    var out = (list || []).slice();
    var clean = (chunk || "").trim();
    if (!clean) return out;
    var key = (clip === undefined || clip === null) ? null : clip;
    var last = out[out.length - 1];
    if (last && last.source === source && last.clip === key) {
      out[out.length - 1] = {
        text: (last.text + " " + clean).trim(),
        source: source,
        clip: key
      };
      return out;
    }
    out.push({ text: clean, source: source, clip: key });
    return out;
  }

  /* Після правки: те, що людина надиктувала й НЕ змінила, лишається голосом.
     Дописане або переписане стає текстом.
     Без цього будь-яка правка перетворювала всю відповідь на набрану вручну —
     і дослідник більше не бачив, що насправді було сказано вголос. */
  function fromEdit(list, value) {
    var edited = (value || "").trim();
    var voiceOnly = [];
    var all = list || [];
    for (var i = 0; i < all.length; i++) {
      if (all[i].source !== "voice") break;
      voiceOnly.push(all[i]);
    }
    var prefix = text(voiceOnly);
    if (prefix && edited.indexOf(prefix) === 0) {
      var tail = edited.slice(prefix.length).trim();
      var kept = voiceOnly.slice();
      if (tail) kept.push({ text: tail, source: "typed", clip: null });
      return kept;
    }
    return edited ? [{ text: edited, source: "typed", clip: null }] : [];
  }

  /* Скільки слів у шматку — для пропорційної підсвітки під час відтворення. */
  function words(part) {
    return ((part && part.text) || "").split(/\s+/).filter(Boolean);
  }

  return { text: text, push: push, fromEdit: fromEdit, words: words };
})();

if (typeof module !== "undefined" && module.exports) module.exports = ITSegments;
