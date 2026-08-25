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
                trash: [], trashOpen: false };

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

  /* Шаблони маскування — технічна річ (регулярки), тому рядковий формат
     `назва | регулярка | замінник` замість трьох полів на правило: швидше
     редагувати, а валідність усе одно перевіряє сервер. */
  function patternsToText(patterns) {
    return (patterns || []).map(function (rule) {
      return [rule.name || "", rule.pattern || "", rule.replacement || ""].join(" | ");
    }).join("\n");
  }

  function patternsFromText(text) {
    return (text || "").split("\n").map(function (line) {
      return line.trim();
    }).filter(function (line) {
      return line.length && line.indexOf("|") !== -1;
    }).map(function (line) {
      // Розділяємо лише за першими двома «|»: регулярка може містити «|» сама.
      var first = line.indexOf("|");
      var last = line.lastIndexOf("|");
      if (last === first) last = line.length;
      return {
        name: line.slice(0, first).trim(),
        pattern: line.slice(first + 1, last).trim(),
        replacement: line.slice(last + 1).trim() || "[ПРИХОВАНО]"
      };
    }).filter(function (rule) { return rule.pattern.length; });
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
    state.spaces.forEach(function (space) {
      var li = document.createElement("li");
      var button = document.createElement("button");
      button.className = state.space === space.key ? "active" : "";
      button.innerHTML = "";
      button.appendChild(document.createTextNode(space.title || space.key));
      if (space.draft) {
        var tag = document.createElement("span");
        tag.className = "draft-tag";
        tag.textContent = "чернетка";
        button.appendChild(tag);
      }
      var sub = document.createElement("span");
      sub.className = "sub" + (space.error ? " broken" : "");
      sub.textContent = space.error
        ? ("⛔ " + space.error)
        : (space.key + " · " + space.guides.length + " гайд(ів)");
      button.appendChild(sub);
      button.addEventListener("click", function () { selectSpace(space.key); });
      li.appendChild(button);
      list.appendChild(li);
    });
  }

  function selectSpace(key) {
    state.space = key;
    toggleDeleteConfirm(false);
    renderSpaces();
    var space = state.spaces.filter(function (s) { return s.key === key; })[0];
    var select = el("guide-select");
    select.innerHTML = "";
    (space.guides || []).forEach(function (g) {
      var option = document.createElement("option");
      option.value = g;
      option.textContent = g;
      select.appendChild(option);
    });

    loadSpaceData();
    if (space.guides && space.guides.length) loadGuide(space.guides[0]);
    else { state.guideData = null; el("guide-topics").value = ""; }
  }

  /* ── гайд ──────────────────────────────────────────────────────────── */

  function loadGuide(key) {
    state.guide = key;
    el("guide-select").value = key;
    api("/api/admin/guide?space=" + encodeURIComponent(state.space) +
        "&guide=" + encodeURIComponent(key)).then(function (data) {
      state.guideData = data;
      el("guide-goal").value = data.goal || "";
      el("guide-opening").value = data.opening || "";
      el("guide-closing").value = data.closing || "";
      el("guide-max-turns").value = data.max_turns || 30;
      el("guide-topics").value = topicsToText(data.topics || []);
      el("guide-error").textContent = "";
    }).catch(function (err) { el("guide-error").textContent = err.message; });
  }

  /* Теми — один текстовий блок замість окремих полів на кожну: абзац =
     тема, перший рядок — назва, решта — пункти «що зʼясувати». Ключ (id)
     не редагується руками — генерується за порядком абзаців, як і раніше
     генерувався для нового простору («topic-1», «topic-2», …). Кількість
     уточнень — необовʼязкове число в дужках після назви; без нього
     лишається дефолт (4).

     Гайд може мати поля, яких у цьому текстовому вигляді просто немає
     (goal, ask_if_missed, ask_for_detail, shown_as, позначки needs_detail
     на пункті) — їх і стара форма з окремими полями не показувала й не
     редагувала. Щоб збереження текстом їх не змило, тему, чий текст не
     змінився, повертаємо як є (з усіма її полями); лише реально
     відредаговані рядки перетворюються на прості рядки без цих позначок.
  */
  function mustLearnText(item) {
    return (item && typeof item === "object") ? (item.text || "") : (item || "");
  }

  function topicsToText(topics) {
    return (topics || []).map(function (t) {
      var probes = t.max_probes == null ? 4 : t.max_probes;
      var head = (t.title || "") + " (" + probes + ")";
      var body = (t.must_learn || []).map(mustLearnText);
      return [head].concat(body).join("\n");
    }).join("\n\n");
  }

  function topicsFromText(text) {
    var original = (state.guideData && state.guideData.topics) || [];
    var blocks = (text || "").split(/\n\s*\n/).map(function (block) {
      return block.split("\n").map(function (s) { return s.trim(); })
        .filter(function (s) { return s.length; });
    }).filter(function (lines) { return lines.length; });

    return blocks.map(function (lines, index) {
      var head = lines[0];
      var match = head.match(/^(.*)\((\d+)\)\s*$/);
      var title = match ? match[1].trim() : head;
      var probesFromText = match ? (parseInt(match[2], 10) || 4) : null;
      var mustLearnLines = lines.slice(1);
      var base = original[index] || {};

      var baseText = (base.must_learn || []).map(mustLearnText);
      var unchanged = base.title === title && baseText.length === mustLearnLines.length &&
        baseText.every(function (t, i) { return t === mustLearnLines[i]; });

      return Object.assign({}, base, {
        id: base.id || ("topic-" + (index + 1)),
        title: title,
        must_learn: unchanged ? base.must_learn : mustLearnLines,
        max_probes: probesFromText != null ? probesFromText
          : (base.max_probes == null ? 4 : base.max_probes)
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
      topics: topicsFromText(el("guide-topics").value)
    });
    el("guide-error").textContent = "";
    post("/api/admin/guide", { space: state.space, guide: state.guide, data: payload })
      .then(function () { flash("Гайд збережено", "ok"); state.guideData = payload; })
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
      el("space-address").value = (data.persona || {}).address || "ви";
      el("space-tone").value = (data.persona || {}).tone || "";
      el("space-intro").value = (data.persona || {}).self_intro || "";
      el("space-vocab").value = lines.toText(data.domain_vocabulary);
      el("space-never").value = lines.toText((data.privacy || {}).never_ask_about);
      el("space-deidentify").checked = !!(data.privacy || {}).deidentify;
      el("space-ready").checked = !data.draft;
      el("space-consent").value = (data.privacy || {}).consent_text || "";
      el("space-patterns").value = patternsToText((data.privacy || {}).patterns);
      el("space-report").value = lines.toText(data.report_sections);
      el("space-mode").value = ((data.interface || {}).mode) || "text";
      el("space-autoplay").checked = !!((data.interface || {}).autoplay);
      el("space-accent").value = (data.branding || {}).accent || "";
      el("space-page-title").value = (data.branding || {}).page_title || "";
      el("space-error").textContent = "";
    }).catch(function (err) { el("space-error").textContent = err.message; });
  }

  function saveSpace() {
    var base = state.spaceData || {};
    var payload = Object.assign({}, base, {
      title: el("space-title").value.trim(),
      languages: el("space-languages").value.split(",").map(function (s) { return s.trim(); })
        .filter(function (s) { return s.length; }),
      persona: Object.assign({}, base.persona || {}, {
        self_intro: el("space-intro").value.trim(),
        address: el("space-address").value,
        tone: el("space-tone").value.trim()
      }),
      domain_vocabulary: lines.fromText(el("space-vocab").value),
      privacy: Object.assign({}, base.privacy || {}, {
        never_ask_about: lines.fromText(el("space-never").value),
        deidentify: el("space-deidentify").checked,
        consent_text: el("space-consent").value.trim(),
        patterns: patternsFromText(el("space-patterns").value)
      }),
      report_sections: lines.fromText(el("space-report").value),
      // Готовність знімає з чернетки саме людина, а не факт «щось зберегли».
      draft: !el("space-ready").checked,
      interface: Object.assign({}, base.interface || {}, {
        mode: el("space-mode").value,
        autoplay: el("space-autoplay").checked
      }),
      // providers (LLM/TTS) сюди не входять: на задеплоєній версії їх все
      // одно підмінює env-змінна (LLM_PROVIDER_OVERRIDE/TTS_PROVIDER_OVERRIDE),
      // тож редагування тут лише вводило б в оману. Що вже було в конфізі —
      // лишається незмінним через base.
      branding: Object.assign({}, base.branding || {}, {
        accent: el("space-accent").value.trim(),
        page_title: el("space-page-title").value.trim()
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

  function toggleDeleteConfirm(show) {
    el("delete-confirm").classList.toggle("hidden", !show);
    el("delete-error").textContent = "";
    if (show) {
      var space = state.spaces.filter(function (s) { return s.key === state.space; })[0];
      el("delete-confirm-title").textContent = (space && (space.title || space.key)) || state.space;
    }
  }

  function deleteSpace() {
    el("delete-error").textContent = "";
    post("/api/admin/space/delete", { space: state.space })
      .then(function () {
        toggleDeleteConfirm(false);
        flash("Перенесено в кошик", "ok");
        if (state.trashOpen) loadTrash();
        return refresh().then(function () {
          if (state.spaces.length) selectSpace(state.spaces[0].key);
        });
      })
      .catch(function (err) { el("delete-error").textContent = err.message; });
  }

  /* ── кошик ─────────────────────────────────────────────────────────── */

  function loadTrash() {
    return api("/api/admin/trash").then(function (data) {
      state.trash = data.items;
      renderTrash();
    });
  }

  function renderTrash() {
    var host = el("trash-list");
    host.innerHTML = "";
    if (!state.trash.length) {
      host.innerHTML = "<li class='muted tiny'>Кошик порожній.</li>";
      return;
    }
    state.trash.forEach(function (item) {
      var li = document.createElement("li");
      var row = document.createElement("div");
      row.className = "trash-row";

      var name = document.createElement("span");
      name.textContent = item.title || item.key;
      row.appendChild(name);

      var restore = document.createElement("button");
      restore.type = "button";
      restore.className = "ghost small";
      restore.textContent = "Відновити";
      restore.addEventListener("click", function () { restoreSpace(item.key); });
      row.appendChild(restore);

      var purge = document.createElement("button");
      purge.type = "button";
      purge.className = "ghost small";
      purge.textContent = "Видалити назавжди";
      purge.addEventListener("click", function () { togglePurgeConfirm(li, item); });
      row.appendChild(purge);

      li.appendChild(row);
      host.appendChild(li);
    });
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
     дія, на відміну від переносу в кошик. */
  function togglePurgeConfirm(li, item) {
    var existing = li.querySelector(".purge-confirm");
    if (existing) { existing.remove(); return; }

    var box = document.createElement("div");
    box.className = "purge-confirm";
    box.innerHTML =
      "<p class='muted tiny'>Видалити «" + (item.title || item.key) +
      "» назавжди. Що зробити з уже зібраними відповідями респондентів?</p>";

    var actions = document.createElement("div");
    actions.className = "actions";

    var keepData = document.createElement("button");
    keepData.type = "button";
    keepData.className = "ghost small";
    keepData.textContent = "Лишити відповіді";
    keepData.addEventListener("click", function () { purgeSpace(item.key, false); });
    actions.appendChild(keepData);

    var withData = document.createElement("button");
    withData.type = "button";
    withData.className = "danger small";
    withData.textContent = "Видалити разом із відповідями";
    withData.addEventListener("click", function () { purgeSpace(item.key, true); });
    actions.appendChild(withData);

    var cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "ghost small";
    cancel.textContent = "Скасувати";
    cancel.addEventListener("click", function () { box.remove(); });
    actions.appendChild(cancel);

    box.appendChild(actions);
    li.appendChild(box);
  }

  function purgeSpace(key, withSessions) {
    post("/api/admin/trash/purge", { space: key, delete_sessions: withSessions })
      .then(function (result) {
        flash(withSessions
          ? ("Видалено назавжди разом із " + result.removed_sessions + " інтервʼю респондентів")
          : "Видалено назавжди. Відповіді респондентів лишились у сховищі", "ok");
        return loadTrash();
      })
      .catch(function (err) { flash(err.message, "bad"); });
  }

  /* ── результати ────────────────────────────────────────────────────── */

  function loadRuns() {
    api("/api/sessions").then(function (data) {
      var host = el("runs-list");
      host.innerHTML = "";
      var items = data.items.filter(function (item) { return item.space === state.space; });
      if (!items.length) {
        host.innerHTML = "<p class='muted'>Завершених інтервʼю тут ще немає.</p>";
        return;
      }
      items.forEach(function (item) {
        var row = document.createElement("div");
        row.className = "run";

        var main = document.createElement("div");
        main.innerHTML = "<strong>" + (item.started_at || "—") + "</strong>" +
          "<div class='muted tiny'>" + item.space + " / " + item.guide +
          " · " + item.prompt_version + "</div>";
        row.appendChild(main);

        var turns = document.createElement("span");
        turns.className = "pill";
        turns.textContent = item.turns + " реплік";
        row.appendChild(turns);

        var incidents = document.createElement("span");
        incidents.className = "pill" + (item.incidents ? " warn" : "");
        incidents.textContent = item.incidents + " інцидентів";
        row.appendChild(incidents);

        // Записи голосу — тут, а не в транскрипті: дослідник спершу вибирає
        // інтервʼю, і йому треба бачити, яке з них можна переслухати.
        if (item.voice && item.voice.length) {
          var voice = document.createElement("button");
          voice.className = "ghost small";
          voice.textContent = "🎧 " + item.voice.length;
          voice.title = "Прослухати записи голосу респондента";
          voice.addEventListener("click", function () {
            showVoice(item.session_id, item.voice, row);
          });
          row.appendChild(voice);
        }

        var open = document.createElement("button");
        open.className = "ghost small";
        open.textContent = "Транскрипт";
        open.addEventListener("click", function () { showTranscript(item.session_id); });
        row.appendChild(open);

        host.appendChild(row);
      });
    }).catch(function (err) {
      el("runs-list").textContent = err.message;
    });
  }

  /* Плеєри розгортаються під рядком інтервʼю. Окремого екрана не робимо:
     дослідник слухає, звіряючи з тим самим рядком, який щойно вибрав. */
  function showVoice(sessionId, clips, row) {
    var existing = row.nextSibling;
    if (existing && existing.className === "voice-clips") {
      existing.parentNode.removeChild(existing);
      return;
    }
    var box = document.createElement("div");
    box.className = "voice-clips";
    clips.forEach(function (name, index) {
      var line = document.createElement("div");
      line.className = "voice-clip";
      var label = document.createElement("span");
      label.className = "muted tiny";
      label.textContent = "запис " + (index + 1) + " · " + name;
      var player = document.createElement("audio");
      player.controls = true;
      player.preload = "none";
      player.src = "/voice/" + sessionId + "/" + name;
      line.appendChild(label);
      line.appendChild(player);
      box.appendChild(line);
    });
    row.parentNode.insertBefore(box, row.nextSibling);
  }

  /* Кожен вид інциденту має власні поля. Раніше рендерер чекав `problems` у
     всіх, і маскування виводилось порожнім рядком. */
  function describeIncident(incident) {
    if (incident.kind === "override") return "🔒 ядро: " + incident.detail;
    if (incident.kind === "guard_rejection") {
      return "⛔ guard відхилив репліку (спроба " + (incident.attempt || 1) + "): " +
        (incident.problems || []).join("; ");
    }
    if (incident.kind === "guard_fallback") {
      return "⚠️ модель не змогла сформулювати репліку без порушень — пішло нейтральне питання";
    }
    if (incident.kind === "deidentified") {
      return "🛡 замасковано у відповіді: " + (incident.rules || []).map(function (r) {
        return r.rule + (r.count > 1 ? (" ×" + r.count) : "");
      }).join(", ");
    }
    return "• " + incident.kind;
  }

  function showTranscript(id) {
    api("/api/admin/transcript?id=" + encodeURIComponent(id)).then(function (data) {
      var host = el("transcript");
      host.innerHTML = "<h2>Транскрипт " + data.session_id + "</h2>";

      (data.incidents || []).forEach(function (incident) {
        var node = document.createElement("div");
        node.className = "incident";
        node.textContent = describeIncident(incident);
        host.appendChild(node);
      });

      (data.turns || []).forEach(function (turn) {
        var node = document.createElement("div");
        node.className = "turn " + turn.role;
        node.innerHTML = "<div class='who'>" +
          (turn.role === "interviewer" ? "інтервʼюер" : "респондент") +
          (turn.topic_id ? (" · " + turn.topic_id) : "") + "</div>";
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
      host.scrollIntoView({ behavior: "smooth", block: "start" });
    }).catch(function (err) { el("transcript").textContent = err.message; });
  }

  /* ── новий простір ─────────────────────────────────────────────────── */

  /* Форма, а не window.prompt: prompt блокує потік і в частині вбудованих
     контекстів браузер його просто не показує — фіча тихо ламається. */
  function toggleNewSpace(show) {
    el("new-space-form").classList.toggle("hidden", !show);
    el("new-space-error").textContent = "";
    if (show) {
      el("new-space-key").value = "";
      el("new-space-title").value = "";
      el("new-space-key").focus();
    }
  }

  function newSpace(event) {
    if (event) event.preventDefault();
    var key = el("new-space-key").value.trim().toLowerCase();
    var title = el("new-space-title").value.trim() || key;
    if (!key) {
      el("new-space-error").textContent = "Потрібен ключ.";
      return;
    }
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
      ["guide", "space", "runs"].forEach(function (name) {
        el("tab-" + name).classList.toggle("hidden", name !== tab.dataset.tab);
      });
      if (tab.dataset.tab === "runs") loadRuns();
    });
  });

  el("btn-save-guide").addEventListener("click", saveGuide);
  el("btn-save-space").addEventListener("click", saveSpace);
  el("btn-delete-space").addEventListener("click", function () { toggleDeleteConfirm(true); });
  el("btn-delete-cancel").addEventListener("click", function () { toggleDeleteConfirm(false); });
  el("btn-delete-confirm").addEventListener("click", deleteSpace);
  el("btn-toggle-trash").addEventListener("click", function () {
    state.trashOpen = !state.trashOpen;
    el("trash-list").classList.toggle("hidden", !state.trashOpen);
    if (state.trashOpen) loadTrash();
  });
  el("btn-new-space").addEventListener("click", function () {
    toggleNewSpace(el("new-space-form").classList.contains("hidden"));
  });
  el("btn-cancel-space").addEventListener("click", function () { toggleNewSpace(false); });
  el("new-space-form").addEventListener("submit", newSpace);
  el("guide-select").addEventListener("change", function () { loadGuide(this.value); });

  function refresh() {
    return api("/api/admin/spaces").then(function (data) {
      state.spaces = data.items;
      el("root-path").textContent = data.root;
      renderSpaces();
    });
  }

  refresh().then(function () {
    if (state.spaces.length) selectSpace(state.spaces[0].key);
  }).catch(function (err) {
    el("space-list").innerHTML = "<li class='muted'>" + err.message + "</li>";
  });
})();
