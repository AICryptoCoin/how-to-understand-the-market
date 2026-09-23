/**
 * Прибор геометрии графики книги «Как понимать рынок».
 *
 * Единственная реализация. `STYLE-GUIDE.md` §7 описывает порядок работы и
 * ссылается сюда; кода проверки в руководстве нет и быть не должно.
 *
 * ЧТО ОН СУДИТ. Столкновение двух подписей — это общий НЕПРОЗРАЧНЫЙ ПИКСЕЛЬ
 * их глифов, и ничего другого. Пересечение ограничивающих рамок (`getBBox`)
 * служит только дешёвым отсевом кандидатов: рамка текста — это em-рамка
 * шрифта, а не занятое глифами место, и она заведомо шире чернил. Полный
 * прогон книги 2026-08-02 (40 страниц × 4 ширины, 198 фигур, 5395 текстовых
 * узлов) дал 102/220/48/104 пересечения рамок на 320/360/390/1280 px и НОЛЬ
 * пар с общим чернильным пикселем. Кандидат по рамке — норма, а не долг.
 *
 * ПОЧЕМУ РАМКА ТАК ВЕЛИКА. Chrome округляет ascent и descent шрифта до целых
 * CSS-пикселей ЭКРАНА, а потом пересчитывает обратно в единицы viewBox. При
 * `.viz-label` 12px и масштабе 0,2767 (окно 320 px) ascent 12 × 1,08 = 12,96
 * единиц = 3,586 px экрана округляется до 4 px, descent 3 единицы = 0,83 px —
 * до 1 px; вместе 5 px экрана = 18,07 единиц вместо 15,96. Чернила при этом
 * не меняются вовсе: ширины букв остаются прежними, ink-высота той же
 * подписи — 11,83 единицы (9,0 над базовой линией, 2,83 под ней). При шаге
 * строк 15 между чернилами соседних строк остаётся 3,17 единицы просвета,
 * а рамки перекрываются на 3,07 — отсюда и весь класс ложных тревог.
 *
 * КАК МЕРИТСЯ ЧЕРНИЛО. Узел `<text>` клонируется вместе с цепочкой предков
 * (в ней живут `transform`), к нему и его `tspan` подставляются вычисленные
 * стили, результат сериализуется в самостоятельный SVG и растеризуется через
 * `Image` + `canvas` в решётку MAG пикселей на единицу viewBox. Решётка общая
 * для всей фигуры (границы кропа выровнены по целым долям 1/MAG), поэтому
 * маски двух узлов складываются побитово без пересчёта координат. Пиксель
 * считается чернильным при alpha ≥ ALPHA_MIN.
 *
 * ЛОВУШКИ СРЕДЫ — обе перекрыты предохранителем `preflight()`:
 *   1. Сразу после подъёма предпросмотра `innerWidth` и `clientWidth` равны
 *      нулю, `getScreenCTM()` вырождается в масштаб ровно 1, и прибор молча
 *      отдаёт пустоту, неотличимую от пройденной приёмки.
 *   2. Измерение внутри `iframe` даёт ЛОЖНЫЕ коллизии: в дочернем контексте
 *      колонка `.content` схлопывается (961 → 304 px при верном clientWidth
 *      1265), фигура рендерится втрое меньше, а кегль подписей задан
 *      абсолютно и не масштабируется. Мерить только в верхнеуровневом
 *      документе.
 *
 * ЖИВОСТЬ. `liveness()` на каждой ширине портит геометрию в памяти и требует,
 * чтобы прибор зажёгся (положительный контроль) и чтобы он НЕ зажигался на
 * разведённых строках (отрицательный контроль). Пустой результат без этих
 * двух контролей предъявлять нельзя.
 *
 * Порядок работы и команды — `STYLE-GUIDE.md` §7.
 */

export const VERSION = '2026-08-02';

