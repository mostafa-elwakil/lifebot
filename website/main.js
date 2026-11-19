/* Rakez marketing site — small, dependency-free enhancements */
(function () {
  "use strict";

  var REPO = "mostafa-elwakil/lifebot";
  var RELEASES = "https://github.com/" + REPO + "/releases";
  var API = "https://api.github.com/repos/" + REPO + "/releases/latest";

  var root = document.documentElement;
  var LANG = (root.lang || "ar").toLowerCase().indexOf("en") === 0 ? "en" : "ar";
  var $ = function (sel, ctx) { return (ctx || document).querySelector(sel); };
  var $$ = function (sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); };

  var TEXT = {
    ar: {
      themeToDark: "تفعيل الوضع الداكن",
      themeToLight: "تفعيل الوضع الفاتح",
      dark: "الوضع الداكن",
      light: "الوضع الفاتح",
      download: "تحميل المثبّت ",
      locale: "ar-EG"
    },
    en: {
      themeToDark: "Switch to dark mode",
      themeToLight: "Switch to light mode",
      dark: "Dark mode",
      light: "Light mode",
      download: "Download installer ",
      locale: "en-GB"
    }
  }[LANG];

  /* ---------------- theme ---------------- */
  function setTheme(theme, persist) {
    root.dataset.theme = theme;
    if (persist) {
      try { localStorage.setItem("rakez-theme", theme); } catch (e) {}
    }
    var meta = $('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "light" ? "#f5f6fa" : "#12131c");
    var btn = $("#theme-toggle");
    if (btn) {
      btn.setAttribute("aria-label", theme === "light" ? TEXT.themeToDark : TEXT.themeToLight);
      btn.setAttribute("title", theme === "light" ? TEXT.dark : TEXT.light);
    }
  }

  var toggle = $("#theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      setTheme(root.dataset.theme === "light" ? "dark" : "light", true);
    });
  }
  setTheme(root.dataset.theme || "dark", false);

  /* ---------------- mobile nav ---------------- */
  var menuBtn = $("#menu-toggle");
  var nav = $("#nav");
  if (menuBtn && nav) {
    menuBtn.addEventListener("click", function () {
      var open = document.body.classList.toggle("nav-open");
      menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    $$("a", nav).forEach(function (link) {
      link.addEventListener("click", function () {
        document.body.classList.remove("nav-open");
        menuBtn.setAttribute("aria-expanded", "false");
      });
    });
    document.addEventListener("click", function (e) {
      if (!document.body.classList.contains("nav-open")) return;
      if (nav.contains(e.target) || menuBtn.contains(e.target)) return;
      document.body.classList.remove("nav-open");
      menuBtn.setAttribute("aria-expanded", "false");
    });
  }

  /* ---------------- sticky header state ---------------- */
  var header = $(".site-header");
  function onScroll() {
    if (!header) return;
    header.classList.toggle("scrolled", window.scrollY > 8);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---------------- reveal on scroll ---------------- */
  var reveals = $$(".reveal");
  if ("IntersectionObserver" in window && reveals.length) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("in");
        io.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -70px 0px", threshold: 0.08 });
    reveals.forEach(function (el) { io.observe(el); });
  } else {
    reveals.forEach(function (el) { el.classList.add("in"); });
  }

  /* ---------------- design tabs ---------------- */
  var CAPTIONS = {
    ar: {
      pill: "Glass Pill — زجاجي هادئ بحدود ملوّنة، الأكثر استخدامًا.",
      neon: "Neon Card — توهّج بنفسجي ووردي لمحبي الأجواء الليلية.",
      split: "Split Flip — لوحتان متقابلتان، الوقت في جهة والمهمة في الأخرى.",
      retro: "Typewriter — ورقة قديمة وحبر داكن، لأجواء الآلة الكاتبة."
    },
    en: {
      pill: "Glass Pill — calm frosted glass with a colored rim. The default.",
      neon: "Neon Card — purple and pink glow for late-night sessions.",
      split: "Split Flip — two facing panels: the time on one side, the task on the other.",
      retro: "Typewriter — old paper and dark ink, straight out of a typewriter."
    }
  }[LANG];
  var stage = $("#stage-demo");
  var caption = $("#stage-caption");
  var tabs = $$("[data-design-tab]");

  function pickDesign(name) {
    if (!stage) return;
    if (!CAPTIONS[name]) name = "pill";
    stage.dataset.design = name;
    if (caption) caption.textContent = CAPTIONS[name];
    tabs.forEach(function (tab) {
      var active = tab.dataset.designTab === name;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () { pickDesign(tab.dataset.designTab); });
    tab.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      var i = tabs.indexOf(tab);
      var dir = e.key === "ArrowLeft" ? 1 : -1;
      var next = tabs[(i + dir + tabs.length) % tabs.length];
      next.focus();
      pickDesign(next.dataset.designTab);
    });
  });

  /* ---------------- hero clock (gentle countdown) ---------------- */
  var clock = $("[data-clock]");
  if (clock && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    var left = 24 * 60 + 59;
    setInterval(function () {
      left = left <= 0 ? 25 * 60 : left - 1;
      var m = Math.floor(left / 60);
      var s = left % 60;
      clock.textContent = (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
    }, 1000);
  }

  /* ---------------- latest release ---------------- */
  function fmtSize(bytes) {
    if (!bytes) return "—";
    var mb = bytes / (1024 * 1024);
    var num = mb >= 10 ? Math.round(mb) : mb.toFixed(1);
    // keep the Latin run LTR inside the Arabic page («74 MB», not «MB 74»)
    return (LANG === "ar" ? "\u200E" : "") + num + " MB";
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleDateString(TEXT.locale, {
        year: "numeric", month: "long", day: "numeric"
      });
    } catch (e) {
      return iso.slice(0, 10);
    }
  }

  function setText(sel, text) {
    $$(sel).forEach(function (el) { el.textContent = text; });
  }

  function applyRelease(release) {
    if (!release) return;
    var tag = release.tag_name || "";
    var version = tag.replace(/^v/i, "");
    var assets = release.assets || [];
    var installer = null;
    for (var i = 0; i < assets.length; i++) {
      if (/\.exe$/i.test(assets[i].name) && /setup/i.test(assets[i].name)) { installer = assets[i]; break; }
    }
    if (!installer) {
      for (var j = 0; j < assets.length; j++) {
        if (/\.exe$/i.test(assets[j].name)) { installer = assets[j]; break; }
      }
    }

    if (version) setText("[data-version]", version);
    if (installer) {
      setText("[data-size]", fmtSize(installer.size));
      setText("[data-download-label]", TEXT.download + version);
      $$("[data-download-link]").forEach(function (a) {
        a.setAttribute("href", installer.browser_download_url || a.getAttribute("href"));
      });
    }
    setText("[data-date]", fmtDate(release.published_at));
  }

  if (window.fetch) {
    fetch(API, { headers: { Accept: "application/vnd.github+json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(applyRelease)
      .catch(function () {
        $$("[data-download-link]").forEach(function (a) {
          if (!a.getAttribute("href") || a.getAttribute("href").charAt(0) === "#") {
            a.setAttribute("href", RELEASES + "/latest");
          }
        });
      });
  }

  /* ---------------- misc ---------------- */
  setText("[data-year]", String(new Date().getFullYear()));
})();
