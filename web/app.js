/* Клієнт респондента: два режими одного інтервʼю.
 *
 * `voice` — без поля введення: мікрофон, доріжка голосу, розпізнаний текст.
 * `text`  — поле введення (і аварійний резерв, коли мікрофона немає).
 *
 * Режим приходить із конфігу простору. Ядро інтервʼю про це не знає: на вхід
 * текст репліки, на вихід текст питання (docs/ai/architecture.md).
 *
 * ⚠️ Приватність: `SpeechRecognition` у Chrome розпізнає не на пристрої, а на
 * серверах вендора браузера (TD-6). Для особистого контура приймально, для
 * корпоративного потрібен серверний STT.
 */

(function () {
  "use strict";

  var el = function (id) { return document.getElementById(id); };

  var state = {
    sessionId: null,
    space: null,
    mode: "text",
    phase: "idle",        // idle | listening | review | speaking
    finalText: "",        // розпізнане й підтверджене
    recognition: null,
    speaker: null,
    waveform: null,
    voiceName: null,
    audio: null,          // <audio> для серверного озвучення
    audioFinish: null,    // прибирання blob-у, якщо зупинили ззовні
    lastAudioUrl: null,   // адреса запису поточного питання (режим банку)
    expectedWords: 15,
    // Нижче цієї межі рушій не зараховує нічого: одне-два слова — це не
    // відповідь, а слово. Клієнт знає межу, щоб назвати людині причину.
    minWordsToCredit: 3,
    audioAvailable: false,
    autoplay: false,      // за замовчуванням питання лишається текстом
    prefetch: null,       // {url, blobUrl} — готове аудіо поточного питання
    prefetchFor: null,
    ttsMode: "none",      // browser | server | none
    speaking: false,
    busy: false,
    interviewPhase: "",   // фаза з сервера: warmup | narrative | topics | closing
    checklistItems: [],   // шпаргалка поточного питання
    // Сценарний режим веде людина кнопками; вільний — модель самими репліками.
    // Навігація вгорі має сенс лише в першому: у другому кроку не існує.
    scripted: false,
    depth: null,           // {answered, total, avg_words} — для екрана підсумку
    // Де людина в сценарії — від цього залежать кнопки навігації.
    atStart: true,
    atEnd: false,
    answered: false,
    // Уже надіслане на ЦЕ питання. У фазі розповіді інтервʼюер мовчить і
    // питання лишається те саме — отже й сказане мусить лишатись на екрані.
    // Раніше текст стирався після кожного надсилання, і людина губила нитку
    // власної розповіді.
    sentText: "",
    /* Відповідь як шматки з походженням, а не один рядок.
       Три речі тримаються на цьому: голос і текст видно окремо, «Редагувати»
       не має чого губити, і кожен шматок знає, з якого запису він узявся —
       тому під час прослуховування можна підсвітити саме ті слова. */
    segments: [],         // [{text, source: "voice"|"typed", clip: індекс|null}]
    clipIndex: null,      // запис, який пишеться зараз
    clipStarted: null,    // коли він почався (для тривалості)
    // Запис голосу респондента. Не для розпізнавання — для дослідника:
    // інтонацію й паузи текст не зберігає.
    recorder: null,
    recordVoice: false,   // простір це пропонує
    voiceConsent: false,  // людина погодилась
    ownClips: [],         // {url, blobUrl} записи поточної відповіді
    ownPlayer: null,      // <audio>, яким людина переслуховує свій голос
    // Остання НЕ завершена фраза. Браузер вважає її проміжною й може так і не
    // зробити остаточною — а це буквально те, що людина щойно сказала.
    interim: ""
  };

  /* ── памʼять про незавершену сесію ─────────────────────────────────── */

  var storeKey = function () { return "interview.session." + (state.space ? state.space.key : "?"); };
  var voiceKey = function () { return "interview.voice." + (state.space ? state.space.key : "?"); };

  function remember(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* приватний режим */ }
  }
  function recall(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function forget(key) {
    try { window.localStorage.removeItem(key); } catch (e) { /* приватний режим */ }
  }

  /* ── розпізнавання ─────────────────────────────────────────────────── */

  function recognitionCtor() {
    return window.SpeechRecognition || window.webkitSpeechRecognition || null;
  }

  function langTag() {
    var first = (state.space && state.space.languages && state.space.languages[0]) || "uk";
    return first === "uk" ? "uk-UA" : first;
  }

  function initRecognition() {
    var Ctor = recognitionCtor();
    if (!Ctor) return null;

    var rec = new Ctor();
    rec.lang = langTag();
    rec.continuous = true;
    rec.interimResults = true;

    rec.onresult = function (event) {
      var interim = "";
      for (var i = event.resultIndex; i < event.results.length; i++) {
        var chunk = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          // Шматок знає, що він із голосу й з якого саме запису — під час
          // прослуховування це дає змогу підсвітити саме ці слова.
          pushSegment(chunk, "voice", state.clipIndex);
          // Остаточний результат заміняє проміжний: тримати обидва означало б
          // дописати ту саму фразу двічі.
          state.interim = "";
        } else {
          interim += chunk;
        }
      }
      state.interim = interim;
      renderHeard(interim);
    };

    rec.onerror = function (event) {
      if (event.error === "no-speech") { setStatus("Не почула — спробуйте ще раз."); return; }
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setStatus("Доступ до мікрофона не надано.", true);
        fallbackToText("Мікрофон недоступний, тому відповідайте, будь ласка, текстом.");
        return;
      }
      if (event.error === "aborted") return;
      setStatus("Мікрофон: " + event.error, true);
      stopListening();
    };

    rec.onend = function () {
      // Браузер обриває розпізнавання за тишею. Якщо людина ще говорить —
      // піднімаємо назад: пауза в думках не є кінцем відповіді.
      if (state.phase === "listening") {
        try { rec.start(); } catch (e) { stopListening(); }
        return;
      }
      // Запис зупинено. Незавершена фраза інакше зникає безслідно: браузер
      // тримав її як проміжну й остаточною так і не зробив. Для людини це
      // виглядало як «я це сказала, а воно не почуло» — і чекліст справді не
      // міг зарахувати те, чого в тексті немає.
      //
      // Забираємо її тут, а не в `stopListening`: остаточний результат часто
      // приходить уже після stop(), і тоді `interim` уже порожній — інакше та
      // сама фраза дописалась би двічі.
      keepInterim();
    };

    return rec;
  }

  /* Незавершена фраза — це теж сказане. Дописуємо її до відповіді. */
  function keepInterim() {
    var tail = (state.interim || "").trim();
    state.interim = "";
    if (!tail) return;
    pushSegment(tail, "voice", state.clipIndex);
    renderHeard("");
    refreshActions();
  }

  /* ── відповідь як шматки з походженням ───────────────────────────────
     Один рядок не дає розрізнити сказане й написане, а «Редагувати» на рядку
     неминуче щось губить: те, що браузер ще тримав як проміжне. */

  /* Самі перетворення — у `web/segments.js`, чистими функціями. Причина не в
     стилі: голосовий шлях неможливо перевірити в браузерній панелі (мікрофон
     там заблокований), тому логіка «сказане ≠ набране» мусить бути покрита
     тестами, а тестувати можна лише те, що не сидить у замиканні зі станом. */
  function segmentsText(list) { return ITSegments.text(list); }

  function pushSegment(text, source, clip) {
    state.segments = ITSegments.push(state.segments, text, source, clip);
    state.finalText = segmentsText(state.segments);
  }

  function clearSegments() {
    state.segments = [];
    state.finalText = "";
  }

  function segmentsFromEdit(value) {
    state.segments = ITSegments.fromEdit(state.segments, value);
    state.finalText = segmentsText(state.segments);
  }

  /* ── відтворення тексту, що почули ─────────────────────────────────── */

  function renderHeard(interim) {
    if (state.mode !== "voice") {
      el("answer").value = (state.finalText + " " + (interim || "")).trim();
      refreshActions();
      return;
    }
    var host = el("heard");
    host.textContent = "";
    if (state.sentText) {
      // Приглушено: це вже сказано й надіслано, правити тут нічого.
      var said = document.createElement("span");
      said.className = "said";
      said.textContent = state.sentText + " ";
      host.appendChild(said);
    }
    state.segments.forEach(function (part, index) {
      var span = document.createElement("span");
      // Клас несе походження: сказане й написане мусить бути видно окремо.
      span.className = "seg seg-" + part.source;
      span.dataset.seg = String(index);
      if (part.clip !== null && part.clip !== undefined) {
        span.dataset.clip = String(part.clip);
      }
      // Кожне слово — окремий вузол. Тільки так можна підсвітити те, що саме
      // зараз звучить у записі.
      part.text.split(/\s+/).forEach(function (word) {
        if (!word) return;
        var w = document.createElement("span");
        w.className = "word";
        if (part.clip !== null && part.clip !== undefined) {
          w.dataset.clip = String(part.clip);
        }
        w.textContent = word;
        span.appendChild(w);
        span.appendChild(document.createTextNode(" "));
      });
      host.appendChild(span);
    });
    if (interim) {
      var span = document.createElement("span");
      span.className = "interim";
      span.textContent = interim;
      host.appendChild(span);
    }
    refreshActions();
  }

  /* ── швидкість відтворення ──────────────────────────────────────────
   *
   * Через `playbackRate`, а не повторним синтезом: діє миттєво, однаково для
   * записаного голосу й для синтезу, і браузер зберігає висоту тону
   * (`preservesPitch`), тому повільніше не означає «нижчим голосом».
   */

  /* Єдина швидкість: 1,0 — рівно так, як записав синтезатор. Вибору немає
     навмисно: регулятор змушував респондента ухвалювати рішення про
     інструмент замість того, щоб думати про свій досвід. */
  var PLAYBACK_RATE = 1.0;

  function effectiveRate() {
    return PLAYBACK_RATE;
  }

  function applyRate(audio) {
    if (!audio) return;
    try {
      audio.playbackRate = effectiveRate();
      if ("preservesPitch" in audio) audio.preservesPitch = true;
      if ("mozPreservesPitch" in audio) audio.mozPreservesPitch = true;
      if ("webkitPreservesPitch" in audio) audio.webkitPreservesPitch = true;
    } catch (e) { /* старий браузер — грає як грає */ }
  }



  /* ── керування записом ─────────────────────────────────────────────── */

  function startListening() {
    if (!state.recognition || state.phase === "listening") return;
    // Слухати ОДНОЧАСНО з озвученням не можна: розпізнавання почує сам
    // інтервʼюер і запише його питання як відповідь респондента. Але замикати
    // людину до кінця читання теж не треба — тому спершу глушимо голос, потім
    // слухаємо. Порядок тут і є вся суть.
    if (state.speaking || (state.speaker && state.speaker.isSpeaking()) ||
        (state.audio && !state.audio.paused && !state.audio.ended)) {
      stopReading(true);
    }

    state.phase = "listening";
    setTalkUI(true);
    refreshActions();
    // finalText не скидаємо: «Продовжити» дописує до вже сказаного.
    setStatus(state.finalText
      ? "Слухаю далі — додам до сказаного."
      : "Слухаю… Говоріть спокійно, паузи — це нормально.");

    if (state.waveform) {
      el("wave").classList.add("live");
      state.waveform.start().then(function (ok) {
        if (!ok) el("wave").classList.remove("live");
        // Записувач після доріжки: потік відкриває саме вона.
        if (ok && state.voiceConsent && state.recorder && state.recorder.start()) {
          // Слова, надиктовані далі, належать саме цьому запису.
          state.clipIndex = state.ownClips.length;
          state.clipStarted = Date.now();
        }
      });
    }
    try {
      state.recognition.start();
    } catch (e) {
      state.phase = "idle";
      setTalkUI(false);
      setStatus("Не вдалося ввімкнути мікрофон.", true);
    }
  }

  function stopListening() {
    if (!state.recognition) return;
    state.phase = "review";
    setTalkUI(false);
    try { state.recognition.stop(); } catch (e) { /* уже зупинено */ }
    // Забрати запис ПЕРЕД тим, як доріжка закриє потік: після stop() у потоку
    // вже немає доріжок, і MediaRecorder лишається без джерела.
    if (state.voiceConsent && state.recorder) {
      // Тривалість беремо з годинника, а не з файлу: webm від MediaRecorder
      // часто віддає duration = Infinity, і тоді ні смуги, ні підсвітки.
      var seconds = state.clipStarted
        ? (Date.now() - state.clipStarted) / 1000 : 0;
      state.clipStarted = null;
      state.clipIndex = null;
      state.recorder.stop(function (blob) { uploadOwnVoice(blob, seconds); });
    }
    if (state.waveform) {
      state.waveform.stop();
      el("wave").classList.remove("live");
    }
    renderHeard("");

    if (state.mode === "voice") {
      var hasText = !!state.finalText.trim();
    refreshActions();
      setStatus(hasText ? "" : "Нічого не почула. Натисніть «Говорити» і спробуйте ще раз.");
    } else {
      setStatus(el("answer").value.trim() ? "Можна виправити текст перед відправкою." : "");
    }
  }

  function setTalkUI(listening) {
    if (state.mode === "voice") {
      var talk = el("btn-talk");
      talk.setAttribute("aria-pressed", listening ? "true" : "false");
      // Ця сама кнопка продовжує відповідь: натиснув ще раз — дописується до
      // вже сказаного. Окрема кнопка «Продовжити» дублювала її роль.
      el("talk-label").textContent = listening
        ? "Зупинити"
        : (state.finalText.trim() ? "Продовжити" : "Говорити");
      // Найпростіші знаки: почати/зупинити, як у будь-якого плеєра —
      // впізнаються швидше, ніж мікрофон-емодзі, і однакові в усіх шрифтах.
      el("talk-icon").textContent = listening ? "⏹" : "▶";
      el("talk-ring") && 0;
    } else {
      var mic = el("btn-mic");
      mic.setAttribute("aria-pressed", listening ? "true" : "false");
      el("mic-label").textContent = listening ? "Стоп" : "Говорити";
    }
  }

  function fallbackToText(message) {
    // Ніколи не заводити людину в тупик: немає мікрофона — є текст.
    state.mode = "text";
    // Уже надиктоване переїжджає в поле. Інакше людина, у якої мікрофон
    // відвалився посеред відповіді, втрачає все сказане — і не зрозуміє чому.
    var carried = state.finalText.trim();
    if (carried && !el("answer").value.trim()) el("answer").value = carried;
    el("voice-area").classList.add("hidden");
    el("answer-area").classList.remove("hidden");
    el("btn-mic").disabled = !recognitionCtor();
    if (el("btn-mic").disabled) el("mic-label").textContent = "Мікрофон недоступний";
    if (message) setStatus(message, true);
    el("answer").focus();
  }

  /* ── інтерфейс ─────────────────────────────────────────────────────── */

  function setStatus(text, isError) {
    var node = el(state.mode === "voice" ? "voice-status" : "status");
    node.textContent = text || "";
    node.className = "status" + (isError ? " error" : "");
  }

  function countWords(text) {
    return (String(text || "").match(/[^\s]+/g) || []).length;
  }

  /* Надіслати можна, щойно є текст. Крапка.

     Тут стояв гейт: кнопка відкривалась, лише коли чекліст зарахований
     повністю. Ідея була гарна, і саме її я й реалізував — але вона трималась
     на припущенні, що оцінювач не бреше. Мірка (`bin/judge_eval.py`) показала,
     що на контрольному наборі, якого налаштування не бачило, він тримає
     64-71 % і найгірший сорт помилок — «відповідь поруч, але не та» — ловить
     одну з трьох. Тобто людину, яка сказала все, кнопка інколи не пускала, а
     людину, яка не сказала, — пускала.

     Ставити ЗАМОК на судження такої точності неправильно. Чекліст лишається:
     він показує, чого ми чекаємо, і галочки в ньому корисні як підказка.
     Але право вирішити, що відповідь готова, лишається за людиною. */
  /* Текстовий резерв (простір без голосу) досі має кнопку «надіслати». */
  function canSend(words) {
    return words > 0;
  }

  /* ── власний голос респондента ──────────────────────────────────────
     Запис їде на сервер одразу, як людина договорила, а не разом із
     відповіддю: так він переживає закриту сторінку. «Сказати заново» його
     видаляє — і в браузері, і на диску. */

  function uploadOwnVoice(blob, seconds) {
    if (!blob || !blob.size || !state.sessionId) return;
    // Локальне посилання — щоб переслухати без запиту до сервера.
    var local = URL.createObjectURL(blob);
    state.ownClips.push({ blobUrl: local, url: null, seconds: seconds || 0 });
    refreshOwnVoice();

    var entry = state.ownClips[state.ownClips.length - 1];
    fetch("/api/voice?session_id=" + encodeURIComponent(state.sessionId), {
      method: "POST",
      headers: { "Content-Type": blob.type || "audio/webm" },
      body: blob
    }).then(function (response) {
      if (!response.ok) return response.json().then(function (data) {
        throw new Error(data.error || ("HTTP " + response.status));
      });
      return response.json();
    }).then(function (data) {
      entry.url = data.url || null;
      entry.name = data.clip || null;
    }).catch(function (err) {
      // Інтервʼю через це не зупиняємо: текст відповіді вже є, і він головний.
      // Але людина мусить знати, що записаного голосу в дослідника не буде.
      entry.failed = true;
      setStatus("Запис голосу не зберігся (" + err.message + "). Текст відповіді збережено.");
    });
  }

  /* Кнопка видима завжди, коли простір пише голос, — просто вимкнена, поки
     записувати нічого. Кнопки, що виникають з нічого, неможливо вивчити: людина
     не знає, що така можливість узагалі є. */
  function refreshOwnVoice() {
    var button = el("btn-play-own");
    if (!button) return;
    var has = state.ownClips.length > 0;
    button.classList.toggle("hidden", !state.voiceConsent);
    button.disabled = state.busy || !has;
    button.title = has
      ? "Прослухати свій запис"
      : "Тут можна буде прослухати свій запис, коли скажете відповідь";
    if (!has) stopOwnVoice();
  }

  /* Записи, які сервер уже має для цієї відповіді. Потрібно, щоб «Мій голос»
     працював і після перезавантаження сторінки: у памʼяті браузера blob-и
     зникають, а на диску файли лишаються. */
  function syncOwnVoice(names) {
    if (!state.sessionId || !names || !names.length) return;
    names.forEach(function (name) {
      var url = "/voice/" + state.sessionId + "/" + name;
      var known = state.ownClips.some(function (clip) { return clip.url === url; });
      if (!known) state.ownClips.push({ url: url, blobUrl: null, name: name });
    });
    refreshOwnVoice();
  }

  function formatTime(seconds) {
    var whole = Math.max(0, Math.floor(seconds || 0));
    return Math.floor(whole / 60) + ":" + ("0" + (whole % 60)).slice(-2);
  }

  /* Підсвітка того, що зараз звучить.

     ⚠️ Слова підсвічуються ПРОПОРЦІЙНО часу, а не за справжніми таймкодами:
     браузерне розпізнавання їх не дає, а міряти самим — окрема задача. Тому
     всередині запису це оцінка, і на довгих паузах вона трохи попереджає або
     відстає. Сам ЗАПИС визначено точно: кожне слово знає, з якого воно. */
  function markPlaying(clip, ratio) {
    var words = document.querySelectorAll('#heard .word[data-clip="' + clip + '"]');
    var current = words.length
      ? Math.min(words.length - 1, Math.floor(ratio * words.length)) : -1;
    Array.prototype.forEach.call(document.querySelectorAll("#heard .word.playing"),
      function (node) { node.classList.remove("playing"); });
    Array.prototype.forEach.call(document.querySelectorAll("#heard .seg.playing"),
      function (node) { node.classList.remove("playing"); });
    if (current < 0) return;
    words[current].classList.add("playing");
    var seg = words[current].closest ? words[current].closest(".seg") : null;
    if (seg) seg.classList.add("playing");
  }

  function clearPlaying() {
    Array.prototype.forEach.call(document.querySelectorAll("#heard .playing"),
      function (node) { node.classList.remove("playing"); });
  }

  /* Записів на одну відповідь може бути кілька: «Продовжити» додає новий.
     Граємо їх поспіль, як одну відповідь, — бо для людини це вона і є. */
  function playOwnVoice() {
    if (!state.ownClips.length) return;
    if (state.ownPlayer) { stopOwnVoice(); return; }
    var index = 0;
    var player = new Audio();
    state.ownPlayer = player;
    el("play-own-label").textContent = "Зупинити";
    el("own-progress").classList.remove("hidden");

    function current() { return state.ownClips[index - 1]; }

    function known(clip) {
      // Тривалість із годинника надійніша за duration: webm від MediaRecorder
      // часто віддає Infinity.
      if (clip && clip.seconds) return clip.seconds;
      return isFinite(player.duration) && player.duration > 0 ? player.duration : 0;
    }

    player.addEventListener("timeupdate", function () {
      var clip = current();
      var total = known(clip);
      var ratio = total ? Math.min(1, player.currentTime / total) : 0;
      el("own-fill").style.width = Math.round(ratio * 100) + "%";
      el("own-time").textContent = state.ownClips.length > 1
        ? ("запис " + index + " з " + state.ownClips.length + " · "
           + formatTime(player.currentTime) + (total ? " / " + formatTime(total) : ""))
        : (formatTime(player.currentTime) + (total ? " / " + formatTime(total) : ""));
      if (total) markPlaying(index - 1, ratio);
    });

    function next() {
      if (index >= state.ownClips.length) { stopOwnVoice(); return; }
      var clip = state.ownClips[index++];
      player.src = clip.blobUrl || clip.url;
      player.play().catch(function () { stopOwnVoice(); });
    }
    player.addEventListener("ended", next);
    player.addEventListener("error", function () { stopOwnVoice(); });
    next();
  }

  function stopOwnVoice() {
    if (state.ownPlayer) {
      try { state.ownPlayer.pause(); } catch (e) { /* уже стоїть */ }
      state.ownPlayer = null;
    }
    var label = el("play-own-label");
    if (label) label.textContent = "Прослухати";
    var bar = el("own-progress");
    if (bar) bar.classList.add("hidden");
    var fill = el("own-fill");
    if (fill) fill.style.width = "0%";
    clearPlaying();
  }

  function dropOwnVoice() {
    stopOwnVoice();
    state.ownClips.forEach(function (clip) {
      if (clip.blobUrl) URL.revokeObjectURL(clip.blobUrl);
    });
    state.ownClips = [];
    refreshOwnVoice();
  }

  /* ── раніше сказане ───────────────────────────────────────────────────
     Людина згадує деталь про раніше поставлене питання вже посеред іншої
     теми. У модерованому інтервʼю дослідник просто повернувся б до тієї теми;
     тут це мусить бути кнопкою, інакше деталь втрачається назавжди. */

  function openHistory(fromSummary) {
    if (state.phase === "listening") stopListening();
    keepInterim();
    // Запамʼятовуємо, звідки прийшли: з підсумку людина хоче повернутись
    // туди ж, а не до питання, яке вже позаду.
    state.historyFromSummary = !!fromSummary;
    el("history").classList.remove("hidden");
    el("history-list").innerHTML = "<p class='muted'>Читаю…</p>";
    post("/api/history", { session_id: state.sessionId })
      .then(function (data) { drawHistory(data.items || []); })
      .catch(function (err) {
        el("history-list").textContent = "Не вдалося прочитати: " + err.message;
      });
  }

  function closeHistory() {
    el("history").classList.add("hidden");
    if (state.historyFromSummary) {
      state.historyFromSummary = false;
      showSummary();
    }
  }

  /* Прослухати відповідь, яку раніше сказали голосом. Записи вже лежать на
     сервері — просто граємо їх поспіль тим самим клипом, яким записали. */
  function attachVoicePlayback(container, names) {
    if (!names || !names.length || !state.sessionId) return;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ghost small history-play";
    btn.textContent = "🔊 Прослухати";
    var player = null;
    function stop() {
      if (player) { try { player.pause(); } catch (e) { /* уже стоїть */ } player = null; }
      btn.textContent = "🔊 Прослухати";
    }
    btn.addEventListener("click", function () {
      if (player) { stop(); return; }
      var index = 0;
      player = new Audio();
      btn.textContent = "⏹ Зупинити";
      function next() {
        if (index >= names.length) { stop(); return; }
        player.src = "/voice/" + state.sessionId + "/" + names[index++];
        player.play().catch(stop);
      }
      player.addEventListener("ended", next);
      player.addEventListener("error", stop);
      next();
    });
    container.appendChild(btn);
  }

  function drawHistory(items) {
    var host = el("history-list");
    host.innerHTML = "";
    // Тримання розповіді не має питання — його не показуємо: людина побачила б
    // порожній рядок і не зрозуміла, до чого він.
    var shown = items.filter(function (item) { return item.question; });
    if (!shown.length) {
      host.innerHTML = "<p class='muted'>Поки що нічого — ви ще не відповіли на жодне запитання.</p>";
      return;
    }
    shown.forEach(function (item) {
      var box = document.createElement("div");
      box.className = "history-item";

      var question = document.createElement("p");
      question.className = "history-q";
      question.textContent = item.question;
      box.appendChild(question);

      // Те саме, чого чекали на цьому питанні, коли воно було поточним —
      // людина повертається дописати деталь і мусить бачити, про що ще
      // варто сказати, а не лише текст питання.
      if (item.expects && item.expects.length) {
        var expects = document.createElement("div");
        expects.className = "history-expects";
        var expectsTitle = document.createElement("span");
        expectsTitle.className = "history-expects-title";
        expectsTitle.textContent = "Про що варто сказати:";
        expects.appendChild(expectsTitle);
        var expectsList = document.createElement("ul");
        item.expects.forEach(function (text) {
          var li = document.createElement("li");
          li.textContent = text;
          expectsList.appendChild(li);
        });
        expects.appendChild(expectsList);
        box.appendChild(expects);
      }

      (item.answers || []).forEach(function (part) {
        var answer = document.createElement("p");
        answer.className = "history-a";
        // Позначку дає сервер, а не порядок: доповнення лежить у кінці
        // транскрипту, і за позицією його не відрізнити.
        if (part.added) {
          answer.className += " added";
          var mark = document.createElement("span");
          mark.className = "added-mark";
          mark.textContent = "згадали пізніше";
          answer.appendChild(mark);
        }
        answer.appendChild(document.createTextNode(part.text));
        attachVoicePlayback(answer, part.voice);
        box.appendChild(answer);
      });

      var tools = document.createElement("div");
      tools.className = "history-tools";
      var add = document.createElement("button");
      add.className = "ghost small";
      add.textContent = "Додати до цього питання";
      tools.appendChild(add);
      box.appendChild(tools);

      var editor = document.createElement("div");
      editor.className = "history-add";
      var field = document.createElement("textarea");
      field.rows = 3;
      field.setAttribute("aria-label", "Що ще згадали про це питання");

      // Диктувати — другий спосіб заповнити те саме поле. На цьому екрані
      // дозволені обидва способи: текст і голос, на відміну від самого
      // інтервʼю, де відповідь виключно голосом.
      var dictateTools = document.createElement("div");
      dictateTools.className = "history-add-tools";
      var dictate = document.createElement("button");
      dictate.type = "button";
      dictate.className = "ghost small";
      dictate.textContent = "🎙 Диктувати";
      var recognizer = null;
      var base = "";
      // Записи цього доповнення. Явно свій масив, а не спільний
      // `session.pending_voice`: людина могла зупинити запис на поточному
      // питанні, зайти сюди дописати щось інше — і той запис ще чекає
      // свого /api/answer. Спільний список забрав би його собі.
      var appendVoiceNames = [];
      var micStream = null;
      var recorder = window.ITAudio
        ? window.ITAudio.createRecorder(function () { return micStream; })
        : null;

      function stopDictate() {
        if (recognizer) { try { recognizer.stop(); } catch (e) { /* уже стоїть */ } }
        recognizer = null;
        dictate.textContent = "🎙 Диктувати";
        dictate.classList.remove("active");
        if (!micStream) return;
        var stream = micStream;
        micStream = null;
        var finish = function (blob) {
          stream.getTracks().forEach(function (t) { t.stop(); });
          if (!blob || !blob.size || !state.sessionId) return;
          fetch("/api/voice?session_id=" + encodeURIComponent(state.sessionId), {
            method: "POST",
            headers: { "Content-Type": blob.type || "audio/webm" },
            body: blob
          }).then(function (r) { return r.json(); }).then(function (data) {
            if (data.clip) appendVoiceNames.push(data.clip);
          }).catch(function () { /* текст лишається — сам запис не критичний */ });
        };
        if (recorder) recorder.stop(finish); else finish(null);
      }
      dictate.addEventListener("click", function () {
        if (recognizer) { stopDictate(); return; }
        var Ctor = recognitionCtor();
        if (!Ctor) {
          dictate.disabled = true;
          dictate.title = "Мікрофон недоступний у цьому браузері";
          return;
        }
        base = field.value;
        recognizer = new Ctor();
        recognizer.lang = langTag();
        recognizer.continuous = true;
        recognizer.interimResults = true;
        recognizer.onresult = function (event) {
          var finalChunk = "", interimChunk = "";
          for (var i = event.resultIndex; i < event.results.length; i++) {
            var chunk = event.results[i][0].transcript;
            if (event.results[i].isFinal) finalChunk += chunk; else interimChunk += chunk;
          }
          if (finalChunk) base = (base + " " + finalChunk).trim();
          field.value = (base + " " + interimChunk).trim();
        };
        recognizer.onerror = function () { stopDictate(); };
        recognizer.onend = function () { if (recognizer) stopDictate(); };
        try {
          recognizer.start();
          dictate.textContent = "⏹ Зупинити";
          dictate.classList.add("active");
        } catch (e) { stopDictate(); return; }

        // Паралельно з розпізнаванням пишемо сам звук — так само, як у
        // головному потоці: голос має зберігатись, а не лише ставати текстом.
        if (state.recordVoice && state.voiceConsent && recorder && navigator.mediaDevices) {
          navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
            // Диктування могли зупинити, поки браузер питав дозвіл.
            if (!recognizer) { stream.getTracks().forEach(function (t) { t.stop(); }); return; }
            micStream = stream;
            recorder.start();
          }).catch(function () { /* без запису — диктувати все одно можна */ });
        }
      });
      dictateTools.appendChild(dictate);

      var actions = document.createElement("div");
      actions.className = "actions";
      var save = document.createElement("button");
      save.className = "primary";
      save.textContent = "Додати";
      var cancel = document.createElement("button");
      cancel.className = "ghost";
      cancel.textContent = "Скасувати";
      actions.appendChild(save);
      actions.appendChild(cancel);
      editor.appendChild(field);
      editor.appendChild(dictateTools);
      editor.appendChild(actions);
      box.appendChild(editor);

      add.addEventListener("click", function () {
        editor.classList.add("open");
        add.disabled = true;
        field.focus();
      });
      cancel.addEventListener("click", function () {
        stopDictate();
        appendVoiceNames = [];
        editor.classList.remove("open");
        add.disabled = false;
        field.value = "";
      });
      save.addEventListener("click", function () {
        stopDictate();
        var text = field.value.trim();
        if (!text) return;
        save.disabled = true;
        post("/api/append", {
          session_id: state.sessionId, index: item.index, text: text,
          voice: appendVoiceNames
        }).then(function (data) {
          renderProgress(data.progress);
          renderChecklist(data.checklist);
          refreshActions();
          drawHistory(data.items || []);
        }).catch(function (err) {
          save.disabled = false;
          field.setAttribute("aria-invalid", "true");
          setStatus("Не вдалося додати: " + err.message, true);
        });
      });

      host.appendChild(box);
    });
  }

  /* Живої перевірки більше немає — свідомо.

     Вона ставила галочки, поки людина говорить: модель оцінювала кожен пункт
     («чи можна з цього дізнатися ось це?»). Мірка показала, чого це варте: на
     контрольному наборі 64-71 % і одна з трьох помилок сорту «відповідь поруч,
     але не та» (`app/interview/judge.py`). Галочка, якій не можна вірити, гірша
     за її відсутність: вона обіцяє облік, якого немає, і на ній трималось
     рішення «чи можна далі».

     Тепер чекліст — шпаргалка: ось про що варто сказати. Перехід між питаннями
     робить сама людина. Код оцінювача лишається (`/api/draft`, `judge.py`,
     `bin/judge_eval.py`) — він потрібен просторам без сценарію й як інструмент
     дослідника, але в цьому потоці не викликається.

     Знято звідси: `scheduleCheck`, `runCheck`, `resetCheck`, `setChecking`. */

  /* Дії не зʼявляються й не зникають — вони вимикаються. Кнопки, що виникають
     з нічого, неможливо вивчити: людина не знає, що взагалі доступно. Тому
     доступність і підказка оновлюються з одного місця після кожної зміни. */
  function refreshActions() {
    var text = state.mode !== "voice" ? el("answer").value : state.finalText;
    var words = countWords(text);
    var has = words > 0;

    if (state.mode === "voice") {
      // Підпис головної кнопки залежить від наявності тексту, тому оновлюється
      // тут, а не лише при старті/зупинці запису.
      if (state.phase !== "listening") {
        el("talk-label").textContent = has ? "Продовжити" : "Говорити";
        el("talk-icon").textContent = "▶";
      }
      // Надіслати — щойно є що надсилати. Сказане голосом не редагується
      // текстом, тому єдина альтернатива — стерти й почати заново.
      var sendBtn = el("btn-send-answer");
      if (sendBtn) sendBtn.disabled = state.busy || !has;
      el("btn-voice-again").disabled = state.busy || !has;
      // Навігація вгорі — лише в сценарному режимі: у вільній розмові кроку
      // немає, наступне питання ставить сама модель у відповідь на репліку.
      var nav = el("voice-confirm");
      if (nav) nav.classList.toggle("hidden", !state.scripted);
      el("btn-next").disabled = state.busy || !(has || state.answered);
      el("btn-prev").disabled = state.busy || state.atStart;
      renderWordProgress();
    } else {
      el("btn-send").disabled = state.busy || !canSend(words);
      renderExpectationText(words);
    }
  }

  /* Обсяг відповіді словами. Не гейт, а орієнтир: поріг — очікування, а не
     заборона. «Шість людей» чи «Оля» — валідні відповіді. Смуга стоїть при
     самому тексті відповіді, а не при чеклісті: це про те, що людина щойно
     сказала, а не про питання. */
  function renderWordProgress() {
    var bar = el("word-progress");
    if (!bar) return;
    // Смуга видима завжди, навіть на нулі: людина мусить бачити мету
    // (скільки слів очікується) ще ДО того, як почала говорити, а не лише
    // тоді, коли вже щось сказала.
    bar.classList.remove("hidden");
    var whole = countWords(wholeAnswer());
    var met = whole >= state.expectedWords;
    bar.classList.toggle("met", met);
    var pct = Math.round(Math.min(1, whole / state.expectedWords) * 100);
    el("word-fill").style.width = pct + "%";
    var label = whole + " " + plural(whole, "слово", "слова", "слів");
    el("word-detail").textContent = met
      ? label + " — розгорнута відповідь."
      : label + " із приблизно " + state.expectedWords + " — можна ще розкрити.";
  }

  /* Текстовий резерв (без мікрофона): та сама підказка про обсяг, своїм рядком
     біля поля вводу, бо там немає окремої смуги під чеклістом. */
  function renderExpectationText(words) {
    var node = el("expectation-text");
    if (!node) return;
    if (!words) {
      node.textContent = "Кілька речень із деталями — приблизно " +
        state.expectedWords + " слів.";
      node.className = "expectation";
    } else if (words >= state.expectedWords) {
      node.textContent = words + " " + plural(words, "слово", "слова", "слів") +
        " — цього достатньо.";
      node.className = "expectation met";
    } else {
      node.textContent = words + " " + plural(words, "слово", "слова", "слів") +
        " з приблизно " + state.expectedWords +
        ". Надіслати можна вже зараз, але деталі допомагають.";
      node.className = "expectation";
    }
  }

  function refreshSend() {
    refreshActions();
  }

  function showScreen(name) {
    ["consent", "interview", "summary", "done"].forEach(function (key) {
      el("screen-" + key).classList.toggle("hidden", key !== name);
    });
    // Розкладка на всю висоту вікна — тільки на інтервʼю: там питання
    // прокручується, а кнопка запису стоїть і не виїжджає під згин. Екран
    // згоди лишається в звичайному потоці, бо його треба дочитати до кінця.
    var shell = document.querySelector(".shell");
    if (shell) shell.classList.toggle("shell-fixed", name === "interview");
  }

  function plural(count, one, few, many) {
    var mod10 = count % 10;
    var mod100 = count % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
    return many;
  }

  /* Тримання розповіді: інтервʼюер НІЧОГО не каже. Питання лишається на
     екрані, поле відповіді очищається, і людина просто продовжує додавати.
     Раніше тут звучало «Ага» — у покроковому інтерфейсі це читається як
     окреме питання, і збиває: людина думає, що її про щось спитали. */
  function renderHold(progress, checklist, message) {
    renderProgress(progress);
    renderChecklist(checklist);
    // (порядок важливий: renderChecklist читає фазу, яку щойно поставив
    //  renderProgress — від неї залежить підпис списку)
    //
    // Питання те саме, отже сказане лишається на екрані: воно переходить із
    // «нового» у «вже надіслане» й показується приглушеним. Раніше екран тут
    // порожнів, і людина губила нитку власної розповіді.
    state.sentText = (state.sentText + " " + state.finalText).trim();
    clearSegments();
    state.interim = "";
    renderHeard("");
    refreshActions();
    setStatus(message || "Продовжуйте — розкажіть далі.");
  }

  /* Прогрес підписом фази, а не номером теми: у фазі розповіді тем немає
     взагалі, і «Тема 1 з 10» там не значить нічого. */
  /* Чекліст очікуваного: людина бачить, чого від неї чекають, і що вже
     зараховано. Це те саме, що вело уточнення всередині — просто видиме. */
  function renderChecklist(items) {
    var box = el("checklist");
    var list = el("checklist-items");
    if (!items || !items.length) {
      box.classList.add("hidden");
      list.innerHTML = "";
      state.checklistItems = [];
      return;
    }
    list.innerHTML = "";
    items.forEach(function (item) {
      var li = document.createElement("li");
      // Просто перелік. Кружечок-галочка був чекбоксом, а чекбокс обіцяє
      // «оце зараховано напевно» — обіцянка, якої оцінювач не витримує
      // (64-71 % на контрольному наборі, див. app/interview/judge.py). Тому
      // маркер списку, а не позначка стану: пункт, який ми вже почули, лише
      // світлішає кольором.
      if (item.done) li.className = "done";
      li.textContent = item.text;
      list.appendChild(li);
    });
    // У фазі розповіді галочка означає «згадали», а не «розповіли вичерпно»:
    // саме так її розуміє рушій — згадану побіжно тему він відкриває питанням
    // рівня 2 «до конкретики», як просить гайд. Підпис мусить казати те саме,
    // інакше галочка обіцяє більше, ніж означає.
    var title = el("checklist-title-text");
    if (title) {
      // Це план, а не облік: «про що варто сказати», не «що зараховано».
      title.textContent = state.interviewPhase === "narrative"
        ? "Про що варто розповісти:"
        : "Про що варто сказати:";
    }
    // Число пунктів прибрано: список і так видно весь одразу, і лічильник
    // поруч із заголовком лише дублював те, що очі вже читають рядками.

    // Довгий список — у дві колонки. Під час вільної розповіді чекліст — це
    // мапа всіх десяти тем; одним стовпцем вона займала більше екрана, ніж
    // саме питання.
    list.classList.toggle("two-cols", items.length > 6);
    box.classList.remove("hidden");
    state.checklistItems = items;
  }

  /* Прогрес — кроки, не суцільна смуга. Кожен крок несе власну лічбу: скільки
     в ньому питань і на скільки вже відповіли — а не позицію курсора, яку
     легко сплутати з «зроблено». У вільній розповіді (без сценарію) лічби
     немає — там рух видно по чеклісту тем, і крок показує лише назву фази. */
  function renderProgress(progress) {
    if (!progress) return;
    if (progress.phase) state.interviewPhase = progress.phase;
    if (typeof progress.at_start === "boolean") state.atStart = progress.at_start;
    if (typeof progress.at_end === "boolean") state.atEnd = progress.at_end;
    if (typeof progress.answered === "boolean") state.answered = progress.answered;
    state.scripted = !!progress.scripted;
    state.depth = progress.depth || null;
    // Останнє питання: кнопка каже, що буде далі, — інакше людина не знає, що
    // натискає завершення розмови.
    var next = el("btn-next");
    if (next) next.textContent = state.atEnd ? "Завершити інтервʼю" : "Наступне питання →";

    var host = el("progress-sections");
    var sections = progress.sections || [];
    if (host) {
      host.innerHTML = "";
      sections.forEach(function (sec) {
        var title = sec && typeof sec === "object" ? sec.title : sec;
        var total = (sec && sec.total) || 0;
        var answered = (sec && sec.answered) || 0;
        var isCurrent = !!(sec && sec.current);
        var isDone = total > 0 && answered >= total && !isCurrent;

        var li = document.createElement("li");
        li.className = "step" + (isCurrent ? " now" : "") + (isDone ? " done" : "");

        var row = document.createElement("span");
        row.className = "step-row";
        var dot = document.createElement("span");
        dot.className = "step-dot";
        row.appendChild(dot);
        var label = document.createElement("span");
        label.className = "step-name";
        label.textContent = title;
        row.appendChild(label);
        if (total > 0) {
          var count = document.createElement("span");
          count.className = "step-count";
          count.textContent = answered + "/" + total;
          row.appendChild(count);
        }
        li.appendChild(row);

        var track = document.createElement("span");
        track.className = "step-track";
        var fill = document.createElement("i");
        fill.style.width = total > 0
          ? Math.round(Math.min(1, answered / total) * 100) + "%"
          : (isDone ? "100%" : "0%");
        track.appendChild(fill);
        li.appendChild(track);

        if (isCurrent) li.setAttribute("aria-current", "step");
        host.appendChild(li);
      });
    }

    var detail = el("progress-detail");
    if (detail) detail.textContent = progress.detail || "";
  }

  /* Одне місце, де малюється питання: старт і крок віддають однакову форму. */
  function renderQuestion(data) {
    if (!data) return;
    renderUtterance(data.utterance, data.progress, data.audio_url, data.checklist);
    // Повернувшись назад, людина мусить бачити свою відповідь, а не порожнє
    // поле: інакше «попереднє» виглядає як «почати заново».
    state.sentText = (data.said || []).join(" ").trim();
    renderHeard("");
    syncOwnVoice(data.voice);
    refreshActions();
  }

  function renderUtterance(text, progress, audioUrl, checklist) {
    el("utterance-text").textContent = text;
    renderProgress(progress);
    renderChecklist(checklist);
    // Нове питання читається з початку: інакше область лишалась прокрученою
    // з попереднього ходу й людина бачила середину тексту.
    var scroller = el("interview-scroll");
    if (scroller) scroller.scrollTop = 0;
    // Нове питання — нова відповідь: і сказане, і записи попередньої вже
    // прикріплені до свого ходу.
    state.sentText = "";
    clearSegments();
    state.interim = "";
    renderHeard("");
    dropOwnVoice();
    refreshActions();
    // Нове питання знімає перехідні повідомлення. Інакше під кнопкою висіло
    // «Думаю…» уже тоді, коли людина читає наступне питання.
    setStatus("");
    state.lastAudioUrl = audioUrl || null;
    // Озвучення доступне, якщо є запис репліки або налаштований синтез.
    state.audioAvailable = !!audioUrl || state.ttsMode !== "none";
    setAudioBar(state.audioAvailable, false);
    if (state.audioAvailable) prefetchAudio(audioUrl);

    // Автовідтворення — лише якщо простір цього просить. За замовчуванням
    // питання лишається текстом, і респондент сам вирішує, слухати чи ні:
    // так не треба чекати синтез, щоб почати відповідати.
    if (state.autoplay) listenToQuestion();
  }

  function listenToQuestion() {
    // Готове з попереднього синтезу — граємо одразу, без запиту й очікування.
    if (state.prefetch) {
      stopAudio();
      setAudioBar(true, true);
      setStatus("");
      // blobUrl НЕ передаємо: звільнить його наступне питання, а до того
      // повторне прослуховування має бути таким само миттєвим.
      startPlayback(new Audio(state.prefetch.url), null);
      return;
    }
    if (state.lastAudioUrl) {
      var url = state.lastAudioUrl;
      playRecorded(url + (url.indexOf("?") === -1 ? "?t=" : "&t=") + Date.now());
    } else {
      speakQuestion(el("utterance-text").textContent);
    }
  }

  /* Смужка під питанням має три стани: «можна прослухати», «читаю» і
     «озвучення недоступне». Питання при цьому завжди на екрані текстом —
     голос лише на вимогу. */
  function setAudioBar(available, speaking) {
    state.speaking = !!speaking;
    el("audio-bar").classList.toggle("hidden", !available);
    if (!available) return;
    el("audio-dot").classList.toggle("hidden", !speaking);
    el("btn-listen").classList.toggle("hidden", !!speaking);
    el("btn-stop-speak").classList.toggle("hidden", !speaking);
    el("audio-text").textContent = speaking ? "Читаю питання…" : "Питання можна прослухати";
  }

  function setSpeakingUI(speaking) {
    setAudioBar(state.audioAvailable, speaking);
  }

  function afterSpeaking() {
    setAudioBar(state.audioAvailable, false);
    // Кнопку мікрофона більше не блокуємо на час читання: натискання «Говорити»
    // саме перебиває голос (див. startListening). Тримати людину замкненою на
    // 13 секунд, поки дочитається питання, — це та сама неповага, від якої ми
    // намагаємось позбавитись у самому інтервʼю.
    el("btn-talk").disabled = false;
    if (state.phase !== "listening") {
      setStatus(state.mode === "voice" ? "Натисніть «Говорити» і відповідайте." : "");
    }
  }

  /* Зупинка читання на вимогу: голос замовкає, мікрофон вільний. */
  function stopReading(quiet) {
    if (!state.speaking) return;
    stopSpeaking();
    setAudioBar(state.audioAvailable, false);
    el("btn-talk").disabled = false;
    if (!quiet && state.phase !== "listening") {
      setStatus("");
    }
  }

  /* Записаний людський голос: аудіо вже лежить на сервері, синтез не потрібен.
     Це не оптимізація — у режимі банку інтервʼюер узагалі не має синтезу. */
  function playRecorded(url) {
    stopAudio();
    setSpeakingUI(true);
    setStatus("");
    startPlayback(new Audio(url), null);
  }

  /* Попередній синтез: аудіо готується у фоні одразу, як прийшло питання.
     Автовідтворення при цьому НЕ вмикається — просто до моменту натискання
     файл уже готовий, і затримка нульова. */
  function prefetchAudio(audioUrl) {
    // Blob попереднього питання більше не потрібен — звільняємо саме тут,
    // а не після відтворення: інакше повторне «Прослухати» знову чекало б синтез.
    if (state.prefetch && state.prefetch.blobUrl) URL.revokeObjectURL(state.prefetch.blobUrl);
    state.prefetch = null;
    state.prefetchFor = null;
    if (audioUrl) {
      // Записана репліка: браузер сам покладе її в кеш.
      var probe = new Audio(audioUrl);
      probe.preload = "auto";
      state.prefetch = { url: audioUrl, blobUrl: null };
      state.prefetchFor = audioUrl;
      return;
    }
    if (state.ttsMode !== "server") return;

    var forSession = state.sessionId;
    fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: forSession })
    }).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.blob();
    }).then(function (blob) {
      // Питання могло змінитись, поки синтезувалось — тоді результат зайвий.
      if (state.sessionId !== forSession) return;
      var url = URL.createObjectURL(blob);
      state.prefetch = { url: url, blobUrl: url };
      state.prefetchFor = "server";
    }).catch(function () {
      state.prefetch = null;
    });
  }

  function startPlayback(audio, blobUrl) {
    state.audio = audio;
    applyRate(audio);
    var done = false;
    function finish(silent) {
      if (done) return;
      done = true;
      if (blobUrl) URL.revokeObjectURL(blobUrl);
      state.audioFinish = null;
      if (!silent) afterSpeaking();
    }
    state.audioFinish = function () { finish(true); };
    audio.addEventListener("ended", function () { finish(false); });
    audio.addEventListener("error", function () { finish(false); });
    // Сторож: якщо аудіо не почалось або подія не прийшла, респондент не має
    // залишитись без можливості відповісти.
    window.setTimeout(function () { finish(false); }, 90000);
    audio.play().catch(function () { finish(false); });
  }

  /* Серверне озвучення. Текст у запиті НЕ передається — сервер сам бере останнє
     питання цієї сесії (інакше ендпоінт став би безкоштовним TTS-проксі). */
  function serverSpeak() {
    stopAudio();
    setSpeakingUI(true);
    setStatus("");

    fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId })
    }).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.blob();
    }).then(function (blob) {
      var url = URL.createObjectURL(blob);
      startPlayback(new Audio(url), url);
    }).catch(function () {
      // Не змогли озвучити — питання лишається на екрані текстом.
      setStatus("Не вдалося озвучити питання — прочитайте його, будь ласка.", true);
      afterSpeaking();
    });
  }

  function stopAudio() {
    if (state.audio) {
      try { state.audio.pause(); } catch (e) { /* уже зупинено */ }
      state.audio = null;
    }
    if (state.audioFinish) state.audioFinish();
  }

  function speakQuestion(text) {
    if (state.ttsMode === "server") { serverSpeak(); return; }
    if (state.ttsMode !== "browser" || !state.speaker) return;

    setSpeakingUI(true);
    setStatus("");
    state.speaker.speak(text, { onEnd: afterSpeaking });
  }

  function stopSpeaking() {
    if (state.speaker) state.speaker.stop();
    stopAudio();
  }

  /* ── вибір голосу ──────────────────────────────────────────────────── */

  function buildVoiceChoice() {
    if (!window.ITAudio || !window.speechSynthesis) return;
    if (!state.space.voice || state.space.voice.tts !== "browser") return;

    var voices = window.ITAudio.listVoices(langTag());
    if (voices.length < 2) {
      // Один голос — вибирати нема з чого, і фальшивий вибір гірший за його
      // відсутність. Скільки голосів реально є, видно в панелі дослідника.
      return;
    }

    var host = el("voice-options");
    host.innerHTML = "";
    voices.forEach(function (voice) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "voice-option" + (voice.name === state.voiceName ? " active" : "");
      button.appendChild(document.createTextNode(voice.name));
      var hint = document.createElement("span");
      hint.className = "try";
      hint.textContent = "прослухати";
      button.appendChild(hint);
      button.addEventListener("click", function () {
        state.voiceName = voice.name;
        remember(voiceKey(), voice.name);
        if (state.speaker) state.speaker.setVoiceName(voice.name);
        Array.prototype.forEach.call(host.children, function (node) {
          node.classList.toggle("active", node === button);
        });
        if (state.speaker) {
          state.speaker.speak("Добрий день. Я поставлю кілька питань про ваш досвід.", {});
        }
      });
      host.appendChild(button);
    });
    el("voice-choice").classList.remove("hidden");
  }

  /* ── мережа ────────────────────────────────────────────────────────── */

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.error || ("HTTP " + response.status));
        return data;
      });
    });
  }

  /* ── сценарій ──────────────────────────────────────────────────────── */

  function describeCapabilities() {
    var parts = [];
    if (recognitionCtor()) {
      parts.push("🎙 Мікрофон доступний.");
    } else {
      parts.push("⌨️ Цей браузер не розпізнає мовлення — інтервʼю пройде текстом (Chrome вміє).");
    }
    if (state.space.repertoire === "bank") {
      parts.push("🔊 Питання можна прослухати записаним людським голосом.");
    } else if (state.ttsMode !== "none") {
      parts.push("🔊 Питання можна прослухати.");
    }
    el("capabilities").textContent = parts.join(" ");
  }

  function loadSpace() {
    return fetch("/api/space").then(function (r) { return r.json(); }).then(function (space) {
      state.space = space;
      state.mode = (space.interface && space.interface.mode) || "text";
      state.autoplay = !!(space.interface && space.interface.autoplay);
      state.expectedWords = (space.interface && space.interface.expected_words) || 15;
      state.recordVoice = !!(space.interface && space.interface.record_voice);
      state.minWordsToCredit =
        (space.interface && space.interface.min_words_to_credit) || 3;
      // Галочку показуємо лише там, де простір справді просить запис.
      el("record-consent").classList.toggle("hidden", !state.recordVoice);
      // Де запис пропонують — без згоди на нього не почати: голос неможливо
      // деідентифікувати, тому це не другорядна дрібниця, а умова старту.
      el("btn-consent").disabled = state.recordVoice && !el("chk-record").checked;
      document.title = space.title;
      el("consent-title").textContent = space.title;
      el("consent-text").textContent = space.consent_text ||
        "Розмова записується у вигляді тексту і використовується для дослідження.";
      // Лише світла тема: у темній --accent і --on-accent підібрані парою
      // під контраст WCAG (кожен --accent там світліший, а --on-accent —
      // темний текст саме під нього), і підміна тільки кольору тла лишила б
      // текст на кнопці нечитабельним. Дефолт теми в обох темах уже
      // сумісний, тож тут просто не чіпаємо темну.
      if (space.accent && !window.matchMedia("(prefers-color-scheme: dark)").matches) {
        document.documentElement.style.setProperty("--accent", space.accent);
      }

      var tts = space.tts || {};
      var ttsProvider = (space.voice && space.voice.tts) || "none";
      state.ttsMode = ttsProvider === "browser"
        ? "browser"
        : (ttsProvider === "none" ? "none" : "server");

      state.voiceName = recall(voiceKey()) || tts.voice || null;
      if (state.ttsMode === "browser" && window.speechSynthesis && window.ITAudio) {
        state.speaker = window.ITAudio.createSpeaker({
          lang: langTag(),
          voiceName: state.voiceName,
          rate: (tts.rate || 0.97) * effectiveRate(),
          pitch: tts.pitch || 1.0,
          gap: tts.gap == null ? 140 : tts.gap
        });
      }
      refreshActions();
      describeCapabilities();

      // Голоси приходять асинхронно — інакше перший вибір буде порожній.
      if (window.speechSynthesis) {
        window.speechSynthesis.getVoices();
        window.speechSynthesis.addEventListener
          ? window.speechSynthesis.addEventListener("voiceschanged", buildVoiceChoice)
          : (window.speechSynthesis.onvoiceschanged = buildVoiceChoice);
        window.setTimeout(buildVoiceChoice, 350);
      }
    });
  }

  function prepareInputMode() {
    var voiceRequested = state.mode === "voice";
    var canListen = !!recognitionCtor() && state.space.voice.stt === "browser";

    if (voiceRequested && !canListen) {
      fallbackToText("Голосовий режим недоступний у цьому браузері — відповідайте текстом.");
      return;
    }

    if (voiceRequested) {
      el("voice-area").classList.remove("hidden");
      el("answer-area").classList.add("hidden");
      el("heard").setAttribute("data-placeholder",
        "Тут з'явиться текст того, що ви скажете.");
      state.recognition = initRecognition();
      if (window.ITAudio) {
        state.waveform = window.ITAudio.createWaveform(el("wave"));
        // Той самий потік мікрофона, що й у доріжки: три споживачі одного
        // пристрою (розпізнавання, доріжка, записувач) — це збої, які потім не
        // відтворюються.
        state.recorder = window.ITAudio.createRecorder(function () {
          return state.waveform && state.waveform.stream();
        });
      }
    } else {
      el("voice-area").classList.add("hidden");
      el("answer-area").classList.remove("hidden");
      state.recognition = canListen ? initRecognition() : null;
      if (!state.recognition) {
        el("btn-mic").disabled = true;
        el("mic-label").textContent = "Мікрофон недоступний";
      }
    }
  }

  function enterInterview(data) {
    state.sessionId = data.session_id;
    state.startPayload = data;
    // Записи, які вже лежать на сервері для незавершеної відповіді.
    setTimeout(function () { syncOwnVoice(data.voice); }, 0);
    // Згоду підтверджує сервер, а не браузер: після перезавантаження сторінки
    // вона мусить братися з сесії, а не з галочки, якої вже ніхто не бачить.
    state.voiceConsent = !!data.voice_consent;
    remember(storeKey(), data.session_id);
    prepareInputMode();
    showScreen("interview");
    renderQuestion(data);
    if (state.mode === "text") el("answer").focus();
  }

  function begin() {
    el("btn-consent").disabled = true;
    if (window.speechSynthesis) window.speechSynthesis.getVoices();
    var wantsRecord = state.recordVoice && el("chk-record").checked;
    post("/api/start", { record_voice: wantsRecord })
      .then(enterInterview).catch(function (err) {
      el("btn-consent").disabled = false;
      el("capabilities").textContent = "Не вдалося почати: " + err.message;
    });
  }

  function resume() {
    el("btn-resume").disabled = true;
    if (window.speechSynthesis) window.speechSynthesis.getVoices();
    post("/api/resume", { session_id: recall(storeKey()) }).then(enterInterview)
      .catch(function (err) {
        forget(storeKey());
        el("resume-box").classList.add("hidden");
        el("start-box").classList.remove("hidden");
        el("capabilities").textContent = "Продовжити не вдалося: " + err.message;
      });
  }

  function offerResume() {
    var id = recall(storeKey());
    if (!id) return Promise.resolve();
    return post("/api/resume", { session_id: id }).then(function (data) {
      el("resume-detail").textContent = data.answered
        ? ("Ви відповіли на " + data.answered + " " +
           plural(data.answered, "питання", "питання", "питань") +
           ". Можна продовжити з того самого місця.")
        : "Можна продовжити з того місця, де ви зупинились.";
      el("resume-box").classList.remove("hidden");
      el("start-box").classList.add("hidden");
    }).catch(function () {
      forget(storeKey());
    });
  }

  /* Те, що піде на сервер цим ходом: лише НОВЕ. Надіслане вже в транскрипті,
     і відправити його вдруге означало б подвоїти репліку. */
  function currentAnswer() {
    if (state.mode !== "voice") return el("answer").value.trim();
    return state.finalText.trim();
  }

  /* Уся відповідь на це питання — надіслане плюс нове. Саме її оцінює жива
     перевірка: для чекліста це одна відповідь, хоч і сказана в кілька заходів. */
  function wholeAnswer() {
    return (state.sentText + " " + currentAnswer()).trim();
  }

  /* Крок сценарієм. Сказане зберігається САМО: губити відповідь через
     натискання «наступне»/«попереднє» неприпустимо, навіть якщо людина
     забула натиснути «Надіслати відповідь» — це підстраховка, не заміна їй. */
  function step(delta) {
    if (state.busy) return;
    if (state.phase === "listening") stopListening();
    keepInterim();
    stopSpeaking();
    setSpeakingUI(false);
    stopOwnVoice();

    var pending = currentAnswer();
    state.busy = true;
    refreshActions();
    setStatus(pending ? "Зберігаю…" : "");

    var saved = pending
      ? post("/api/answer", { session_id: state.sessionId, text: pending })
      : Promise.resolve(null);

    saved.then(function () {
      return post("/api/step", { session_id: state.sessionId, delta: delta });
    }).then(function (data) {
      state.busy = false;
      state.phase = "idle";
      renderQuestion(data);
      setStatus("");
    }).catch(function (err) {
      state.busy = false;
      refreshActions();
      // Сказане не втрачаємо: людина не має переказувати відповідь через збій.
      setStatus(err.message + " Сказане збережено — спробуйте ще раз.", true);
    });
  }

  /* Надіслати відповідь. У сценарному режимі це «зберегти» й «далі» за одну
     дію: людина щойно сказала, що готова, і повторно тягнутись до «Наступне»
     зайве. Кнопки «Попереднє»/«Наступне» вгорі лишаються для навігації без
     нового запису. У вільній розповіді сервер сам вирішує, тримати питання чи
     поставити наступне — це і є `data.hold`/нове питання. */
  function submitAnswer() {
    if (state.busy) return;
    if (state.phase === "listening") stopListening();
    keepInterim();
    var text = currentAnswer();
    if (!text) return;
    stopSpeaking();
    setSpeakingUI(false);
    stopOwnVoice();

    state.busy = true;
    refreshActions();
    setStatus("Надсилаю…");

    post("/api/answer", { session_id: state.sessionId, text: text })
      .then(function (data) {
        state.busy = false;
        if (data.recorded) {
          // Надіслати в сценарії — це «зберегти» й «далі» за одну дію: після
          // явного «Надіслати» не змушуємо ще раз тягнутись до «Наступного».
          // На останньому питанні «далі» нікуди немає — туди й показуємо
          // підсумок, а не порожнє питання.
          syncOwnVoice(data.voice);
          state.sentText = (state.sentText + " " + state.finalText).trim();
          clearSegments();
          state.interim = "";
          renderHeard("");
          renderProgress(data.progress);
          renderChecklist(data.checklist);
          refreshActions();
          if (state.atEnd) showSummary(); else step(1);
          return;
        }
        if (data.done) {
          forget(storeKey());
          el("done-text").textContent = data.utterance;
          showScreen("done");
          return;
        }
        if (data.hold) {
          syncOwnVoice(data.voice);
          renderHold(data.progress, data.checklist);
          return;
        }
        renderQuestion(data);
      }).catch(function (err) {
        state.busy = false;
        refreshActions();
        setStatus(err.message + " Сказане лишилось на екрані — спробуйте ще раз.", true);
      });
  }

  /* Останнє питання сценарію: перш ніж завершити розмову, показуємо підсумок
     — скільки відповіли й наскільки розгорнуто. Фінал (`/api/finish`) —
     окрема дія людини з того екрана, не наслідок кліку «Наступне». */
  function finishFlow() {
    if (state.busy) return;
    var pending = currentAnswer();
    if (!pending) { showSummary(); return; }
    state.busy = true;
    refreshActions();
    setStatus("Зберігаю…");
    post("/api/answer", { session_id: state.sessionId, text: pending })
      .then(function (data) {
        state.busy = false;
        if (data.progress) state.depth = data.progress.depth || state.depth;
        state.sentText = (state.sentText + " " + state.finalText).trim();
        clearSegments();
        state.interim = "";
        renderHeard("");
        refreshActions();
        setStatus("");
        showSummary();
      }).catch(function (err) {
        state.busy = false;
        refreshActions();
        setStatus(err.message + " Сказане збережено — спробуйте ще раз.", true);
      });
  }

  function showSummary() {
    var depth = state.depth || {};
    // Підсумок — тільки коли справді відповіли на все. «0 із 25» тут
    // означало б, що курсор долетів до кінця сценарію без жодної відповіді
    // (збій мережі, помилка навігації) — людину тоді просто лишаємо на
    // питанні, яке насправді ще не відповіли, а не лякаємо нулем.
    if (depth.total && depth.answered < depth.total) {
      showScreen("interview");
      setStatus("Спершу відповідь на це питання.", true);
      return;
    }
    var node = el("summary-depth");
    if (node) {
      node.textContent = depth.total
        ? ("Ви відповіли на " + depth.answered + " із " + depth.total + " " +
           plural(depth.total, "питання", "питання", "питань") +
           (depth.avg_words
             ? (", у середньому " + depth.avg_words + " " +
                plural(Math.round(depth.avg_words), "слово", "слова", "слів") +
                " на відповідь.")
             : "."))
        : "Дякуємо за розмову.";
    }
    // Колір замість того, щоб рахувати середнє слів очима: зелений — так само
    // розгорнуто, як цінує сама смуга обсягу над мікрофоном (--good/--warn).
    var quality = el("summary-quality");
    if (quality) {
      var avg = depth.avg_words || 0;
      if (!depth.total || !avg) {
        quality.classList.add("hidden");
      } else {
        var tier = avg >= state.expectedWords ? "good"
                 : avg >= state.expectedWords / 2 ? "warn" : "low";
        var labels = { good: "Розгорнуті відповіді", warn: "Помірно розгорнуті",
                       low: "Стислі відповіді" };
        quality.className = "summary-quality tier-" + tier;
        el("summary-quality-label").textContent = labels[tier];
      }
    }
    showScreen("summary");
  }

  /* ── події ─────────────────────────────────────────────────────────── */

  el("btn-consent").addEventListener("click", begin);
  el("chk-record").addEventListener("change", function () {
    el("btn-consent").disabled = state.recordVoice && !el("chk-record").checked;
  });
  el("btn-resume").addEventListener("click", resume);
  el("btn-restart").addEventListener("click", function () {
    forget(storeKey());
    el("resume-box").classList.add("hidden");
    el("start-box").classList.remove("hidden");
  });

  el("btn-talk").addEventListener("click", function () {
    if (state.phase === "listening") stopListening(); else startListening();
  });
  el("btn-next").addEventListener("click", function () {
    if (state.atEnd) finishFlow(); else step(1);
  });
  el("btn-prev").addEventListener("click", function () { step(-1); });
  el("btn-send-answer").addEventListener("click", submitAnswer);
  el("btn-voice-again").addEventListener("click", function () {
    // Стирається те, що ще не пішло. Надіслане вже в транскрипті — прибрати
    // його звідси означало б збрехати про те, що є в даних.
    clearSegments();
    state.interim = "";
    renderHeard("");
    // Текст стерто — галочки й запис голосу мусять зникнути разом із ним.
    // Файли видаляє сервер: людина сказала «цього не було».
    dropOwnVoice();
    refreshActions();
    startListening();
  });
  el("btn-play-own").addEventListener("click", playOwnVoice);
  el("btn-history").addEventListener("click", openHistory);
  el("btn-history-close").addEventListener("click", closeHistory);
  el("btn-listen").addEventListener("click", listenToQuestion);
  el("btn-stop-speak").addEventListener("click", function () { stopReading(false); });

  // Escape глушить голос: очікувана дія, і не треба шукати кнопку очима.
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && state.speaking) stopReading(false);
  });

  el("btn-send").addEventListener("click", submitAnswer);
  el("btn-mic").addEventListener("click", function () {
    if (state.phase === "listening") stopListening(); else startListening();
  });
  el("answer").addEventListener("input", refreshSend);
  el("answer").addEventListener("keydown", function (event) {
    // Ctrl/Cmd+Enter надсилає: Enter лишається переносом рядка, бо люди
    // диктують довгі відповіді й тиснуть Enter посеред думки.
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") submitAnswer();
  });

  el("btn-summary-send").addEventListener("click", function () {
    if (state.busy) return;
    state.busy = true;
    el("btn-summary-send").disabled = true;
    post("/api/finish", { session_id: state.sessionId }).then(function (data) {
      state.busy = false;
      forget(storeKey());
      el("done-text").textContent = data.utterance;
      showScreen("done");
    }).catch(function (err) {
      state.busy = false;
      el("btn-summary-send").disabled = false;
      el("summary-depth").textContent = "Не вдалося надіслати: " + err.message;
    });
  });
  el("btn-summary-add").addEventListener("click", function () { openHistory(true); });
  el("btn-summary-restart").addEventListener("click", function () {
    forget(storeKey());
    el("resume-box").classList.add("hidden");
    el("start-box").classList.remove("hidden");
    el("btn-consent").disabled = state.recordVoice && !el("chk-record").checked;
    showScreen("consent");
  });

  loadSpace().then(offerResume).catch(function (err) {
    el("capabilities").textContent = "Не вдалося завантажити конфіг: " + err.message;
  });
})();