/** Порог «непрозрачности» пикселя, 0–255. */
export const ALPHA_MIN = 128;
/** Разрешение растра: пикселей на единицу viewBox. */
export const MAG = 6;
/** Запас растра вокруг рамки, пикселей. */
const PAD = 1;
/** Допуск выхода за viewBox, единиц. */
const OVERFLOW_TOL = 0.5;
/** Сколько примеров кандидатов возвращать со страницы. */
const SAMPLES = 4;

const NS = 'http://www.w3.org/2000/svg';

/** Свойства, без которых клон не воспроизводит раскладку строки. */
const STYLE_PROPS = [
  'font-family', 'font-size', 'font-weight', 'font-style', 'font-stretch',
  'font-variant', 'font-variant-numeric', 'letter-spacing', 'word-spacing',
  'text-anchor', 'dominant-baseline', 'alignment-baseline', 'baseline-shift',
  'direction', 'writing-mode', 'text-orientation', 'glyph-orientation-vertical',
  'paint-order', 'stroke-width', 'stroke-linejoin', 'stroke-linecap',
];

// ────────────────────────────────────────────────────────────────────────────
// Среда
// ────────────────────────────────────────────────────────────────────────────

export function figureSvgs() {
  // Формулы тоже рисуются SVG и тоже попадают в подписи к фигурам, но это
  // не чернила фигуры: с включением рендерера 2026-09-23 счёт по главе 10
  // подскочил с 5 «фигур» до 50. Сегодня вреда нет — у MathJax глифы идут
  // через <use>, а не <text>, и мерить в них нечего. Но масштаб прибора
  // берётся с svgs[0], и стоит формуле оказаться первой в документе, как
  // весь замер поедет. Поэтому исключаем явно, а не надеемся на порядок.
  return [...document.querySelectorAll('figure.figure svg')]
    .filter(s => !s.closest('mjx-container'));
}

export function env() {
  const de = document.documentElement;
  const svgs = figureSvgs();
  let ctmScale = null;
  if (svgs.length) {
    const m = svgs[0].getScreenCTM();
    if (m) ctmScale = m.a;
  }
  return {
    url: location.href,
    topLevel: window.top === window.self,
    innerWidth: window.innerWidth,
    clientWidth: de.clientWidth,
    scrollWidth: de.scrollWidth,
    contentWidth: document.querySelector('.content')
      ? Math.round(document.querySelector('.content').getBoundingClientRect().width) : null,
    fonts: document.fonts ? document.fonts.status : 'нет API',
    dpr: window.devicePixelRatio,
    ctmScale,
    figures: svgs.length,
  };
}

/**
 * Предохранитель. Пока он не зелёный, любой результат прибора — мусор,
 * и пустой результат в том числе.
 */
export function preflight() {
  const e = env();
  const bad = [];
  if (!e.topLevel)
    bad.push('замер идёт внутри iframe — раскладка в дочернем контексте схлопывается, ' +
             'коллизии будут ложными; мерить только в верхнеуровневом документе');
  if (!e.clientWidth)
    bad.push('documentElement.clientWidth = 0 — вьюпорт не поднялся: задать размер окна и ПЕРЕЗАГРУЗИТЬ страницу');
  if (!e.innerWidth)
    bad.push('window.innerWidth = 0 — то же самое');
  if (e.fonts !== 'loaded')
    bad.push('шрифты ещё не разложены: document.fonts.status = ' + e.fonts);
  if (!e.figures) bad.push('на странице нет ни одной figure.figure svg');
  else if (e.ctmScale === null) bad.push('getScreenCTM() = null — SVG не отрисован');
  else if (e.ctmScale === 1)
    bad.push('масштаб CTM ровно 1 — признак вырожденного вьюпорта; замер выбросить');
  return { ok: bad.length === 0, env: e, reasons: bad };
}

// ────────────────────────────────────────────────────────────────────────────
// Рамки
// ────────────────────────────────────────────────────────────────────────────

