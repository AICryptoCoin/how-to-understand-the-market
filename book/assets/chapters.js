/* Единый реестр глав книги.
   ЕДИНСТВЕННОЕ место, где правится оглавление: боковая панель, навигация
   «предыдущая/следующая», прогресс на обложке, хлебные крошки и все
   перекрёстные ссылки строятся отсюда.

   ─────────────────────────────────────────────────────────────────────────
   НОМЕР ГЛАВЫ НЕ ХРАНИТСЯ. Он равен позиции в массиве плюс один и считается
   на старте в book.js. Настоящий идентификатор главы — поле `id` (слаг):
   оно не меняется никогда, даже когда глава переезжает на другое место.
   Поэтому вставка новой главы в середину книги — это одна строка здесь,
   и ни одна ссылка от этого не ломается.

   Правила правки:
     · порядок массива = порядок книги, менять его — значит перенумеровать книгу;
     · `id` уникален и вечен; в разметке главы он стоит в <body data-chapter-id>;
     · `part` ссылается на `id` части из BOOK_PARTS;
     · `file` — имя файла без числового префикса;
     · написал главу — переключи `status` на "done".
   ───────────────────────────────────────────────────────────────────────── */

window.BOOK_PARTS = [
  { id: "zachem",       label: "Часть 0",     title: "Зачем" },
  { id: "cikl",         label: "Часть I",     title: "Экономика и цикл: что измеряем и чему верим" },
  { id: "predlozhenie", label: "Часть II",    title: "Предложение и рост" },
  { id: "spros",        label: "Часть III",   title: "Спрос и разрыв" },
  { id: "dvigatel",     label: "Часть IV",    title: "Двигатель цикла: H-O-P-E" },
  { id: "inflyaciya",   label: "Часть V",     title: "Инфляция" },
  { id: "dengi-cb",     label: "Часть VI",    title: "Деньги и центральный банк" },
  { id: "stavki",       label: "Часть VII",   title: "Ставки и кривая" },
  { id: "vodoprovod",   label: "Часть VIII",  title: "Денежный водопровод" },
  { id: "fiskal",       label: "Часть IX",    title: "Фискальная политика и долг" },
  { id: "kredit",       label: "Часть X",     title: "Кредитный цикл и финансовая нестабильность" },
  { id: "otkrytaya",    label: "Часть XI",    title: "Открытая экономика и долларовая система" },
  { id: "metod",        label: "Часть XII",   title: "Эмпирический метод" },
  { id: "rynki",        label: "Часть XIII",  title: "Рынки — как это торгуется" },
  { id: "sintez",       label: "Часть XIV",   title: "Синтез — сама шпаргалка" },
  { id: "istoriya",     label: "Часть XV",    title: "История как лаборатория" },
  { id: "most",         label: "Часть XVI",   title: "Мост к разработке" },
  // ВРЕМЕННО. Первая глава новой постановки. Реестр перестраивается
  // при сверке с написанным (PROGRESS.md §6, пункт 7); до тех пор
  // новая глава живёт здесь, чтобы приборы её видели и не считали сиротой.
  { id: "novaya-rabota", label: "Часть XVII",  title: "Научная работа: как отличают прогноз от угадывания" },
];

