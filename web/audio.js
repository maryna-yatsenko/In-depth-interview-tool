/* Звук: озвучення питань і візуалізація голосу респондента.
 *
 * Виділено з app.js окремо, бо це єдине місце, де інструмент працює з Web Audio
 * і speechSynthesis. Ядро інтервʼю про звук не знає взагалі.
 */

window.ITAudio = (function () {
  "use strict";

  /* ── Озвучення ─────────────────────────────────────────────────────────
   *
   * Головний прийом проти «робота»: не віддавати браузеру весь абзац одним
   * куском. Рушій вимовляє довгий текст рівною монотонною лінією і сам не
   * ставить паузи там, де їх ставить людина. Якщо порізати на речення й
   * промовляти їх окремими висловлюваннями з короткими паузами, інтонація
   * скидається на кожній фразі, а паузи падають туди, де кома й точка.
   * Це чути одразу — сильніше, ніж будь-яке крутіння rate і pitch.
   */

  var MAX_CHUNK = 140;   // довші куски рушій вимовляє монотонно
  var MIN_CHUNK = 12;    // коротші зшиваємо, щоб не було рубленої мови;

  function splitForSpeech(text) {
    var clean = String(text || "").replace(/\s+/g, " ").trim();
    if (!clean) return [];

    // Спершу за кінцем речення, зберігаючи знак.
    var sentences = clean.match(/[^.!?…]+[.!?…]*/g) || [clean];
    var chunks = [];

    sentences.forEach(function (sentence) {
      var part = sentence.trim();
      if (!part) return;
      if (part.length <= MAX_CHUNK) { chunks.push(part); return; }
      // Довге речення ріжемо за комами й тире — там людина теж дихає.
      // Без lookbehind навмисно: у Safari він з'явився лише в 16.4, а падати
      // на розділенні тексту через версію браузера респондента — дурна причина.
      var pieces = [];
      var buf = "";
      part.split(" ").forEach(function (word) {
        buf = buf ? (buf + " " + word) : word;
        if (/[,;—–]$/.test(word)) { pieces.push(buf); buf = ""; }
      });
      if (buf) pieces.push(buf);
      var buffer = "";
      pieces.forEach(function (piece) {
        piece = piece.trim();
        if (!piece) return;
        if ((buffer + " " + piece).trim().length > MAX_CHUNK && buffer) {
          chunks.push(buffer.trim());
          buffer = piece;
        } else {
          buffer = (buffer + " " + piece).trim();
        }
      });
      if (buffer) chunks.push(buffer.trim());
    });

    // Зшиваємо занадто короткі куски з наступним.
    var merged = [];
    chunks.forEach(function (chunk) {
      if (merged.length && merged[merged.length - 1].length < MIN_CHUNK) {
        merged[merged.length - 1] = merged[merged.length - 1] + " " + chunk;
      } else {
        merged.push(chunk);
      }
    });
    return merged;
  }

  function listVoices(lang) {
    if (!window.speechSynthesis) return [];
    var voices = window.speechSynthesis.getVoices() || [];
    if (!lang) return voices;
    var short = String(lang).split("-")[0].toLowerCase();
    return voices.filter(function (voice) {
      return voice.lang && voice.lang.toLowerCase().indexOf(short) === 0;
    });
  }

  function pickVoice(lang, preferredName) {
    var candidates = listVoices(lang);
    if (!candidates.length) return null;
    if (preferredName) {
      for (var i = 0; i < candidates.length; i++) {
        if (candidates[i].name === preferredName) return candidates[i];
      }
    }
    // За інших рівних беремо «покращений» голос, якщо система його має:
    // на macOS такі варіанти звучать помітно природніше за базові.
    for (var j = 0; j < candidates.length; j++) {
      if (/enhanced|premium|siri/i.test(candidates[j].name)) return candidates[j];
    }
    return candidates[0];
  }

  function createSpeaker(options) {
    var config = options || {};
    var state = { chain: [], cancelled: false, speaking: false };

    function stop() {
      state.cancelled = true;
      state.chain = [];
      state.speaking = false;
      if (window.speechSynthesis) window.speechSynthesis.cancel();
    }

    function speak(text, callbacks) {
      var handlers = callbacks || {};
      if (!window.speechSynthesis) { if (handlers.onEnd) handlers.onEnd(); return; }
      stop();
      state.cancelled = false;

      var chunks = splitForSpeech(text);
      if (!chunks.length) { if (handlers.onEnd) handlers.onEnd(); return; }

      var voice = pickVoice(config.lang, config.voiceName);
      var index = 0;
      state.speaking = true;

      function next() {
        if (state.cancelled) return;
        if (index >= chunks.length) {
          state.speaking = false;
          if (handlers.onEnd) handlers.onEnd();
          return;
        }
        var phrase = chunks[index];
        var utter = new SpeechSynthesisUtterance(phrase);
        utter.lang = config.lang || "uk-UA";
        if (voice) utter.voice = voice;
        utter.rate = config.rate || 0.97;
        utter.pitch = config.pitch || 1.0;
        utter.volume = config.volume || 1.0;
        index += 1;

        // Сторож на кожну фразу. speechSynthesis на macOS іноді не викликає
        // ні onend, ні onerror — і тоді ланцюжок зупиняється назавжди, а
        // респондент лишається з заблокованою кнопкою і без можливості
        // відповісти. Це фатально, тому не покладаємось на подію.
        var advanced = false;
        var watchdog = null;

        function advance(delay) {
          if (advanced || state.cancelled) return;
          advanced = true;
          if (watchdog) window.clearTimeout(watchdog);
          window.setTimeout(next, delay);
        }

        // Оцінка тривалості: ~13 символів на секунду при rate 1, з запасом ×2.
        var estimate = (phrase.length / 13) * 1000 / (utter.rate || 1) + 1500;
        watchdog = window.setTimeout(function () { advance(0); }, estimate * 2);

        utter.onend = function () {
          // Пауза між фразами: без неї речення злипаються в один потік.
          advance(config.gap == null ? 140 : config.gap);
        };
        utter.onerror = function () { advance(60); };

        window.speechSynthesis.speak(utter);
      }

      if (handlers.onStart) handlers.onStart();
      next();
    }

    return {
      speak: speak,
      stop: stop,
      isSpeaking: function () { return state.speaking; },
      setVoiceName: function (name) { config.voiceName = name; },
      config: config
    };
  }

  /* ── Доріжка голосу ────────────────────────────────────────────────────
   *
   * Показує респонденту, що його чують. Це не окраса: без візуального
   * підтвердження людина не розуміє, чи мікрофон працює, і починає говорити
   * невпевнено — а це вже впливає на дані.
   */

  function createWaveform(canvas) {
    var context = null;
    var analyser = null;
    var source = null;
    var stream = null;
    var raf = null;
    var data = null;
    var level = 0;

    function draw() {
      if (!analyser || !canvas) return;
      var ctx = canvas.getContext("2d");
      var dpr = window.devicePixelRatio || 1;
      var width = canvas.clientWidth;
      var height = canvas.clientHeight;
      if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
        canvas.width = width * dpr;
        canvas.height = height * dpr;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);

      analyser.getByteTimeDomainData(data);

      var accent = getComputedStyle(document.documentElement)
        .getPropertyValue("--accent").trim() || "#3a3a3a";
      var bars = Math.max(24, Math.floor(width / 7));
      var step = Math.floor(data.length / bars);
      var barWidth = Math.max(2, (width / bars) * 0.55);
      var peak = 0;

      ctx.fillStyle = accent;
      for (var i = 0; i < bars; i++) {
        var max = 0;
        for (var j = 0; j < step; j++) {
          var v = Math.abs(data[i * step + j] - 128) / 128;
          if (v > max) max = v;
        }
        if (max > peak) peak = max;
        // Мінімальна висота — щоб доріжка існувала й у тиші, а не блимала.
        var barHeight = Math.max(2, Math.min(height, max * height * 1.7));
        var x = i * (width / bars) + (width / bars - barWidth) / 2;
        var y = (height - barHeight) / 2;
        ctx.globalAlpha = 0.35 + Math.min(0.65, max * 2);
        ctx.beginPath();
        var r = barWidth / 2;
        ctx.roundRect ? ctx.roundRect(x, y, barWidth, barHeight, r)
                      : ctx.rect(x, y, barWidth, barHeight);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      level = peak;
      raf = window.requestAnimationFrame(draw);
    }

    function start() {
      if (!navigator.mediaDevices || !window.AudioContext) return Promise.resolve(false);
      if (context) return Promise.resolve(true);
      return navigator.mediaDevices.getUserMedia({ audio: true }).then(function (media) {
        stream = media;
        context = new (window.AudioContext || window.webkitAudioContext)();
        analyser = context.createAnalyser();
        analyser.fftSize = 1024;
        analyser.smoothingTimeConstant = 0.75;
        data = new Uint8Array(analyser.fftSize);
        source = context.createMediaStreamSource(stream);
        source.connect(analyser);
        draw();
        return true;
      }).catch(function () {
        // Немає доступу до мікрофона для візуалізації — не привід валити інтервʼю.
        return false;
      });
    }

    function stop() {
      if (raf) { window.cancelAnimationFrame(raf); raf = null; }
      if (source) { try { source.disconnect(); } catch (e) {} source = null; }
      if (context) { try { context.close(); } catch (e) {} context = null; }
      if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
      analyser = null;
      if (canvas) {
        var ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
    }

    return {
      start: start, stop: stop, level: function () { return level; },
      stream: function () { return stream; }
    };
  }

  /* ── запис голосу респондента ──────────────────────────────────────────
     Не для розпізнавання — для дослідника: інтонація, пауза, «ну як би» в
     тексті не лишаються. Тому пишеться те саме, що чує мікрофон.

     Потік беремо в доріжки: вона його вже відкрила. Другий getUserMedia на той
     самий мікрофон працює не в усіх браузерах однаково, а тут ще й
     розпізнавання мовлення сидить на тому самому пристрої. */
  function createRecorder(streamGetter) {
    var recorder = null;
    var chunks = [];
    var mime = "";

    function supported() {
      return typeof window.MediaRecorder !== "undefined";
    }

    function pickMime() {
      if (!window.MediaRecorder || !window.MediaRecorder.isTypeSupported) return "";
      // Порядок за перевагою: opus дає найменший файл, mp4 — резерв Safari.
      var candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus",
                        "audio/mp4", "audio/mpeg"];
      for (var i = 0; i < candidates.length; i++) {
        if (window.MediaRecorder.isTypeSupported(candidates[i])) return candidates[i];
      }
      return "";
    }

    function start() {
      if (!supported()) return false;
      var stream = streamGetter && streamGetter();
      if (!stream) return false;
      chunks = [];
      mime = pickMime();
      try {
        recorder = mime ? new MediaRecorder(stream, { mimeType: mime })
                        : new MediaRecorder(stream);
      } catch (e) {
        recorder = null;
        return false;
      }
      recorder.ondataavailable = function (event) {
        if (event.data && event.data.size) chunks.push(event.data);
      };
      try {
        recorder.start();
      } catch (e) {
        recorder = null;
        return false;
      }
      return true;
    }

    /* Повертає Blob через колбек: `stop()` у MediaRecorder асинхронний, і
       останній кусок приходить уже після нього. Забирати blob одразу означало
       б втрачати хвіст фрази. */
    function stop(done) {
      if (!recorder) { done(null); return; }
      var active = recorder;
      recorder = null;
      active.onstop = function () {
        var type = (active.mimeType || mime || "audio/webm").split(";")[0];
        var blob = chunks.length ? new Blob(chunks, { type: type }) : null;
        chunks = [];
        done(blob);
      };
      try {
        active.stop();
      } catch (e) {
        done(null);
      }
    }

    return { supported: supported, start: start, stop: stop };
  }

  return {
    splitForSpeech: splitForSpeech,
    createRecorder: createRecorder,
    listVoices: listVoices,
    pickVoice: pickVoice,
    createSpeaker: createSpeaker,
    createWaveform: createWaveform
  };
})();
