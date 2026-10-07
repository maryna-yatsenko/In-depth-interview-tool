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
  // Простір із посилання (?space=<key>): сервер може обслуговувати кілька
  // просторів одночасно (адмінка дає лінк на кожен окремо), і без цього
  // параметра всі посилання вели б у той самий простір, з яким запущено
  // сервер. Порожньо — сервер бере свій дефолтний (деплой на один простір,
  // де параметра ніхто й не додає): поведінка лишається такою ж, як була.
  var SPACE_KEY = new URLSearchParams(location.search).get("space") || "";
  function withSpace(url) {
    if (!SPACE_KEY) return url;
    var sep = url.indexOf("?") === -1 ? "?" : "&";
    return url + sep + "space=" + encodeURIComponent(SPACE_KEY);
  }
  // Заповнює watchBottomSpace() нижче. Окрема змінна, а не виклик напряму:
  // showScreen() (значно вище за файлом) теж має її смикати одразу після
  // того, як нижній блок стає видимим — саме на цьому переході
  // ResizeObserver один раз не спрацював (був ще прихований батьківський
  // екран, коли підписка щойно ставилась).
  var recalcBottomSpace = function () {};

  /* Векторні іконки замість емодзі: однаковий вигляд у всіх системах і
     шрифтах (емодзі-рендер відрізняється між ОС), колір бере з тексту
     навколо (currentColor), а не свій власний. Розмір/відступ — у .icon
     (styles.css), тут лише розмітка. Рядки статичні (нема підстановок
     користувацького тексту), тому їх безпечно ставити через innerHTML. */
  var ICONS = {
    play: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4l13 8-13 8V4z"/></svg>',
    stop: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>',
    speaker: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9v6h4l5 5V4L8 9H4z"/><path d="M16.5 8.5a5 5 0 0 1 0 7"/><path d="M19.5 5.5a9 9 0 0 1 0 13"/></svg>',
    mic: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></svg>',
    redo: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7"/><polyline points="3 3 3 8 8 8"/></svg>',
    keyboard: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="6" width="20" height="12" rx="2"/><line x1="6" y1="10" x2="6.01" y2="10"/><line x1="10" y1="10" x2="10.01" y2="10"/><line x1="14" y1="10" x2="14.01" y2="10"/><line x1="18" y1="10" x2="18.01" y2="10"/><line x1="6" y1="14" x2="18" y2="14"/></svg>',
    // Обличчя, а не абстрактна крапка кольору: підсумок про те, наскільки
    // розгорнуто відповідали, читається одразу, ще до тексту підпису.
    faceGood: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M8.5 10.5h.01M15.5 10.5h.01"/><path d="M8 14.5q4 3.5 8 0"/></svg>',
    faceWarn: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M8.5 10.5h.01M15.5 10.5h.01"/><line x1="8" y1="15" x2="16" y2="15"/></svg>',
    faceLow: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M8.5 10.5h.01M15.5 10.5h.01"/><circle cx="12" cy="15" r="1.4" fill="currentColor" stroke="none"/></svg>'
  };

  var state = {
    sessionId: null,
    space: null,
    mode: "text",
    phase: "idle",        // idle | listening | review | speaking
    finalText: "",        // розпізнане й підтверджене
    recognition: null,
    waveform: null,
    audio: null,          // <audio>, яким грається запис питання
    audioFinish: null,    // прибирання blob-у, якщо зупинили ззовні
    lastAudioUrl: null,   // адреса запису поточного питання (людський голос)
    expectedWords: 15,
    audioAvailable: false,
    autoplay: false,      // за замовчуванням питання лишається текстом
    prefetch: null,       // {url, blobUrl} — готове аудіо поточного питання
    prefetchFor: null,
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
    if (state.speaking ||
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
      el("talk-icon").innerHTML = listening ? ICONS.stop : ICONS.play;
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
    fetch(withSpace("/api/voice?session_id=" + encodeURIComponent(state.sessionId)), {
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
    btn.innerHTML = ICONS.speaker + " Прослухати";
    var player = null;
    function stop() {
      if (player) { try { player.pause(); } catch (e) { /* уже стоїть */ } player = null; }
      btn.innerHTML = ICONS.speaker + " Прослухати";
    }
    btn.addEventListener("click", function () {
      if (player) { stop(); return; }
      var index = 0;
      player = new Audio();
      btn.innerHTML = ICONS.stop + " Зупинити";
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
    shown.forEach(function (item, index) {
      var box = document.createElement("div");
      box.className = "history-item";

      var question = document.createElement("p");
      question.className = "history-q";
      // Номер — щоб було видно, яке це за рахунком питання в розмові, а не
      // лише «десь серед раніше сказаного».
      var num = document.createElement("span");
      num.className = "history-q-num";
      num.textContent = (index + 1) + ".";
      question.appendChild(num);
      question.appendChild(document.createTextNode(" " + item.question));
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
        // "Додано пізніше" тепер каже лише колір обводки (styles.css,
        // .history-a.added) — текстова позначка над відповіддю не несла
        // окремого сенсу, лише дублювала колір словами.
        if (part.added) answer.className += " added";
        // Обводка зліва — на внутрішній обгортці, не на самому <p>: інакше
        // вона тяглася б і крізь padding-bottom до пунктирної лінії знизу,
        // і розрив між сірим/фіолетовим відрізком на межі двох відповідей
        // був би непомітний (лінія й так пофарбована, просто іншим кольором).
        var inner = document.createElement("div");
        inner.className = "history-a-inner";
        inner.appendChild(document.createTextNode(part.text));
        attachVoicePlayback(inner, part.voice);
        answer.appendChild(inner);
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
      dictate.innerHTML = ICONS.mic + " Диктувати";
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
        dictate.innerHTML = ICONS.mic + " Диктувати";
        dictate.classList.remove("active");
        if (!micStream) return;
        var stream = micStream;
        micStream = null;
        var finish = function (blob) {
          stream.getTracks().forEach(function (t) { t.stop(); });
          if (!blob || !blob.size || !state.sessionId) return;
          fetch(withSpace("/api/voice?session_id=" + encodeURIComponent(state.sessionId)), {
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
          dictate.innerHTML = ICONS.stop + " Зупинити";
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
      actions.appendChild(cancel);
      actions.appendChild(save);
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
        el("talk-icon").innerHTML = ICONS.play;
      }
      // Надіслати — щойно є що надсилати. Сказане голосом не редагується
      // текстом, тому єдина альтернатива — стерти й почати заново.
      var sendBtn = el("btn-send-answer");
      if (sendBtn) sendBtn.disabled = state.busy || !has;
      el("btn-voice-again").disabled = state.busy || !has;
      // Навігація вгорі — лише в сценарному режимі: у вільній розмові кроку
      // немає, наступне питання ставить сама модель у відповідь на репліку.
      // «Раніше сказане» стоїть у тому ж ряду, тож ховаємо лише стрілки.
      ["btn-prev", "btn-next"].forEach(function (id) {
        var node = el(id);
        if (node) node.classList.toggle("hidden", !state.scripted);
      });
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
    recalcBottomSpace();
  }

  /* Один вихід на екран подяки з двох різних місць (вільна розповідь
     дійшла кінця сама / людина явно натиснула «Надіслати мої відповіді») —
     щоб скидання форми відгуку не забули додати лише в одному з них. */
  function finishToDoneScreen(utterance) {
    forget(storeKey());
    el("done-text").textContent = utterance;
    resetFeedbackForm();
    showScreen("done");
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
  /* Згорнути/розгорнути памʼятку: людина може прибрати її з очей. Стан живе, поки відкрита
     сторінка, і діє на всі питання. */
  function setChecklistCollapsed(collapsed) {
    state.checklistCollapsed = collapsed;
    var box = el("checklist");
    var toggle = el("checklist-toggle");
    if (box) box.classList.toggle("collapsed", collapsed);
    if (toggle) toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
  }

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
    setChecklistCollapsed(!!state.checklistCollapsed);
    state.checklistItems = items;
  }

  /* Прогрес — кроки, не суцільна смуга. Кожен крок несе власну лічбу: скільки
     в ньому питань і на скільки вже відповіли — а не позицію курсора, яку
     легко сплутати з «зроблено». У вільній розповіді (без сценарію) лічби
     немає — там рух видно по чеклісту тем, і крок показує лише назву фази. */
  var NEXT_ARROW = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>';

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
    if (next) {
      // Далі — стрілка без підпису. Лише на останньому питанні кнопці
      // повертається підпис: це вже не «далі», а завершення розмови.
      next.classList.toggle("is-finish", !!state.atEnd);
      next.setAttribute("aria-label", state.atEnd ? "Завершити інтервʼю" : "Наступне питання");
      next.title = state.atEnd ? "Завершити інтервʼю" : "Наступне питання";
      next.innerHTML = state.atEnd ? "Завершити інтервʼю" : NEXT_ARROW;
    }

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
    // Озвучення доступне, лише якщо дослідник записав це питання голосом.
    state.audioAvailable = !!audioUrl;
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
    // Без "Питання можна прослухати" в стані спокою: кнопка поруч і так
    // очевидно про це каже, підпис лише дублював. "Читаю питання…" лишили —
    // це стан, а не пояснення очевидного. Приховуємо порожній підпис (не
    // лише textContent = "") — інакше він, навіть порожній, лишається
    // окремим елементом рядка й gap між елементами відсуває кнопку праворуч.
    el("audio-text").classList.toggle("hidden", !speaking);
    el("audio-text").textContent = speaking ? "Читаю питання…" : "";
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

  /* Попереднє прогрівання кешу: щойно прийшло питання із записом, браузер
     одразу починає його вантажити — тоді натискання «Прослухати» грає без
     затримки. */
  function prefetchAudio(audioUrl) {
    // Blob попереднього питання більше не потрібен — звільняємо саме тут,
    // а не після відтворення: інакше повторне «Прослухати» знову чекало б.
    if (state.prefetch && state.prefetch.blobUrl) URL.revokeObjectURL(state.prefetch.blobUrl);
    state.prefetch = null;
    state.prefetchFor = null;
    if (!audioUrl) return;
    // Записана репліка: браузер сам покладе її в кеш.
    var probe = new Audio(audioUrl);
    probe.preload = "auto";
    state.prefetch = { url: audioUrl, blobUrl: null };
    state.prefetchFor = audioUrl;
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

  function stopAudio() {
    if (state.audio) {
      try { state.audio.pause(); } catch (e) { /* уже зупинено */ }
      state.audio = null;
    }
    if (state.audioFinish) state.audioFinish();
  }

  function stopSpeaking() {
    stopAudio();
  }

  /* ── мережа ────────────────────────────────────────────────────────── */

  function post(url, body) {
    return fetch(withSpace(url), {
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
      parts.push(ICONS.mic + " Мікрофон доступний.");
    } else {
      parts.push(ICONS.keyboard + " Цей браузер не розпізнає мовлення — інтервʼю пройде текстом (Chrome вміє).");
    }
    if (state.space.repertoire === "bank") {
      parts.push(ICONS.speaker + " Питання можна прослухати записаним людським голосом.");
    }
    el("capabilities").innerHTML = parts.join(" ");
  }

  /* Тема — той самий трек-тогл (сонце/місяць) із рухомою пігулкою, що й у
     кабінеті дослідника (.theme-switch/.theme-btn, admin.js), лише прибитий
     до кута екрана (styles.css). data-theme стоїть на <html> (document
     Element), бо змінні лежать на :root, не на <body>, як в адмінці. */
  function currentTheme() {
    return document.documentElement.dataset.theme ||
      (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }
  function initThemeSwitch() {
    var lightBtn = el("btn-theme-light");
    var darkBtn = el("btn-theme-dark");
    var switchEl = document.querySelector(".theme-switch");
    if (!lightBtn || !darkBtn || !switchEl) return;
    var KEY = "interview-theme";
    function paint() {
      var now = currentTheme();
      lightBtn.classList.toggle("active", now === "light");
      darkBtn.classList.toggle("active", now === "dark");
      switchEl.dataset.active = now;
    }
    function apply(theme) {
      document.documentElement.dataset.theme = theme;
      try { localStorage.setItem(KEY, theme); } catch (e) { /* приватний режим — ігнор */ }
      paint();
    }
    var saved = null;
    try { saved = localStorage.getItem(KEY); } catch (e) { /* ігнор */ }
    if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
    paint();
    lightBtn.addEventListener("click", function () { apply("light"); });
    darkBtn.addEventListener("click", function () { apply("dark"); });
  }
  initThemeSwitch();

  /* Перша сторінка форми. Якщо Вітання гайда — вступ (opening_intro), саме воно й є текстом
     цієї сторінки: абзаци до рядка «Що важливо знати» — вступ, рядки під ним — пункти картки.
     Інакше — текст згоди простору й типова картка «Що важливо знати». */
  function renderFirstPage(space) {
    var note = el("privacy-note");
    var list = el("privacy-note-list");
    var intro = String((space.opening_intro && space.opening) || "").trim();
    if (!intro) {
      el("consent-text").textContent = space.consent_text ||
        "Розмова записується у вигляді тексту і використовується для дослідження.";
      return;
    }
    var heading = intro.match(/^\s*Що важливо знати\s*:?\s*$/im);
    var head = heading ? intro.slice(0, heading.index) : intro;
    var tail = heading ? intro.slice(heading.index + heading[0].length) : "";
    el("consent-text").textContent = head.trim();
    var points = tail.split(/\r?\n/).map(function (line) {
      return line.replace(/^\s*(?:[-•*–—]|\d+[.)])\s*/, "").trim();
    }).filter(Boolean);
    list.innerHTML = "";
    points.forEach(function (text) {
      var li = document.createElement("li");
      li.textContent = text;
      list.appendChild(li);
    });
    note.classList.toggle("hidden", !points.length);
  }

  function loadSpace() {
    return fetch(withSpace("/api/space")).then(function (r) { return r.json(); }).then(function (space) {
      state.space = space;
      state.mode = (space.interface && space.interface.mode) || "text";
      state.autoplay = !!(space.interface && space.interface.autoplay);
      state.expectedWords = (space.interface && space.interface.expected_words) || 15;
      state.recordVoice = !!(space.interface && space.interface.record_voice);
      // Галочку показуємо лише там, де простір справді просить запис.
      el("record-consent").classList.toggle("hidden", !state.recordVoice);
      // Де запис пропонують — без згоди на нього не почати: голос неможливо
      // деідентифікувати, тому це не другорядна дрібниця, а умова старту.
      syncStartButton();
      document.title = space.title;
      el("consent-title").textContent = space.title;
      renderFirstPage(space);
      // Кастомний акцент простору (space.accent) свідомо ігноруємо: сторінка
      // респондента завжди показує стандартний фіолетовий, в обох темах —
      // те саме поле в адмінці згодом приберуть як застаріле.
      state.feedbackStyle = ["emoji", "hearts", "numbers"].indexOf(space.feedback_style) >= 0
        ? space.feedback_style : "stars";
      // Вигляд тексту питання задає дослідник (адмінка → «Вигляд питань»).
      document.documentElement.setAttribute("data-q-size", space.question_font_size || "medium");
      document.documentElement.setAttribute("data-q-weight", space.question_font_weight || "regular");
      el("feedback-title").textContent = space.feedback_prompt ||
        "Як вам було проходити це інтервʼю?";
      applyFeedbackStyle();

      refreshActions();
      describeCapabilities();
    });
  }

  // Зірочки заливаються кумулятивно (1-2-3 з 5), смайлики — питання про
  // емоцію, а не про «скільки»: підсвічується лише один вибраний, як
  // група радіо-кнопок, якою цей контрол уже й позначений в розмітці.
  var FEEDBACK_EMOJI = ["😞", "🙁", "😐", "🙂", "😄"];

  var FEEDBACK_LABELS = ["Дуже погано", "Погано", "Нормально", "Добре", "Чудово"];
  var FEEDBACK_HEART = '<svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" ' +
    'stroke-linejoin="round" aria-hidden="true"><path d="M12 21s-7.5-4.6-9.6-9.1C.9 8.6 2.8 5 6.2 5c2 0 3.3 1 3.8 2.1h4C14.5 6 15.8 5 17.8 5c3.4 0 5.3 3.6 3.8 6.9C19.5 16.4 12 21 12 21z"/></svg>';

  function applyFeedbackStyle() {
    // Стиль фіксується один раз при завантаженні сторінки (loadSpace
    // викликається лише тут, при старті) — повертати SVG назад нема
    // потреби, це не перемикач посеред сесії.
    var style = state.feedbackStyle;
    ["emoji", "hearts", "numbers"].forEach(function (name) {
      el("feedback-stars").classList.toggle(name + "-mode", style === name);
    });
    document.querySelectorAll(".feedback-star").forEach(function (star) {
      var value = Number(star.dataset.value);
      if (style === "emoji") {
        star.innerHTML = '<span class="fe">' + (FEEDBACK_EMOJI[value - 1] || "") + '</span>' +
          '<span class="fl">' + (FEEDBACK_LABELS[value - 1] || "") + '</span>';
      }
      else if (style === "numbers") star.textContent = String(value);
      else if (style === "hearts") star.innerHTML = FEEDBACK_HEART;
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
    // Плавна поява нижньої панелі (styles.css, .reveal) — окремим кроком,
    // не одразу: рендер вище (прогрес-бар, чекліст, текст питання) важкий
    // і синхронний, і якби анімація стартувала на цьому самому кадрі,
    // перші її кадри губились би, і поява виглядала б різкою. Подвійний
    // rAF — не один: перший спрацьовує ще до того, як браузер устиг
    // розкласти щойно відрендерене (клас додався б у той самий кадр, що й
    // uncover); другий гарантовано йде вже після реального layout/paint.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        var panel = el(state.mode === "voice" ? "voice-area" : "answer-area");
        if (panel) panel.classList.add("reveal");
      });
    });
  }

  // ПІБ — умова старту так само, як згода на запис голосу: без нього кнопка
  // лишається заблокованою.
  function syncStartButton() {
    var missingConsent = state.recordVoice && !el("chk-record").checked;
    var missingName = !el("respondent-name").value.trim();
    el("btn-consent").disabled = missingConsent || missingName;
  }

  function begin() {
    el("btn-consent").disabled = true;
    var wantsRecord = state.recordVoice && el("chk-record").checked;
    var respondentName = el("respondent-name").value.trim();
    post("/api/start", { record_voice: wantsRecord, respondent_name: respondentName })
      .then(enterInterview).catch(function (err) {
      syncStartButton();
      el("capabilities").textContent = "Не вдалося почати: " + err.message;
    });
  }

  function resume() {
    el("btn-resume").disabled = true;
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
      // Ім'я вже збережене на відновлюваній сесії — поле для нового вводу
      // тут лише плутало б.
      el("name-field").classList.add("hidden");
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
          finishToDoneScreen(data.utterance);
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
        // Сама назва тіру нічого не каже респонденту, навіщо йому це бачити
        // й що з цим робити — підказка внизу відповідає на обидва питання,
        // і для "good" теж: без неї виглядало б, ніби чогось бракує.
        var hints = {
          good: "Дослідник отримає багато деталей — дякуємо за розгорнуту розповідь.",
          warn: "Непогано. Якщо є що додати — це можна зробити нижче, кнопкою «Додати ще щось».",
          low: "Відповіді вийшли короткими. За бажання розкрийте їх детальніше — кнопкою «Додати ще щось» нижче."
        };
        var icons = { good: "faceGood", warn: "faceWarn", low: "faceLow" };
        quality.className = "summary-quality tier-" + tier;
        el("summary-quality-icon").innerHTML = ICONS[icons[tier]];
        el("summary-quality-label").textContent = labels[tier];
        el("summary-quality-hint").textContent = hints[tier];
      }
    }
    showScreen("summary");
  }

  /* ── події ─────────────────────────────────────────────────────────── */

  el("btn-consent").addEventListener("click", begin);
  el("chk-record").addEventListener("change", syncStartButton);
  el("respondent-name").addEventListener("input", syncStartButton);
  el("btn-resume").addEventListener("click", resume);
  el("checklist-toggle").addEventListener("click", function () {
    setChecklistCollapsed(!state.checklistCollapsed);
  });
  el("btn-restart").addEventListener("click", function () {
    forget(storeKey());
    el("resume-box").classList.add("hidden");
    el("start-box").classList.remove("hidden");
    el("name-field").classList.remove("hidden");
    syncStartButton();
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
      finishToDoneScreen(data.utterance);
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
    el("name-field").classList.remove("hidden");
    syncStartButton();
    showScreen("consent");
  });

  /* Відгук про сам досвід проходження — екран «Дякую». Необовʼязково: жодна
     зірка не мусить бути обрана, кнопка «Надіслати» вмикається, щойно є
     оцінка АБО коментар (щось одне вже має сенс відправляти). */
  (function () {
    var stars = Array.prototype.slice.call(document.querySelectorAll(".feedback-star"));
    var comment = el("feedback-comment");
    var sendBtn = el("btn-feedback-send");
    if (!stars.length || !comment || !sendBtn) return;

    function paint(upTo) {
      stars.forEach(function (star) {
        var value = Number(star.dataset.value);
        // Зірки — заливка кумулятивна («3 з 5» лишає підсвіченими 1,2,3);
        // смайлики — обране почуття, а не кількість, тому підсвічується
        // лише один, обраний саме зараз.
        var single = state.feedbackStyle === "emoji" || state.feedbackStyle === "numbers";
        var filled = single ? value === upTo : value <= upTo;
        star.classList.toggle("is-filled", filled);
      });
    }
    stars.forEach(function (star) {
      star.addEventListener("mouseenter", function () { paint(Number(star.dataset.value)); });
      star.addEventListener("click", function () {
        state.feedbackRating = Number(star.dataset.value);
        paint(state.feedbackRating);
        refreshFeedbackSend();
      });
    });
    el("feedback-stars").addEventListener("mouseleave", function () {
      paint(state.feedbackRating || 0);
    });

    function refreshFeedbackSend() {
      sendBtn.disabled = !state.feedbackRating && !comment.value.trim();
    }
    comment.addEventListener("input", refreshFeedbackSend);

    sendBtn.addEventListener("click", function () {
      sendBtn.disabled = true;
      post("/api/feedback", {
        session_id: state.sessionId,
        rating: state.feedbackRating || null,
        comment: comment.value.trim()
      }).then(function () {
        el("feedback-block").classList.add("hidden");
        el("feedback-thanks").classList.remove("hidden");
      }).catch(function (err) {
        sendBtn.disabled = false;
        el("feedback-status").textContent = "Не вдалося надіслати: " + err.message;
      });
    });
    el("btn-feedback-skip").addEventListener("click", function () {
      el("feedback-block").classList.add("hidden");
    });
  })();

  /* Скидання перед кожним новим показом екрана «Дякую» (finishToDoneScreen):
     без цього повторне інтервʼю в тій самій вкладці показало б минулу
     оцінку чи вимкнену кнопку «Надіслати» від попереднього разу. */
  function resetFeedbackForm() {
    state.feedbackRating = 0;
    document.querySelectorAll(".feedback-star").forEach(function (star) {
      star.classList.remove("is-filled");
    });
    var comment = el("feedback-comment");
    if (comment) comment.value = "";
    var sendBtn = el("btn-feedback-send");
    if (sendBtn) sendBtn.disabled = true;
    el("feedback-status").textContent = "";
    el("feedback-block").classList.remove("hidden");
    el("feedback-thanks").classList.add("hidden");
  }

  /* Нижній блок (voice-area/answer-area) — абсолютний, прибитий до низу
     (styles.css), тому фізично не займає місця в потоці. Прокрутна зона
     питання відступає від нього на його висоту + невеликий запас
     (margin, не padding — інакше довге питання могло б доскролитись
     впритул до чекліста без жодного проміжку). Висота міняється (чекліст,
     помилки, смуга «читаю») — тому стежимо, а не рахуємо один раз при
     завантаженні. */
  var BOTTOM_GAP = 24;
  function watchBottomSpace() {
    var targets = [el("voice-area"), el("answer-area")].filter(Boolean);
    if (!targets.length) return;
    var apply = function () {
      var height = 0;
      targets.forEach(function (t) { height = Math.max(height, t.offsetHeight); });
      document.documentElement.style.setProperty("--bottom-space", (height + BOTTOM_GAP) + "px");
    };
    recalcBottomSpace = apply;
    if (window.ResizeObserver) {
      var observer = new ResizeObserver(apply);
      targets.forEach(function (t) { observer.observe(t); });
    } else {
      window.addEventListener("resize", apply);
    }
    /* ResizeObserver сам по собі не завжди встигає: чекліст і текст відповіді
       дозаповнюються асинхронно вже після появи екрана, і бувало, що саме цю
       зміну висоти він пропускав (--bottom-space застигав на проміжному
       значенні). MutationObserver на вміст цих блоків — підстраховка, що
       перераховує на будь-яку зміну DOM усередині, а не лише на власний resize. */
    if (window.MutationObserver) {
      var mutationObserver = new MutationObserver(apply);
      targets.forEach(function (t) {
        mutationObserver.observe(t, { childList: true, subtree: true, characterData: true, attributes: true });
      });
    }
    apply();
  }
  watchBottomSpace();

  /* ── DESIGN-CANVAS: стани за URL ─────────────────────────────────────
     `?canvas=<стан>` приводить сторінку в названий стан через ТОЙ САМИЙ API й ті самі функції, що й
     людина (старт, відповіді, кроки) — нічого не малюється окремо. Працює лише на localhost.
     Стани: consent, consent-filled, resume, q-first, q-mid, q-last, history-empty, history-list,
     summary, done, done-thanks. Суфікс `-dark` вмикає темну тему.
     DELETE WITH: the design-canvas/ folder (canvas-app/), разом із цим блоком. */
  function applyCanvasPin(pin) {
    var host = window.location.hostname;
    if (host !== "localhost" && host !== "127.0.0.1") return offerResume();
    if (/-dark$/.test(pin)) {
      pin = pin.replace(/-dark$/, "");
      document.documentElement.setAttribute("data-theme", "dark");
    }
    forget(storeKey());
    var sample = "Це була дуже цікава ситуація, я добре її памʼятаю і можу розповісти детальніше про те, що саме відбувалося тоді.";
    if (pin === "consent") return Promise.resolve();
    if (pin === "consent-filled") {
      el("respondent-name").value = "Олена Коваленко";
      var chk = el("chk-record");
      if (chk && !el("record-consent").classList.contains("hidden")) chk.checked = true;
      syncStartButton();
      return Promise.resolve();
    }
    return post("/api/start", { record_voice: false, respondent_name: "Олена Коваленко" }).then(function (started) {
      if (pin === "resume") {
        return post("/api/answer", { session_id: started.session_id, text: sample }).then(function () {
          remember(storeKey(), started.session_id);
          return offerResume();
        });
      }
      var total = (started.progress && started.progress.depth && started.progress.depth.total) || 4;
      var goal = { "q-first": 0, "history-empty": 0, "q-mid": 1, "q-mid-folded": 1, "q-last": total - 1, "history-list": 2, "summary": total, "done": total, "done-thanks": total,
        "done-numbers": total, "done-hearts": total, "done-emoji": total,
        "done-drum": total, "done-stars-4": total, "done-emoji-4": total, "done-hearts-4": total }[pin];
      if (goal === undefined) return Promise.resolve();
      var chain = Promise.resolve({ started: started, last: null });
      var i;
      function answerOne(prev) {
        return post("/api/answer", { session_id: started.session_id, text: sample }).then(function (ans) {
          return { started: started, last: ans };
        });
      }
      function stepOne(prev) {
        return post("/api/step", { session_id: started.session_id, delta: 1 }).then(function (nxt) {
          return { started: started, last: nxt };
        });
      }
      for (i = 0; i < goal; i++) {
        (function (index) {
          chain = chain.then(answerOne);
          if (index < total - 1) chain = chain.then(stepOne);
        })(i);
      }
      return chain.then(function (res) {
        var atSummary = goal >= total;
        enterInterview(res.last && !atSummary && res.last.utterance
          ? Object.assign({ session_id: started.session_id }, res.last) : started);
        state.sessionId = started.session_id;
        if (atSummary) {
          renderProgress(res.last.progress);
          state.depth = (res.last.progress && res.last.progress.depth) || state.depth;
          showSummary();
          if (/^done/.test(pin)) {
            return post("/api/finish", { session_id: started.session_id }).then(function (fin) {
              finishToDoneScreen(fin.utterance);
              if (pin === "done-drum") document.documentElement.setAttribute("data-canvas-hold", "drum");
              var variant = /^done-(numbers|hearts|emoji)(-4)?$/.exec(pin);
              if (variant) { state.feedbackStyle = variant[1]; applyFeedbackStyle(); }
              // Вибір четвертої оцінки справжнім кліком: видно вибраний стан рейтингу.
              if (/-4$/.test(pin)) {
                var fourth = document.querySelector('.feedback-star[data-value="4"]');
                if (fourth) fourth.click();
              }
              if (pin === "done-thanks") {
                el("feedback-block").classList.add("hidden");
                el("feedback-thanks").classList.remove("hidden");
              }
            });
          }
        }
        if (pin === "history-empty" || pin === "history-list") openHistory();
        if (pin === "q-mid-folded") setChecklistCollapsed(true);
      });
    });
  }

  var canvasPin = new URLSearchParams(window.location.search).get("canvas");
  loadSpace().then(function () {
    if (!canvasPin) return offerResume();
    /* Сигнал для capture.mjs: стан застосовано (контракт design-canvas). */
    return applyCanvasPin(canvasPin).then(function () {
      document.documentElement.setAttribute("data-canvas-pinned", canvasPin);
    });
  }).catch(function (err) {
    el("capabilities").textContent = "Не вдалося завантажити конфіг: " + err.message;
  });
})();
