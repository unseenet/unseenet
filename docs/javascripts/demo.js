// Plays the terminal recordings (elements with data-cast) with the bundled
// asciinema player (assets/asciinema/, Apache-2.0). Nothing is loaded from
// other sites. A recording starts when it scrolls into view, unless the
// reader prefers reduced motion; then it waits for a click on play.
// The "Larger" buttons let one recording on the front page take the full width.
(function () {
  "use strict";

  var THEME = {
    foreground: "#e8f3ef",
    background: "#10302a",
    palette: "#10302a:#e06c75:#34d399:#e5c07b:#61afef:#c678dd:#56b6c2:#dcdfe4:" +
             "#5c6370:#e06c75:#34d399:#e5c07b:#61afef:#c678dd:#56b6c2:#ffffff"
  };

  function base() {
    // The site's root, so the page works under any path (and in mkdocs serve)
    var script = document.querySelector('script[src$="javascripts/demo.js"]');
    return script ? script.src.replace(/javascripts\/demo\.js.*$/, "") : "";
  }

  function mount(el) {
    if (el.dataset.mounted || typeof AsciinemaPlayer === "undefined") return;
    el.dataset.mounted = "1";
    var still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var player = AsciinemaPlayer.create(base() + el.dataset.cast, el, {
      fit: "both",          // fills the 16:10 frame the page gives it
      idleTimeLimit: 2,
      loop: true,
      poster: el.dataset.poster || "npt:0:5",
      terminalFontFamily: '"Fira Code", "DejaVu Sans Mono", ui-monospace, Menlo, Consolas, monospace',
      theme: "unseenet",
      controls: true
    });
    if (still || !("IntersectionObserver" in window)) return;
    var started = false;
    new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && entry.intersectionRatio > 0.5) {
          if (!started) { started = true; player.play(); }
        } else if (started) {
          player.pause();
          started = false;
        }
      });
    }, { threshold: [0, 0.5, 1] }).observe(el);
  }

  function addTheme() {
    if (document.getElementById("un-ap-theme")) return;
    var css = ".asciinema-player-theme-unseenet{" +
      "--term-color-foreground:" + THEME.foreground + ";" +
      "--term-color-background:" + THEME.background + ";";
    THEME.palette.split(":").forEach(function (c, i) { css += "--term-color-" + i + ":" + c + ";"; });
    css += "}";
    var style = document.createElement("style");
    style.id = "un-ap-theme";
    style.textContent = css;
    document.head.appendChild(style);
  }

  function sizeButtons() {
    document.querySelectorAll(".un-rec__size").forEach(function (btn) {
      if (btn.dataset.bound) return;
      btn.dataset.bound = "1";
      btn.hidden = false;
      btn.addEventListener("click", function () {
        var fig = btn.closest(".un-rec");
        var large = !fig.classList.contains("is-large");
        document.querySelectorAll(".un-rec.is-large").forEach(function (other) {
          other.classList.remove("is-large");
          var b = other.querySelector(".un-rec__size");
          b.textContent = "Larger";
          b.setAttribute("aria-expanded", "false");
        });
        if (large) fig.classList.add("is-large");
        btn.textContent = large ? "Smaller" : "Larger";
        btn.setAttribute("aria-expanded", large ? "true" : "false");
        fig.scrollIntoView({ block: "nearest", behavior: "smooth" });
      });
    });
  }

  function init() {
    sizeButtons();
    var casts = document.querySelectorAll(".un-term[data-cast]");
    if (!casts.length) return;
    addTheme();
    casts.forEach(mount);
  }

  // Material for MkDocs with instant loading publishes document$; plain pages do not
  if (window.document$ && window.document$.subscribe) {
    window.document$.subscribe(init);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
