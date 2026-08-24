/* Банк реплік у панелі дослідника: запис своїм голосом.
 *
 * Чому це головний екран, а не додаток до налаштувань: у режимі банку саме тут
 * лежить методологія. Інтервʼюер не формулює питання — він вибирає з цього
 * набору, тому кожне формулювання тут піде всім респондентам однаково.
 */

window.ITPhrases = (function () {
  "use strict";

  var el = function (id) { return document.getElementById(id); };

  var state = {
    space: null,
    phrases: [],
    topics: [],
    kinds: [],
    recorder: null,
    recordingId: null,
    chunks: [],
    stream: null,
    player: null
  };

  var GROUPS = [
    { kind: "opening", title: "Відкриття — звучить на старті, однакове для всіх" },
    { kind: "topic", title: "Питання до тем гайда" },
    { kind: "probe", title: "Загальні уточнення — доречні в будь-якій темі" },
    { kind: "closing", title: "Завершення" }
  ];

  function api(path, options) {
    return fetch(path, options).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.error || ("HTTP " + response.status));
        return data;
      });
    });
  }

  /* ── запис ──────────────────────────────────────────────────────────── */

  function stopStream() {
    if (state.stream) {
      state.stream.getTracks().forEach(function (t) { t.stop(); });
      state.stream = null;
    }
  }

  function startRecording(phraseId, button, stateNode) {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      stateNode.textContent = "браузер не вміє записувати";
      return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      state.stream = stream;
      state.chunks = [];
      var recorder = new MediaRecorder(stream);
      state.recorder = recorder;
      state.recordingId = phraseId;

      recorder.ondataavailable = function (event) {
        if (event.data && event.data.size) state.chunks.push(event.data);
      };
      recorder.onstop = function () {
        stopStream();
        // Тип беремо з самого рекордера: Chrome віддає webm, Safari — mp4,
        // і вгадувати за розширенням не варто.
        var type = recorder.mimeType || "audio/webm";
        var blob = new Blob(state.chunks, { type: type });
        stateNode.textContent = "надсилаю…";
        upload(phraseId, blob, type).then(function (info) {
          stateNode.textContent = "записано, " + Math.round(info.bytes / 1024) + " КБ";
          load();
        }).catch(function (err) {
          stateNode.textContent = "не збереглось: " + err.message;
        });
      };

      recorder.start();
      button.classList.add("active");
      button.textContent = "■ Стоп";
      stateNode.textContent = "записую…";
    }).catch(function () {
      stateNode.textContent = "доступ до мікрофона не надано";
    });
  }

  function stopRecording(button) {
    if (state.recorder && state.recorder.state !== "inactive") {
      state.recorder.stop();
    }
    state.recorder = null;
    state.recordingId = null;
    button.classList.remove("active");
    button.textContent = "● Записати";
  }

  function upload(phraseId, blob, type) {
    return fetch("/api/admin/phrase/audio?space=" + encodeURIComponent(state.space) +
                 "&id=" + encodeURIComponent(phraseId), {
      method: "POST",
      headers: { "Content-Type": type },
      body: blob
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.error || ("HTTP " + response.status));
        return data;
      });
    });
  }

  function play(phraseId, stateNode) {
    if (state.player) { try { state.player.pause(); } catch (e) {} }
    // Кеш обходимо: після перезапису адреса та сама, а вміст інший.
    state.player = new Audio("/audio/" + encodeURIComponent(phraseId) + "?t=" + Date.now());
    state.player.play().catch(function () { stateNode.textContent = "не вдалося відтворити"; });
  }

  /* ── відображення ───────────────────────────────────────────────────── */

  function phraseNode(phrase) {
    var wrap = document.createElement("div");
    wrap.className = "phrase " + (phrase.recorded ? "recorded" : "unrecorded");
    wrap.dataset.id = phrase.id;

    var left = document.createElement("div");

    var text = document.createElement("textarea");
    text.rows = 2;
    text.value = phrase.text;
    text.dataset.field = "text";
    left.appendChild(text);

    var meta = document.createElement("div");
    meta.className = "meta";

    var pid = document.createElement("span");
    pid.className = "pid";
    pid.textContent = phrase.id;
    meta.appendChild(pid);

    var kind = document.createElement("select");
    kind.dataset.field = "kind";
    state.kinds.forEach(function (k) {
      var option = document.createElement("option");
      option.value = k;
      option.textContent = k;
      kind.appendChild(option);
    });
    kind.value = phrase.kind;
    meta.appendChild(kind);

    var topic = document.createElement("select");
    topic.dataset.field = "topic_id";
    var none = document.createElement("option");
    none.value = "";
    none.textContent = "— без теми —";
    topic.appendChild(none);
    state.topics.forEach(function (id) {
      var option = document.createElement("option");
      option.value = id;
      option.textContent = id;
      topic.appendChild(option);
    });
    topic.value = phrase.topic_id || "";
    meta.appendChild(topic);

    var drop = document.createElement("button");
    drop.type = "button";
    drop.className = "ghost small";
    drop.textContent = "прибрати репліку";
    drop.addEventListener("click", function () { wrap.remove(); });
    meta.appendChild(drop);

    left.appendChild(meta);

    if (phrase.warnings && phrase.warnings.length) {
      var warn = document.createElement("div");
      warn.className = "warn";
      warn.textContent = "⚠️ формулювання: " + phrase.warnings.join("; ");
      left.appendChild(warn);
    }
    wrap.appendChild(left);

    var controls = document.createElement("div");
    controls.className = "controls";

    var stateNode = document.createElement("span");
    stateNode.className = "state";
    stateNode.textContent = phrase.recorded ? "записано" : "не записано";

    var rec = document.createElement("button");
    rec.type = "button";
    rec.className = "rec";
    rec.textContent = "● Записати";
    rec.addEventListener("click", function () {
      if (state.recordingId === phrase.id) stopRecording(rec);
      else startRecording(phrase.id, rec, stateNode);
    });
    controls.appendChild(rec);

    if (phrase.recorded) {
      var listen = document.createElement("button");
      listen.type = "button";
      listen.className = "ghost";
      listen.textContent = "▶ Прослухати";
      listen.addEventListener("click", function () { play(phrase.id, stateNode); });
      controls.appendChild(listen);

      var erase = document.createElement("button");
      erase.type = "button";
      erase.className = "ghost";
      erase.textContent = "✕ Стерти запис";
      erase.addEventListener("click", function () {
        api("/api/admin/phrase/audio/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ space: state.space, id: phrase.id })
        }).then(load).catch(function (err) { stateNode.textContent = err.message; });
      });
      controls.appendChild(erase);
    }

    controls.appendChild(stateNode);
    wrap.appendChild(controls);
    return wrap;
  }

  function render() {
    var host = el("phrase-list");
    host.innerHTML = "";
    GROUPS.forEach(function (group) {
      var items = state.phrases.filter(function (p) { return p.kind === group.kind; });
      if (!items.length) return;
      var section = document.createElement("div");
      section.className = "phrase-group";
      var title = document.createElement("h3");
      title.textContent = group.title;
      section.appendChild(title);
      items.forEach(function (phrase) { section.appendChild(phraseNode(phrase)); });
      host.appendChild(section);
    });
  }

  function renderGaps(gaps) {
    var box = el("bank-gaps");
    if (!gaps || !gaps.length) {
      box.classList.add("hidden");
      box.innerHTML = "";
      return;
    }
    box.classList.remove("hidden");
    box.innerHTML = "<strong>Інтервʼю ще не почнеться — банк неповний:</strong>";
    var list = document.createElement("ul");
    gaps.forEach(function (gap) {
      var li = document.createElement("li");
      li.textContent = gap;
      list.appendChild(li);
    });
    box.appendChild(list);
  }

  function collect() {
    return Array.prototype.map.call(el("phrase-list").querySelectorAll(".phrase"), function (node) {
      var kind = node.querySelector('[data-field="kind"]').value;
      var item = {
        id: node.dataset.id,
        kind: kind,
        text: node.querySelector('[data-field="text"]').value.trim()
      };
      var topic = node.querySelector('[data-field="topic_id"]').value;
      if (topic) item.topic_id = topic;
      return item;
    });
  }

  function save() {
    el("phrases-error").textContent = "";
    return api("/api/admin/phrases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ space: state.space, phrases: collect() })
    }).then(load).catch(function (err) {
      el("phrases-error").textContent = err.message;
      throw err;
    });
  }

  function addPhrase() {
    var id = window.prompt("Ідентифікатор репліки (латиницею, напр. probe-why):");
    if (!id) return;
    state.phrases.push({ id: id.trim().toLowerCase(), kind: "probe", text: "", recorded: false });
    render();
  }

  function load() {
    if (!state.space) return Promise.resolve();
    return api("/api/admin/phrases?space=" + encodeURIComponent(state.space))
      .then(function (data) {
        state.phrases = data.phrases;
        state.topics = data.topics || [];
        state.kinds = data.kinds || ["opening", "closing", "topic", "probe"];
        renderGaps(data.gaps);
        render();
      }).catch(function (err) {
        el("phrases-error").textContent = err.message;
      });
  }

  function init(spaceKey) {
    state.space = spaceKey;
    return load();
  }

  el("btn-save-phrases").addEventListener("click", save);
  el("btn-add-phrase").addEventListener("click", addPhrase);

  return { init: init, reload: load };
})();
