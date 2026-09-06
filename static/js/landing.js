/* Landing motion. GSAP vendored same-origin. Honors reduced motion. */
(function () {
  "use strict";
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced || typeof window.gsap === "undefined") return;
  gsap.registerPlugin(ScrollTrigger);

  /* -- Floating orbs parallax -- */
  var orbs = document.querySelectorAll(".orb");
  if (orbs.length) {
    gsap.to(".orb-1", {
      x: 60, y: 40, duration: 20, ease: "sine.inOut", repeat: -1, yoyo: true,
    });
    gsap.to(".orb-2", {
      x: -50, y: -30, duration: 16, ease: "sine.inOut", repeat: -1, yoyo: true,
    });
    gsap.to(".orb-3", {
      x: 40, y: -50, duration: 22, ease: "sine.inOut", repeat: -1, yoyo: true,
    });
  }

  /* -- Hero entrance -- */
  var heroTl = gsap.timeline({ delay: 0.15 });
  heroTl
    .from(".hero .reveal", {
      opacity: 0, y: 40, duration: 0.9, ease: "expo.out", stagger: 0.1,
    })
    .from(".mock", {
      opacity: 0, y: 60, scale: 0.97, duration: 1.1, ease: "expo.out",
    }, "-=0.5");

  /* -- Mock chat typing simulation -- */
  var mockRows = document.querySelectorAll(".mock .row");
  if (mockRows.length >= 2) {
    var mockTl = gsap.timeline({ delay: 1.4 });
    mockTl
      .from(mockRows[0], { opacity: 0, x: -20, duration: 0.4, ease: "power2.out" })
      .from(mockRows[1], { opacity: 0, x: 20, duration: 0.4, ease: "power2.out" }, "+=0.3");
  }

  /* -- Feature cards staggered reveal -- */
  gsap.utils.toArray(".feat").forEach(function (el, i) {
    gsap.from(el, {
      opacity: 0, y: 50, scale: 0.96, duration: 0.7, ease: "power3.out",
      scrollTrigger: { trigger: el, start: "top 90%" },
      delay: (i % 4) * 0.08,
    });
  });

  /* -- Logo subtle pulse -- */
  gsap.to(".logo span", {
    filter: "brightness(1.2)", duration: 2, ease: "sine.inOut",
    repeat: -1, yoyo: true,
  });

  /* -- Parallax on scroll for orbs -- */
  ScrollTrigger.create({
    trigger: ".hero",
    start: "top top",
    end: "bottom top",
    onUpdate: function (self) {
      var p = self.progress;
      gsap.set(".orb-1", { y: p * -80 });
      gsap.set(".orb-2", { y: p * -60 });
      gsap.set(".orb-3", { y: p * -40 });
    },
  });
})();
