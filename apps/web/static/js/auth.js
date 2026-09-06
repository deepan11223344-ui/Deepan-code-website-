/* Auth flows. Session lives in HttpOnly cookies (JS never sees tokens).
   CSRF pair is fetched after login and kept in memory only.
   GSAP transitions between steps. Honors reduced motion. */
(function () {
  "use strict";
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var G = !reduced && typeof window.gsap !== "undefined" ? window.gsap : null;

  function $(id) { return document.getElementById(id); }
  function err(box, msg) { $(box).textContent = msg || ""; }

  function intro() {
    if (!G) return;
    gsap.from("#card", { opacity: 0, y: 30, scale: 0.97, duration: 0.6, ease: "expo.out" });
    gsap.from(".orb", { opacity: 0, scale: 0.5, duration: 1.2, ease: "expo.out", stagger: 0.2 });
  }

  function show(which) {
    var ids = ["step-creds", "step-signup", "step-totp"];
    var current = ids.find(function (id) { return !$(id).hidden; });
    if (current === which) return;

    if (G && current) {
      var card = $("#card");
      gsap.to(card, {
        opacity: 0, y: -10, duration: 0.15, ease: "power2.in",
        onComplete: function () {
          ids.forEach(function (id) { $(id).hidden = id !== which; });
          gsap.fromTo(card,
            { opacity: 0, y: 10 },
            { opacity: 1, y: 0, duration: 0.3, ease: "power2.out" }
          );
        }
      });
    } else {
      ids.forEach(function (id) { $(id).hidden = id !== which; });
    }
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
  if ($("showLogin2")) $("showLogin2").addEventListener("click", function (e) { e.preventDefault(); show("step-creds"); });

  $("loginBtn").addEventListener("click", async function () {
    err("err", "");
    var btn = $("loginBtn");
    btn.textContent = "Logging in…"; btn.disabled = true;
    var r = await post("/api/auth/login", { email: $("email").value.trim(), password: $("password").value });
    btn.textContent = "Log in"; btn.disabled = false;
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
  $("code").addEventListener("keydown", function (e) { if (e.key === "Enter") $("totpBtn").click(); });

  $("signupBtn").addEventListener("click", async function () {
    err("err2", "");
    var btn = $("signupBtn");
    btn.textContent = "Creating…"; btn.disabled = true;
    var r = await post("/api/auth/signup", {
      email: $("s-email").value.trim(), password: $("s-password").value, invite_code: $("invite").value,
    });
    btn.textContent = "Create account"; btn.disabled = false;
    if (r.status === 200) { window.location.href = "/chat"; return; }
    err("err2", (r.data && r.data.detail) || "Signup failed");
  });

  $("totpBtn").addEventListener("click", async function () {
    err("err3", "");
    var btn = $("totpBtn");
    btn.textContent = "Verifying…"; btn.disabled = true;
    var r = await post("/api/auth/login/totp", { ticket: ticket, code: $("code").value.trim() });
    btn.textContent = "Verify"; btn.disabled = false;
    if (r.status === 200) { window.location.href = "/chat"; return; }
    err("err3", (r.data && r.data.detail) || "Invalid code");
  });

  intro();
})();