function isRendered(t) {
  const cs = getComputedStyle(t);
  if (cs.display === 'none' || cs.visibility === 'hidden') return false;
  if (parseFloat(cs.opacity) === 0) return false;
  if (cs.fill === 'none' && cs.stroke === 'none') return false;
  let b;
  try { b = t.getBBox(); } catch (_) { return false; }
  return b.width > 0 && b.height > 0;
}

export function textNodes(svg) {
  return [...svg.querySelectorAll('text')].filter(t => t.textContent.trim() && isRendered(t));
}

/** em-рамка узла в координатах viewBox. Заведомо шире чернил — только отсев. */
function emBox(svg, t, toVB) {
  const b = t.getBBox();
  const M = toVB.multiply(t.getScreenCTM());
  const xs = [], ys = [];
  for (const [x, y] of [[b.x, b.y], [b.x + b.width, b.y],
                        [b.x, b.y + b.height], [b.x + b.width, b.y + b.height]]) {
    const p = svg.createSVGPoint();
    p.x = x; p.y = y;
    const q = p.matrixTransform(M);
    xs.push(q.x); ys.push(q.y);
  }
  return { x1: Math.min(...xs), y1: Math.min(...ys), x2: Math.max(...xs), y2: Math.max(...ys) };
}

// ────────────────────────────────────────────────────────────────────────────
// Чернила
// ────────────────────────────────────────────────────────────────────────────

function inlineStyle(src, dst) {
  const cs = getComputedStyle(src);
  const parts = STYLE_PROPS.map(p => p + ':' + cs.getPropertyValue(p));
  parts.push('fill:#000', 'fill-opacity:1', 'opacity:1');
  const stroke = cs.getPropertyValue('stroke');
  const sw = parseFloat(cs.getPropertyValue('stroke-width'));
  parts.push(stroke && stroke !== 'none' && sw > 0
    ? 'stroke:#000;stroke-opacity:1' : 'stroke:none');
  dst.setAttribute('style', parts.join(';'));
  for (let i = 0; i < src.children.length && i < dst.children.length; i++)
    inlineStyle(src.children[i], dst.children[i]);
}

/**
 * Маска чернил узла на общей решётке фигуры.
 * Возвращает {i0,j0,w,h,m,n,ink}; `n = 0` означает, что растеризация не
 * состоялась — это отказ прибора, а не отсутствие дефекта.
 */
async function inkMask(svg, t, box) {
  const i0 = Math.floor(box.x1 * MAG) - PAD, j0 = Math.floor(box.y1 * MAG) - PAD;
  const i1 = Math.ceil(box.x2 * MAG) + PAD, j1 = Math.ceil(box.y2 * MAG) + PAD;
  const w = i1 - i0, h = j1 - j0;

  const holder = document.createElementNS(NS, 'svg');
  holder.setAttribute('xmlns', NS);
  holder.setAttribute('viewBox', `${i0 / MAG} ${j0 / MAG} ${w / MAG} ${h / MAG}`);
  holder.setAttribute('width', String(w));
  holder.setAttribute('height', String(h));
  // defs и style тащим целиком: на них висят clip-path и градиенты
  for (const d of svg.querySelectorAll(':scope > defs, :scope > style'))
    holder.appendChild(d.cloneNode(true));

  const chain = [];
  for (let p = t; p && p !== svg; p = p.parentNode) chain.unshift(p);
  let cur = holder;
  for (const el of chain) {
    let c;
    if (el === t) {
      c = t.cloneNode(true);
      inlineStyle(t, c);
    } else {
      c = document.createElementNS(NS, el.tagName);
      for (const a of el.attributes) if (a.name !== 'style') c.setAttribute(a.name, a.value);
      const tr = getComputedStyle(el).transform;
      if (!el.hasAttribute('transform') && tr && tr !== 'none')
        c.setAttribute('style', 'transform:' + tr);
    }
    cur.appendChild(c);
    cur = c;
  }

  const src = 'data:image/svg+xml;charset=utf-8,' +
    encodeURIComponent(new XMLSerializer().serializeToString(holder));
  const img = new Image();
  await new Promise((res, rej) => {
    img.onload = res;
    img.onerror = () => rej(new Error('растеризация SVG не удалась'));
    img.src = src;
  });

  const cv = document.createElement('canvas');
  cv.width = w; cv.height = h;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  cx.drawImage(img, 0, 0, w, h);
  const data = cx.getImageData(0, 0, w, h).data;

  const m = new Uint8Array(w * h);
  let n = 0, x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  for (let k = 0; k < w * h; k++) {
    if (data[k * 4 + 3] < ALPHA_MIN) continue;
    m[k] = 1; n++;
    const x = k % w, y = (k - x) / w;
    if (x < x0) x0 = x;
    if (x > x1) x1 = x;
    if (y < y0) y0 = y;
    if (y > y1) y1 = y;
  }
  const ink = n ? {
    x1: +((i0 + x0) / MAG).toFixed(2), y1: +((j0 + y0) / MAG).toFixed(2),
    x2: +((i0 + x1 + 1) / MAG).toFixed(2), y2: +((j0 + y1 + 1) / MAG).toFixed(2),
  } : null;
  return { i0, j0, w, h, m, n, ink };
}

