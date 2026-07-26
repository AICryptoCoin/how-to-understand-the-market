/* Книжный рантайм: тема, боковая панель, навигация, тултипы, табличные двойники.
   Подключается ПОСЛЕ chapters.js. Ничего не требует от разметки главы, кроме
   <body data-chapter="N"> (или data-cover для обложки). */
(function () {
  "use strict";

  var chapters = window.BOOK_CHAPTERS || [];
  var parts = window.BOOK_PARTS || [];
  var current = document.body.dataset.chapter ? parseInt(document.body.dataset.chapter, 10) : null;
  var byN = function (n) { return chapters.filter(function (c) { return c.n === n; })[0]; };

  /* ---------- тема ---------- */
  var THEMES = ["auto", "light", "dark"];
  var LABEL = { auto: "Тема: авто", light: "Тема: светлая", dark: "Тема: тёмная" };
  var ICON = { auto: "◐", light: "☀", dark: "☾" };

  function applyTheme(t) {
    if (t === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("kpr-theme", t); } catch (e) {}
    var btn = document.getElementById("theme-btn");
    if (btn) { btn.textContent = ICON[t] + "  " + LABEL[t]; btn.setAttribute("aria-label", LABEL[t]); }
  }

  function initTheme() {
    var saved = "auto";
    try { saved = localStorage.getItem("kpr-theme") || "auto"; } catch (e) {}
    applyTheme(THEMES.indexOf(saved) >= 0 ? saved : "auto");
    var btn = document.getElementById("theme-btn");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var now = "auto";
      try { now = localStorage.getItem("kpr-theme") || "auto"; } catch (e) {}
      applyTheme(THEMES[(THEMES.indexOf(now) + 1) % THEMES.length]);
    });
  }

  /* ---------- боковая панель ---------- */
  function buildSidebar() {
    var nav = document.getElementById("book-nav");
    if (!nav) return;
    var html = "";
    parts.forEach(function (p) {
      var list = chapters.filter(function (c) { return c.part === p.id; });
      if (!list.length) return;
      html += '<h2>' + esc(p.label) + " · " + esc(p.title) + "</h2><ol>";
      list.forEach(function (c) {
        var isCur = c.n === current;
        var done = c.status === "done";
        var cls = done ? "" : ' class="todo"';
        var cur = isCur ? ' aria-current="page"' : "";
        var inner = '<span class="num">' + c.n + "</span><span>" + esc(c.title) + "</span>";
        html += "<li>" + (done
          ? '<a href="' + c.file + '"' + cur + ">" + inner + "</a>"
          : "<span" + cls + ' style="display:flex;gap:.55rem;padding:.3rem .5rem">' + inner + "</span>") + "</li>";
      });
      html += "</ol>";
    });
    nav.innerHTML = html;
  }

  /* ---------- хлебные крошки и переходы ---------- */
  function buildChrome() {
    if (current == null) return;
    var c = byN(current);
    if (!c) return;
    var p = parts.filter(function (x) { return x.id === c.part; })[0];
    var where = document.getElementById("topbar-where");
    if (where && p) where.textContent = p.label + " · Глава " + c.n + ". " + c.title;

    var navEl = document.getElementById("chapter-nav");
    if (!navEl) return;
    var prev = byN(current - 1), next = byN(current + 1);
    navEl.innerHTML =
      cell(prev, "prev", "Предыдущая глава") + cell(next, "next", "Следующая глава");

    function cell(ch, cls, label) {
      if (!ch) return '<span class="' + cls + ' empty"></span>';
      var body = '<span class="dirn">' + label + '</span><span class="ttl">' +
        ch.n + ". " + esc(ch.title) + "</span>";
      return ch.status === "done"
        ? '<a class="' + cls + '" href="' + ch.file + '">' + body + "</a>"
        : '<span class="' + cls + '" style="opacity:.45;padding:.9rem 1.1rem;border:1px dashed var(--hairline);border-radius:.5rem;display:block">' +
          body + '<span class="dirn">ещё не написана</span></span>';
    }
  }

  /* ---------- якоря у заголовков ---------- */
  function buildAnchors() {
    document.querySelectorAll(".prose h2[id], .prose h3[id]").forEach(function (h) {
      var a = document.createElement("a");
      a.className = "anchor"; a.href = "#" + h.id; a.textContent = "#";
      a.setAttribute("aria-label", "Ссылка на раздел");
      h.appendChild(a);
    });
  }

  /* ---------- тултипы для графики ----------
     Любой элемент с [data-tip] внутри .figure получает подсказку по наведению
     И по клавиатурному фокусу. Подсказка — усиление, а не единственный путь к
     значению: у каждой фигуры есть табличный двойник. */
  function initTips() {
    var tip = document.getElementById("viz-tip");
    if (!tip) {
      tip = document.createElement("div");
      tip.id = "viz-tip"; tip.setAttribute("role", "status");
      document.body.appendChild(tip);
    }
    function show(el) {
      var txt = el.getAttribute("data-tip");
      if (!txt) return;
      tip.innerHTML = txt;
      tip.setAttribute("data-show", "1");
      var r = el.getBoundingClientRect();
      tip.style.left = (r.left + r.width / 2) + "px";
      tip.style.top = r.top + "px";
    }
    function hide() { tip.setAttribute("data-show", "0"); }

    document.addEventListener("pointerover", function (e) {
      var el = e.target.closest ? e.target.closest("[data-tip]") : null;
      if (el) show(el);
    });
    document.addEventListener("pointerout", function (e) {
      if (e.target.closest && e.target.closest("[data-tip]")) hide();
    });
    document.addEventListener("focusin", function (e) {
      var el = e.target.closest ? e.target.closest("[data-tip]") : null;
      if (el) show(el);
    });
    document.addEventListener("focusout", hide);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") hide(); });

    /* Клавиатурная доступность: любой [data-tip] фокусируем */
    document.querySelectorAll("[data-tip]").forEach(function (el) {
      if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
    });
  }

  /* ---------- переключатель «таблица» ---------- */
  function initTableToggles() {
    document.querySelectorAll(".figure").forEach(function (fig) {
      var table = fig.querySelector(".figure__table");
      if (!table) return;
      var tools = fig.querySelector(".figure__tools");
      if (!tools) {
        tools = document.createElement("div");
        tools.className = "figure__tools";
        (fig.querySelector("figcaption") || fig).insertAdjacentElement("afterend", tools);
      }
      var btn = document.createElement("button");
      btn.className = "btn"; btn.type = "button";
      btn.setAttribute("aria-pressed", "false");
      btn.textContent = "Таблица значений";
      btn.addEventListener("click", function () {
        var open = table.hasAttribute("hidden");
        if (open) table.removeAttribute("hidden"); else table.setAttribute("hidden", "");
        btn.setAttribute("aria-pressed", String(open));
      });
      tools.appendChild(btn);
    });
  }

  /* ---------- мобильная панель ---------- */
  function initSidebarToggle() {
    var btn = document.getElementById("sidebar-btn");
    var bar = document.querySelector(".sidebar");
    if (!btn || !bar) return;
    if (window.matchMedia("(max-width: 60rem)").matches) bar.setAttribute("hidden", "");
    btn.addEventListener("click", function () {
      var hidden = bar.hasAttribute("hidden");
      if (hidden) bar.removeAttribute("hidden"); else bar.setAttribute("hidden", "");
      btn.setAttribute("aria-expanded", String(hidden));
    });
  }

  /* ---------- обложка: оглавление и прогресс ---------- */
  function buildCover() {
    var host = document.getElementById("cover-toc");
    if (!host) return;
    var done = chapters.filter(function (c) { return c.status === "done"; }).length;
    var pct = Math.round((done / chapters.length) * 100);
    var bar = document.getElementById("cover-progress");
    if (bar) {
      bar.innerHTML =
        "<span>Написано " + done + " из " + chapters.length + " глав</span>" +
        '<span class="progress__bar"><span class="progress__fill" style="width:' + pct + '%"></span></span>' +
        "<span>" + pct + "%</span>";
    }
    var html = "";
    parts.forEach(function (p) {
      var list = chapters.filter(function (c) { return c.part === p.id; });
      if (!list.length) return;
      html += '<div class="toc-part"><div class="toc-part__label">' + esc(p.label) +
        '</div><div class="toc-part__title">' + esc(p.title) + "</div></div><ul class=\"toc-list\">";
      list.forEach(function (c) {
        var inner = '<span class="num">' + c.n + '</span><span>' + esc(c.title) + "</span>";
        html += "<li>" + (c.status === "done"
          ? '<a href="' + c.file + '">' + inner + '<span class="status status--done">готова</span></a>'
          : '<span class="stub">' + inner + '<span class="status status--todo">в работе</span></span>') + "</li>";
      });
      html += "</ul>";
    });
    host.innerHTML = html;
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
    });
  }

  function boot() {
    initTheme(); buildSidebar(); buildChrome(); buildAnchors();
    initTips(); initTableToggles(); initSidebarToggle(); buildCover();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
