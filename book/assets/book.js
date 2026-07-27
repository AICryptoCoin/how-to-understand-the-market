/* Книжный рантайм: тема, боковая панель, навигация, перекрёстные ссылки,
   нумерация фигур, тултипы, табличные двойники.
   Подключается ПОСЛЕ chapters.js. Ничего не требует от разметки главы, кроме
   <body data-chapter-id="слаг"> (или data-cover для обложки).

   ─────────────────────────────────────────────────────────────────────────
   Номер главы нигде не хранится: он равен позиции в BOOK_CHAPTERS плюс один
   и вычисляется здесь, на старте. Всё остальное — боковая панель, хлебные
   крошки, переходы, перекрёстные ссылки, номера фигур — берёт число отсюда.
   Поэтому вставка главы в середину книги не требует править ни одну главу.

   Числа, записанные в разметке (в .xref__n, .figref__n, .figure__num,
   в <title> страницы), — запасной вариант для чтения без JavaScript и для
   печати. Скрипт их подтверждает или исправляет, `tools/linkify.py --check`
   ловит расхождение до того, как оно попадёт читателю.
   ───────────────────────────────────────────────────────────────────────── */
(function () {
  "use strict";

  var chapters = window.BOOK_CHAPTERS || [];
  var parts = window.BOOK_PARTS || [];

  /* Единственное место, где появляется номер главы. */
  var index = {};                                   // id → позиция в массиве
  var byFile = {};                                  // имя файла → позиция
  chapters.forEach(function (c, i) {
    c.n = i + 1;
    index[c.id] = i;
    byFile[c.file] = i;
  });

  function fileToId() {
    var name = (location.pathname.split("/").pop() || "");
    var i = byFile[name];
    return i === undefined ? null : chapters[i].id;
  }

  var curId = document.body.dataset.chapterId || fileToId();
  var curIdx = (curId != null && index[curId] !== undefined) ? index[curId] : null;
  var cur = curIdx == null ? null : chapters[curIdx];

  function partOf(c) {
    return parts.filter(function (p) { return p.id === c.part; })[0];
  }

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
        var isCur = curIdx != null && c === cur;
        var done = c.status === "done";
        var cur_ = isCur ? ' aria-current="page"' : "";
        var inner = '<span class="num">' + c.n + "</span><span>" + esc(c.title) + "</span>";
        html += "<li>" + (done
          ? '<a href="' + c.file + '"' + cur_ + ">" + inner + "</a>"
          : '<span class="todo">' + inner + "</span>") + "</li>";
      });
      html += "</ol>";
    });
    nav.innerHTML = html;
  }

  /* ---------- шапка, хлебные крошки и переходы ---------- */
  function buildChrome() {
    if (!cur) return;
    var p = partOf(cur);

    var where = document.getElementById("topbar-where");
    if (where && p) where.textContent = p.label + " · Глава " + cur.n + ". " + cur.title;

    /* Хлебная крошка над заголовком и заголовок вкладки — тоже из реестра:
       иначе они расходятся с книгой при первой же вставке главы. */
    var eyebrow = document.querySelector(".prose .chapter-eyebrow");
    if (eyebrow && p) eyebrow.textContent = p.label + " · " + p.title + " · Глава " + cur.n;
    document.title = cur.n + ". " + cur.title + " — Как понимать рынок";

    var navEl = document.getElementById("chapter-nav");
    if (!navEl) return;
    navEl.innerHTML = cell(chapters[curIdx - 1], "prev", "Предыдущая глава") +
                      cell(chapters[curIdx + 1], "next", "Следующая глава");

    function cell(ch, cls, label) {
      if (!ch) return '<span class="' + cls + ' empty"></span>';
      var body = '<span class="dirn">' + label + '</span><span class="ttl">' +
        ch.n + ". " + esc(ch.title) + "</span>";
      return ch.status === "done"
        ? '<a class="' + cls + '" href="' + ch.file + '">' + body + "</a>"
        : '<span class="' + cls + ' stub">' + body +
          '<span class="dirn">ещё не написана</span></span>';
    }
  }

  /* ---------- перекрёстные ссылки ----------
     Автор пишет слаг и падеж, скрипт пишет цифру:

       см. <a class="xref" data-ch="faktory">главу <b class="xref__n">56</b></a>
       см. <a class="xref" data-ch="hope" data-anchor="s8">…</a>

     Ссылка на саму себя или подпись внутри графики обходится без <a>:
     достаточно <b class="xref__n" data-ch="k-kodu">71</b> — в SVG роль <b>
     играет <tspan> (HTML-теги внутри <text> не рендерятся). */
  function fillXrefs() {
    document.querySelectorAll("a.xref[data-ch]").forEach(function (a) {
      var c = chapters[index[a.dataset.ch]];
      if (!c) { a.classList.add("xref--broken"); return; }
      var frag = a.dataset.anchor ? "#" + a.dataset.anchor : "";
      a.setAttribute("href", (c === cur ? "" : c.file) + frag);
      a.setAttribute("title", c.n + ". " + c.title);
      if (c.status !== "done") a.classList.add("xref--todo");
      setNum(a.querySelector(".xref__n"), c.n);
    });
    /* Голые номера: самоссылки в прозе и подписи в SVG. */
    document.querySelectorAll(".xref__n[data-ch]").forEach(function (el) {
      var c = chapters[index[el.dataset.ch]];
      if (c) setNum(el, c.n);
    });
  }

  function setNum(el, value) {
    if (el && el.textContent !== String(value)) el.textContent = value;
  }

  /* ---------- нумерация фигур ----------
     id фигуры — fig-<слаг главы>-<k>. Номер «N.k» рисуется из позиции главы,
     поэтому переезд главы не требует править ни подпись, ни отсылки к ней. */
  function numberFigures() {
    if (curIdx == null) return;
    var k = 0;
    document.querySelectorAll("figure.figure").forEach(function (f) {
      k++;
      var num = (curIdx + 1) + "." + k;
      f.dataset.fignum = num;
      setNum(f.querySelector(".figure__num"), "Рис. " + num + ".");
    });
  }

  /* Отсылка к фигуре: <a class="figref" data-ch="hope" data-fig="2">…</a>.
     Цифру и адрес считает скрипт — в том числе для фигур чужой главы. */
  function fillFigrefs() {
    document.querySelectorAll("a.figref[data-ch][data-fig]").forEach(function (a) {
      var c = chapters[index[a.dataset.ch]];
      if (!c) { a.classList.add("xref--broken"); return; }
      var frag = "#fig-" + c.id + "-" + a.dataset.fig;
      a.setAttribute("href", (c === cur ? "" : c.file) + frag);
      a.setAttribute("title", "Рис. " + c.n + "." + a.dataset.fig + " · глава " + c.n + ". " + c.title);
      setNum(a.querySelector(".figref__n"), c.n + "." + a.dataset.fig);
    });
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
          : '<span class="stub">' + inner + '<span class="status status--todo">не написана</span></span>') + "</li>";
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
    fillXrefs(); numberFigures(); fillFigrefs();
    initTips(); initTableToggles(); initSidebarToggle(); buildCover();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