/** Число общих непрозрачных пикселей двух масок. Это и есть вердикт. */
function sharedInk(a, b) {
  const i0 = Math.max(a.i0, b.i0), i1 = Math.min(a.i0 + a.w, b.i0 + b.w);
  const j0 = Math.max(a.j0, b.j0), j1 = Math.min(a.j0 + a.h, b.j0 + b.h);
  let n = 0;
  for (let j = j0; j < j1; j++)
    for (let i = i0; i < i1; i++)
      if (a.m[(j - a.j0) * a.w + (i - a.i0)] && b.m[(j - b.j0) * b.w + (i - b.i0)]) n++;
  return n;
}

// ────────────────────────────────────────────────────────────────────────────
// Замер страницы
// ────────────────────────────────────────────────────────────────────────────

const short = t => t.textContent.trim().replace(/\s+/g, ' ').slice(0, 42);
const countIn = (pages, k) => pages.reduce((s, p) => s + p[k].length, 0);

/**
 * Кто именно вылезает вбок: элемент шире своего окна, у которого нет предка
 * с `overflow-x: auto|hidden`. Почти всегда это одно из трёх — неразрывный
 * токен (URL, путь, тикер), flex/grid-элемент с `min-width: auto`, широкая
 * таблица без `.table-scroll`.
 */
function culprits() {
  const out = [];
  for (const el of document.querySelectorAll('.content *')) {
    if (el.scrollWidth <= el.clientWidth + 1) continue;
    let clipped = false;
    for (let p = el.parentElement; p; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'hidden' || ox === 'scroll') { clipped = true; break; }
    }
    if (clipped) continue;
    out.push({
      tag: el.tagName.toLowerCase(), cls: el.className && String(el.className).slice(0, 40),
      scrollWidth: el.scrollWidth, clientWidth: el.clientWidth,
      text: (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40),
    });
  }
  return out;
}

/**
 * Замер уже загруженного документа.
 * `collisions` — вердикт (общий пиксель). `boxPairs` — кандидаты по рамкам,
 * они дефектом НЕ являются и нужны только чтобы видеть, что отсев работает.
 */
