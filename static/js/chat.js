/* DeepanCode chat client — no auth required. */
(function () {
  "use strict";
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var G = !reduced && typeof window.gsap !== "undefined" ? window.gsap : null;

  function $(id) { return document.getElementById(id); }
  var csrf = { session_id: "", token: "" };
  var ws = null, convId = 0, streaming = false, lastTool = "";
  var shouldStick = true;
  /* -- HTTP helper -- */
  async function api(path, opts) {
    opts = opts || {};
    opts.credentials = "include";
    opts.headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    var r = await fetch(path, opts);
    return r;
  }

  /* -- Time formatting -- */
  function fmtTime(d) {
    if (!d) return "";
    var dt = new Date(d);
    if (isNaN(dt)) return "";
    var now = new Date();
    var h = dt.getHours(), m = dt.getMinutes();
    var ampm = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    var time = h + ":" + (m < 10 ? "0" : "") + m + " " + ampm;
    if (dt.toDateString() === now.toDateString()) return time;
    var months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return months[dt.getMonth()] + " " + dt.getDate() + ", " + time;
  }

  /* -- Safe mini-markdown -- */
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function md(src) {
    var E = esc(src), out = "", re = /```(\w*)\n([\s\S]*?)(```|$)/g, last = 0, m;
    function inline(s) {
      s = s.replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/\*([^*]+)\*/g, "<em>$1</em>");
      s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (_, t, u) {
        if (/^https?:\/\//i.test(u)) return '<a href="' + u + '" target="_blank" rel="noopener noreferrer">' + t + "</a>";
        return t;
      });
      return s.replace(/^### (.*)$/gm, "<h4>$1</h4>")
        .replace(/^## (.*)$/gm, "<h3>$1</h3>")
        .replace(/^> (.*)$/gm, "<blockquote>$1</blockquote>")
        .replace(/^- (.*)$/gm, "<li>$1</li>")
        .replace(/(<li>.*<\/li>)/s, "<ul>$1</ul>");
    }
    while ((m = re.exec(E))) {
      var lang = m[1] || "";
      var langLabel = lang ? '<span class="lang-label">' + lang + '</span>' : "";
      out += "<p>" + inline(m.input.slice(last, m.index)).replace(/\n{2,}/g, "</p><p>") + "</p>";
      out += "<pre>" + langLabel + "<code>" + m[2].replace(/^\n+|\n+$/g, "") + "</code></pre>";
      last = m.index + m[0].length;
    }
    out += "<p>" + inline(E.slice(last)).replace(/\n{2,}/g, "</p><p>") + "</p>";
    return out.replace(/<p><\/p>/g, "");
  }

  /* -- Toasts -- */
  function toast(msg, isErr) {
    var el = document.createElement("div");
    el.className = "toast" + (isErr ? " err" : "");
    el.textContent = msg;
    $("toasts").appendChild(el);
    if (G) {
      var tl = gsap.timeline({ onComplete: function () { el.remove(); } });
      tl.from(el, { opacity: 0, x: 60, duration: 0.35, ease: "expo.out" })
        .to(el, { opacity: 0, x: 40, duration: 0.3, delay: 3.2 });
    } else { setTimeout(function () { el.remove(); }, 3600); }
  }

  /* -- Message DOM -- */
  function stick() {
    var s = $("stream");
    if (shouldStick) s.scrollTop = s.scrollHeight;
  }
  $("stream").addEventListener("scroll", function () {
    var s = $("stream");
    shouldStick = s.scrollHeight - s.scrollTop - s.clientHeight < 120;
  });

  function animateIn(el) {
    if (G) gsap.from(el, { opacity: 0, y: 16, duration: 0.4, ease: "power3.out" });
  }

  function addMsg(who, html, isHtml, timestamp) {
    var wrap = document.createElement("div");
    wrap.className = "msg" + (who === "you" ? " me" : "");

    var header = document.createElement("div");
    header.className = "msg-header";

    var avatar = document.createElement("div");
    avatar.className = "avatar " + (who === "you" ? "user" : "ai");
    avatar.textContent = who === "you" ? "U" : "DC";

    var meta = document.createElement("div");

    var label = document.createElement("div");
    label.className = "who";
    label.textContent = who === "you" ? "You" : who === "tool" ? "Tool" : "DeepanCode";
    meta.appendChild(label);

    if (timestamp) {
      var ts = document.createElement("span");
      ts.className = "timestamp";
      ts.textContent = fmtTime(timestamp);
      meta.appendChild(ts);
    }

    header.appendChild(avatar);
    header.appendChild(meta);

    var body = document.createElement("div");
    body.className = "body";
    if (isHtml) body.innerHTML = html; else body.textContent = html;

    wrap.appendChild(header);
    wrap.appendChild(body);
    $("stream").appendChild(wrap);
    animateIn(wrap);
    stick();
    return body;
  }

  function addThink() {
    var el = document.createElement("div");
    el.className = "think-rich-live";
    el.innerHTML = '<div class="rich-spinner-wrap"><span class="rich-dots-spinner"></span><span class="rich-dots-text">Thinking...</span></div><span class="tpre" hidden></span>';
    var pre = el.querySelector(".tpre");
    el.addEventListener("click", function () { pre.hidden = !pre.hidden; });
    $("stream").appendChild(el);
    if (G) gsap.from(el, { opacity: 0, y: 6, duration: 0.3, ease: "power2.out" });
    return { el: el, pre: pre };
  }

  function openArtifact(title, text) {
    $("artsTitle").textContent = title.length > 40 ? title.slice(0, 40) + "…" : title;
    $("artsBody").textContent = text;
    var arts = $("arts");
    if (!arts.classList.contains("open")) {
      arts.classList.add("open");
      if (G) gsap.from(arts, { opacity: 0, x: 40, duration: 0.4, ease: "expo.out" });
    }
    stick();
  }

  /* -- Conversation list -- */
  async function loadList(q) {
    var r = await api("/api/conversations?limit=100" + (q ? "&search=" + encodeURIComponent(q) : ""));
    var d = await r.json();
    var list = $("clist");
    list.innerHTML = '<div class="clist-label">Recent</div>';
    (d.conversations || []).forEach(function (c) {
      var rawTitle = c.title || "Untitled";
      var cleanTitle = rawTitle.replace(/\[(AGENT|PLAN) MODE:.*?\]/gi, "").replace(/^hello\s*[-:]?\s*/i, "").trim() || rawTitle;
      var el = document.createElement("div");
      el.className = "citem" + (c.id === convId ? " active" : "");
      el.innerHTML = '<svg class="citem-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>' +
        '<span class="citem-title">' + esc(cleanTitle) + '</span>' +
        '<button class="citem-delete" type="button" title="Delete conversation" aria-label="Delete conversation: ' + esc(cleanTitle) + '">' +
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>' +
        '</button>';
      el.title = rawTitle;
      el.addEventListener("click", function () { openConv(c.id, c.title); });
      el.querySelector(".citem-delete").addEventListener("click", async function (event) {
        event.stopPropagation();
        if (!confirm("Delete this conversation? This cannot be undone.")) return;
        var rr = await api("/api/conversations/" + c.id, { method: "DELETE" });
        if (!rr.ok) { toast("Delete failed", true); return; }
        if (convId === c.id) {
          convId = 0;
          document.title = "Chat — DeepanCode";
          $("stream").innerHTML = "";
          emptyState(true);
        }
        toast("Conversation deleted");
        loadList($("search").value);
      });
      el.addEventListener("dblclick", async function () {
        var t = prompt("Rename conversation", c.title || "");
        if (t === null) return;
        var rr = await api("/api/conversations/" + c.id, { method: "PATCH", body: JSON.stringify({ title: t }) });
        if (rr.ok) { toast("Renamed"); loadList($("search").value); } else toast("Rename failed", true);
      });
      list.appendChild(el);
    });
  }

  async function openConv(id, title) {
    convId = id;
    $("stream").innerHTML = "";
    document.title = (title || "Chat") + " — DeepanCode";
    var r = await api("/api/conversations/" + id + "/messages?limit=500");
    var d = await r.json();
    var lastContent = "";
    (d.messages || []).forEach(function (m) {
      if (m.role === "system") return;
      var content = (m.content || "").trim();
      if (content.toLowerCase().includes("unauthorized") && lastContent.toLowerCase().includes("unauthorized")) return;
      lastContent = content;
      if (m.role === "user") addMsg("you", m.content || "", false, m.created_at);
      else if (m.role === "assistant") addMsg("ai", md(m.content || "[task done]"), true, m.created_at);
    });
    loadList($("search").value);
    emptyState(false);
  }

  function emptyState(show) {
    var s = $("stream");
    if (!show) { var e = $("emptyState"); if (e) e.remove(); return; }
    s.innerHTML = '<div class="empty" id="emptyState">' +
      '<h1>Welcome</h1>' +
      '<p>What would you like to build today?</p>' +
      '<div class="sugg">' +
      '<button data-q="Explain this project architecture"><span class="sugg-icon">&#x1F4C1;</span> Explain this project</button>' +
      '<button data-q="Review my latest changes for security issues"><span class="sugg-icon">&#x1F512;</span> Security review</button>' +
      '<button data-q="Write tests for the auth module"><span class="sugg-icon">&#x1F9EA;</span> Write tests</button>' +
      '<button data-q="Help me debug a failing test"><span class="sugg-icon">&#x1F41B;</span> Debug a test</button>' +
      "</div></div>";
    s.querySelectorAll("[data-q]").forEach(function (b) {
      b.addEventListener("click", function () { $("input").value = b.getAttribute("data-q"); send(); });
    });
    if (G) {
      gsap.from("#emptyState h1", { opacity: 0, y: 24, duration: 0.6, ease: "expo.out" });
      gsap.from("#emptyState p", { opacity: 0, y: 16, duration: 0.5, ease: "expo.out", delay: 0.1 });
      gsap.from(".sugg button", { opacity: 0, y: 20, duration: 0.5, ease: "expo.out", stagger: 0.06, delay: 0.2 });
    }
  }

  /* -- WebSocket chat -- */
  function connect() {
    var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(proto + "//" + window.location.host + "/ws/chat");
    ws.onopen = function () { };
    ws.onmessage = function (ev) {
      var m;
      try { m = JSON.parse(ev.data); } catch (e) { return; }
      onEvent(m);
    };
    ws.onclose = function () {
      setStreaming(false);
      setTimeout(function () { if (!streaming) connect(); }, 2500);
    };
    ws.onerror = function () { try { ws.close(); } catch (e) { /* noop */ } };
  }

  function setStreaming(on) {
    streaming = on;
    var b = $("sendBtn");
    if (!on && curThink && curThink.el) {
      if (curThink.el.parentNode) curThink.el.parentNode.removeChild(curThink.el);
      curThink = null;
    }
    if (on) {
      b.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"></rect></svg>';
      b.className = "send stop";
      b.title = "Stop generating";
    } else {
      b.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>';
      b.className = "send";
      b.title = "Send (Enter)";
    }
  }

  var curBody = null, curThink = null;

  function onEvent(m) {
    if (m.type === "auth_ok") { return; }
    if (m.type === "thinking_chunk") {
      if (!curThink) curThink = addThink();
      curThink.pre.hidden = false;
      curThink.pre.textContent += m.message || "";
      stick(); return;
    }
    if (m.type === "chunk" || m.type === "tool_call" || m.type === "tool_result" || m.type === "assistant") {
      if (curThink && curThink.el) {
        if (curThink.el.parentNode) curThink.el.parentNode.removeChild(curThink.el);
        curThink = null;
      }
    }
    if (m.type === "tool_call") {
      lastTool = m.message || "";
      stick(); return;
    }
    if (m.type === "tool_result") {
      if (/^(create_file|edit_file)\b/.test(lastTool)) openArtifact(lastTool, m.message || "");
      return;
    }
    if (m.type === "assistant") {
      curBody = addMsg("ai", md(m.message || ""), true);
      curThink = null; return;
    }
    if (m.type === "warning") { toast(m.message || "warning", true); return; }
    if (m.type === "error") {
      var errEl = addMsg("ai", '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>' + esc("Error: " + (m.message || "unknown")), true);
      errEl.closest(".msg").classList.add("error");
      setStreaming(false); return;
    }
    if (m.type === "done") {
      if (m.conversation_id) convId = m.conversation_id;
      curBody = null; curThink = null; lastTool = "";
      setStreaming(false);
      loadList($("search").value); updateUsage();
    }
  }

  function send() {
    var text = $("input").value.trim();
    if (!text || streaming) return;
    if (!ws || ws.readyState !== 1) { toast("Not connected yet", true); return; }
    var e = $("emptyState"); if (e) e.remove();
    var attachments = Array.prototype.slice.call(window.chatAttachments || []);
    var requestText = text;
    var selectedMode = $("set-mode").value || "agent";
    if (selectedMode === "plan") requestText += "\n\n[PLAN MODE: inspect context and provide an ordered plan; do not edit files until approval.]";
    if (selectedMode === "agent") requestText += "\n\n[AGENT MODE: implement the task, run focused checks, and report the result.]";
    if ($("codeBtn").classList.contains("active")) requestText += "\n\n[Use code-focused reasoning and include implementation details.]";
    if ($("webBtn").classList.contains("active")) requestText += "\n\n[Use web search for current information when useful.]";
    addMsg("you", text, false, new Date().toISOString());
    $("input").value = ""; $("input").style.height = "auto";
    window.chatAttachments = [];
    renderAttachments();
    setStreaming(true);
    curThink = addThink();
    ws.send(JSON.stringify({ type: "chat", conversation_id: convId || null, message: requestText, attachments: attachments }));
  }

  $("sendBtn").addEventListener("click", function () {
    if (streaming) { try { ws.close(); } catch (e) { /* noop */ } toast("Stopped"); return; }
    send();
  });
  $("input").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  $("input").addEventListener("input", function () {
    this.style.height = "auto";
    this.style.height = Math.min(this.scrollHeight, 160) + "px";
  });

  window.chatAttachments = [];
  function renderAttachments() {
    var wrap = $("attachments");
    wrap.innerHTML = "";
    (window.chatAttachments || []).forEach(function (file, index) {
      var item = document.createElement("div");
      item.className = "attachment";
      item.innerHTML = '<span aria-hidden="true">&#128196;</span><span class="attachment-name"></span><button class="attachment-remove" type="button" title="Remove file" aria-label="Remove file">&times;</button>';
      item.querySelector(".attachment-name").textContent = file.name;
      item.querySelector(".attachment-remove").addEventListener("click", function () {
        window.chatAttachments.splice(index, 1);
        renderAttachments();
      });
      wrap.appendChild(item);
    });
    wrap.hidden = !window.chatAttachments.length;
  }
  async function uploadSelected(files) {
    if (!files.length) return;
    var form = new FormData();
    Array.prototype.forEach.call(files, function (file) { form.append("files", file, file.name); });
    try {
      var response = await fetch("/api/uploads", { method: "POST", body: form, credentials: "include" });
      var data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Upload failed");
      window.chatAttachments = (window.chatAttachments || []).concat(data.files || []);
      renderAttachments();
      toast((data.files || []).length + " file" + ((data.files || []).length === 1 ? "" : "s") + " uploaded");
    } catch (error) {
      toast(error.message || "Upload failed", true);
    }
  }
  $("attachBtn").addEventListener("click", function () {
    $("fileInput").accept = "";
    $("fileInput").click();
  });
  $("imageBtn").addEventListener("click", function () { $("fileInput").accept = "image/*"; $("fileInput").click(); });
  $("folderBtn").addEventListener("click", function () { $("folderInput").click(); });
  $("fileInput").addEventListener("change", function () {
    uploadSelected(this.files);
    this.value = "";
  });
  $("folderInput").addEventListener("change", function () {
    uploadSelected(this.files);
    this.value = "";
  });
  ["codeBtn", "webBtn"].forEach(function (id) {
    $(id).addEventListener("click", function () {
      this.classList.toggle("active");
      toast(this.classList.contains("active") ? this.title + " enabled" : this.title + " disabled");
    });
  });
  $("quickBtn").addEventListener("click", function () {
    var input = $("input");
    input.value = input.value ? input.value + "\n\nPlease answer with clear, actionable steps." : "Please help me with ";
    input.dispatchEvent(new Event("input"));
    input.focus();
  });
  var recognition = null;
  $("voiceBtn").addEventListener("click", async function () {
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) { toast("Voice input is not supported by this browser", true); return; }
    if (recognition) { recognition.stop(); return; }
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      try {
        var microphone = await navigator.mediaDevices.getUserMedia({ audio: true });
        microphone.getTracks().forEach(function (track) { track.stop(); });
      } catch (error) {
        toast("Microphone permission was denied", true);
        return;
      }
    }
    recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.onresult = function (event) {
      var transcript = "";
      for (var i = event.resultIndex; i < event.results.length; i++) transcript += event.results[i][0].transcript;
      $("input").value += ($("input").value ? " " : "") + transcript;
      $("input").dispatchEvent(new Event("input"));
    };
    recognition.onerror = function (event) { toast(event.error === "not-allowed" ? "Microphone permission was denied" : "Voice input failed", true); };
    recognition.onend = function () { recognition = null; $("voiceBtn").classList.remove("active"); };
    recognition.start();
    this.classList.add("active");
    toast("Microphone enabled");
  });
  $("fullscreenBtn").addEventListener("click", function () {
    var composer = document.querySelector(".composer");
    composer.classList.toggle("fullscreen");
    this.title = composer.classList.contains("fullscreen") ? "Collapse composer" : "Expand composer";
  });

  /* -- Models / usage / settings -- */
  var modelCatalog = [];
  var allProviders = {};
  var activeModelProvider = "all";

  function providerLabel(provider) {
    if (allProviders[provider]) return allProviders[provider].name;
    return String(provider || "Other").replace(/[-_]/g, " ");
  }

  function renderModelBrowser() {
    var query = ($("modelSearch").value || "").trim().toLowerCase();
    var visible = modelCatalog.filter(function (model) {
      var inProvider = activeModelProvider === "all" || model.provider === activeModelProvider;
      return inProvider && (!query || [model.name, model.id, model.provider, model.description].join(" ").toLowerCase().indexOf(query) >= 0);
    });
    var groups = {};
    visible.forEach(function (model) {
      var key = model.provider || "other";
      if (!groups[key]) groups[key] = [];
      groups[key].push(model);
    });
    var list = $("modelList"); list.innerHTML = "";
    Object.keys(groups).sort().forEach(function (provider) {
      var heading = document.createElement("div");
      heading.className = "model-group"; heading.textContent = providerLabel(provider);
      list.appendChild(heading);
      groups[provider].forEach(function (model) {
        var button = document.createElement("button");
        button.type = "button"; button.className = "model-option";
        var activeOption = $("modelSel").options[$("modelSel").selectedIndex];
        var activeKey = activeOption ? activeOption.dataset.modelKey : "";
        if (activeKey === (model.provider + "::" + model.id)) button.classList.add("selected");
        button.innerHTML = '<span><strong></strong><small></small></span><span class="model-check"></span>';
        button.querySelector("strong").textContent = model.name || model.id;
        button.querySelector("small").textContent = model.id + (model.description ? " · " + model.description : "");
        if (activeKey === (model.provider + "::" + model.id)) button.querySelector(".model-check").textContent = "\u2713";
        button.addEventListener("click", function () { selectModel(model); });
        list.appendChild(button);
      });
    });
    $("modelCount").textContent = visible.length + " of " + modelCatalog.length + " models";
    if (!visible.length) list.innerHTML = '<div class="text-dim">No models match your search.</div>';
  }

  function renderModelTabs() {
    var providers = ["all"].concat(Array.from(new Set(modelCatalog.map(function (model) { return model.provider; }))).sort());
    var tabs = $("modelTabs"); tabs.innerHTML = "";
    providers.forEach(function (provider) {
      var tab = document.createElement("button");
      tab.type = "button"; tab.className = "model-tab" + (provider === activeModelProvider ? " active" : "");
      tab.setAttribute("role", "tab"); tab.setAttribute("aria-selected", provider === activeModelProvider ? "true" : "false");
      tab.textContent = provider === "all" ? "All models" : providerLabel(provider);
      tab.title = allProviders[provider] ? allProviders[provider].description : "";
      tab.addEventListener("click", function () { activeModelProvider = provider; renderModelTabs(); renderModelBrowser(); });
      tabs.appendChild(tab);
    });
  }

  async function selectModel(model) {
    var modelKey = model.provider + "::" + model.id;
    Array.prototype.some.call($("modelSel").options, function (option, index) {
      if (option.dataset.modelKey === modelKey) { $("modelSel").selectedIndex = index; return true; }
      return false;
    });
    var response = await api("/api/settings", {
      method: "PATCH", body: JSON.stringify({ model: model.id, provider: model.provider || "openrouter" })
    });
    if (!response.ok) { toast("Model selection failed", true); return; }
    var lbl = $("currentModelLabel");
    if (lbl) lbl.textContent = model.name || model.id;
    renderModelBrowser();
    $("modelsModal").classList.remove("open");
    toast((model.name || model.id) + " selected");
  }

  async function loadModels() {
    /* Load providers first */
    try {
      var pr = await api("/api/providers");
      if (pr.ok) {
        var pd = await pr.json();
        allProviders = pd.providers || {};
      }
    } catch (e) { /* noop */ }

    /* Load models */
    var r = await api("/api/models");
    if (!r.ok) {
      modelCatalog = [];
      renderModelTabs();
      $("modelSel").innerHTML = '<option value="">Could not load models</option>';
      $("modelCount").textContent = "Models unavailable (" + r.status + ")";
      return;
    }
    var d = await r.json();
    modelCatalog = Array.isArray(d.models) ? d.models.filter(function (model) {
      return model && model.id && model.provider;
    }) : [];

    renderModelTabs();
    var sel = $("modelSel"); sel.innerHTML = "";
    modelCatalog.forEach(function (m) {
      var o = document.createElement("option");
      o.value = m.provider + "::" + m.id; o.textContent = (m.name || m.id);
      o.dataset.provider = m.provider || "";
      o.dataset.modelId = m.id;
      o.dataset.modelKey = (m.provider || "openrouter") + "::" + m.id;
      sel.appendChild(o);
    });
    var s = await api("/api/settings");
    var st = await s.json();
    var initialIndex = Array.prototype.findIndex.call(sel.options, function (option) {
      return option.dataset.modelId === st.model && (!st.provider || option.dataset.provider === st.provider);
    });
    if (initialIndex >= 0) {
      sel.selectedIndex = initialIndex;
      var lbl = $("currentModelLabel");
      if (lbl) lbl.textContent = sel.options[initialIndex].textContent;
    }
    document.documentElement.setAttribute("data-theme", st.theme || "light");
    sel.addEventListener("change", async function () {
      var option = sel.options[sel.selectedIndex];
      var model = modelCatalog.find(function (item) { return item.id === option.dataset.modelId && item.provider === option.dataset.provider; });
      await api("/api/settings", { method: "PATCH", body: JSON.stringify({ model: option.dataset.modelId, provider: option.dataset.provider || (model && model.provider) || "openrouter" }) });
      renderModelBrowser();
      toast("Model switched to " + (model ? model.name : sel.value));
    });
    renderModelBrowser();
  }

  async function updateUsage() {
    try {
      var r = await api("/api/usage");
      var d = await r.json();
      var chats = typeof d.conversations === "number" ? d.conversations : (typeof d.chats === "number" ? d.chats : 0);
      var tokens = d.total_tokens || 0;
      $("usage").textContent = chats + (chats === 1 ? " chat · " : " chats · ") + tokens + " tokens";
    } catch (e) {
      $("usage").textContent = "0 chats · 0 tokens";
    }
  }

  function fillSettings(st) {
    $("set-provider").innerHTML = "";
    var providers = Object.keys(allProviders).sort().map(function(key) {
      return [key, allProviders[key].name + (st.keys_configured && st.keys_configured[key] ? " (key set)" : "")];
    });
    providers.forEach(function (entry) {
      var p = entry[0];
      var o = document.createElement("option");
      o.value = p; o.textContent = entry[1];
      $("set-provider").appendChild(o);
    });
    ["mode", "effort", "theme", "thinking"].forEach(function (k) {
      var el = $("set-" + k);
      if (!el) return;
      if (k === "thinking" && el.tagName === "SELECT") { el.value = st.thinking === false ? "off" : "on"; return; }
      if (typeof el.value !== "undefined" && st[k] !== undefined && el.tagName === "SELECT") {
        Array.prototype.forEach.call(el.options, function (o) { if (o.value === st[k]) el.value = o.value; });
      }
    });
    if (!$("set-mode").options.length) {
      ["plan", "agent", "code", "architect", "ask", "debug", "review"].forEach(function (m) {
        var o = document.createElement("option"); o.value = m; o.textContent = m;
        $("set-mode").appendChild(o);
      });
    }
    if (!$("set-effort").options.length) {
      ["low", "medium", "high"].forEach(function (m) {
        var o = document.createElement("option"); o.value = m; o.textContent = m;
        $("set-effort").appendChild(o);
      });
    }
    $("set-provider").value = st.provider || "openrouter";
    $("set-mode").value = st.mode || "agent";
    $("set-effort").value = st.effort || "medium";
    $("set-theme").value = st.theme || "dark";
  }

  async function openSettings() {
    if (Object.keys(allProviders).length === 0) {
      try {
        var pr = await api("/api/providers");
        if (pr.ok) {
          var pd = await pr.json();
          allProviders = pd.providers || {};
        }
      } catch (e) { /* noop */ }
    }
    var r = await api("/api/settings");
    fillSettings(await r.json());
    $("settingsModal").classList.add("open");
    if (G) gsap.from("#settingsModal .card", { opacity: 0, y: 24, duration: 0.4, ease: "expo.out" });
  }

  /* -- Wire up chrome -- */
  $("newChat").addEventListener("click", async function () {
    var r = await api("/api/conversations", { method: "POST", body: JSON.stringify({ title: "Untitled" }) });
    var d = await r.json();
    openConv(d.conversation_id, "Untitled");
  });
  $("search").addEventListener("input", function () { loadList(this.value); });
  function toggleSidebar() {
    var hidden = $("sidebar").classList.toggle("hidden");
    $("toggleSide").title = hidden ? "Open sidebar" : "Collapse sidebar";
    $("showSide").title = hidden ? "Open sidebar" : "Collapse sidebar";
  }
  $("toggleSide").addEventListener("click", toggleSidebar);
  $("showSide").addEventListener("click", function () {
    toggleSidebar();
    if (!$("sidebar").classList.contains("hidden") && G) gsap.from($("sidebar"), { x: -260, opacity: 0, duration: 0.35, ease: "expo.out" });
  });
  $("closeArts").addEventListener("click", function () { $("arts").classList.remove("open"); });
  $("openSettings").addEventListener("click", function (e) { e.preventDefault(); openSettings(); });
  $("closeSettings").addEventListener("click", function () { $("settingsModal").classList.remove("open"); });
  $("saveSettings").addEventListener("click", async function () {
    var provider = $("set-provider").value;
    var providerModel = Array.prototype.find.call($("modelSel").options, function (option) {
      return option.dataset.provider === provider;
    });
    if (providerModel) $("modelSel").value = providerModel.value;
    var selectedModelOption = $("modelSel").options[$("modelSel").selectedIndex];
    var body = {
      provider: provider, model: selectedModelOption ? selectedModelOption.dataset.modelId : "", mode: $("set-mode").value,
      effort: $("set-effort").value, theme: $("set-theme").value,
      thinking: $("set-thinking").value !== "off",
    };
    var r = await api("/api/settings", { method: "PATCH", body: JSON.stringify(body) });
    if (!r.ok) { $("setErr").textContent = "Save failed"; return; }
    document.documentElement.setAttribute("data-theme", body.theme);
    var key = $("set-key").value.trim();
    if (key) {
      var rk = await api("/api/keys", { method: "POST", body: JSON.stringify({ provider: body.provider, api_key: key }) });
      if (!rk.ok) {
        var errData = await rk.json().catch(function() { return {}; });
        $("setErr").textContent = errData.detail || "Key save failed";
        return;
      }
      $("set-key").value = "";
      toast("API key saved for " + providerLabel(body.provider));
    }
    $("setErr").textContent = "";
    toast("Settings saved");
    var pr = await api("/api/providers");
    if (pr.ok) {
      var pd = await pr.json();
      allProviders = pd.providers || {};
    }
  });
  $("set-theme").addEventListener("change", function () {
    document.documentElement.setAttribute("data-theme", this.value);
  });
  $("browseModels").addEventListener("click", function () {
    $("modelsModal").classList.add("open");
    $("modelSearch").value = "";
    renderModelBrowser();
    $("modelSearch").focus();
  });
  $("browseModelsTop").addEventListener("click", function () {
    $("modelsModal").classList.add("open");
    $("modelSearch").value = "";
    renderModelBrowser();
    $("modelSearch").focus();
  });
  $("modelSearch").addEventListener("input", renderModelBrowser);
  $("closeModels").addEventListener("click", function () { $("modelsModal").classList.remove("open"); });

  /* -- Boot -- */
  (async function boot() {
    document.documentElement.setAttribute("data-theme", "light");
    $("userName").textContent = "User";
    $("userEmail").textContent = "DeepanCode";
    await loadModels();
    await loadList("");
    await updateUsage();
    emptyState(true);
    connect();
  })();
})();
