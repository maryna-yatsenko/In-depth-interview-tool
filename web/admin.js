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
    var url = (state.respondentUrl || location.origin).replace(/\/$/, "") + "/?space=" + encodeURIComponent(state.space || "");
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
        tip.textContent = "Скопіювати посилання на форму";
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

      var draftTag = null;
      var text = document.createElement("span");
      text.className = "space-list-text";
      text.appendChild(document.createTextNode(space.title || space.key));
      if (space.draft) {
        var tag = document.createElement("span");
        tag.className = "draft-tag";
        tag.textContent = "Чернетка";
        draftTag = tag;
      }
      // Рядок «дата | статус»: горизонтальний автолейаут по одній осі, між ними тонкий вертикальний розділювач.
      if (space.created_at || draftTag) {
        var meta = document.createElement("span");
        meta.className = "space-meta";
        if (space.created_at) {
          var created = document.createElement("span");
          created.className = "space-date";
          created.textContent = formatDate(space.created_at);
          meta.appendChild(created);
        }
        if (draftTag) {
          if (space.created_at) {
            var divider = document.createElement("span");
            divider.className = "space-divider";
            meta.appendChild(divider);
          }
          meta.appendChild(draftTag);
        }
        text.appendChild(meta);
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
      el("guide-question-size").value = data.question_font_size || "medium";
      el("guide-question-weight").value = data.question_font_weight || "regular";
      selects.questionSize.refresh();
      selects.questionWeight.refresh();
      renderTopicCards(data.topics || []);
      el("guide-error").textContent = "";
    }).catch(function (err) { el("guide-error").textContent = err.message; });
  }

  /* Питання — картка на тему гайда: дослівний текст, який почує респондент
     (ask_if_missed — єдине питання теми), і чекліст must_learn під ним.

     Ключ (id) не редагується руками — лишається як є для наявних тем,
     генерується за порядком карток для нових (як і раніше генерувався для
     нового простору: «topic-1», «topic-2», …). Поля, яких немає в картці
     (goal, max_probes, shown_as), — з `_original`, який зберігаємо на самій
     картці при рендері, щоб збереження не змило те, чого форма не показує. */
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

  /* ── Смислові блоки ─────────────────────────────────────────────────────
     Блок — контейнер: назва вгорі, питання всередині, власна кнопка
     «Додати питання». У гайді це лише поле `block` у кожному питанні (серія
     сусідніх питань з однаковою назвою — один крок прогресу в респондента),
     тому формат даних лишається пласким, а контейнери — це вигляд. */
  function topicCards() {
    return Array.prototype.slice.call(document.querySelectorAll(".topic-card"));
  }

  function blockEls() {
    return Array.prototype.slice.call(document.querySelectorAll(".topic-block"));
  }

  function pluralQuestions(n) {
    var tail = n % 100;
    if (tail >= 11 && tail <= 14) return "питань";
    var last = n % 10;
    if (last >= 1 && last <= 4) return "питання";
    return "питань";
  }

  /* Номер картки — саме її позиція серед усіх карток гайда, а не щось
     збережене в темі: перераховуємо після кожної зміни порядку/кількості.
     Блок, з якого прибрали всі питання, зникає (крім єдиного). */
  function refreshTopicOrderControls() {
    blockEls().forEach(function (block) {
      if (!block.querySelector(".topic-card") && blockEls().length > 1) block.remove();
    });
    var blocks = blockEls();
    var cards = topicCards();
    cards.forEach(function (card, index) {
      var number = card.querySelector(".topic-number");
      if (number) number.textContent = (index + 1) + ".";
      var remove = card.querySelector(".topic-remove");
      if (remove) remove.disabled = cards.length <= 1;
    });
    blocks.forEach(function (block) {
      var n = block.querySelectorAll(".topic-card").length;
      block.querySelector(".block-count").textContent = n + " " + pluralQuestions(n);
      block.querySelector(".block-remove").disabled = blocks.length <= 1;
    });
  }

  function uniqueBlockName() {
    var names = blockEls().map(function (b) { return b.querySelector(".block-name").value.trim(); });
    var name = "Новий блок";
    for (var i = 2; names.indexOf(name) !== -1; i++) name = "Новий блок " + i;
    return name;
  }

  function buildBlock(name) {
    var block = document.createElement("section");
    block.className = "topic-block";

    var head = document.createElement("div");
    head.className = "topic-block-head";

    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "icon-btn block-toggle";
    toggle.setAttribute("aria-expanded", "true");
    toggle.title = "Згорнути/розгорнути блок";
    toggle.innerHTML = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';
    toggle.addEventListener("click", function () {
      var collapsed = block.classList.toggle("collapsed");
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    });
    head.appendChild(toggle);

    // Назва — заголовок блоку: над нею дрібна підпис-мітка, щоб було ясно,
    // що це за рівень, а саме поле читається як заголовок, не як звичайне поле.
    var titleBox = document.createElement("div");
    titleBox.className = "block-title-box";
    var tag = document.createElement("span");
    tag.className = "block-tag";
    tag.textContent = "Блок:";
    titleBox.appendChild(tag);
    var input = document.createElement("input");
    input.type = "text";
    input.className = "block-name";
    input.value = name || "";
    input.placeholder = "Без назви";
    input.setAttribute("aria-label", "Назва блоку");
    titleBox.appendChild(input);
    head.appendChild(titleBox);

    var count = document.createElement("span");
    count.className = "block-count";
    head.appendChild(count);

    var removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "icon-btn block-remove";
    removeBtn.innerHTML = ICONS.trash;
    removeBtn.title = "Видалити блок разом із його питаннями";
    removeBtn.addEventListener("click", function () {
      var filled = Array.prototype.filter.call(
        block.querySelectorAll(".topic-question-input"),
        function (field) { return field.value.trim(); }).length;
      if (filled && !window.confirm("Видалити блок разом із питаннями (" + filled + ")?")) return;
      block.remove();
      refreshTopicOrderControls();
    });
    head.appendChild(removeBtn);
    block.appendChild(head);

    var cards = document.createElement("div");
    cards.className = "topic-block-cards";
    block.appendChild(cards);

    var foot = document.createElement("div");
    foot.className = "topic-block-foot";
    var add = document.createElement("button");
    add.type = "button";
    add.className = "add-topic block-add";
    add.innerHTML = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14"/><path d="M5 12h14"/></svg><span>Додати питання</span>';
    add.addEventListener("click", function () {
      var card = buildTopicCard({});
      cards.appendChild(card);
      refreshTopicOrderControls();
      var field = card.querySelector(".topic-question-input");
      if (field) field.focus();
    });
    foot.appendChild(add);
    block.appendChild(foot);
    return block;
  }

  function addBlock() {
    var block = buildBlock(uniqueBlockName());
    block.querySelector(".topic-block-cards").appendChild(buildTopicCard({}));
    el("guide-topics-list").appendChild(block);
    refreshTopicOrderControls();
    var field = block.querySelector(".block-name");
    field.focus();
    field.select();
  }

  function lastBlockCards() {
    var blocks = blockEls();
    var block = blocks[blocks.length - 1];
    if (!block) {
      block = buildBlock("");
      el("guide-topics-list").appendChild(block);
    }
    return block.querySelector(".topic-block-cards");
  }

  /* Порядок — попапом, перетягуванням, бачачи лише заголовки: серед повних
     карток (питання, чекліст, запис голосу) прокручувати весь гайд, щоб
     перенести питання на три позиції вище, незручно. Тут два рівні: блоки
     (тягнуться за шапку) й питання в них (тягнуться між блоками). Самі
     картки не чіпаються, доки не натиснуто «Зберегти». */
  function openTopicOrderModal() {
    var list = el("topic-order-list");
    list.innerHTML = "";
    blockEls().forEach(function (block) {
      var item = document.createElement("div");
      item.className = "reorder-block";
      item._block = block;

      var head = document.createElement("div");
      head.className = "reorder-block-head";
      head.draggable = true;
      var handle = document.createElement("span");
      handle.className = "reorder-handle";
      handle.textContent = "⠿";
      handle.setAttribute("aria-hidden", "true");
      head.appendChild(handle);
      var title = document.createElement("span");
      title.className = "reorder-block-title";
      title.textContent = block.querySelector(".block-name").value.trim() || "Без назви";
      head.appendChild(title);
      item.appendChild(head);

      var body = document.createElement("div");
      body.className = "reorder-block-body";
      Array.prototype.forEach.call(block.querySelectorAll(".topic-card"), function (card) {
        var questionInput = card.querySelector(".topic-question-input");
        var row = document.createElement("div");
        row.className = "reorder-row";
        row.draggable = true;
        row._card = card;
        row._label = (questionInput && questionInput.value.trim()) || "(без назви)";
        var rowHandle = document.createElement("span");
        rowHandle.className = "reorder-handle";
        rowHandle.textContent = "⠿";
        rowHandle.setAttribute("aria-hidden", "true");
        row.appendChild(rowHandle);
        var text = document.createElement("span");
        text.className = "reorder-title";
        row.appendChild(text);
        body.appendChild(row);
      });
      item.appendChild(body);
      list.appendChild(item);
    });
    renumberReorderRows();
    el("topic-order-modal").classList.remove("hidden");
  }

  function renumberReorderRows() {
    Array.prototype.forEach.call(document.querySelectorAll("#topic-order-list .reorder-row"), function (row, index) {
      row.querySelector(".reorder-title").textContent = (index + 1) + ". " + row._label;
    });
  }

  (function wireTopicOrderDrag() {
    var list = el("topic-order-list");
    var dragging = null;
    list.addEventListener("dragstart", function (e) {
      var row = e.target.closest(".reorder-row");
      var head = e.target.closest(".reorder-block-head");
      dragging = row || (head && head.parentNode) || null;
      if (!dragging) return;
      dragging.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      // Дані самому drag-подію не потрібні — переносимо вузли напряму;
      // рядок все одно потрібен, щоб Firefox узагалі дозволив drag.
      try { e.dataTransfer.setData("text/plain", ""); } catch (err) { /* байдуже */ }
    });
    list.addEventListener("dragend", function () {
      if (dragging) dragging.classList.remove("dragging");
      dragging = null;
      renumberReorderRows();
    });
    list.addEventListener("dragover", function (e) {
      if (!dragging) return;
      e.preventDefault();
      var overBlock = e.target.closest(".reorder-block");
      if (!overBlock) return;
      if (dragging.classList.contains("reorder-row")) {
        var overRow = e.target.closest(".reorder-row");
        if (overRow && overRow !== dragging) {
          var rect = overRow.getBoundingClientRect();
          var before = (e.clientY - rect.top) < rect.height / 2;
          overRow.parentNode.insertBefore(dragging, before ? overRow : overRow.nextSibling);
        } else if (!overRow && overBlock !== dragging.closest(".reorder-block")) {
          // Над шапкою чи порожнім місцем іншого блоку — питання лягає в його кінець.
          overBlock.querySelector(".reorder-block-body").appendChild(dragging);
        }
      } else if (overBlock !== dragging && e.target.closest(".reorder-block-head")) {
        var headRect = e.target.closest(".reorder-block-head").getBoundingClientRect();
        var above = (e.clientY - headRect.top) < headRect.height / 2;
        list.insertBefore(dragging, above ? overBlock : overBlock.nextSibling);
      }
    });
  })();

  function applyTopicOrderFromModal() {
    var host = el("guide-topics-list");
    Array.prototype.forEach.call(document.querySelectorAll("#topic-order-list .reorder-block"), function (item) {
      var block = item._block;
      host.appendChild(block);
      var cardsHost = block.querySelector(".topic-block-cards");
      Array.prototype.forEach.call(item.querySelectorAll(".reorder-row"), function (row) {
        cardsHost.appendChild(row._card);
      });
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
    addPoint.innerHTML = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14"/><path d="M5 12h14"/></svg>' + "<span>додати пункт</span>";
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
    clearImportedDocs();
    var current = null;
    var currentName = null;
    (topics || []).forEach(function (topic) {
      var name = (topic.block || "").trim();
      if (!current || name !== currentName) {
        current = buildBlock(name);
        currentName = name;
        host.appendChild(current);
      }
      current.querySelector(".topic-block-cards").appendChild(buildTopicCard(topic));
    });
    refreshTopicOrderControls();
  }

  function collectTopicsFromCards() {
    var entries = [];
    blockEls().forEach(function (block) {
      var blockName = block.querySelector(".block-name").value.trim();
      Array.prototype.forEach.call(block.querySelectorAll(".topic-card"), function (card) {
        entries.push({ card: card, block: blockName });
      });
    });
    return entries.map(function (entry, index) {
      var card = entry.card;
      var original = card._original || {};
      var askIfMissed = card.querySelector(".topic-question-input").value.trim();
      // Пункти чекліста — завжди прості рядки: рушій більше не судить, чи
      // відповідь достатньо розгорнута, тож обʼєктна форма (needs_detail/
      // min_words) тут не потрібна навіть для вже наявних пунктів.
      var mustLearn = Array.prototype.map.call(
        card.querySelectorAll(".must-learn-item input"),
        function (input) { return input.value.trim(); }
      ).filter(Boolean);

      var topic = Object.assign({}, original, {
        id: original.id || ("topic-" + (index + 1)),
        title: askIfMissed.slice(0, 40) || ("Питання " + (index + 1)),
        ask_if_missed: askIfMissed,
        must_learn: mustLearn
      });
      delete topic.ask_for_detail;
      if (entry.block) topic.block = entry.block;
      else delete topic.block;
      return topic;
    });
  }

  function saveGuide(options) {
    var quiet = !!(options && options.quiet);
    var payload = Object.assign({}, state.guideData || {}, {
      key: state.guide,
      goal: el("guide-goal").value.trim(),
      opening: el("guide-opening").value.trim(),
      closing: el("guide-closing").value.trim(),
      max_turns: parseInt(el("guide-max-turns").value, 10) || 30,
      feedback_prompt: el("guide-feedback-prompt").value.trim(),
      feedback_style: el("guide-feedback-style").value,
      question_font_size: el("guide-question-size").value,
      question_font_weight: el("guide-question-weight").value,
      topics: collectTopicsFromCards()
    });
    // Застарілі поля колишньої «драбини заглиблення»: рушій їх більше не
    // читає, і адмінка не має тихо носити їх далі з кожним збереженням.
    delete payload.deepening;
    delete payload.generalization_markers;
    el("guide-error").textContent = "";
    return post("/api/admin/guide", { space: state.space, guide: state.guide, data: payload })
      .then(function () {
        if (!quiet) flash("Гайд збережено", "ok");
        state.guideData = payload;
        // Перемальовуємо картки: нові питання отримали справжній id щойно
        // зараз — доти запис голосу для них був недоступний.
        renderTopicCards(payload.topics);
      })
      .catch(function (err) {
        el("guide-error").textContent = err.message;
        flash("Не збережено", "bad");
        throw err;
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
      // Акцентний колір з адмінки прибрано: сторінка респондента його і так ігнорувала. Що вже було
      // в конфізі — лишається незмінним.
      branding: Object.assign({}, base.branding || {})
    });
    el("space-error").textContent = "";
    post("/api/admin/space", { space: state.space, data: payload })
      .then(function () {
        state.spaceData = payload;
        // «Вигляд питань» і «Оцінка досвіду» тепер у налаштуваннях, а живуть у гайді, тож цей
        // «Зберегти» зберігає й їх.
        return state.guide ? saveGuide({ quiet: true }) : null;
      })
      .then(function () {
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

      /* Розмова поділена на блоки «Питання N»: питання інтервʼюера й відповідь
         респондента стоять разом, а не суцільним списком реплік. Останній
         блок без відповіді — це прощання, а не питання. */
      var turnsAll = data.turns || [];
      var group = null;
      var questionNumber = 0;
      turnsAll.forEach(function (turn, index) {
        if (turn.role === "interviewer") {
          var answered = turnsAll[index + 1] && turnsAll[index + 1].role === "respondent";
          group = document.createElement("section");
          group.className = "qa-group";
          var heading = document.createElement("h3");
          heading.className = "qa-heading";
          heading.textContent = answered || index < turnsAll.length - 1
            ? "Питання " + (++questionNumber) : "Завершення";
          group.appendChild(heading);
          host.appendChild(group);
        } else if (!group) {
          group = document.createElement("section");
          group.className = "qa-group";
          host.appendChild(group);
        }
        var node = document.createElement("div");
        node.className = "turn " + turn.role;
        node.innerHTML = "<div class='who'>" +
          (turn.role === "interviewer" ? "інтервʼюер" : "респондент") + "</div>";
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
        group.appendChild(node);
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

  /* ── вивантаження всіх даних ──────────────────────────────────────────
     Один Markdown-файл на все дослідження: без нових залежностей (жодної
     .docx-бібліотеки офлайн не поставити), без бекенд-ендпоінта — ті самі
     дані, які вже віддає /api/admin/transcript для модалки "Деталі", лише
     довантажені по черзі для кожної сесії списку. Аудіо-плеєри свідомо не
     потрапляють сюди: у документі лишається тільки текст (turn.text є в
     кожному ході незалежно від того, голосова відповідь чи текстова —
     turn.voice лише вказує на файл запису). */

  function wordCount(text) {
    return ((text || "").match(/\S+/g) || []).length;
  }

  function downloadTextFile(filename, text) {
    var blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  /* Агрегати по всьому дослідженню — рахуються з уже довантажених повних
     сесій (data.turns/incidents/etc.), а не з короткого списку /api/sessions:
     останній не несе ні тексту реплік, ні часу завершення для тривалості. */
  function sessionStats(sessions) {
    var total = sessions.length;
    var completed = sessions.filter(function (s) { return s.completed; });
    var topicsTotal = (state.guideData && state.guideData.topics || []).length;

    var durations = [];
    completed.forEach(function (s) {
      if (!s.started_at || !s.finished_at) return;
      var ms = new Date(s.finished_at) - new Date(s.started_at);
      if (ms > 0) durations.push(ms / 60000);
    });

    var respondentWordCounts = [];
    sessions.forEach(function (s) {
      (s.turns || []).forEach(function (t) {
        if (t.role === "respondent") respondentWordCounts.push(wordCount(t.text));
      });
    });

    var coverageRatios = [];
    if (topicsTotal) {
      sessions.forEach(function (s) {
        coverageRatios.push((s.topics_covered || []).length / topicsTotal);
      });
    }

    var consented = sessions.filter(function (s) { return s.voice_consent; }).length;

    var ratings = [];
    sessions.forEach(function (s) {
      if (s.feedback && s.feedback.rating) ratings.push(s.feedback.rating);
    });

    var avg = function (list) {
      return list.length ? list.reduce(function (a, b) { return a + b; }, 0) / list.length : null;
    };
    var fmt1 = function (n) { return n === null ? "—" : n.toFixed(1); };
    var fmtPct = function (n) { return n === null ? "—" : Math.round(n * 100) + "%"; };

    return [
      "- Респондентів: " + total + " (завершено: " + completed.length +
        ", перервано: " + (total - completed.length) + ")",
      "- Середня тривалість завершеного інтервʼю: " + fmt1(avg(durations)) + " хв",
      "- Середня глибина відповіді: " + fmt1(avg(respondentWordCounts)) + " слів на репліку респондента",
      "- Покриття тем: " + fmtPct(avg(coverageRatios)),
      "- Згода на запис голосу: " + consented + " з " + total,
      "- Середня оцінка досвіду: " + fmt1(avg(ratings)) + "/5 (з " + ratings.length + " оцінок)"
    ].join("\n");
  }

  function sessionToMarkdown(session) {
    var out = [];
    var heading = session.respondent_name || session.session_id;
    out.push("## " + heading + " — " + formatDateTime(session.started_at) +
      (session.completed ? "" : ", перервано"));

    if (session.feedback && (session.feedback.rating || session.feedback.comment)) {
      var fb = "**Оцінка досвіду:**";
      if (session.feedback.rating) fb += " " + session.feedback.rating + "/5";
      if (session.feedback.comment) fb += " — \"" + session.feedback.comment + "\"";
      out.push(fb);
    }

    if (session.incidents && session.incidents.length) {
      out.push("**Інциденти:**");
      session.incidents.forEach(function (incident) {
        out.push("- " + describeIncident(incident).text);
      });
    }

    out.push("");
    (session.turns || []).forEach(function (turn) {
      var who = turn.role === "interviewer" ? "ІНТЕРВ'ЮЕР" : "РЕСПОНДЕНТ";
      out.push("**" + who + ":** " + (turn.text || ""));
    });

    return out.join("\n");
  }

  function exportAllRuns() {
    var items = state.runs || [];
    var btn = el("btn-export-runs");
    if (!items.length) {
      flash("Немає завершених інтервʼю для вивантаження", "bad");
      return;
    }
    btn.disabled = true;
    var originalText = btn.innerHTML;
    btn.textContent = "Готую…";

    Promise.all(items.map(function (item) {
      return api("/api/admin/transcript?id=" + encodeURIComponent(item.session_id));
    })).then(function (sessions) {
      var title = (state.spaceData && state.spaceData.title) || state.space;
      var doc = [
        "# " + title,
        "Експортовано: " + formatDateTime(new Date().toISOString()),
        "",
        "## Статистика",
        sessionStats(sessions),
        ""
      ];
      sessions.forEach(function (session) {
        doc.push(sessionToMarkdown(session));
        doc.push("");
      });

      var filename = (state.space || "дослідження") + "-" +
        new Date().toISOString().slice(0, 10) + ".md";
      downloadTextFile(filename, doc.join("\n"));
      flash("Завантажено", "ok");
    }).catch(function (err) {
      flash("Не вдалося вивантажити: " + err.message, "bad");
    }).finally(function () {
      btn.disabled = false;
      btn.innerHTML = originalText;
    });
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

  /* ── Імпорт списку питань з файлу ────────────────────────────────────
     Файл може нести й блоки (категорії) — тоді питання розкладаються по них:
     — .txt/.md: рядок «Блок: Назва» / «Категорія: Назва» / «## Назва» / «Назва:»
       відкриває блок, рядки під ним — його питання (маркери й нумерацію
       зрізаємо); без заголовків — просто одне питання в рядку;
     — .csv: з заголовком (колонки «блок»/«категорія» й «питання») — по колонках;
       без заголовка — перша колонка, як і раніше;
     — .json: масив рядків; масив обʼєктів з полем block/category; групи
       {block, questions: […]}; або обʼєкт {«Блок»: […питання…]}.
     Нові картки лише додаються в редактор: нічого не зберігається, доки
     дослідник не натисне «Зберегти гайд». */
  var IMPORT_BLOCK_WORDS = "блок|категорія|категория|розділ|раздел|block|category|section";
  var IMPORT_BLOCK_KEYS = ["block", "category", "section", "блок", "категорія", "категория", "розділ"];
  var IMPORT_GROUP_NAME_KEYS = IMPORT_BLOCK_KEYS.concat(["title", "name", "назва"]);
  var IMPORT_LIST_KEYS = ["questions", "topics", "items", "питання"];

  function firstOf(item, keys) {
    for (var i = 0; i < keys.length; i++) {
      var value = item[keys[i]];
      if (value !== undefined && value !== null && String(value).trim() !== "") return value;
    }
    return "";
  }

  function importQuestion(item, block) {
    if (typeof item === "string") return { text: item.trim(), must_learn: [], block: block };
    var text = item.ask_if_missed || item.text || item.question || item["питання"] || "";
    var own = String(firstOf(item, IMPORT_BLOCK_KEYS)).trim();
    return {
      text: String(text).trim(),
      must_learn: item.must_learn || item.expects || [],
      block: own || block
    };
  }

  function importFromJson(data, block, out) {
    var list = Array.isArray(data) ? data : null;
    if (!list && data && typeof data === "object") {
      var listed = null;
      ["blocks", "categories", "sections", "блоки", "категорії"].concat(IMPORT_LIST_KEYS).forEach(function (key) {
        if (!listed && Array.isArray(data[key])) listed = data[key];
      });
      if (listed) list = listed;
      else {
        // {"Назва блоку": [питання…], …}
        Object.keys(data).forEach(function (key) {
          if (Array.isArray(data[key])) importFromJson(data[key], key.trim(), out);
        });
        return out;
      }
    }
    (list || []).forEach(function (item) {
      if (item && typeof item === "object" && !Array.isArray(item)) {
        var children = null;
        IMPORT_LIST_KEYS.forEach(function (key) {
          if (!children && Array.isArray(item[key])) children = item[key];
        });
        var hasOwnText = item.ask_if_missed || item.text || item.question || item["питання"];
        if (children && !hasOwnText) {
          var groupName = String(firstOf(item, IMPORT_GROUP_NAME_KEYS)).trim() || block;
          importFromJson(children, groupName, out);
          return;
        }
      }
      out.push(importQuestion(item, block));
    });
    return out;
  }

  // Мінімальний розбір CSV з лапками; роздільник — кома або крапка з комою.
  function parseCsv(text) {
    var firstLine = text.split(/\r?\n/, 1)[0] || "";
    var delimiter = (firstLine.split(";").length > firstLine.split(",").length) ? ";" : ",";
    var rows = [], row = [], cell = "", quoted = false;
    for (var i = 0; i < text.length; i++) {
      var ch = text[i];
      if (quoted) {
        if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; }
        else if (ch === '"') quoted = false;
        else cell += ch;
      } else if (ch === '"') quoted = true;
      else if (ch === delimiter) { row.push(cell); cell = ""; }
      else if (ch === "\n" || ch === "\r") {
        if (ch === "\r" && text[i + 1] === "\n") i++;
        row.push(cell); cell = "";
        rows.push(row); row = [];
      } else cell += ch;
    }
    if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
    return rows.filter(function (r) { return r.some(function (c) { return c.trim(); }); });
  }

  function importFromCsv(text) {
    var rows = parseCsv(text);
    if (!rows.length) return [];
    var header = rows[0].map(function (c) { return c.trim().toLowerCase(); });
    var blockCol = -1, questionCol = -1, checklistCol = -1;
    header.forEach(function (cell, index) {
      if (new RegExp("^(" + IMPORT_BLOCK_WORDS + ")$").test(cell)) blockCol = index;
      else if (/^(питання|question|текст|text)$/.test(cell)) questionCol = index;
      else if (/^(чекліст|checklist|must_learn|expects|про що варто сказати)$/.test(cell)) checklistCol = index;
    });
    var hasHeader = blockCol !== -1 || questionCol !== -1;
    if (hasHeader) rows.shift();
    if (questionCol === -1) {
      for (var i = 0; i < (rows[0] || header).length; i++) {
        if (i !== blockCol && i !== checklistCol) { questionCol = i; break; }
      }
      if (questionCol === -1) questionCol = 0;
    }
    return rows.map(function (cols) {
      var points = checklistCol === -1 ? [] : String(cols[checklistCol] || "")
        .split(/[|\n]/).map(function (x) { return x.trim(); }).filter(Boolean);
      return {
        text: String(cols[questionCol] || "").trim(),
        must_learn: points,
        block: blockCol === -1 ? "" : String(cols[blockCol] || "").trim()
      };
    });
  }

  function importFromText(text) {
    var out = [];
    var block = "";
    var last = null;          // останнє питання — до нього відносяться пункти чекліста
    var lastNumbered = false; // питання було пронумероване (тоді «- …» під ним — пункти)
    var lastNumber = 0;       // номер останнього пронумерованого питання
    var inChecklist = false;  // після рядка «Про що варто сказати:»
    var checklistStart = 0;   // скільки пунктів було до цього підпису
    var heading = [
      /^#{1,6}\s+(.+)$/,
      new RegExp("^(?:" + IMPORT_BLOCK_WORDS + ")\\s*(?:№\\s*)?[\\dIVXLC]*\\s*[:.\\-–—)]\\s*(.+)$", "i")
    ];
    var bare = new RegExp("^(?:" + IMPORT_BLOCK_WORDS + ")\\s*(?:№\\s*)?\\d+$", "i");
    // Підпис чекліста: так він зветься в редакторі («Про що варто сказати:»).
    var label = /^(?:про що (?:варто )?(?:сказати|почути)|чекліст|checklist)\s*:\s*(.*)$/i;

    text.split(/\r?\n/).forEach(function (raw) {
      // Жирний шрифт і підкреслення з Markdown («**Блок: Назва**») зрізаємо.
      var line = raw.replace(/\*\*|__|`/g, "").trim();
      if (!line) return;

      var lm = line.match(label);
      if (lm && last) {
        inChecklist = true;
        checklistStart = last.must_learn.length;
        if (lm[1].trim()) last.must_learn.push(lm[1].trim());
        return;
      }

      var found = null;
      for (var i = 0; i < heading.length && !found; i++) {
        var m = line.match(heading[i]);
        if (m) found = m[1];
      }
      if (!found && bare.test(line)) found = line;
      // «Знайомство:» — рядок із двокрапкою наприкінці й без знака питання — теж заголовок.
      if (!found && /:$/.test(line) && line.indexOf("?") === -1) found = line.slice(0, -1);
      if (found) {
        block = found.replace(/^#+\s*/, "").trim();
        last = null;
        inChecklist = false;
        return;
      }

      var bullet = /^[-*•]\s+/.test(line);
      var paren = line.match(/^(\d+)\)\s+/);
      var dotted = line.match(/^(\d+)\.\s+/);
      var number = paren ? parseInt(paren[1], 10) : (dotted ? parseInt(dotted[1], 10) : 0);
      var content = line.replace(/^(?:[-*•]|\d+[.)])\s+/, "").trim();
      if (!content) return;

      if (inChecklist && last) {
        // У чеклісті: «1)» і «-» — пункти. «N.» — нове питання лише коли N — наступний
        // номер питання; інакше це теж пункт.
        // Коли «N.» збігається і з наступним питанням, і з наступним пунктом — вирішує
        // знак питання наприкінці: пункти шпаргалки зазвичай не питання.
        var nextPoint = last.must_learn.length - checklistStart + 1;
        var isQuestion = dotted && number === lastNumber + 1 &&
          (number !== nextPoint || /\?$/.test(content));
        if (!isQuestion && (bullet || paren || dotted)) { last.must_learn.push(content); return; }
        inChecklist = false;
      }
      // «- …» одразу під пронумерованим питанням — пункт його чекліста, а не нове питання.
      if (bullet && last && lastNumbered) { last.must_learn.push(content); return; }

      last = { text: content, must_learn: [], block: block };
      lastNumbered = !!(paren || dotted);
      if (lastNumbered) lastNumber = number;
      out.push(last);
    });
    return out;
  }

  function parseQuestionsFile(name, text) {
    text = String(text || "").replace(/^﻿/, "");
    var items;
    if (/\.json$/i.test(name)) items = importFromJson(JSON.parse(text), "", []);
    else if (/\.csv$/i.test(name)) items = importFromCsv(text);
    else items = importFromText(text);
    return items.filter(function (q) { return q.text; });
  }

  /* Питання з назвою блоку йдуть у блок із такою назвою (існуючий або новий);
     без назви — в останній блок, як було до появи блоків. */
  function appendImportedQuestions(questions, importId) {
    var fallback = lastBlockCards();
    var hosts = {};
    blockEls().forEach(function (block) {
      var name = block.querySelector(".block-name").value.trim();
      if (name && !hosts[name]) hosts[name] = block.querySelector(".topic-block-cards");
    });
    var newBlocks = 0;
    questions.forEach(function (q) {
      var host = fallback;
      if (q.block) {
        if (!hosts[q.block]) {
          var block = buildBlock(q.block);
          el("guide-topics-list").appendChild(block);
          hosts[q.block] = block.querySelector(".topic-block-cards");
          newBlocks++;
        }
        host = hosts[q.block];
      }
      var card = buildTopicCard({ ask_if_missed: q.text, must_learn: q.must_learn });
      card._importId = importId;
      host.appendChild(card);
    });
    refreshTopicOrderControls();
    return newBlocks;
  }

  /* Документи, з яких зараз у редакторі є питання. Видалення документа
     прибирає всі його питання (блок, що спорожнів, зникає разом із ними).
     Після збереження гайда питання вже частина гайда, тож список очищується. */
  var importSeq = 0;

  function clearImportedDocs() {
    var host = el("import-docs");
    if (host) host.innerHTML = "";
  }

  function addImportedDoc(importId, name, count, newBlocks) {
    var row = document.createElement("div");
    row.className = "import-result";
    row.innerHTML = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>';
    var nameNode = document.createElement("span");
    nameNode.className = "import-name";
    nameNode.textContent = name;
    row.appendChild(nameNode);
    var countNode = document.createElement("span");
    countNode.className = "import-count";
    var message = count + " " + pluralQuestions(count);
    if (newBlocks) message += ", нових блоків: " + newBlocks;
    countNode.textContent = message;
    row.appendChild(countNode);
    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "icon-btn import-dismiss";
    remove.title = "Видалити документ разом із його питаннями";
    remove.setAttribute("aria-label", "Видалити документ разом із його питаннями");
    remove.innerHTML = ICONS.trash;
    remove.addEventListener("click", function () { removeImportedDoc(importId, name, row); });
    row.appendChild(remove);
    el("import-docs").appendChild(row);
  }

  function removeImportedDoc(importId, name, row) {
    var cards = topicCards().filter(function (card) { return card._importId === importId; });
    if (cards.length && !window.confirm(
        "Видалити документ «" + name + "» разом із його питаннями (" + cards.length + ")?")) return;
    cards.forEach(function (card) { card.remove(); });
    refreshTopicOrderControls();
    // Гайд без жодного питання не збережеться — лишаємо порожню картку, щоб редактор не був порожнім.
    if (!topicCards().length) {
      var block = buildBlock("");
      block.querySelector(".topic-block-cards").appendChild(buildTopicCard({}));
      el("guide-topics-list").appendChild(block);
      refreshTopicOrderControls();
    }
    row.remove();
  }

  var IMPORT_PROMPT = [
    "Ти допомагаєш дослідниці підготувати гайд для глибинного інтервʼю. Склади список питань для такого дослідження: [ВСТАВТЕ СЮДИ МЕТУ ДОСЛІДЖЕННЯ І ХТО РЕСПОНДЕНТИ].",
    "",
    "Дай відповідь ЛИШЕ текстом файлу, без вступу, пояснень і розмітки Markdown (без жирного шрифту, таблиць, блоків коду), у такому форматі:",
    "",
    "Блок: Назва смислового блоку",
    "1. Текст питання, яке почує респондент?",
    "Про що варто сказати:",
    "1) перший пункт шпаргалки",
    "2) другий пункт шпаргалки",
    "2. Наступне питання?",
    "Про що варто сказати:",
    "1) пункт",
    "",
    "Блок: Назва наступного блоку",
    "3. Питання наступного блоку?",
    "",
    "Правила:",
    "- Назва блоку стоїть лише в рядку «Блок: …» і більше ніде. У тексті питань назв блоків немає.",
    "- Питання нумеруються наскрізно: 1., 2., 3. через усі блоки (цифра й крапка). Блоки не нумеруй.",
    "- Під кожним питанням — рядок «Про що варто сказати:», а під ним 2–4 пункти шпаргалки, ПРОНУМЕРОВАНІ окремо для кожного питання: 1), 2), 3) (цифра й дужка, щоб їх не плутати з питаннями). Це підказка для дослідниці про те, що варто почути у відповіді, а не текст для респондента.",
    "- 3–6 блоків за логікою розмови: від знайомства й контексту до деталей і підсумку.",
    "- У кожному блоці 2–5 питань, усього не більше 30.",
    "- Питання відкриті («Розкажіть…», «Як…», «Що…»): одне питання — одна думка, без підказок відповіді й без закритих «так/ні».",
    "- Питання звернені до респондента на «ви», природною розмовною мовою."
  ].join("\n");

  function copyImportPrompt(button) {
    var done = function () {
      var original = button.textContent;
      button.textContent = "Скопійовано";
      setTimeout(function () { button.textContent = original; }, 1800);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(IMPORT_PROMPT).then(done, function () { window.prompt("Скопіюйте промпт:", IMPORT_PROMPT); });
    } else {
      window.prompt("Скопіюйте промпт:", IMPORT_PROMPT);
    }
  }

  function importQuestionsFile(file) {
    var errorNode = el("import-error");
    errorNode.textContent = "";
    if (!file) return;
    if (file.size > 200 * 1024) { errorNode.textContent = "Файл завеликий: до 200 КБ."; return; }
    var reader = new FileReader();
    reader.onerror = function () { errorNode.textContent = "Не вдалося прочитати файл."; };
    reader.onload = function () {
      var questions;
      try { questions = parseQuestionsFile(file.name, reader.result); }
      catch (err) { errorNode.textContent = "Файл не схожий на список питань: " + err.message; return; }
      if (!questions.length) { errorNode.textContent = "У файлі немає питань."; return; }
      if (questions.length > 100) { errorNode.textContent = "Забагато питань: до 100 за раз."; return; }
      importSeq += 1;
      var newBlocks = appendImportedQuestions(questions, importSeq);
      addImportedDoc(importSeq, file.name, questions.length, newBlocks);
    };
    reader.readAsText(file, "utf-8");
  }
  (function () {
    var drop = el("import-drop");
    var input = el("import-file");
    drop.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); input.click(); }
    });
    input.addEventListener("change", function () {
      importQuestionsFile(input.files && input.files[0]);
      input.value = "";
    });
    ["dragenter", "dragover"].forEach(function (type) {
      drop.addEventListener(type, function (event) { event.preventDefault(); drop.classList.add("dragover"); });
    });
    ["dragleave", "drop"].forEach(function (type) {
      drop.addEventListener(type, function (event) { event.preventDefault(); drop.classList.remove("dragover"); });
    });
    drop.addEventListener("drop", function (event) {
      importQuestionsFile(event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0]);
    });
    el("import-copy-prompt").addEventListener("click", function () { copyImportPrompt(el("import-copy-prompt")); });
  })();

  el("btn-add-block").addEventListener("click", addBlock);
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
  el("btn-export-runs").addEventListener("click", exportAllRuns);
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
  el("btn-save-guide").addEventListener("click", function () { saveGuide().catch(function () { /* помилку вже показано */ }); });
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
    feedbackStyle: initSelect("guide-feedback-style"),
    questionSize: initSelect("guide-question-size"),
    questionWeight: initSelect("guide-question-weight")
  };

  /* Семпл кольору просто в полі — видно, який відтінок стоїть, без
     здогадок по hex. */
  

  function refresh() {
    return api("/api/admin/spaces").then(function (data) {
      state.spaces = data.items;
      renderSpaces();
    });
  }

  /* ── DESIGN-CANVAS: стани за URL ─────────────────────────────────────
     `?canvas=<стан>` натискає ТІ САМІ кнопки, що й дослідник. Працює лише на localhost.
     Стани: questions, runs-list, transcript, new-space, status-menu, trash-empty.
     DELETE WITH: the design-canvas/ folder (canvas-app/), разом із цим блоком. */
  function applyCanvasPin(pin) {
    var host = window.location.hostname;
    if (host !== "localhost" && host !== "127.0.0.1") return Promise.resolve();
    function click(selector) { var node = document.querySelector(selector); if (node) node.click(); }
    function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }
    function post(url, body) {
      return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}) }).then(function (r) { return r.json(); });
    }
    function ensureFinishedRun() {
      return fetch("/api/sessions").then(function (r) { return r.json(); }).then(function (list) {
        var items = list.items || list.sessions || list || [];
        if (items.length) return null;
        return post("/api/start", { record_voice: false, respondent_name: "Олена Коваленко" }).then(function (started) {
          var text = "Це була дуже цікава ситуація, я добре її памʼятаю і можу розповісти детальніше.";
          // Повне інтервʼю: відповідь на кожне питання, щоб транскрипт мав усю послідовність питань.
          function next(count) {
            return post("/api/answer", { session_id: started.session_id, text: text }).then(function (ans) {
              if (count >= 12 || !ans.progress || ans.progress.at_end) return null;
              return post("/api/step", { session_id: started.session_id, delta: 1 }).then(function () { return next(count + 1); });
            });
          }
          return next(0).then(function () { return post("/api/finish", { session_id: started.session_id }); });
        });
      });
    }
    if (pin === "questions") { click('.tab[data-tab="questions"]'); return Promise.resolve(); }
    if (pin === "status-menu") { click("#page-status"); return Promise.resolve(); }
    if (pin === "new-space") { click("#btn-new-space"); return Promise.resolve(); }
    if (pin === "trash-empty") { click("#btn-toggle-trash"); return Promise.resolve(); }
    if (pin === "runs-list" || pin === "transcript") {
      return ensureFinishedRun().then(function () {
        click('.tab[data-tab="runs"]');
        return wait(600);
      }).then(function () {
        if (pin === "transcript") { var open = document.querySelector("#runs-list .run button"); if (open) open.click(); }
      });
    }
    return Promise.resolve();
  }

  // Адреса окремого сайту респондента (якщо панель і форма — різні сайти).
  fetch("/api/admin/site").then(function (r) { return r.json(); }).then(function (d) {
    state.respondentUrl = (d && d.respondent_url) || "";
  }).catch(function () { /* лишається поточний origin */ });

  refresh().then(function () {
    if (state.spaces.length) selectSpace(state.spaces[0].key);
    var pin = new URLSearchParams(window.location.search).get("canvas");
    if (pin) return applyCanvasPin(pin).then(function () {
      /* Сигнал для capture.mjs: стан застосовано (контракт design-canvas). */
      document.documentElement.setAttribute("data-canvas-pinned", pin);
    });
  }).catch(function (err) {
    el("space-list").innerHTML = "<li class='muted'>" + err.message + "</li>";
  });
  loadTrash();
})();
