/* Звук: візуалізація й запис голосу респондента.
 *
 * Виділено з app.js окремо, бо це єдине місце, де інструмент працює з Web
 * Audio. Ядро інтервʼю про звук не знає взагалі.
 *
 * Озвучення питань синтезом (speechSynthesis/TTS) тут свідомо більше немає:
 * питання начитує сам дослідник (адмінка → Налаштування → питання →
 * мікрофон), респондент чує живий голос, а не синтез.
 */

window.ITAudio = (function () {
  "use strict";

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
    createRecorder: createRecorder,
    createWaveform: createWaveform
  };
})();
