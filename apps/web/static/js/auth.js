/* Auth flows. Session lives in HttpOnly cookies (JS never sees tokens).
   CSRF pair is fetched after login and kept in memory only. */
(function () {
  "use strict";
  function $(id) { return document.getElementById(id); }
  function err(box, msg) { $(box).textContent = msg || ""; }
  function intro() {
    if (typeof window.gsap === "undefined") return;
    gsap.from("#card", { opacity: 0, y: 24, duration: 0.6, ease: "expo.out" });
  }
  function show(which) {
    ["step-creds", "step-signup", "step-totp"].forEach(function (id) {
      $(id).hidden = id !== which;
    });
  }
  async function post(path, body) {
    var res = await fetch(path, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    var data = null;
    try { data = await res.json(); } catch (e) { /* non-JSON */ }
    return { status: res.status, data: data };
  }
  var ticket = null;

  $("showSignup").addEventListener("click", function (e) { e.preventDefault(); show("step-signup"); });
  $("showLogin").addEventListener("click", function (e) { e.preventDefault(); show("step-creds"); });

  $("loginBtn").addEventListener("click", async function () {
    err("err", "");
    var r = await post("/api/auth/login", { email: $("email").value.trim(), password: $("password").value });
    if (r.status === 200 && r.data && r.data.need_totp) {
      ticket = r.data.ticket;
      show("step-totp");
      $("code").focus();
      return;
    }
    if (r.status === 200) { window.location.href = "/chat"; return; }
    err("err", (r.data && r.data.detail) || "Login failed");
  });
  $("password").addEventListener("keydown", function (e) { if (e.key === "Enter") $("loginBtn").click(); });

  $("signupBtn").addEventListener("click", async function () {
    err("err2", "");
    var r = await post("/api/auth/signup", {
      email: $("s-email").value.trim(), password: $("s-password").value, invite_code: $("invite").value,
    });
    if (r.status === 200) { window.location.href = "/chat"; return; }
    err("err2", (r.data && r.data.detail) || "Signup failed");
  });

  $("totpBtn").addEventListener("click", async function () {
    err("err3", "");
    var r = await post("/api/auth/login/totp", { ticket: ticket, code: $("code").value.trim() });
    if (r.status === 200) { window.location.href = "/chat"; return; }
    err("err3", (r.data && r.data.detail) || "Invalid code");
  });

  intro();
})();