export async function measurePage(opts = {}) {
  const res = {
    file: opts.file || location.pathname.split('/').pop(),
    figures: 0, texts: 0, boxPairs: 0, legacyBoxPairs: 0, rastered: 0, inkPixels: 0,
    collisions: [], overflow: [], samples: [], htmlInSvg: 0, wide: [], warnings: [],
  };
  // Горизонтальная прокрутка страницы. Сравнение — с clientWidth, а не с
  // innerWidth: innerWidth включает полосу прокрутки и прячет переполнения
  // в 2–15 px, самые частые.
  const de = document.documentElement;
  res.pageScroll = de.scrollWidth > de.clientWidth;
  if (res.pageScroll) res.wide = culprits().slice(0, 6);
  for (const [si, svg] of figureSvgs().entries()) {
    const scm = svg.getScreenCTM();
    if (!scm) { res.warnings.push({ fig: si + 1, why: 'getScreenCTM() = null' }); continue; }
    const toVB = scm.inverse();
    const vb = svg.viewBox.baseVal;
    const ts = textNodes(svg);
    res.figures++;
    res.texts += ts.length;
    res.htmlInSvg += [...svg.querySelectorAll('text')]
      .filter(t => t.querySelector('b,i,strong,em,br')).length;

    const boxes = ts.map(t => ({ t, box: emBox(svg, t, toVB), txt: short(t) }));
    const need = new Set(), pairs = [];
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i].box, b = boxes[j].box;
        const ox = Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1);
        const oy = Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1);
        if (ox <= 0 || oy <= 0) continue;
        pairs.push([i, j, +ox.toFixed(2), +oy.toFixed(2)]);
        need.add(i); need.add(j);
        if (ox > 3 && oy > 3) res.legacyBoxPairs++;   // прежний, негодный вердикт §7
      }
    const ovf = [];
    boxes.forEach((o, i) => {
      const b = o.box;
      if (b.x1 < -2 || b.y1 < -2 || b.x2 > vb.width + 2 || b.y2 > vb.height + 2) {
        ovf.push(i); need.add(i);
      }
    });
    res.boxPairs += pairs.length;

    const masks = new Map();
    for (const i of need) {
      try {
        const m = await inkMask(svg, boxes[i].t, boxes[i].box);
        masks.set(i, m);
        res.rastered++;
        res.inkPixels += m.n;
        if (!m.n) res.warnings.push({
          fig: si + 1, txt: boxes[i].txt,
          why: 'растеризация дала ноль чернил — прибор на этом узле не доказан',
        });
      } catch (e) {
        res.warnings.push({ fig: si + 1, txt: boxes[i].txt, why: String(e.message || e) });
      }
    }

    for (const [i, j, ox, oy] of pairs) {
      const A = masks.get(i), B = masks.get(j);
      if (!A || !B) continue;
      const shared = sharedInk(A, B);
      const rec = {
        fig: si + 1, a: boxes[i].txt, b: boxes[j].txt,
        boxOverlap: { x: ox, y: oy }, inkA: A.n, inkB: B.n, sharedInk: shared,
      };
      if (shared > 0) res.collisions.push(rec);
      else if (res.samples.length < SAMPLES) res.samples.push(rec);
    }

    for (const i of ovf) {
      const A = masks.get(i);
      if (!A || !A.ink) continue;
      const k = A.ink;
      const out = Math.max(-k.x1, -k.y1, k.x2 - vb.width, k.y2 - vb.height);
      if (out > OVERFLOW_TOL)
        res.overflow.push({ fig: si + 1, txt: boxes[i].txt, outUnits: +out.toFixed(2), ink: k });
    }
  }
  return res;
}

// ────────────────────────────────────────────────────────────────────────────
// Доказательство живости
// ────────────────────────────────────────────────────────────────────────────

/**
 * Портит геометрию в памяти и требует от прибора обоих ответов:
 *  · положительный — сдвиг на 2 единицы обязан дать общий пиксель;
 *  · отрицательный — сдвиг на высоту чернил + 0,5 обязан дать кандидата
 *    по рамкам и НОЛЬ общих пикселей (это и есть соседние строки подписи).
 * Без обеих половин пустой результат прогона ничего не доказывает.
 */
