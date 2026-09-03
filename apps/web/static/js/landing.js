/* Landing motion. GSAP vendored same-origin. Honors reduced motion. */
(function () {
  "use strict";
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced || typeof window.gsap === "undefined") return;
  gsap.registerPlugin(ScrollTrigger);

  gsap.from(".hero .reveal", {
    opacity: 0, y: 36, duration: 0.9, ease: "expo.out", stagger: 0.12, delay: 0.1,
  });
  gsap.from(".mock", { opacity: 0, y: 60, duration: 1.1, ease: "expo.out", delay: 0.5 });
  gsap.utils.toArray(".feat").forEach(function (el, i) {
    gsap.from(el, {
      opacity: 0, y: 40, duration: 0.7, ease: "power3.out",
      scrollTrigger: { trigger: el, start: "top 88%" }, delay: (i % 4) * 0.06,
    });
  });
})();
