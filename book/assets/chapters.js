/* Единый реестр глав книги.
   ЕДИНСТВЕННОЕ место, где правится оглавление: боковая панель, навигация
   «предыдущая/следующая», прогресс на обложке и хлебные крошки строятся отсюда.
   Написал главу — переключи её status на "done". */

window.BOOK_PARTS = [
  { id: 0, label: "Часть 0", title: "Зачем" },
  { id: 1, label: "Часть I", title: "Фундамент" },
  { id: 2, label: "Часть II", title: "Двигатель цикла — макро-индикаторы" },
  { id: 3, label: "Часть III", title: "ФРС и ставки — вертикальная ось" },
  { id: 4, label: "Часть IV", title: "Рынки — как это торгуется" },
  { id: 5, label: "Часть V", title: "Синтез — сама шпаргалка" },
  { id: 6, label: "Часть VI", title: "Мост к нашей разработке" },
];

window.BOOK_CHAPTERS = [
  { n:  1, part: 0, file: "ch01-karta-vmesto-prognoza.html", title: "Карта вместо прогноза",              status: "done" },

  { n:  2, part: 1, file: "ch02-ekonomika-kak-potok.html",   title: "Экономика как поток: ВВП",           status: "done" },
  { n:  3, part: 1, file: "ch03-biznes-cikl.html",           title: "Бизнес-цикл и иерархия циклов",      status: "done" },
  { n:  4, part: 1, file: "ch04-dengi-i-kredit.html",        title: "Деньги, кредит и ликвидность",       status: "todo" },

  { n:  5, part: 2, file: "ch05-hope.html",                  title: "H-O-P-E: скелет опережения",         status: "done" },
  { n:  6, part: 2, file: "ch06-zhilyo.html",                title: "Жильё — первое звено",               status: "done" },
  { n:  7, part: 2, file: "ch07-zakazy-proizvodstvo.html",   title: "Заказы, производство, запасы",       status: "todo" },
  { n:  8, part: 2, file: "ch08-pribyl.html",                title: "Прибыль корпораций",                 status: "todo" },
  { n:  9, part: 2, file: "ch09-trud-i-potrebitel.html",     title: "Труд, доходы и потребитель",         status: "todo" },
  { n: 10, part: 2, file: "ch10-ceny-i-inflyaciya.html",     title: "Цены и инфляция",                    status: "todo" },

  { n: 11, part: 3, file: "ch11-frs-ustroystvo.html",        title: "ФРС: устройство и каналы",           status: "todo" },
  { n: 12, part: 3, file: "ch12-kak-chitat-frs.html",        title: "Как читать ФРС",                     status: "todo" },
  { n: 13, part: 3, file: "ch13-krivaya-mehanika.html",      title: "Кривая доходности: механика",        status: "todo" },
  { n: 14, part: 3, file: "ch14-formy-i-realnye-stavki.html",title: "Формы, режимы и реальные ставки",    status: "todo" },

  { n: 15, part: 4, file: "ch15-mezhrynochnyy-analiz.html",  title: "Межрыночный анализ",                 status: "todo" },
  { n: 16, part: 4, file: "ch16-dollar-zoloto-syryo.html",   title: "Доллар, золото, сырьё",              status: "todo" },
  { n: 17, part: 4, file: "ch17-faktory.html",               title: "Факторы и факторная ротация",        status: "todo" },
  { n: 18, part: 4, file: "ch18-sentiment.html",             title: "Сентимент, широта, позиционирование",status: "todo" },

  { n: 19, part: 5, file: "ch19-evolyuciya-shpargalki.html", title: "Эволюция шпаргалки",                 status: "todo" },
  { n: 20, part: 5, file: "ch20-anatomiya-shpargalki.html",  title: "Анатомия шпаргалки",                 status: "todo" },
  { n: 21, part: 5, file: "ch21-framework.html",             title: "Framework макро-трейдера",           status: "todo" },

  { n: 22, part: 6, file: "ch22-kripta-kak-makro-aktiv.html",title: "Крипта как макро-актив",             status: "todo" },
  { n: 23, part: 6, file: "ch23-istochniki-dannyh.html",     title: "Источники данных и гигиена",         status: "todo" },
  { n: 24, part: 6, file: "ch24-ot-shpargalki-k-kodu.html",  title: "От шпаргалки к коду",                status: "todo" },
];