export async function liveness() {
  const svgs = figureSvgs();
  if (!svgs.length) return { ok: false, why: 'нет фигур' };
  const svg = svgs[0];
  const toVB = svg.getScreenCTM().inverse();
  const ts = textNodes(svg);
  if (!ts.length) return { ok: false, why: 'нет подписей в первой фигуре' };
  const t = ts.reduce((a, b) => (b.textContent.trim().length > a.textContent.trim().length ? b : a));

  const baseBox = emBox(svg, t, toVB);
  const baseMask = await inkMask(svg, t, baseBox);
  if (!baseMask.n) return { ok: false, why: 'растеризация опорной подписи дала ноль чернил' };
  const inkH = +(baseMask.ink.y2 - baseMask.ink.y1).toFixed(2);

  async function probe(shift) {
    const g = document.createElementNS(NS, 'g');
    g.setAttribute('transform', `translate(0 ${shift})`);
    g.appendChild(t.cloneNode(true));
    t.parentNode.appendChild(g);
    try {
      const c = g.firstChild;
      const box = emBox(svg, c, toVB);
      const oy = Math.min(baseBox.y2, box.y2) - Math.max(baseBox.y1, box.y1);
      const ox = Math.min(baseBox.x2, box.x2) - Math.max(baseBox.x1, box.x1);
      const mask = await inkMask(svg, c, box);
      return {
        shiftUnits: shift,
        boxOverlap: { x: +ox.toFixed(2), y: +oy.toFixed(2) },
        isCandidate: ox > 0 && oy > 0,
        inkPixels: mask.n,
        sharedInk: sharedInk(baseMask, mask),
      };
    } finally { g.remove(); }
  }

  const positive = await probe(2);
  const negative = await probe(+(inkH + 0.5).toFixed(2));
  const ok = positive.sharedInk > 0 && negative.isCandidate && negative.sharedInk === 0;
  return {
    ok, figure: 1, text: short(t),
    emBoxHeight: +(baseBox.y2 - baseBox.y1).toFixed(2),
    inkHeight: inkH,
    inkPixels: baseMask.n,
    positive, negative,
    why: ok ? null : 'контроль живости не сошёлся — результату прогона верить нельзя',
  };
}

// ────────────────────────────────────────────────────────────────────────────
// Самопроверка на эталоне
// ────────────────────────────────────────────────────────────────────────────

export const FIXTURE = 'tools/fixtures/geometry-collision.html';

/**
 * Что эталон обязан дать. Числа выверены по самому эталону; правите его —
 * правьте и эту таблицу. Ширина на них не влияет: наложения в рис. Э.1
 * сделаны с запасом, а просвет в рис. Э.2 — около единицы viewBox.
 */
export const SELFTEST_EXPECT = { boxPairs: 3, collisions: 2, cleanCandidates: 1 };

/**
 * Красный и зелёный на одной странице: прибор обязан зажечься на двух парах
 * с общими глифами и промолчать на паре, у которой пересекаются только рамки.
 */
