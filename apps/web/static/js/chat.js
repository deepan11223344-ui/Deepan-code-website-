/* DeepanCode chat client. Same-origin only: no external requests anywhere.
   Motion: GSAP for container transitions; streaming text appends directly
   (no per-token animation — performance). Honors reduced motion. */
(function () {
  "use strict";
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var G = !reduced && typeof window.gsap !== "undefined" ? window.gsap : null;

  function $(id) { return document.getElementById(id); }
  var csrf = { session_id: "", token: "" };
  var ws = null, convId = 0, streaming = false, lastTool = "";
  var shouldStick = true;

  /* -- HTTP helper (cookies auto-sent; CSRF attached; one refresh retry) -- */
  async function csrfPair() {
    var r = await fetch("/api/auth/csrf-token", { credentials: "include" });
    if (!r.ok) throw new Error("session expired");
    var d = await r.json();
    csrf.session_id = d.session_id; csrf.token = d.csrf_token;
  }
  async function api(path, opts) {
    opts = opts || {};
    opts.credentials = "include";
    opts.headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    if (csrf.session_id && /POST|PATCH|PUT|DELETE/.test(opts.method || "GET")) {
      opts.headers["X-Session-Id"] = csrf.session_id;
      opts.headers["X-CSRF-Token"] = csrf.token;
    }
    var r = await fetch(path, opts);
    if (r.status === 403 && /POST|PATCH|PUT|DELETE/.test(opts.method || "GET")) {
      try { await csrfPair(); } catch (e) { window.location.href = "/login"; throw e; }
      opts.headers["X-Session-Id"] = csrf.session_id;
      opts.headers["X-CSRF-Token"] = csrf.token;
      r = await fetch(path, opts);
    }
    if (r.status === 401) { window.location.href = "/login"; throw new Error("unauthorized"); }
    return r;
  }

  /* -- Safe mini-markdown: escape first, allow fences/bold/code/headings,
        links restricted to http(s) with rel guard, javascript:/data: dropped. -- */
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function md(src) {
    var E = esc(src), out = "", re = /```(\w*)\n([\s\S]*?)(```|$)/g, last = 0, m;
    function inline(s) {
      s = s.replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (_, t, u) {
        if (/^https?:\/\//i.test(u)) return '<a href="' + u + '" target="_blank" rel="noopener noreferrer">' + t + "</a>";
        return t;
      });
      return s.replace(/^### (.*)$/gm, "<h4>$1</h4>").replace(/^## (.*)$/gm, "<h3>$1</h3>");
    }
    while ((m = re.exec(E))) {
      out += "<p>" + inline(m.input.slice(last, m.index)).replace(/\n{2,}/g, "</p><p>") + "</p>";
      out += "<pre><code>" + m[2].replace(/^\n+|\n+$/g, "") + "</code></pre>";
      last = m.index + m[0].length;
    }
    out += "<p>" + inline(E.slice(last)).replace(/\n{2,}/g, "</p><p>") + "</p>";
    return out.replace(/<p><\/p>/g, "");
  }

  /* -- Toasts (GSAP timeline) -- */
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
    if (G) gsap.from(el, { opacity: 0, y: 14, duration: 0.35, ease: "power3.out" });
  }
  function addMsg(who, html, isHtml) {
    var wrap = document.createElement("div");
    wrap.className = "msg" + (who === "you" ? " me" : "");
    var label = who === "you" ? "You" : who === "tool" ? "Tool" : "DeepanCode";
    var body = document.createElement("div");
    body.className = "body";
    if (isHtml) body.innerHTML = html; else body.textContent = html;
    var w = document.createElement("div");
    w.className = "who"; w.textContent = label;
    wrap.appendChild(w); wrap.appendChild(body);
    $("stream").appendChild(wrap);
    animateIn(wrap); stick();
    return body;
  }
  function addThink() {
    var el = document.createElement("div");
    el.className = "think";
    el.innerHTML = "Thinking… <span class='tpre' hidden></span>";
    var pre = el.querySelector(".tpre");
    el.addEventListener("click", function () { pre.hidden = !pre.hidden; });
    $("stream").appendChild(el);
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
    var list = $("clist"); list.innerHTML = "";
    (d.conversations || []).forEach(function (c) {
      var el = document.createElement("div");
      el.className = "citem" + (c.id === convId ? " active" : "");
      el.textContent = c.title || "Untitled";
      el.title = c.title || "";
      el.addEventListener("click", function () { openConv(c.id, c.title); });
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
    (d.messages || []).forEach(function (m) {
      if (m.role === "system") return;
      if (m.role === "user") addMsg("you", m.content || "");
      else if (m.role === "assistant") addMsg("ai", md(m.content || "[task done]"), true);
    });
    loadList($("search").value);
    emptyState(false);
  }
  function emptyState(show) {
    var s = $("stream");
    if (!show) { var e = $("emptyState"); if (e) e.remove(); return; }
    s.innerHTML = '<div class="empty" id="emptyState"><h1>Good evening, <span class="grad">builder.</span></h1>' +
      '<div class="sugg">' +
      '<button data-q="Explain this project architecture">Explain this project</button>' +
      '<button data-q="Review my latest changes for security issues">Security review</button>' +
      '<button data-q="Write tests for the auth module">Write tests</button>' +
      '<button data-q="Help me debug a failing test">Debug a test</button>' +
      "</div></div>";
    s.querySelectorAll("[data-q]").forEach(function (b) {
      b.addEventListener("click", function () { $("input").value = b.getAttribute("data-q"); send(); });
    });
    if (G) gsap.from("#emptyState > *", { opacity: 0, y: 24, duration: 0.6, ease: "expo.out", stagger: 0.08 });
  }

  /* -- WebSocket chat -- */
  function connect() {
    var badge = $("connBadge");
    var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(proto + "//" + window.location.host + "/ws/chat");
    ws.onopen = function () { ws.send(JSON.stringify({ type: "auth" })); };
    ws.onmessage = function (ev) {
      var m;
      try { m = JSON.parse(ev.data); } catch (e) { return; }
      onEvent(m);
    };
    ws.onclose = function () {
      badge.textContent = "reconnecting…"; badge.className = "badge";
      setStreaming(false);
      setTimeout(function () { if (!streaming) connect(); }, 2500);
    };
    ws.onerror = function () { try { ws.close(); } catch (e) { /* noop */ } };
  }
  function setStreaming(on) {
    streaming = on;
    var b = $("sendBtn");
    b.textContent = on ? "Stop" : "Send";
    b.className = "send" + (on ? " stop" : "");
  }
  var curBody = null, curThink = null;
  function onEvent(m) {
    var badge = $("connBadge");
    if (m.type === "auth_ok") { badge.textContent = "live"; badge.className = "badge live"; return; }
    if (m.type === "thinking_chunk") {
      if (!curThink) curThink = addThink();
      curThink.pre.hidden = false;
      curThink.pre.textContent += m.message || "";
      stick(); return;
    }
    if (m.type === "thinking_done") {
      if (curThink) { curThink.el.firstChild.textContent = "Thought"; curThink = null; }
      return;
    }
    if (m.type === "tool_call") {
      lastTool = m.message || "";
      var t = document.createElement("div");
      t.className = "tool"; t.textContent = "▸ " + lastTool;
      $("stream").appendChild(t); animateIn(t); stick(); return;
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
      addMsg("ai", "Error: " + (m.message || "unknown"));
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
    addMsg("you", text);
    $("input").value = ""; $("input").style.height = "auto";
    setStreaming(true);
    ws.send(JSON.stringify({ type: "chat", conversation_id: convId || null, message: text }));
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

  /* -- Models / usage / settings -- */
  async function loadModels() {
    var r = await api("/api/models");
    var d = await r.json();
    var sel = $("modelSel"); sel.innerHTML = "";
    (d.models || []).forEach(function (m) {
      var o = document.createElement("option");
      o.value = m.id; o.textContent = (m.provider || "") + " / " + (m.name || m.id);
      sel.appendChild(o);
    });
    var s = await api("/api/settings");
    var st = await s.json();
    if (st.model) sel.value = st.model;
    sel.addEventListener("change", async function () {
      await api("/api/settings", { method: "PATCH", body: JSON.stringify({ model: sel.value }) });
      toast("Model switched");
    });
  }
  async function updateUsage() {
    try {
      var r = await api("/api/usage");
      var d = await r.json();
      $("usage").textContent = d.conversations + " chats · " + (d.total_tokens || 0) + " tokens";
    } catch (e) { /* noop */ }
  }
  function fillSettings(st) {
    var provs = {};
    (st.keys_configured || {});
    $("set-provider").innerHTML = "";
    ["openrouter", "opencode"].forEach(function (p) {
      var o = document.createElement("option");
      o.value = p; o.textContent = p + ((st.keys_configured || {})[p] ? " (key ✓)" : "");
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
      ["code", "architect", "ask", "debug", "review"].forEach(function (m) {
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
    $("set-mode").value = st.mode || "code";
    $("set-effort").value = st.effort || "medium";
    $("set-theme").value = st.theme || "dark";
    $("totpState").textContent = st.totp_enabled ? "2FA is ON" : "2FA is off";
  }
  async function openSettings() {
    var r = await api("/api/settings");
    fillSettings(await r.json());
    $("settingsModal").classList.add("open");
    if (G) gsap.from("#settingsModal .card", { opacity: 0, y: 20, duration: 0.35, ease: "expo.out" });
  }

  /* -- Wire up chrome -- */
  $("newChat").addEventListener("click", async function () {
    var r = await api("/api/conversations", { method: "POST", body: JSON.stringify({ title: "Untitled" }) });
    var d = await r.json();
    openConv(d.conversation_id, "Untitled");
  });
  $("search").addEventListener("input", function () { loadList(this.value); });
  $("toggleSide").addEventListener("click", function () { $("sidebar").classList.add("hidden"); });
  $("showSide").addEventListener("click", function () { $("sidebar").classList.remove("hidden"); });
  $("closeArts").addEventListener("click", function () { $("arts").classList.remove("open"); });
  $("openSettings").addEventListener("click", function (e) { e.preventDefault(); openSettings(); });
  $("closeSettings").addEventListener("click", function () { $("settingsModal").classList.remove("open"); });
  $("logout").addEventListener("click", async function (e) {
    e.preventDefault();
    await api("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  });
  $("saveSettings").addEventListener("click", async function () {
    var body = {
      provider: $("set-provider").value, mode: $("set-mode").value,
      effort: $("set-effort").value, theme: $("set-theme").value,
      thinking: $("set-thinking").value !== "off",
    };
    var r = await api("/api/settings", { method: "PATCH", body: JSON.stringify(body) });
    if (!r.ok) { $("setErr").textContent = "Save failed"; return; }
    document.documentElement.setAttribute("data-theme", body.theme);
    var key = $("set-key").value.trim();
    if (key) {
      var rk = await api("/api/keys", { method: "POST", body: JSON.stringify({ provider: body.provider, api_key: key }) });
      if (!rk.ok) { $("setErr").textContent = "Key save failed"; return; }
      $("set-key").value = "";
    }
    $("setErr").textContent = "";
    toast("Settings saved");
  });
  $("totpStart").addEventListener("click", async function () {
    var r = await api("/api/auth/totp/enroll", { method: "POST", body: "{}" });
    if (!r.ok) { $("setErr").textContent = "Enroll failed"; return; }
    var d = await r.json();
    $("totpSecret").textContent = "Secret: " + d.secret + " — add to your authenticator app, then confirm:";
    $("totpSetup").hidden = false;
  });
  $("totpEnable").addEventListener("click", async function () {
    var r = await api("/api/auth/totp/verify", { method: "POST", body: JSON.stringify({ code: $("totpCode").value.trim() }) });
    if (!r.ok) { $("setErr").textContent = "Invalid code"; return; }
    $("totpState").textContent = "2FA is ON";
    $("totpSetup").hidden = true;
    toast("2FA enabled");
  });

  /* -- Boot -- */
  (async function boot() {
    try { await csrfPair(); }
    catch (e) { window.location.href = "/login"; return; }
    try {
      var s = await api("/api/settings");
      var st = await s.json();
      document.documentElement.setAttribute("data-theme", st.theme || "dark");
    } catch (e) { window.location.href = "/login"; return; }
    await loadModels();
    await loadList("");
    await updateUsage();
    emptyState(true);
    connect();
  })();
})();
