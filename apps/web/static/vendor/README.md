# Vendored frontend libraries (same-origin, no CDN at runtime)

These files are served from `/static/vendor/` by our own server. The browser
never contacts a third party. Re-vendor with pinned versions only:

- `gsap.min.js` — GSAP 3.12.5 (core)
- `ScrollTrigger.min.js` — GSAP ScrollTrigger 3.12.5 (landing page only)

Source (build-time only): https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/
Expected bytes must start with `/*! GSAP 3.12.5` / `/*! ScrollTrigger 3.12.5`.
