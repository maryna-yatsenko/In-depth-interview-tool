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
                voiceName: "", speaker: null, ttsProvider: null, preview: null };

  var SAMPLE = "Розкажіть, будь ласка, про останній випадок, коли це сталося. " +
               "Що ви зробили далі?";

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
    if (window.ITPhrases) window.ITPhrases.init(key);
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
    else { state.guideData = null; el("topics").innerHTML = "<p class='muted'>У цьому просторі немає гайда.</p>"; }
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
      renderTopics(data.topics || []);
      el("guide-error").textContent = "";
    }).catch(function (err) { el("guide-error").textContent = err.message; });
  }

  function topicNode(topic) {
    var wrap = document.createElement("div");
    wrap.className = "topic";

    var head = document.createElement("div");
    head.className = "topic-head";
    head.innerHTML =
      '<label>Назва теми<input type="text" data-field="title"></label>' +
      '<label class="narrow">Ключ<input type="text" data-field="id"></label>' +
      '<label class="narrow">Уточнень<input type="number" min="1" max="12" data-field="max_probes"></label>' +
      '<button class="drop" title="Прибрати тему">✕</button>';
    wrap.appendChild(head);

    var learn = document.createElement("label");
    learn.className = "block";
    learn.innerHTML = "Що треба зʼясувати — по одному рядку" +
      '<textarea rows="3" data-field="must_learn"></textarea>';
    wrap.appendChild(learn);

    wrap.querySelector('[data-field="title"]').value = topic.title || "";
    wrap.querySelector('[data-field="id"]').value = topic.id || "";
    wrap.querySelector('[data-field="max_probes"]').value = topic.max_probes || 4;
    wrap.querySelector('[data-field="must_learn"]').value = lines.toText(topic.must_learn);

    head.querySelector(".drop").addEventListener("click", function () { wrap.remove(); });
    return wrap;
  }

  function renderTopics(topics) {
    var host = el("topics");
    host.innerHTML = "";
    topics.forEach(function (topic) { host.appendChild(topicNode(topic)); });
  }

  function collectTopics() {
    return Array.prototype.map.call(el("topics").querySelectorAll(".topic"), function (node) {
      return {
        id: node.querySelector('[data-field="id"]').value.trim(),
        title: node.querySelector('[data-field="title"]').value.trim(),
        max_probes: parseInt(node.querySelector('[data-field="max_probes"]').value, 10) || 4,
        must_learn: lines.fromText(node.querySelector('[data-field="must_learn"]').value)
      };
    });
  }

  function saveGuide() {
    var payload = Object.assign({}, state.guideData || {}, {
      key: state.guide,
      goal: el("guide-goal").value.trim(),
      opening: el("guide-opening").value.trim(),
      closing: el("guide-closing").value.trim(),
      max_turns: parseInt(el("guide-max-turns").value, 10) || 30,
      topics: collectTopics()
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
      var tts = (data.providers || {}).tts || {};
      state.voiceName = tts.voice || "";
      state.ttsConfigured = tts.provider || "browser";
      el("space-tts-provider").value = tts.provider || "browser";
      el("space-rate").value = tts.rate == null ? 0.97 : tts.rate;
      el("space-pitch").value = tts.pitch == null ? 1.0 : tts.pitch;
      el("space-gap").value = tts.gap == null ? 150 : tts.gap;
      el("space-length").value = tts.length_scale == null ? 1.06 : tts.length_scale;
      el("space-silence").value = tts.sentence_silence == null ? 0.4 : tts.sentence_silence;
      el("space-stress").checked = tts.add_stress !== false;
      el("space-noise").value = tts.noise_scale == null ? "" : String(tts.noise_scale);
      toggleTuning(tts.provider || "browser");
      el("space-mode").value = ((data.interface || {}).mode) || "text";
      el("space-autoplay").checked = !!((data.interface || {}).autoplay);
      el("space-repertoire").value = data.repertoire || "free";
      showSliderValues();
      renderVoices();
      el("space-accent").value = (data.branding || {}).accent || "";
      el("space-page-title").value = (data.branding || {}).page_title || "";
      el("space-error").textContent = "";
    }).catch(function (err) { el("space-error").textContent = err.message; });
  }

  /* Зберігаємо тільки ті поля, які стосуються обраного провайдера: змішувати
     браузерні rate/pitch з піперівськими length_scale у одному обʼєкті — шлях
     до конфігу, у якому не зрозуміло, що на що впливає. */
  function buildTtsConfig(base) {
    var config = Object.assign({}, base);
    var provider = el("space-tts-provider").value;
    config.provider = provider;
    config.voice = state.voiceName || "";
    var server = provider !== "browser" && provider !== "none";
    if (server) {
      var tuning = serverTuning();
      config.length_scale = tuning.length_scale;
      config.sentence_silence = tuning.sentence_silence;
      config.add_stress = tuning.add_stress;
      if (tuning.noise_scale === undefined) {
        delete config.noise_scale;
        delete config.noise_w_scale;
      } else {
        config.noise_scale = tuning.noise_scale;
        config.noise_w_scale = tuning.noise_w_scale;
      }
    } else {
      config.rate = parseFloat(el("space-rate").value) || 0.97;
      config.pitch = parseFloat(el("space-pitch").value) || 1.0;
      config.gap = parseInt(el("space-gap").value, 10) || 0;
    }
    return config;
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
      repertoire: el("space-repertoire").value,
      interface: Object.assign({}, base.interface || {}, {
        mode: el("space-mode").value,
        autoplay: el("space-autoplay").checked
      }),
      providers: Object.assign({}, base.providers || {}, {
        tts: buildTtsConfig((base.providers || {}).tts || {})
      }),
      branding: Object.assign({}, base.branding || {}, {
        accent: el("space-accent").value.trim(),
        page_title: el("space-page-title").value.trim()
      })
    });
    el("space-error").textContent = "";
    post("/api/admin/space", { space: state.space, data: payload })
      .then(function () {
        state.spaceData = payload;
        // Провайдер міг змінитись — просимо сервер перезібрати його наживо,
        // інакше довелось би перезапускати сервер і рвати live-сесії.
        return post("/api/admin/tts/reload", {}).then(function (info) {
          flash("Збережено · озвучення: " + info.provider, "ok");
          state.voiceName = "";
          return refresh().then(function () { return loadSpaceData(); });
        }).catch(function (err) {
          flash("Збережено, але озвучення не піднялось: " + err.message, "bad");
          return refresh();
        });
      })
      .catch(function (err) {
        el("space-error").textContent = err.message;
        flash("Не збережено", "bad");
      });
  }

  /* ── голос ─────────────────────────────────────────────────────────────
   *
   * Список голосів — те, що реально віддає цей браузер. Нічого не додаємо «за
   * специфікацією»: Web Speech API не повідомляє ні статі, ні якості, і
   * підписувати голоси навмання означало б вигадувати дані. Тому підпис один —
   * назва й мова від системи, а рішення ухвалює людина, послухавши.
   */

  function spaceLang() {
    var langs = (state.spaceData && state.spaceData.languages) || ["uk"];
    return langs[0] === "uk" ? "uk-UA" : langs[0];
  }

  function ttsSettings() {
    return {
      lang: spaceLang(),
      voiceName: state.voiceName || null,
      rate: parseFloat(el("space-rate").value) || 0.97,
      pitch: parseFloat(el("space-pitch").value) || 1.0,
      gap: parseInt(el("space-gap").value, 10)
    };
  }

  /* Параметри локальної моделі — інші, ніж у браузера. Раніше тут показувались
     браузерні швидкість і тон, і на Piper вони не впливали ніяк: дослідник
     рухав слайдери й не чув жодної зміни. */
  function serverTuning() {
    var noise = el("space-noise").value;
    var tuning = {
      length_scale: parseFloat(el("space-length").value) || 1.0,
      sentence_silence: parseFloat(el("space-silence").value),
      add_stress: el("space-stress").checked
    };
    if (noise !== "") {
      tuning.noise_scale = parseFloat(noise);
      tuning.noise_w_scale = noise === "0" ? 0 : 0.4;
    }
    return tuning;
  }

  function tryVoice(name) {
    if (state.ttsProvider && state.ttsProvider !== "browser") {
      // Серверний провайдер: аудіо синтезує сервер, текст фіксований у коді.
      if (state.preview) { try { state.preview.pause(); } catch (e) {} }
      var body = serverTuning();
      body.voice = name || state.voiceName || null;
      el("tuning-note").textContent = "синтезую…";
      fetch("/api/admin/tts/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      }).then(function (response) {
        if (!response.ok) return response.json().then(function (d) { throw new Error(d.error); });
        return response.blob();
      }).then(function (blob) {
        var url = URL.createObjectURL(blob);
        state.preview = new Audio(url);
        state.preview.addEventListener("ended", function () {
          URL.revokeObjectURL(url);
          el("tuning-note").textContent = "";
        });
        el("tuning-note").textContent = "";
        state.preview.play();
      }).catch(function (err) {
        el("tuning-note").textContent = "";
        flash(err.message, "bad");
      });
      return;
    }

    if (!window.ITAudio || !window.speechSynthesis) return;
    var config = ttsSettings();
    if (name) config.voiceName = name;
    if (state.speaker) state.speaker.stop();
    state.speaker = window.ITAudio.createSpeaker(config);
    state.speaker.speak(SAMPLE, {});
  }

  function renderVoices() {
    // Спершу питаємо сервер: якщо озвучення серверне, голоси беруться від
    // провайдера, а не з браузера дослідника — це різні набори.
    fetch("/api/tts/voices").then(function (r) { return r.json(); }).then(function (data) {
      state.ttsProvider = data.provider;
      toggleTuning(data.provider);
      if (data.provider && data.provider !== "browser") {
        drawVoices((data.items || []).map(function (item) {
          return { name: item.name, lang: item.locale || "", localService: true,
                   gender: item.gender || "" };
        }), data.provider, data.error);
        return;
      }
      if (!window.ITAudio || !window.speechSynthesis) { drawVoices([], "browser"); return; }
      drawVoices(window.ITAudio.listVoices(spaceLang()), "browser");
    }).catch(function () {
      if (window.ITAudio && window.speechSynthesis) {
        drawVoices(window.ITAudio.listVoices(spaceLang()), "browser");
      }
    });
  }

  function drawVoices(voices, provider, error) {
    var host = el("voice-list");
    host.innerHTML = "";

    var where = provider === "browser" ? ("браузер, мова " + spaceLang()) : ("провайдер " + provider);
    el("voice-count").textContent = voices.length
      ? (voices.length + " " + (voices.length === 1 ? "голос" : "голосів") + " — " + where)
      : ("голосів немає — " + where);

    if (error) {
      host.innerHTML = "<p class='error-text'>" + error + "</p>";
      return;
    }
    if (!voices.length) {
      host.innerHTML = "<p class='muted tiny'>Голосів немає — питання не озвучуватимуться.</p>";
      return;
    }

    voices.forEach(function (voice) {
      var row = document.createElement("div");
      row.className = "voice-row" + (voice.name === state.voiceName ? " active" : "");

      var play = document.createElement("button");
      play.type = "button";
      play.textContent = "▶";
      play.title = "Прослухати";
      play.addEventListener("click", function () { tryVoice(voice.name); });
      row.appendChild(play);

      var name = document.createElement("span");
      name.className = "name";
      name.textContent = voice.name;
      row.appendChild(name);

      var lang = document.createElement("span");
      lang.className = "lang";
      lang.textContent = [voice.lang, voice.gender].filter(Boolean).join(" · ");
      row.appendChild(lang);

      var choose = document.createElement("button");
      choose.type = "button";
      choose.textContent = voice.name === state.voiceName ? "обрано" : "обрати";
      if (voice.name === state.voiceName) choose.className = "chosen";
      choose.addEventListener("click", function () {
        state.voiceName = voice.name;
        renderVoices();
      });
      row.appendChild(choose);

      host.appendChild(row);
    });
  }

  /* ── інтервʼю ──────────────────────────────────────────────────────── */

  function loadRuns() {
    api("/api/sessions").then(function (data) {
      var host = el("runs-list");
      host.innerHTML = "";
      if (!data.items.length) {
        host.innerHTML = "<p class='muted'>Завершених інтервʼю ще немає.</p>";
        return;
      }
      data.items.forEach(function (item) {
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
        flash("Простір створено з шаблону", "ok");
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
      if (tab.dataset.tab === "phrases" && window.ITPhrases) window.ITPhrases.init(state.space);
    });
  });

  function showSliderValues() {
    el("rate-value").textContent = "×" + parseFloat(el("space-rate").value).toFixed(2);
    el("pitch-value").textContent = "×" + parseFloat(el("space-pitch").value).toFixed(2);
    el("length-value").textContent = "×" + parseFloat(el("space-length").value).toFixed(2);
    el("silence-value").textContent = parseFloat(el("space-silence").value).toFixed(2);
  }

  function toggleTuning(provider) {
    var server = provider && provider !== "browser" && provider !== "none";
    el("tuning-server").classList.toggle("hidden", !server);
    el("tuning-browser").classList.toggle("hidden", server);
  }
  el("space-rate").addEventListener("input", showSliderValues);
  el("space-pitch").addEventListener("input", showSliderValues);
  el("space-length").addEventListener("input", showSliderValues);
  el("space-silence").addEventListener("input", showSliderValues);
  el("btn-try-voice").addEventListener("click", function () { tryVoice(null); });

  // Голоси приходять асинхронно — перший рендер може бути порожнім.
  if (window.speechSynthesis) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = function () {
      if (state.spaceData) renderVoices();
    };
  }

  el("btn-save-guide").addEventListener("click", saveGuide);
  el("btn-save-space").addEventListener("click", saveSpace);
  el("btn-new-space").addEventListener("click", function () {
    toggleNewSpace(el("new-space-form").classList.contains("hidden"));
  });
  el("btn-cancel-space").addEventListener("click", function () { toggleNewSpace(false); });
  el("new-space-form").addEventListener("submit", newSpace);
  el("btn-add-topic").addEventListener("click", function () {
    el("topics").appendChild(topicNode({ max_probes: 4 }));
  });
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