export async function selftest(url = FIXTURE) {
  const here = location.pathname.endsWith(url.split('/').pop());
  let r;
  if (here) {
    r = await measurePage({ file: url });
  } else {
    const host = document.querySelector('article.prose');
    if (!host) return { ok: false, why: 'некуда подставить эталон: нет article.prose' };
    const keep = host.innerHTML;
    try {
      const html = await (await fetch(url, { cache: 'no-store' })).text();
      const art = new DOMParser().parseFromString(html, 'text/html').querySelector('article.prose');
      if (!art) return { ok: false, why: 'эталон не разобрался: ' + url };
      host.innerHTML = art.innerHTML;
      document.body.getBoundingClientRect();
      await new Promise(res => setTimeout(res, 0));
      r = await measurePage({ file: url });
    } catch (e) {
      return { ok: false, why: String((e && e.message) || e) };
    } finally { host.innerHTML = keep; }
  }
  const got = {
    boxPairs: r.boxPairs,
    collisions: r.collisions.length,
    cleanCandidates: r.boxPairs - r.collisions.length,
  };
  const ok = got.boxPairs === SELFTEST_EXPECT.boxPairs &&
             got.collisions === SELFTEST_EXPECT.collisions &&
             got.cleanCandidates === SELFTEST_EXPECT.cleanCandidates &&
             r.collisions.every(c => c.sharedInk > 0) &&
             !r.warnings.length;
  return {
    ok, file: url, expect: SELFTEST_EXPECT, got,
    legacyBoxPairs: r.legacyBoxPairs,   // прежний вердикт §7: ловит и невиновную пару
    red: r.collisions.map(c => ({ a: c.a, b: c.b, sharedInk: c.sharedInk })),
    green: r.samples.map(c => ({ a: c.a, b: c.b, boxOverlapY: c.boxOverlap.y, sharedInk: c.sharedInk })),
    warnings: r.warnings,
    why: ok ? null : 'эталон разошёлся с таблицей — прибору верить нельзя',
  };
}

// ────────────────────────────────────────────────────────────────────────────
// Прогоны
// ────────────────────────────────────────────────────────────────────────────

/** Одна открытая страница: предохранитель + живость + замер. */
export async function run(opts = {}) {
  const pre = preflight();
  if (!pre.ok && !opts.force)
    return { version: VERSION, ok: false, abort: pre.reasons, env: pre.env };
  const live = await liveness();
  const page = await measurePage(opts);
  return {
    version: VERSION, env: pre.env, liveness: live, page,
    ok: live.ok && !page.collisions.length && !page.overflow.length &&
        !page.warnings.length && !page.htmlInSvg && !page.pageScroll,
  };
}

/**
 * Прогон нескольких глав без перезагрузки: содержимое `article.prose`
 * подменяется на разобранное из ответа сервера. Документ остаётся
 * верхнеуровневым и той же ширины, поэтому раскладка не схлопывается —
 * в отличие от iframe. Равносильность подмены и настоящего перехода
 * обязана быть проверена (`STYLE-GUIDE.md` §7, «сверка способа»).
 */