window.BOOK_CHAPTERS = [
  /* ── Часть 0. Зачем ─────────────────────────────────────────────────── */
  { id: "karta",                part: "zachem",       file: "karta-vmesto-prognoza.html",  title: "Карта вместо прогноза",                                    status: "done" },
  { id: "chto-takoe-makro",     part: "zachem",       file: "chto-takoe-makro.html",       title: "Что такое макроэкономика и почему в ней спорят",           status: "done" },

  /* ── Часть I. Экономика и цикл ──────────────────────────────────────── */
  { id: "vvp",                  part: "cikl",         file: "ekonomika-kak-potok.html",    title: "Экономика как поток: ВВП",                                 status: "done" },
  { id: "biznes-cikl",          part: "cikl",         file: "biznes-cikl.html",            title: "Бизнес-цикл и иерархия циклов",                            status: "done" },
  { id: "kak-chitat-empiriku",  part: "cikl",         file: "kak-chitat-empiriku.html",    title: "Как читать эмпирическое утверждение",                      status: "done" },

  /* ── Часть II. Предложение и рост ───────────────────────────────────── */
  { id: "rost-proizvoditelnost",part: "predlozhenie", file: "rost-proizvoditelnost.html",  title: "Откуда берётся рост: производительность и капитал",        status: "done" },
  { id: "demografiya",          part: "predlozhenie", file: "demografiya.html",            title: "Демография и предложение труда",                           status: "done" },
  { id: "energiya",             part: "predlozhenie", file: "energiya.html",               title: "Энергия как макро-переменная",                             status: "done" },
  { id: "cepochki-postavok",    part: "predlozhenie", file: "cepochki-postavok.html",      title: "Цепочки поставок и шоки предложения",                      status: "done" },

  /* ── Часть III. Спрос и разрыв ──────────────────────────────────────── */
  { id: "as-ad",                part: "spros",        file: "as-ad.html",                  title: "Совокупный спрос и совокупное предложение",                status: "done" },
  { id: "razryv-vypuska",       part: "spros",        file: "razryv-vypuska.html",         title: "Потенциальный выпуск и разрыв выпуска",                    status: "done" },

  /* ── Часть IV. Двигатель цикла: H-O-P-E ─────────────────────────────── */
  { id: "hope",                 part: "dvigatel",     file: "hope.html",                   title: "H-O-P-E: скелет опережения",                               status: "done" },
  { id: "zhilyo",               part: "dvigatel",     file: "zhilyo.html",                 title: "Жильё — первое звено",                                     status: "done" },
  { id: "zakazy",               part: "dvigatel",     file: "zakazy-proizvodstvo.html",    title: "Заказы, производство, запасы",                             status: "done" },
  { id: "pribyl",               part: "dvigatel",     file: "pribyl.html",                 title: "Прибыль корпораций",                                       status: "done" },
  { id: "trud",                 part: "dvigatel",     file: "trud-i-potrebitel.html",      title: "Труд, доходы и потребитель",                               status: "done" },

  /* ── Часть V. Инфляция ──────────────────────────────────────────────── */
  { id: "phillips",             part: "inflyaciya",   file: "phillips.html",               title: "Кривая Филлипса: подъём, провал и современные версии",     status: "todo" },
  { id: "ozhidaniya",           part: "inflyaciya",   file: "ozhidaniya.html",             title: "Ожидания: адаптивные, рациональные, заякоренные",          status: "todo" },
  { id: "ceny",                 part: "inflyaciya",   file: "ceny-i-inflyaciya.html",      title: "Цены и инфляция: CPI, PCE, PPI",                           status: "done" },
  { id: "shok-spros-predlozhenie", part: "inflyaciya",file: "shok-spros-predlozhenie.html",title: "Как отличить шок спроса от шока предложения",              status: "todo" },

  /* ── Часть VI. Деньги и центральный банк ────────────────────────────── */
  { id: "dengi",                part: "dengi-cb",     file: "dengi-i-kredit.html",         title: "Деньги, кредит и ликвидность",                             status: "done" },
  { id: "frs-ustroystvo",       part: "dengi-cb",     file: "frs-ustroystvo.html",         title: "ФРС: устройство и каналы",                                 status: "done" },
  { id: "r-star",               part: "dengi-cb",     file: "r-star.html",                 title: "Естественная ставка r*: Викселль, HLW, LW",                status: "todo" },
  { id: "taylor",               part: "dengi-cb",     file: "taylor.html",                 title: "Правило Тейлора и пределы правил",                         status: "todo" },
  { id: "kak-chitat-frs",       part: "dengi-cb",     file: "kak-chitat-frs.html",         title: "Как читать ФРС",                                           status: "done" },

  /* ── Часть VII. Ставки и кривая ─────────────────────────────────────── */
  { id: "krivaya-mehanika",     part: "stavki",       file: "krivaya-mehanika.html",       title: "Кривая доходности: механика",                              status: "done" },
  { id: "premiya-za-srok",      part: "stavki",       file: "premiya-za-srok.html",        title: "Временна́я структура и премия за срок",                     status: "todo" },
  { id: "formy-krivoy",         part: "stavki",       file: "formy-i-realnye-stavki.html", title: "Формы, режимы и реальные ставки",                          status: "done" },

  /* ── Часть VIII. Денежный водопровод ────────────────────────────────── */
  { id: "koridor-i-pol",        part: "vodoprovod",   file: "koridor-i-pol.html",          title: "Коридор и пол: как ФРС на самом деле задаёт ставку",       status: "todo" },
  { id: "repo-sofr",            part: "vodoprovod",   file: "repo-sofr.html",              title: "Репо, обеспечение и SOFR; сентябрь 2019",                  status: "todo" },
  { id: "qt-i-likvidnost",      part: "vodoprovod",   file: "qt-i-likvidnost.html",        title: "Баланс ФРС как переменная: QT, RRP, TGA, «чистая ликвидность»", status: "todo" },
  { id: "dilery",               part: "vodoprovod",   file: "dilery.html",                 title: "Дилеры и ёмкость посредничества",                          status: "todo" },

  /* ── Часть IX. Фискальная политика и долг ───────────────────────────── */
  { id: "multiplikatory",       part: "fiskal",       file: "multiplikatory.html",         title: "Фискальные мультипликаторы",                               status: "todo" },
  { id: "dolgovaya-dinamika",   part: "fiskal",       file: "dolgovaya-dinamika.html",     title: "Долговая динамика: r против g",                            status: "todo" },
  { id: "fiskalnoe-dominirovanie", part: "fiskal",    file: "fiskalnoe-dominirovanie.html",title: "Фискальное доминирование",                                 status: "todo" },
  { id: "qra",                  part: "fiskal",       file: "qra.html",                    title: "Казначейство как рыночный фактор: QRA и структура выпуска",status: "todo" },

  /* ── Часть X. Кредитный цикл и финансовая нестабильность ────────────── */
  { id: "minsky",               part: "kredit",       file: "minsky.html",                 title: "Кредитный цикл: Мински и финансовый акселератор",          status: "todo" },
  { id: "deleveridzh",          part: "kredit",       file: "deleveridzh.html",            title: "Леверидж и делеверидж",                                    status: "todo" },
  { id: "kreditnye-spredy",     part: "kredit",       file: "kreditnye-spredy.html",       title: "Кредитные спреды как система",                             status: "todo" },
  { id: "tenevoy-banking",      part: "kredit",       file: "tenevoy-banking.html",        title: "Теневой банкинг и небанковское посредничество",            status: "todo" },
  { id: "mart-2023",            part: "kredit",       file: "mart-2023.html",              title: "Март 2023: банковский стресс как урок",                    status: "todo" },

  /* ── Часть XI. Открытая экономика и долларовая система ──────────────── */
  { id: "valyutnyy-kurs",       part: "otkrytaya",    file: "valyutnyy-kurs.html",         title: "Валютный курс: почему паритет процентных ставок не работает", status: "todo" },
  { id: "potoki-kapitala",      part: "otkrytaya",    file: "potoki-kapitala.html",        title: "Потоки капитала и глобальный финансовый цикл",             status: "todo" },
  { id: "dollarovaya-sistema",  part: "otkrytaya",    file: "dollarovaya-sistema.html",    title: "Долларовая система и дилемма Триффина",                    status: "todo" },
  { id: "kitay",                part: "otkrytaya",    file: "kitay.html",                  title: "Китай как макро-объект",                                   status: "todo" },
  { id: "ecb-boj",              part: "otkrytaya",    file: "ecb-boj.html",                title: "ЕЦБ и Банк Японии: два не-Фед'а",                          status: "todo" },
  { id: "em",                   part: "otkrytaya",    file: "em.html",                     title: "Развивающиеся рынки",                                      status: "todo" },

  /* ── Часть XII. Эмпирический метод ──────────────────────────────────── */
  { id: "proverka-utverzhdeniya", part: "metod",      file: "proverka-utverzhdeniya.html", title: "Что значит проверить макро-утверждение",                   status: "done" },
  { id: "stacionarnost",        part: "metod",        file: "stacionarnost.html",          title: "Стационарность, ложная регрессия, коинтеграция",           status: "done" },
  { id: "lid-lag",              part: "metod",        file: "lid-lag.html",                title: "Лид-лаг: оценка и её неустойчивость",                      status: "done" },
  { id: "strukturnye-razryvy",  part: "metod",        file: "strukturnye-razryvy.html",    title: "Структурные разрывы и режимы",                             status: "done" },
  { id: "vne-vyborki",          part: "metod",        file: "vne-vyborki.html",            title: "Проверка вне выборки и множественность гипотез",           status: "done" },
  { id: "real-taym",            part: "metod",        file: "real-taym.html",              title: "Реал-тайм против пересмотренного",                         status: "done" },

  /* ── Часть XIII. Рынки — как это торгуется ──────────────────────────── */
  { id: "mezhrynochnyy",        part: "rynki",        file: "mezhrynochnyy-analiz.html",   title: "Межрыночный анализ",                                       status: "done" },
  { id: "dollar-zoloto",        part: "rynki",        file: "dollar-zoloto-syryo.html",    title: "Доллар, золото, сырьё",                                    status: "done" },
  { id: "faktory",              part: "rynki",        file: "faktory.html",                title: "Факторы и факторная ротация",                              status: "done" },
  { id: "sentiment",            part: "rynki",        file: "sentiment.html",              title: "Сентимент, широта, позиционирование",                      status: "done" },

  /* ── Часть XIV. Синтез — сама шпаргалка ─────────────────────────────── */
  { id: "evolyuciya",           part: "sintez",       file: "evolyuciya-shpargalki.html",  title: "Эволюция шпаргалки",                                       status: "done" },
  { id: "anatomiya",            part: "sintez",       file: "anatomiya-shpargalki.html",   title: "Анатомия шпаргалки",                                       status: "done" },
  { id: "framework",            part: "sintez",       file: "framework.html",              title: "Framework макро-трейдера",                                 status: "done" },

  /* ── Часть XV. История как лаборатория ──────────────────────────────── */
  { id: "protokol-epizoda",     part: "istoriya",     file: "protokol-epizoda.html",       title: "Как читать исторический эпизод",                           status: "todo" },
  { id: "1970e",                part: "istoriya",     file: "1970e.html",                  title: "1970-е: великая инфляция и Волкер",                        status: "todo" },
  { id: "velikoe-smyagchenie",  part: "istoriya",     file: "velikoe-smyagchenie.html",    title: "Великое смягчение",                                        status: "todo" },
  { id: "2008",                 part: "istoriya",     file: "2008.html",                   title: "2008: кредитный кризис",                                   status: "todo" },
  { id: "zirp",                 part: "istoriya",     file: "zirp.html",                   title: "Десятилетие нулевых ставок",                               status: "todo" },
  { id: "kovid",                part: "istoriya",     file: "kovid.html",                  title: "Ковид: остановка и заливка",                               status: "todo" },
  { id: "inflyaciya-2021",      part: "istoriya",     file: "inflyaciya-2021.html",        title: "Инфляция 2021–2023 и мягкая посадка, которой не ждали",    status: "todo" },
  { id: "itog-istorii",         part: "istoriya",     file: "itog-istorii.html",           title: "Что часы пережили и что мы меняем",                        status: "todo" },

  /* ── Часть XVI. Мост к разработке ───────────────────────────────────── */
  { id: "kripta",               part: "most",         file: "kripta-kak-makro-aktiv.html", title: "Крипта как макро-актив",                                   status: "done" },
  { id: "istochniki",           part: "most",         file: "istochniki-dannyh.html",      title: "Источники данных и гигиена",                               status: "done" },
  { id: "k-kodu",               part: "most",         file: "ot-shpargalki-k-kodu.html",   title: "От шпаргалки к коду",                                      status: "done" },
  { id: "ocenochnaya-funkciya", part: "novaya-rabota", file: "ocenochnaya-funkciya.html",  title: "Правильная оценочная функция",                             status: "done" },
];
