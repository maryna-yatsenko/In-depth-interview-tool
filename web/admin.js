/* Панель дослідника: простори, гайди, транскрипти.
 *
 * Сенс цього екрана — щоб методологію правила людина, а не редактор JSON.
 * Валідація тут навмисне мінімальна: істина на сервері, він перевіряє тим самим
 * завантажувачем, що й реальне інтервʼю, і повертає зрозумілу помилку.
 */

(function () {
  "use strict";

  var el = function (id) { return document.getElementById(id); };
  var state = { spaces: [], space: null, guide: null, guideData: null, spaceData: null,
                trash: [], runs: [] };
  var accentSwatchPaint = function () {};
  var setRailCollapsed = function () {};

  /* Векторні іконки замість емодзі — розмітка статична (нема користувацького
     тексту всередині SVG), тому innerHTML для НИХ безпечний; де поруч стоїть
     текст із конфігу/транскрипту (space.error, incident.detail тощо), той
     текст завжди йде окремим text-вузлом (createTextNode), а не в цей рядок. */
  var ICONS = {
    ban: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    lock: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="11" width="16" height="9" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
    alertTriangle: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l10 18H2L12 3z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12" y2="17.01"/></svg>',
    shield: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6l7-3z"/></svg>',
    dot: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="12" r="4"/></svg>',
    star: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2.5l3.09 6.26L22 9.77l-5 4.87 1.18 6.86L12 18.27l-6.18 3.23L7 14.64l-5-4.87 6.91-1.01L12 2.5z"/></svg>',
    mic: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></svg>',
    stop: '<svg class="icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>',
    trash: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>',
    restore: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>',
    chevronUp: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="18 15 12 9 6 15"/></svg>',
    chevronDown: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>',
    check: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><polyline points="8 12.5 11 15.5 16 9.5"/></svg>',
    alertCircle: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="13"/><line x1="12" y1="16" x2="12" y2="16.01"/></svg>',
    folder: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/></svg>',
    close: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/></svg>'
  };

  /* ── допоміжне ─────────────────────────────────────────────────────── */

  function api(path, options) {
    return fetch(path, options).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.error || ("HTTP " + response.status));
        return data;
      });
    });
  }

  function post(path, body) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  }

  function flash(message, kind) {
    var node = el("save-flash");
    node.textContent = message;
    node.className = "flash " + (kind || "");
    if (message) setTimeout(function () { node.textContent = ""; node.className = "flash"; }, 4000);
  }

  /* Посилання на форму респондента — з ?space=<key> поточного дослідження:
     respondent-сторінка й API тепер уміють приймати цей параметр (інакше
     завжди йшли б у той простір, з яким запущено сервер, — незалежно від
     того, яке дослідження зараз відкрите в адмінці). */
  function copyRespondentLink() {
    var url = location.origin + "/?space=" + encodeURIComponent(state.space || "");
    var btn = el("btn-copy-link");
    var tip = btn.querySelector(".tooltip");
    if (!(navigator.clipboard && navigator.clipboard.writeText)) {
      flash("Копіювання недоступне в цьому браузері", "bad");
      return;
    }
    navigator.clipboard.writeText(url).then(function () {
      btn.classList.add("copied");
      tip.textContent = "Скопійовано";
      setTimeout(function () {
        btn.classList.remove("copied");
        tip.textContent = "Скопіювати";
      }, 2000);
    }).catch(function () { flash("Не вдалося скопіювати посилання", "bad"); });
  }

  var lines = {
    toText: function (list) { return (list || []).join("\n"); },
    fromText: function (text) {
      return (text || "").split("\n").map(function (s) { return s.trim(); })
        .filter(function (s) { return s.length; });
    }
  };

  /* ── простори ──────────────────────────────────────────────────────── */

  function renderSpaces() {
    var list = el("space-list");
    list.innerHTML = "";
    el("rail-space-count").textContent = state.spaces.length;
    state.spaces.forEach(function (space) {
      var li = document.createElement("li");
      var button = document.createElement("button");
      button.className = state.space === space.key ? "active" : "";
      button.innerHTML = ICONS.folder;

      var text = document.createElement("span");
      text.className = "space-list-text";
      text.appendChild(document.createTextNode(space.title || space.key));
      if (space.draft) {
        var tag = document.createElement("span");
        tag.className = "draft-tag";
        tag.textContent = "чернетка";
        text.appendChild(tag);
      }
      if (space.created_at) {
        var created = document.createElement("span");
        created.className = "space-date";
        created.textContent = formatDate(space.created_at);
        text.appendChild(created);
      }
      if (space.error) {
        var sub = document.createElement("span");
        sub.className = "sub broken";
        sub.innerHTML = ICONS.ban;
        sub.appendChild(document.createTextNode(" " + space.error));
        text.appendChild(sub);
      }
      button.appendChild(text);
      button.addEventListener("click", function () { selectSpace(space.key); });
      li.appendChild(button);
      list.appendChild(li);
    });
  }

  // Єдине місце статусу — клікабельний чіп у шапці сторінки; поля-
  // перемикача в картці "Дослідження" більше нема, і draft читається/
  // пишеться прямо в state.spaceData.
  function renderStatusChip(draft) {
    el("status-select").classList.remove("hidden");
    var status = el("page-status");
    status.className = "status-chip status-trigger " + (draft ? "draft" : "live");
    status.querySelector(".status-chip-icon").innerHTML = draft ? ICONS.alertCircle : ICONS.check;
    status.querySelector(".status-chip-label").textContent = draft ? "Чернетка" : "Опубліковано";
    Array.prototype.forEach.call(el("status-panel").querySelectorAll(".status-option"), function (opt) {
      opt.classList.toggle("selected", (opt.dataset.draft === "true") === !!draft);
    });
  }

  function selectSpace(key) {
    state.space = key;
    closeDeleteConfirm();
    renderSpaces();
    var space = state.spaces.filter(function (s) { return s.key === key; })[0];

    // Шапка сторінки: яке дослідження зараз відкрите. Дублює виділення в
    // лівій панелі свідомо — там назва обрізана, тут повна.
    el("page-title").textContent = space.title || space.key;
    renderStatusChip(space.draft);

    loadSpaceData();
    if (space.guides && space.guides.length) loadGuide(space.guides[0]);
    else { state.guideData = null; el("guide-topics-list").innerHTML = ""; }
    // Перемикання дослідження, поки відкрита вкладка "Результати", мусить
    // одразу підмінити список — інакше на екрані лишаються запуски
    // попереднього інтервʼю, доки хтось не клацне по вкладці ще раз.
    if (!el("tab-runs").classList.contains("hidden")) loadRuns();
  }

  /* ── гайд ──────────────────────────────────────────────────────────── */

  function loadGuide(key) {
    state.guide = key;
    api("/api/admin/guide?space=" + encodeURIComponent(state.space) +
        "&guide=" + encodeURIComponent(key)).then(function (data) {
      state.guideData = data;
      el("guide-goal").value = data.goal || "";
      el("guide-opening").value = data.opening || "";
      el("guide-closing").value = data.closing || "";
      el("guide-max-turns").value = data.max_turns || 30;
      el("guide-feedback-prompt").value = data.feedback_prompt || "";
      el("guide-feedback-style").value = data.feedback_style || "stars";
      selects.feedbackStyle.refresh();
      renderTopicCards(data.topics || []);
      el("guide-error").textContent = "";
    }).catch(function (err) { el("guide-error").textContent = err.message; });
  }

  /* Питання — картка на тему гайда: текст, який почує респондент
     (ask_if_missed — рівень 1; ask_for_detail — рівень 2, якщо тему лише
     згадали побіжно, необовʼязково), і чекліст must_learn під ним. Раніше
     тут був один текстовий блок, де редагувались лише title/must_learn, а
     саме формулювання питання (ask_if_missed/ask_for_detail) не було видно
     й не редагувалось узагалі — ці два поля тепер саме тому тут головні.

     Ключ (id) не редагується руками — лишається як є для наявних тем,
     генерується за порядком карток для нових (як і раніше генерувався для
     нового простору: «topic-1», «topic-2», …). Поля, яких немає в картці
     (goal, max_probes, shown_as, needs_detail на пункті), — з `_original`,
     який зберігаємо на самій картці при рендері, щоб збереження не змило
     те, чого форма не показує. */
  function mustLearnText(item) {
    return (item && typeof item === "object") ? (item.text || "") : (item || "");
  }

  /* Без голосового ВВОДУ (диктування в текст) узагалі — лише голосове
     ВІДТВОРЕННЯ питання, окремо від тексту (buildRecordableQuestionField
     нижче). Текст тут завжди друкується руками. */
  function buildTextField(opts) {
    var wrap = document.createElement("label");
    wrap.className = "block topic-field";
    wrap.appendChild(document.createTextNode(opts.label));

    var field = document.createElement("textarea");
    field.rows = 2;
    field.className = opts.className;
    field.value = opts.value || "";
    if (opts.placeholder) field.placeholder = opts.placeholder;
    wrap.appendChild(field);

    return wrap;
  }

  /* Номер — позиція пункту в списку, перераховується після кожної зміни
     (як і номери самих питань вище). Перетягувати можна лише за ручку
     (⠿), а не за сам рядок: рядок містить текстове поле, і зробити його
     всього draggable заважало б звичайному виділенню тексту в ньому. */
  function renumberMustLearnItems(list) {
    Array.prototype.forEach.call(list.querySelectorAll(".must-learn-item"), function (row, index) {
      row.querySelector(".must-learn-number").textContent = (index + 1) + ".";
    });
  }

  function wireMustLearnDrag(row, handle) {
    handle.addEventListener("dragstart", function (e) {
      row.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", ""); } catch (err) { /* байдуже */ }
    });
    handle.addEventListener("dragend", function () {
      row.classList.remove("dragging");
      renumberMustLearnItems(row.parentNode);
    });
    row.addEventListener("dragover", function (e) {
      var list = row.parentNode;
      var dragging = list && list.querySelector(".must-learn-item.dragging");
      if (!dragging || dragging === row) return;
      e.preventDefault();
      var rect = row.getBoundingClientRect();
      var before = (e.clientY - rect.top) < rect.height / 2;
      list.insertBefore(dragging, before ? row : row.nextSibling);
    });
  }

  function buildMustLearnRow(text) {
    var row = document.createElement("div");
    row.className = "must-learn-item";

    var handle = document.createElement("span");
    handle.className = "must-learn-handle";
    handle.textContent = "⠿";
    handle.draggable = true;
    handle.title = "Перетягнути, щоб змінити порядок";
    handle.setAttribute("aria-hidden", "true");
    row.appendChild(handle);

    var number = document.createElement("span");
    number.className = "must-learn-number";
    row.appendChild(number);

    var input = document.createElement("input");
    input.type = "text";
    input.value = text || "";
    input.placeholder = "Пункт, який треба зʼясувати";
    row.appendChild(input);

    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "icon-btn must-learn-remove";
    remove.innerHTML = ICONS.close;
    remove.title = "Прибрати пункт";
    remove.addEventListener("click", function () {
      var list = row.parentNode;
      row.remove();
      renumberMustLearnItems(list);
    });
    row.appendChild(remove);

    wireMustLearnDrag(row, handle);
    return row;
  }

  /* Номер картки — саме її позиція серед карток, а не щось збережене в
     темі: перерахувати треба після кожної зміни порядку/кількості, а не
     один раз при рендері. Та сама нагода вимикає «вгору»/«вниз» на краях
     і «видалити» — коли лишилось одне питання. */
  function refreshTopicOrderControls() {
    var cards = document.querySelectorAll(".topic-card");
    Array.prototype.forEach.call(cards, function (card, index) {
      var number = card.querySelector(".topic-number");
      if (number) number.textContent = (index + 1) + ".";
      var remove = card.querySelector(".topic-remove");
      if (remove) remove.disabled = cards.length <= 1;
    });
  }

  /* Порядок питань — попапом, перетягуванням, бачачи лише заголовки: серед
     повних карток (питання, чекліст, запис голосу) стрілки на кожній губились,
     а прокручувати весь гайд, щоб перенести питання на три позиції вище,
     незручно. Тут — легкі рядки-проксі (число + назва), самі картки не
     чіпаються, доки не натиснуто «Готово»: тоді порядок рядків переносимо
     на реальні картки одним проходом. */
  function openTopicOrderModal() {
    var list = el("topic-order-list");
    list.innerHTML = "";
    Array.prototype.forEach.call(document.querySelectorAll(".topic-card"), function (card) {
      var questionInput = card.querySelector(".topic-question-input");
      var label = (questionInput && questionInput.value.trim()) || "(без назви)";
      var row = document.createElement("div");
      row.className = "reorder-row";
      row.draggable = true;
      row._card = card;
      var handle = document.createElement("span");
      handle.className = "reorder-handle";
      handle.textContent = "⠿";
      handle.setAttribute("aria-hidden", "true");
      row.appendChild(handle);
      var text = document.createElement("span");
      text.className = "reorder-title";
      text.textContent = label;
      row.appendChild(text);
      wireReorderRow(row);
      list.appendChild(row);
    });
    renumberReorderRows();
    el("topic-order-modal").classList.remove("hidden");
  }

  function renumberReorderRows() {
    Array.prototype.forEach.call(document.querySelectorAll(".reorder-row"), function (row, index) {
      row.querySelector(".reorder-title").textContent = (index + 1) + ". " + row._label;
    });
  }

  function wireReorderRow(row) {
    // Чиста назва (без номера) — так renumberReorderRows завжди підставляє
    // правильний номер, скільки разів rядки не переставляй.
    row._label = row.querySelector(".reorder-title").textContent;
    row.addEventListener("dragstart", function (e) {
      row.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      // Дані самому drag-подію не потрібні — переносимо вузли напряму;
      // рядок все одно потрібен, щоб Firefox узагалі дозволив drag.
      try { e.dataTransfer.setData("text/plain", ""); } catch (err) { /* байдуже */ }
    });
    row.addEventListener("dragend", function () {
      row.classList.remove("dragging");
      renumberReorderRows();
    });
    row.addEventListener("dragover", function (e) {
      e.preventDefault();
      var dragging = document.querySelector(".reorder-row.dragging");
      if (!dragging || dragging === row) return;
      var rect = row.getBoundingClientRect();
      var before = (e.clientY - rect.top) < rect.height / 2;
      row.parentNode.insertBefore(dragging, before ? row : row.nextSibling);
    });
  }

  function applyTopicOrderFromModal() {
    var host = el("guide-topics-list");
    Array.prototype.forEach.call(document.querySelectorAll(".reorder-row"), function (row) {
      host.appendChild(row._card);
    });
    refreshTopicOrderControls();
  }

  /* Текст і голос — окремо й паралельно, без хрестовпливу: текст питання
     друкується руками (як будь-яке інше поле), а мікрофон тут лише пише
     аудіофайл — те, що почує респондент замість синтезу ШІ/TTS. Ніякого
     розпізнавання мовлення в текст тут немає навмисно. */
  function buildRecordableQuestionField(topic) {
    var wrap = document.createElement("div");
    wrap.className = "topic-field";

    var textarea = document.createElement("textarea");
    textarea.rows = 2;
    textarea.className = "topic-question-input";
    textarea.value = topic.ask_if_missed || "";
    textarea.placeholder = "Що саме питає інтервʼюер, якщо респондент про це ще не сказав сам.";
    wrap.appendChild(textarea);

    var row = document.createElement("div");
    row.className = "record-row";

    var recordBtn = document.createElement("button");
    recordBtn.type = "button";
    recordBtn.className = "ghost small record-btn";

    var player = document.createElement("audio");
    player.className = "topic-audio-player hidden";
    player.controls = true;
    player.preload = "metadata";

    var deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "ghost small topic-audio-delete hidden";
    deleteBtn.innerHTML = ICONS.trash;
    deleteBtn.title = "Прибрати запис";

    var status = document.createElement("span");
    status.className = "record-status muted tiny";

    row.appendChild(recordBtn);
    row.appendChild(player);
    row.appendChild(deleteBtn);
    row.appendChild(status);
    wrap.appendChild(row);

    var topicId = topic.id || "";
    if (!topicId) {
      recordBtn.disabled = true;
      recordBtn.innerHTML = ICONS.mic + "Записати голосом";
      recordBtn.title = "Спершу збережіть гайд — запис прив'язується до "
        + "ідентифікатора питання, а в нового його ще немає.";
      status.textContent = "Доступно після збереження.";
      return wrap;
    }

    function audioUrl() {
      return "/audio/topic/" + encodeURIComponent(state.space) + "/"
        + encodeURIComponent(state.guide) + "/" + encodeURIComponent(topicId);
    }

    // Існування запису дізнаємось спробою завантажити його ж — окремого
    // ендпоінта "чи є запис" нема: одна річ замість двох.
    // Кнопка запису й аудіодоріжка не показуються одночасно: поки запис
    // існує, єдина дія над ним — прибрати (deleteBtn), а сам запис
    // замінюється лише після видалення старого, не поверх нього.
    player.addEventListener("error", function () {
      player.classList.add("hidden");
      deleteBtn.classList.add("hidden");
      recordBtn.classList.remove("hidden");
      recordBtn.innerHTML = ICONS.mic + "Записати голосом";
    });
    player.addEventListener("loadedmetadata", function () {
      player.classList.remove("hidden");
      deleteBtn.classList.remove("hidden");
      recordBtn.classList.add("hidden");
    });
    recordBtn.innerHTML = ICONS.mic + "Записати голосом";
    player.src = audioUrl() + "?t=" + Date.now();

    var mediaRecorder = null;
    var chunks = [];

    function upload(blob) {
      status.textContent = "Зберігаю…";
      recordBtn.disabled = true;
      fetch("/api/admin/topic-audio?space=" + encodeURIComponent(state.space)
          + "&guide=" + encodeURIComponent(state.guide)
          + "&topic=" + encodeURIComponent(topicId), {
        method: "POST",
        headers: { "Content-Type": blob.type || "audio/webm" },
        body: blob
      }).then(function (r) {
        return r.json().then(function (body) { return { ok: r.ok, body: body }; });
      }).then(function (res) {
        recordBtn.disabled = false;
        if (!res.ok) {
          status.textContent = "Не вдалося зберегти: " + (res.body.error || "?");
          return;
        }
        status.textContent = "Записано.";
        player.src = audioUrl() + "?t=" + Date.now();
      }).catch(function () {
        recordBtn.disabled = false;
        status.textContent = "Не вдалося зберегти запис.";
      });
    }

    recordBtn.addEventListener("click", function () {
      if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
        return;
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
        status.textContent = "Мікрофон недоступний у цьому браузері.";
        return;
      }
      navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
        chunks = [];
        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.ondataavailable = function (e) {
          if (e.data && e.data.size) chunks.push(e.data);
        };
        mediaRecorder.onstop = function () {
          stream.getTracks().forEach(function (t) { t.stop(); });
          upload(new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" }));
        };
        mediaRecorder.start();
        recordBtn.innerHTML = ICONS.stop + "Зупинити";
        recordBtn.classList.add("active");
        status.textContent = "Записую…";
      }).catch(function () {
        status.textContent = "Не вдалося отримати доступ до мікрофона.";
      });
    });

    deleteBtn.addEventListener("click", function () {
      if (!window.confirm("Прибрати запис голосу для цього питання?")) return;
      post("/api/admin/topic-audio/delete",
           { space: state.space, guide: state.guide, topic: topicId })
        .then(function () {
          player.classList.add("hidden");
          player.removeAttribute("src");
          deleteBtn.classList.add("hidden");
          recordBtn.classList.remove("hidden");
          recordBtn.innerHTML = ICONS.mic + "Записати голосом";
          status.textContent = "Запис прибрано.";
        })
        .catch(function (err) { status.textContent = "Не вдалося прибрати: " + err.message; });
    });

    return wrap;
  }

  function buildTopicCard(topic) {
    topic = topic || {};
    var card = document.createElement("div");
    card.className = "topic-card";
    card._original = topic;

    var head = document.createElement("div");
    head.className = "topic-card-head";

    var number = document.createElement("span");
    number.className = "topic-number";
    head.appendChild(number);

    var titleLabel = document.createElement("span");
    titleLabel.className = "topic-title-label";
    titleLabel.textContent = "Питання";
    head.appendChild(titleLabel);

    var removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "icon-btn topic-remove";
    removeBtn.innerHTML = ICONS.trash;
    removeBtn.title = "Видалити це питання";
    removeBtn.addEventListener("click", function () {
      card.remove();
      refreshTopicOrderControls();
    });
    head.appendChild(removeBtn);
    card.appendChild(head);

    card.appendChild(buildRecordableQuestionField(topic));

    var mustLearnWrap = document.createElement("div");
    mustLearnWrap.className = "must-learn-block";
    var mustLearnLabel = document.createElement("div");
    mustLearnLabel.className = "must-learn-label";
    mustLearnLabel.textContent = "Про що варто сказати:";
    mustLearnWrap.appendChild(mustLearnLabel);
    var mustLearnList = document.createElement("div");
    mustLearnList.className = "must-learn-list";
    var items = topic.must_learn && topic.must_learn.length ? topic.must_learn : [""];
    items.forEach(function (item) {
      mustLearnList.appendChild(buildMustLearnRow(mustLearnText(item)));
    });
    renumberMustLearnItems(mustLearnList);
    mustLearnWrap.appendChild(mustLearnList);
    var addPoint = document.createElement("button");
    addPoint.type = "button";
    addPoint.className = "ghost small must-learn-add";
    addPoint.textContent = "+ додати пункт";
    addPoint.addEventListener("click", function () {
      mustLearnList.appendChild(buildMustLearnRow(""));
      renumberMustLearnItems(mustLearnList);
    });
    mustLearnWrap.appendChild(addPoint);
    card.appendChild(mustLearnWrap);

    return card;
  }

  function renderTopicCards(topics) {
    var host = el("guide-topics-list");
    host.innerHTML = "";
    (topics || []).forEach(function (topic) { host.appendChild(buildTopicCard(topic)); });
    refreshTopicOrderControls();
  }

  function collectTopicsFromCards() {
    return Array.prototype.map.call(document.querySelectorAll(".topic-card"), function (card, index) {
      var original = card._original || {};
      var askIfMissed = card.querySelector(".topic-question-input").value.trim();
      // За текстом, а не позицією: пункти можна перетягувати (попап вище),
      // і після цього той самий пункт стоїть на іншому індексі. Порівняння
      // "той самий індекс" тоді помилково вирішувало б, що текст змінився,
      // і губило б позначку needs_detail (просить розгорнуту відповідь),
      // якої ця форма не редагує.
      var originalByText = {};
      (original.must_learn || []).forEach(function (item) {
        var text = mustLearnText(item);
        if (text && !(text in originalByText)) originalByText[text] = item;
      });
      var mustLearn = Array.prototype.map.call(
        card.querySelectorAll(".must-learn-item input"),
        function (input) {
          var text = input.value.trim();
          return text && (text in originalByText) ? originalByText[text] : text;
        }
      ).filter(function (item) { return mustLearnText(item); });

      return Object.assign({}, original, {
        id: original.id || ("topic-" + (index + 1)),
        title: askIfMissed.slice(0, 40) || ("Питання " + (index + 1)),
        ask_if_missed: askIfMissed,
        must_learn: mustLearn
      });
    });
  }

  function saveGuide() {
    var payload = Object.assign({}, state.guideData || {}, {
      key: state.guide,
      goal: el("guide-goal").value.trim(),
      opening: el("guide-opening").value.trim(),
      closing: el("guide-closing").value.trim(),
      max_turns: parseInt(el("guide-max-turns").value, 10) || 30,
      feedback_prompt: el("guide-feedback-prompt").value.trim(),
      feedback_style: el("guide-feedback-style").value,
      topics: collectTopicsFromCards()
    });
    el("guide-error").textContent = "";
    post("/api/admin/guide", { space: state.space, guide: state.guide, data: payload })
      .then(function () {
        flash("Гайд збережено", "ok");
        state.guideData = payload;
        // Перемальовуємо картки: нові питання отримали справжній id щойно
        // зараз — доти запис голосу для них був недоступний.
        renderTopicCards(payload.topics);
      })
      .catch(function (err) {
        el("guide-error").textContent = err.message;
        flash("Не збережено", "bad");
      });
  }

  /* ── простір ───────────────────────────────────────────────────────── */

  function loadSpaceData() {
    api("/api/admin/space?space=" + encodeURIComponent(state.space)).then(function (data) {
      state.spaceData = data;
      el("space-title").value = data.title || "";
      el("space-languages").value = (data.languages || []).join(", ");
      languageChips.refresh();
      renderStatusChip(data.draft);
      el("space-mode").value = ((data.interface || {}).mode) || "text";
      selects.mode.refresh();
      el("space-accent").value = (data.branding || {}).accent || "";
      accentSwatchPaint();
      el("space-error").textContent = "";
    }).catch(function (err) { el("space-error").textContent = err.message; });
  }

  function saveSpace() {
    var base = state.spaceData || {};
    var payload = Object.assign({}, base, {
      title: el("space-title").value.trim(),
      languages: el("space-languages").value.split(",").map(function (s) { return s.trim(); })
        .filter(function (s) { return s.length; }),
      // persona.self_intro і privacy (deidentify/consent_text/patterns) тут
      // не редагуються — адмінка їх більше не показує, тож просто йдуть з
      // base незміненими.
      // Готовність перемикається чіпом у шапці (renderStatusChip), а не
      // окремим полем тут — base.draft уже містить актуальне значення.
      draft: !!base.draft,
      interface: Object.assign({}, base.interface || {}, {
        mode: el("space-mode").value
      }),
      // providers (LLM/TTS) сюди не входять: на задеплоєній версії їх все
      // одно підмінює env-змінна (LLM_PROVIDER_OVERRIDE/TTS_PROVIDER_OVERRIDE),
      // тож редагування тут лише вводило б в оману. Що вже було в конфізі —
      // лишається незмінним через base.
      branding: Object.assign({}, base.branding || {}, {
        accent: el("space-accent").value.trim()
      })
    });
    el("space-error").textContent = "";
    post("/api/admin/space", { space: state.space, data: payload })
      .then(function () {
        state.spaceData = payload;
        flash("Збережено", "ok");
        return refresh();
      })
      .catch(function (err) {
        el("space-error").textContent = err.message;
        flash("Не збережено", "bad");
      });
  }

  /* ── видалення (у кошик) ──────────────────────────────────────────────
   *
   * Сюди дані респондентів не потрапляють: рішення про них — лише в кошику,
   * на «видалити назавжди», де відкату вже не буде.
   */

  function openDeleteConfirm() {
    el("delete-error").textContent = "";
    var space = state.spaces.filter(function (s) { return s.key === state.space; })[0];
    el("delete-confirm-title").textContent = (space && (space.title || space.key)) || state.space;
    el("delete-modal").classList.remove("hidden");
  }

  function closeDeleteConfirm() {
    el("delete-modal").classList.add("hidden");
  }

  function deleteSpace() {
    el("delete-error").textContent = "";
    post("/api/admin/space/delete", { space: state.space })
      .then(function () {
        closeDeleteConfirm();
        flash("Перенесено в кошик", "ok");
        loadTrash();
        return refresh().then(function () {
          if (state.spaces.length) selectSpace(state.spaces[0].key);
        });
      })
      .catch(function (err) { el("delete-error").textContent = err.message; });
  }

  /* ── кошик ─────────────────────────────────────────────────────────── */

  function openTrash() {
    el("trash-modal").classList.remove("hidden");
    loadTrash();
  }

  function closeTrash() {
    el("trash-modal").classList.add("hidden");
  }

  function loadTrash() {
    return api("/api/admin/trash").then(function (data) {
      state.trash = data.items;
      renderTrash();
    });
  }

  function renderTrash() {
    el("rail-trash-count").textContent = String(state.trash.length);
    var host = el("trash-list");
    host.innerHTML = "";
    if (!state.trash.length) {
      host.innerHTML = "<li class='muted tiny'>Кошик порожній.</li>";
      return;
    }
    state.trash.forEach(function (item) {
      // .run — той самий клас-картка, що й "Проведені інтервʼю": назва
      // зліва, дії — іконки-кнопки з тултіпом справа, а не текстові
      // кнопки, що ламали перенесення довгих назв. <li> лишається
      // звичайним блоком (не .run сам) — підтвердження остаточного
      // видалення (togglePurgeConfirm) додається йому ж другою дитиною,
      // під рядком картки, а не всередину flex-рядка .run.
      var li = document.createElement("li");
      var row = document.createElement("div");
      row.className = "run";
      li.appendChild(row);

      var info = document.createElement("div");
      info.className = "run-info";
      var head = document.createElement("div");
      head.className = "run-head";
      var name = document.createElement("strong");
      name.textContent = item.title || item.key;
      head.appendChild(name);
      info.appendChild(head);
      if (item.deleted_at) {
        var meta = document.createElement("div");
        meta.className = "run-meta";
        var date = document.createElement("span");
        date.textContent = formatDeletedAt(item.deleted_at);
        meta.appendChild(date);
        info.appendChild(meta);
      }
      row.appendChild(info);

      var actions = document.createElement("div");
      actions.className = "run-actions";

      var restore = document.createElement("button");
      restore.type = "button";
      restore.className = "icon-btn restore";
      restore.setAttribute("aria-label", "Відновити");
      restore.innerHTML = ICONS.restore;
      restore.appendChild(tooltipEl("Відновити"));
      restore.addEventListener("click", function () { restoreSpace(item.key); });
      actions.appendChild(restore);

      var purge = document.createElement("button");
      purge.type = "button";
      purge.className = "icon-btn";
      purge.setAttribute("aria-label", "Видалити назавжди");
      purge.innerHTML = ICONS.trash;
      purge.appendChild(tooltipEl("Видалити назавжди"));
      purge.addEventListener("click", function () { openPurgeConfirm(item); });
      actions.appendChild(purge);

      row.appendChild(actions);
      host.appendChild(li);
    });
  }

  function tooltipEl(text) {
    var tip = document.createElement("span");
    tip.className = "tooltip";
    tip.setAttribute("role", "tooltip");
    tip.textContent = text;
    return tip;
  }

  function restoreSpace(key) {
    post("/api/admin/trash/restore", { space: key })
      .then(function () {
        flash("Відновлено", "ok");
        return Promise.all([refresh(), loadTrash()]).then(function () { selectSpace(key); });
      })
      .catch(function (err) { flash(err.message, "bad"); });
  }

  /* Питання про відповіді респондентів — саме тут: це остання й безповоротна
     дія, на відміну від переносу в кошик. Модалка, а не розкривна панель
     прямо в рядку кошика (той самий скелет, що й решта модалок) —
     pendingPurgeKey запам'ятовує, для якого саме простору зараз питаємо,
     бо кнопки в модалці одні на всіх, не по одній копії на кожен рядок. */
  var pendingPurgeKey = null;

  function openPurgeConfirm(item) {
    pendingPurgeKey = item.key;
    el("purge-error").textContent = "";
    el("purge-confirm-text").textContent = "Видалити «" + (item.title || item.key) +
      "» назавжди. Що зробити з уже зібраними відповідями респондентів?";
    el("purge-modal").classList.remove("hidden");
  }

  function closePurgeConfirm() {
    pendingPurgeKey = null;
    el("purge-modal").classList.add("hidden");
  }

  function purgeSpace(withSessions) {
    var key = pendingPurgeKey;
    if (!key) return;
    el("purge-error").textContent = "";
    post("/api/admin/trash/purge", { space: key, delete_sessions: withSessions })
      .then(function (result) {
        closePurgeConfirm();
        flash(withSessions
          ? ("Видалено назавжди разом із " + result.removed_sessions + " інтервʼю респондентів")
          : "Видалено назавжди. Відповіді респондентів лишились у сховищі", "ok");
        return loadTrash();
      })
      .catch(function (err) { el("purge-error").textContent = err.message; });
  }

  /* ── результати ────────────────────────────────────────────────────── */

  /* Без залежності від локалі браузера — завжди ДД.ММ.РРРР ГГ:ХХ:СС. */
  function formatDateTime(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    var pad = function (n) { return String(n).padStart(2, "0"); };
    return pad(d.getDate()) + "." + pad(d.getMonth() + 1) + "." + d.getFullYear() +
      ", " + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }

  /* Той самий формат ДД.ММ.РРРР, без часу — для дати створення в сайдбарі. */
  function formatDate(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    var pad = function (n) { return String(n).padStart(2, "0"); };
    return pad(d.getDate()) + "." + pad(d.getMonth() + 1) + "." + d.getFullYear();
  }

  /* deleted_at — unix-секунди (mtime файлу) на диску, ISO-рядок на
     Postgres: приймаємо обидва, як і сам бекенд віддає залежно від
     режиму сховища. Той самий формат виводу, що й formatDateTime. */
  function formatDeletedAt(value) {
    if (!value) return "";
    var d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
    if (isNaN(d.getTime())) return "";
    var pad = function (n) { return String(n).padStart(2, "0"); };
    return pad(d.getDate()) + "." + pad(d.getMonth() + 1) + "." + d.getFullYear() +
      ", " + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }

  function loadRuns() {
    api("/api/sessions").then(function (data) {
      state.runs = data.items.filter(function (item) { return item.space === state.space; });
      renderRuns();
    }).catch(function (err) {
      el("runs-list").textContent = err.message;
    });
  }

  function renderRuns() {
      var host = el("runs-list");
      host.innerHTML = "";
      var items = state.runs || [];

      el("runs-count").textContent = items.length ? items.length : "";

      if (!items.length) {
        host.innerHTML = "<p class='list-empty muted'>Завершених інтервʼю тут ще немає.</p>";
        return;
      }
      items.forEach(function (item) {
        var row = document.createElement("div");
        row.className = "run";

        // Ліва колонка — все, що описує саме це інтервʼю (хто, коли,
        // скільки, як оцінене): один зв'язний блок, а не розкидані по
        // різних кутках рядка факти. Права — лише дії, окремо й завжди
        // по вертикальному центру всього рядка, а не приклеєні до
        // нижнього рядка метаданих.
        var info = document.createElement("div");
        info.className = "run-info";

        var head = document.createElement("div");
        head.className = "run-head";
        var nameEl = document.createElement("strong");
        nameEl.textContent = item.respondent_name || "Без ПІБ";
        head.appendChild(nameEl);
        info.appendChild(head);

        // Рейтинг → репліки → дата: від найбільш вагомого (як пройшло) до
        // найнейтральнішого факту (коли це було) — той самий порядок, що
        // й читач очікує в реченні "оцінка, обсяг, час", не розкидано по
        // різних кутках картки.
        var meta = document.createElement("div");
        meta.className = "run-meta";

        // Крапка між фактами — без неї рейтинг/репліки/дата читались як
        // випадково розкидані по рядку слова, не одна послідовність.
        // CSS-бокс, не текстовий символ: гліф "·" при більшому розмірі не
        // центрувався по базовій лінії тексту так само, як сам бокс.
        // Пропускається перед першим елементом (додає лише сам appendMeta).
        function appendMeta(el) {
          if (meta.children.length) {
            var sep = document.createElement("span");
            sep.className = "run-meta-sep";
            sep.setAttribute("aria-hidden", "true");
            meta.appendChild(sep);
          }
          meta.appendChild(el);
        }

        // Відгук про сам досвід — окремо від інцидентів (ті про якість
        // розмови, це про те, чи респонденту було зручно її проходити).
        if (item.feedback && item.feedback.rating) {
          var rating = document.createElement("span");
          rating.className = "pill pill-accent";
          rating.innerHTML = ICONS.star + item.feedback.rating + "/5";
          if (item.feedback.comment) rating.title = item.feedback.comment;
          appendMeta(rating);
        }

        // Нейтральний лічильник — контурна пігулка; змістовний статус —
        // залита з іконкою. Дві форми статус-бейджа з референсу, поділені
        // саме за вагою: скільки реплік — це факт, інциденти — це стан.
        var turns = document.createElement("span");
        turns.className = "pill pill-info";
        turns.textContent = item.turns + " реплік";
        appendMeta(turns);

        var dateEl = document.createElement("span");
        dateEl.className = "run-date muted tiny";
        dateEl.textContent = formatDateTime(item.started_at);
        appendMeta(dateEl);

        info.appendChild(meta);
        row.appendChild(info);

        var actions = document.createElement("div");
        actions.className = "run-actions";

        var open = document.createElement("button");
        open.className = "ghost small";
        open.textContent = "Деталі";
        open.addEventListener("click", function () { showTranscript(item.session_id); });
        actions.appendChild(open);

        row.appendChild(actions);
        host.appendChild(row);
      });
  }

  /* Кожен вид інциденту має власні поля. Раніше рендерер чекав `problems` у
     всіх, і маскування виводилось порожнім рядком. */
  /* Іконка окремо від тексту (не в один рядок): текст може містити те, що
     сказала модель чи респондент, і його не можна пускати через innerHTML. */
  function describeIncident(incident) {
    if (incident.kind === "override") {
      return { icon: "lock", text: "ядро: " + incident.detail };
    }
    if (incident.kind === "guard_rejection") {
      return {
        icon: "ban",
        text: "guard відхилив репліку (спроба " + (incident.attempt || 1) + "): " +
          (incident.problems || []).join("; ")
      };
    }
    if (incident.kind === "guard_fallback") {
      return {
        icon: "alertTriangle",
        text: "модель не змогла сформулювати репліку без порушень — пішло нейтральне питання"
      };
    }
    if (incident.kind === "deidentified") {
      return {
        icon: "shield",
        text: "замасковано у відповіді: " + (incident.rules || []).map(function (r) {
          return r.rule + (r.count > 1 ? (" ×" + r.count) : "");
        }).join(", ")
      };
    }
    return { icon: "dot", text: incident.kind };
  }

  function showTranscript(id) {
    api("/api/admin/transcript?id=" + encodeURIComponent(id)).then(function (data) {
      var host = el("transcript");
      host.innerHTML = "";
      el("transcript-title").textContent = "Транскрипт — " +
        (data.respondent_name || data.session_id);

      // Відгук про сам досвід — окремим блоком угорі, до інцидентів: це
      // загальне враження респондента, а не подія всередині розмови.
      if (data.feedback) {
        var feedback = document.createElement("div");
        feedback.className = "feedback-note";
        if (data.feedback.rating) {
          var rating = document.createElement("div");
          rating.innerHTML = ICONS.star;
          rating.appendChild(document.createTextNode(" " + data.feedback.rating + "/5"));
          feedback.appendChild(rating);
        }
        if (data.feedback.comment) {
          var comment = document.createElement("div");
          comment.className = "muted";
          comment.textContent = data.feedback.comment;
          feedback.appendChild(comment);
        }
        host.appendChild(feedback);
      }

      (data.incidents || []).forEach(function (incident) {
        var node = document.createElement("div");
        node.className = "incident";
        var described = describeIncident(incident);
        node.innerHTML = ICONS[described.icon];
        node.appendChild(document.createTextNode(" " + described.text));
        host.appendChild(node);
      });

      (data.turns || []).forEach(function (turn) {
        var node = document.createElement("div");
        node.className = "turn " + turn.role;
        node.innerHTML = "<div class='who'>" +
          (turn.role === "interviewer" ? "інтервʼюер" : "респондент") +
          (turn.topic_id ? (" · " + turn.topic_id) : "") + "</div>";
        // Запис голосу — перед текстом, не після: дослідник спершу чує,
        // потім звіряє з тим, що модель розпізнала як текст цієї ж репліки.
        if (turn.voice && turn.voice.length) {
          var voiceBox = document.createElement("div");
          voiceBox.className = "turn-voice";
          turn.voice.forEach(function (name) {
            var player = document.createElement("audio");
            player.controls = true;
            player.preload = "none";
            player.src = "/voice/" + id + "/" + name;
            voiceBox.appendChild(player);
          });
          node.appendChild(voiceBox);
        }
        var body = document.createElement("div");
        body.textContent = turn.text;
        node.appendChild(body);
        if (turn.masked && turn.masked.length) {
          var mask = document.createElement("div");
          mask.className = "masked-note";
          mask.textContent = "замасковано: " + turn.masked.map(function (m) {
            return m.rule + (m.count > 1 ? (" ×" + m.count) : "");
          }).join(", ");
          node.appendChild(mask);
        }
        host.appendChild(node);
      });
      host.scrollTop = 0;
      el("transcript-modal").classList.remove("hidden");
    }).catch(function (err) {
      el("transcript-title").textContent = "Транскрипт";
      el("transcript").textContent = err.message;
      el("transcript-modal").classList.remove("hidden");
    });
  }

  function closeTranscript() {
    el("transcript-modal").classList.add("hidden");
  }

  /* ── новий простір ─────────────────────────────────────────────────── */

  /* Форма, а не window.prompt: prompt блокує потік і в частині вбудованих
     контекстів браузер його просто не показує — фіча тихо ламається. */
  function toggleNewSpace(show) {
    el("new-space-form").classList.toggle("hidden", !show);
    el("new-space-error").textContent = "";
    if (show) {
      el("new-space-title").value = "";
      el("new-space-title").focus();
    }
  }

  // Ключ — лише технічне імʼя теки/API-параметр, людині його вводити
  // нема сенсу: ідентична латиниця+час гарантує унікальність і проходить
  // серверну перевірку (KEY_RE), незалежно від того, якою мовою назва.
  function generateSpaceKey() {
    return "study-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  }

  function newSpace(event) {
    if (event) event.preventDefault();
    var title = el("new-space-title").value.trim();
    if (!title) {
      el("new-space-error").textContent = "Потрібна назва.";
      return;
    }
    var key = generateSpaceKey();
    el("new-space-error").textContent = "";
    post("/api/admin/space/new", { space: key, title: title })
      .then(function () {
        flash("Інтервʼю створено з шаблону", "ok");
        toggleNewSpace(false);
        return refresh().then(function () { selectSpace(key); });
      })
      .catch(function (err) { el("new-space-error").textContent = err.message; });
  }

  /* ── вкладки й запуск ──────────────────────────────────────────────── */

  Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (tab) {
    tab.addEventListener("click", function () {
      Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (t) {
        t.classList.toggle("active", t === tab);
      });
      ["space", "questions", "runs"].forEach(function (name) {
        el("tab-" + name).classList.toggle("hidden", name !== tab.dataset.tab);
      });
      if (tab.dataset.tab === "runs") loadRuns();
    });
  });

  el("btn-add-topic").addEventListener("click", function () {
    el("guide-topics-list").appendChild(buildTopicCard({}));
    refreshTopicOrderControls();
  });
  el("btn-reorder-topics").addEventListener("click", openTopicOrderModal);
  // "Зберегти" застосовує перетягнутий порядок; × у шапці — просто
  // закриває, без застосування (як скасувати), той самий принцип, що
  // й ×/Escape/клік повз картку скрізь в інтерфейсі.
  el("btn-reorder-close").addEventListener("click", function () {
    applyTopicOrderFromModal();
    el("topic-order-modal").classList.add("hidden");
  });
  el("btn-reorder-cancel").addEventListener("click", function () {
    el("topic-order-modal").classList.add("hidden");
  });
  el("btn-reorder-x").addEventListener("click", function () {
    el("topic-order-modal").classList.add("hidden");
  });
  el("btn-transcript-close").addEventListener("click", closeTranscript);
  el("btn-transcript-x").addEventListener("click", closeTranscript);
  el("transcript-modal").addEventListener("click", function (event) {
    if (event.target.id === "transcript-modal") closeTranscript();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    if (!el("transcript-modal").classList.contains("hidden")) closeTranscript();
    if (!el("trash-modal").classList.contains("hidden")) closeTrash();
    if (!el("delete-modal").classList.contains("hidden")) closeDeleteConfirm();
    if (!el("purge-modal").classList.contains("hidden")) closePurgeConfirm();
  });
  el("btn-save-guide").addEventListener("click", saveGuide);
  el("btn-save-space").addEventListener("click", saveSpace);
  // Статус — дропдаун із двома варіантами (шеврон, панель відкривається/
  // закривається так само, як звичайний .select), а не простий тогл по
  // кліку: тригер лишається кольоровим чіпом, панель — окрема сутність.
  (function () {
    var wrap = el("status-select");
    var trigger = el("page-status");
    var panel = el("status-panel");

    function closePanel() {
      panel.classList.add("hidden");
      wrap.classList.remove("open");
      trigger.setAttribute("aria-expanded", "false");
    }
    trigger.addEventListener("click", function (event) {
      event.stopPropagation();
      var wasOpen = !panel.classList.contains("hidden");
      Array.prototype.forEach.call(document.querySelectorAll(".select.open"), function (other) {
        other.classList.remove("open");
        other.querySelector(".select-panel").classList.add("hidden");
      });
      if (wasOpen) { closePanel(); return; }
      panel.classList.remove("hidden");
      wrap.classList.add("open");
      trigger.setAttribute("aria-expanded", "true");
    });
    Array.prototype.forEach.call(panel.querySelectorAll(".status-option"), function (opt) {
      opt.addEventListener("click", function (event) {
        event.stopPropagation();
        if (!state.spaceData) { closePanel(); return; }
        state.spaceData.draft = opt.dataset.draft === "true";
        renderStatusChip(state.spaceData.draft);
        closePanel();
      });
    });
    document.addEventListener("click", closePanel);
    document.addEventListener("keydown", function (event) { if (event.key === "Escape") closePanel(); });
  })();
  el("btn-delete-space").addEventListener("click", openDeleteConfirm);
  el("btn-delete-cancel").addEventListener("click", closeDeleteConfirm);
  el("btn-delete-x").addEventListener("click", closeDeleteConfirm);
  el("btn-delete-confirm").addEventListener("click", deleteSpace);
  el("delete-modal").addEventListener("click", function (event) {
    if (event.target.id === "delete-modal") closeDeleteConfirm();
  });
  el("btn-copy-link").addEventListener("click", copyRespondentLink);
  el("btn-toggle-trash").addEventListener("click", openTrash);
  el("btn-trash-x").addEventListener("click", closeTrash);
  el("btn-trash-close").addEventListener("click", closeTrash);
  el("trash-modal").addEventListener("click", function (event) {
    if (event.target.id === "trash-modal") closeTrash();
  });
  el("btn-purge-x").addEventListener("click", closePurgeConfirm);
  el("btn-purge-keep").addEventListener("click", function () { purgeSpace(false); });
  el("btn-purge-with").addEventListener("click", function () { purgeSpace(true); });
  el("purge-modal").addEventListener("click", function (event) {
    if (event.target.id === "purge-modal") closePurgeConfirm();
  });
  el("btn-new-space").addEventListener("click", function () {
    var willShow = el("new-space-form").classList.contains("hidden");
    // Форма нового дослідження в згорнутій панелі ховається через CSS
    // (немає місця в 56px-колонці) — без цього клік по "+" виглядав би так,
    // ніби нічого не відбулось.
    if (willShow) setRailCollapsed(false);
    toggleNewSpace(willShow);
  });
  el("btn-cancel-space").addEventListener("click", function () { toggleNewSpace(false); });
  el("new-space-form").addEventListener("submit", newSpace);

  /* Тема — один трек-тогл із двома іконками (сонце/місяць), а не дві
     незалежні кнопки: обрана підсвічена рухомою пігулкою (dataset.active
     на .theme-switch керує її позицією в CSS), а не одна іконка, що
     змінюється. Явний вибір, не лише системна настройка — без цього
     людина з темною системною темою не могла б побачити світлу версію
     взагалі. */
  (function () {
    var KEY = "admin-theme";
    var body = document.body;
    function current() {
      return body.dataset.theme ||
        (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    }
    function paint() {
      var now = current();
      el("btn-theme-light").classList.toggle("active", now === "light");
      el("btn-theme-dark").classList.toggle("active", now === "dark");
      document.querySelector(".theme-switch").dataset.active = now;
    }
    function apply(theme) {
      body.dataset.theme = theme;
      try { localStorage.setItem(KEY, theme); } catch (e) { /* приватний режим — просто ігнор */ }
      paint();
    }
    var saved = null;
    try { saved = localStorage.getItem(KEY); } catch (e) { /* ігнор */ }
    if (saved === "light" || saved === "dark") body.dataset.theme = saved;
    paint();
    el("btn-theme-light").addEventListener("click", function () { apply("light"); });
    el("btn-theme-dark").addEventListener("click", function () { apply("dark"); });
  })();

  /* Згортання панелі — той самий патерн памʼяті вибору, що й тема:
     явна кнопка, стан лишається між перезавантаженнями через localStorage. */
  (function () {
    var KEY = "admin-rail-collapsed";
    var app = document.querySelector(".app");
    var btn = el("btn-rail-collapse");
    function paint(collapsed) {
      app.classList.toggle("rail-collapsed", collapsed);
      btn.setAttribute("aria-label", collapsed ? "Розгорнути панель" : "Згорнути панель");
      btn.title = collapsed ? "Розгорнути панель" : "Згорнути панель";
    }
    var saved = null;
    try { saved = localStorage.getItem(KEY); } catch (e) { /* ігнор */ }
    var collapsed = saved === "1";
    paint(collapsed);
    btn.addEventListener("click", function () {
      collapsed = !collapsed;
      try { localStorage.setItem(KEY, collapsed ? "1" : "0"); } catch (e) { /* ігнор */ }
      paint(collapsed);
    });
    setRailCollapsed = function (value) {
      collapsed = value;
      try { localStorage.setItem(KEY, collapsed ? "1" : "0"); } catch (e) { /* ігнор */ }
      paint(collapsed);
    };
  })();

  /* Підказка "Як влаштовані картки питань" — закривається назавжди: раз
     прочитавши, її більше не показуємо (той самий патерн памʼяті, що тема
     й rail). */
  (function () {
    var KEY = "admin-questions-callout-dismissed";
    var callout = el("questions-callout");
    var btn = el("btn-callout-close");
    if (!callout || !btn) return;
    var dismissed = false;
    try { dismissed = localStorage.getItem(KEY) === "1"; } catch (e) { /* ігнор */ }
    if (dismissed) callout.classList.add("hidden");
    btn.addEventListener("click", function () {
      callout.classList.add("hidden");
      try { localStorage.setItem(KEY, "1"); } catch (e) { /* ігнор */ }
    });
  })();

  /* Чипи, що знімаються, замість голого "через кому"-поля — Tags із
     Kanban-картки й тег-адер з модалки Create project. Прихований input
     лишається джерелом правди (.value = "uk, ru"), решта коду його читає
     і пише так само, як і раніше — чипи лише малюють його вміст. */
  function initChipField(id) {
    var hidden = el(id);
    var placeholder = hidden.placeholder || "";
    hidden.type = "hidden";

    var box = document.createElement("div");
    box.className = "chip-box";
    var typer = document.createElement("input");
    typer.type = "text"; typer.className = "chip-typer"; typer.placeholder = placeholder;
    hidden.parentNode.insertBefore(box, hidden.nextSibling);
    box.appendChild(typer);

    function items() {
      return (hidden.value || "").split(",").map(function (s) { return s.trim(); })
        .filter(function (s) { return s.length; });
    }
    function setItems(list) { hidden.value = list.join(", "); }

    function render() {
      Array.prototype.slice.call(box.querySelectorAll(".chip")).forEach(function (c) { c.remove(); });
      items().forEach(function (text, index) {
        var chip = document.createElement("span");
        chip.className = "chip";
        chip.appendChild(document.createTextNode(text));
        var remove = document.createElement("button");
        remove.type = "button"; remove.className = "chip-remove"; remove.innerHTML = ICONS.close;
        remove.title = "Прибрати";
        remove.addEventListener("click", function () {
          var list = items(); list.splice(index, 1); setItems(list); render();
        });
        chip.appendChild(remove);
        box.insertBefore(chip, typer);
      });
    }
    function commit() {
      var text = typer.value.trim();
      if (!text) return;
      var list = items(); list.push(text); setItems(list);
      typer.value = "";
      render();
    }
    typer.addEventListener("keydown", function (event) {
      if (event.key === "," || event.key === "Enter") { event.preventDefault(); commit(); }
      else if (event.key === "Backspace" && !typer.value) {
        var list = items();
        if (list.length) { list.pop(); setItems(list); render(); }
      }
    });
    typer.addEventListener("blur", commit);
    box.addEventListener("click", function (event) { if (event.target === box) typer.focus(); });

    render();
    return { refresh: render };
  }
  var languageChips = initChipField("space-languages");

  /* Кастомний дропдаун замість нативного <select> — саме той вигляд, що в
     референсі: поле з шевроном, плаваюча панель із тінню, ховер-підсвітка
     рядка й галочка на обраному. Нативний select лишається в DOM і далі
     тримає значення (.value читає решта коду), просто не показується. */
  function initSelect(id, variant) {
    var native = el(id);
    var wrap = document.createElement("div");
    wrap.className = "select" + (variant === "pill" ? " select-pill" : "");
    native.parentNode.insertBefore(wrap, native);
    wrap.appendChild(native);
    native.classList.add("select-native");

    var trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "select-trigger";
    var value = document.createElement("span");
    value.className = "select-value";
    trigger.appendChild(value);
    trigger.insertAdjacentHTML("beforeend", ICONS.chevronDown);
    wrap.appendChild(trigger);

    var panel = document.createElement("div");
    panel.className = "select-panel hidden";
    wrap.appendChild(panel);

    function close() { panel.classList.add("hidden"); wrap.classList.remove("open"); }

    function render() {
      var current = native.options[native.selectedIndex];
      value.textContent = current ? current.textContent : "";
      panel.innerHTML = "";
      Array.prototype.forEach.call(native.options, function (option, index) {
        var row = document.createElement("button");
        row.type = "button";
        row.className = "select-option" + (index === native.selectedIndex ? " selected" : "");
        row.appendChild(document.createTextNode(option.textContent));
        if (index === native.selectedIndex) row.insertAdjacentHTML("beforeend", ICONS.check);
        row.addEventListener("click", function (event) {
          event.stopPropagation();
          native.selectedIndex = index;
          native.dispatchEvent(new Event("change", { bubbles: true }));
          render();
          close();
        });
        panel.appendChild(row);
      });
    }

    trigger.addEventListener("click", function (event) {
      event.stopPropagation();
      var wasOpen = !panel.classList.contains("hidden");
      // Закрити всі інші відкриті дропдауни — одночасно відкритий лише один.
      Array.prototype.forEach.call(document.querySelectorAll(".select.open"), function (other) {
        other.classList.remove("open");
        other.querySelector(".select-panel").classList.add("hidden");
      });
      if (wasOpen) return;
      render();
      panel.classList.remove("hidden");
      wrap.classList.add("open");
    });
    document.addEventListener("click", close);
    document.addEventListener("keydown", function (event) { if (event.key === "Escape") close(); });

    render();
    return { refresh: render };
  }

  var selects = {
    mode: initSelect("space-mode"),
    feedbackStyle: initSelect("guide-feedback-style")
  };

  /* Семпл кольору просто в полі — видно, який відтінок стоїть, без
     здогадок по hex. */
  (function () {
    var input = el("space-accent");
    var swatch = el("accent-swatch");
    function paint() { swatch.style.background = input.value.trim() || "transparent"; }
    input.addEventListener("input", paint);
    input.addEventListener("change", paint);
    accentSwatchPaint = paint;
  })();

  function refresh() {
    return api("/api/admin/spaces").then(function (data) {
      state.spaces = data.items;
      renderSpaces();
    });
  }

  refresh().then(function () {
    if (state.spaces.length) selectSpace(state.spaces[0].key);
  }).catch(function (err) {
    el("space-list").innerHTML = "<li class='muted'>" + err.message + "</li>";
  });
  loadTrash();
})();