export async function sweep(files, opts = {}) {
  const pre = preflight();
  if (!pre.ok && !opts.force)
    return { version: VERSION, ok: false, abort: pre.reasons, env: pre.env };
  const host = document.querySelector('article.prose');
  if (!host) return { version: VERSION, ok: false, abort: ['нет article.prose'] };

  const out = {
    version: VERSION, env: pre.env,
    selftest: opts.skipSelftest ? null : await selftest(),
    liveness: await liveness(),
    pages: [],
  };
  const keep = host.innerHTML;
  try {
    for (const f of files) {
      let doc = null;
      try {
        const html = await (await fetch(f, { cache: 'no-store' })).text();
        doc = new DOMParser().parseFromString(html, 'text/html');
      } catch (e) {
        out.pages.push({ file: f, error: String(e.message || e) });
        continue;
      }
      // Страница без графики (обложка, errata) — не отказ, а нулевой замер.
      if (!doc.querySelector('figure.figure svg')) {
        out.pages.push({
          file: f, figures: 0, texts: 0, boxPairs: 0, legacyBoxPairs: 0, rastered: 0,
          inkPixels: 0, collisions: [], overflow: [], samples: [], htmlInSvg: 0,
          wide: [], pageScroll: false, warnings: [], ms: 0, note: 'графики нет',
        });
        if (opts.onPage) opts.onPage(f, out.pages.length);
        continue;
      }
      const art = doc.querySelector('article.prose');
      if (!art) { out.pages.push({ file: f, error: 'есть графика, но нет article.prose' }); continue; }
      host.innerHTML = art.innerHTML;
      // Раскладку доводим принудительным чтением и макрозадачей, а НЕ
      // requestAnimationFrame: в скрытой вкладке кадры не композитятся,
      // и rAF не вызывается никогда — прогон висит без единой ошибки.
      document.body.getBoundingClientRect();
      await new Promise(r => setTimeout(r, 0));
      const t0 = performance.now();
      const page = await measurePage({ file: f });
      page.ms = Math.round(performance.now() - t0);
      out.pages.push(page);
      if (opts.onPage) opts.onPage(f, out.pages.length);
    }
  } finally {
    host.innerHTML = keep;
  }

  const live = out.pages.filter(p => !p.error);
  const sum = k => live.reduce((s, p) => s + p[k], 0);
  out.totals = {
    pages: out.pages.length, failed: out.pages.length - live.length,
    figures: sum('figures'), texts: sum('texts'),
    boxPairs: sum('boxPairs'), legacyBoxPairs: sum('legacyBoxPairs'),
    rastered: sum('rastered'), inkPixels: sum('inkPixels'),
    collisions: countIn(live, 'collisions'), overflow: countIn(live, 'overflow'),
    htmlInSvg: sum('htmlInSvg'), warnings: countIn(live, 'warnings'),
    pageScroll: live.filter(p => p.pageScroll).length,
  };
  out.collisions = live.flatMap(p => p.collisions.map(c => ({ file: p.file, ...c })));
  out.overflow = live.flatMap(p => p.overflow.map(c => ({ file: p.file, ...c })));
  out.warnings = live.flatMap(p => p.warnings.map(c => ({ file: p.file, ...c })));
  out.wide = live.filter(p => p.pageScroll).map(p => ({ file: p.file, wide: p.wide }));
  out.ok = out.liveness.ok && (!out.selftest || out.selftest.ok) &&
           !out.totals.collisions && !out.totals.overflow && !out.totals.pageScroll &&
           !out.totals.warnings && !out.totals.htmlInSvg && !out.totals.failed;
  return out;
}

// ────────────────────────────────────────────────────────────────────────────
// Фоновый прогон: вызов из консоли не переживает всю книгу за один ответ
// ────────────────────────────────────────────────────────────────────────────

let job = null;

/** Запускает `sweep` в фоне. Результат забирать `pollSweep()`. */
export function startSweep(files, opts = {}) {
  if (job && !job.done) return { started: false, why: 'прогон уже идёт', progress: job.progress };
  const j = job = { done: false, out: null, error: null, progress: { total: files.length, done: 0, file: null } };
  sweep(files, { ...opts, onPage: (f, n) => { j.progress.done = n; j.progress.file = f; } })
    .then(o => { j.out = o; })
    .catch(e => { j.error = String((e && e.message) || e); })
    .finally(() => { j.done = true; });
  return { started: true, total: files.length };
}

/** Короткая сводка прогона; `{full: true}` — со всеми страницами. */
export function pollSweep(opts = {}) {
  if (!job) return { state: 'прогона не было' };
  if (!job.done) return { state: 'идёт', progress: job.progress };
  if (job.error) return { state: 'отказ', error: job.error };
  const o = job.out;
  return {
    state: 'готово', ok: o.ok, env: o.env, selftest: o.selftest, liveness: o.liveness, totals: o.totals,
    collisions: o.collisions, overflow: o.overflow, warnings: o.warnings, wide: o.wide,
    pages: opts.full ? o.pages.map(p => ({
      file: p.file, error: p.error, figures: p.figures, texts: p.texts,
      boxPairs: p.boxPairs, legacyBoxPairs: p.legacyBoxPairs, rastered: p.rastered,
      inkPixels: p.inkPixels, collisions: p.collisions && p.collisions.length,
      ms: p.ms,
    })) : undefined,
    samples: o.pages.flatMap(p => (p.samples || []).map(s => ({ file: p.file, ...s }))).slice(0, 6),
  };
}
