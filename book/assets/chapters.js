/* Единый реестр глав новой книги.
   Номер главы не хранится: это позиция записи в BOOK_CHAPTERS плюс один.
   Полный порядок и названия берутся из MASTER-PLAN.md.
*/

window.BOOK_PARTS = [
  { id: "zachem-kniga",           label: "Часть 0",   title: "Зачем эта книга" },
  { id: "yazyk-neopredelennosti", label: "Часть I",   title: "Язык неопределённости" },
  { id: "ocenka-prognoza",        label: "Часть II",  title: "Как отличить хороший прогноз от удачного" },
  { id: "kanal-sprosa",           label: "Часть III", title: "Спрос" },
  { id: "kanal-predlozheniya",    label: "Часть IV",  title: "Предложение" },
  { id: "kanal-politiki",         label: "Часть V",   title: "Политика" },
  { id: "kanal-kredita",          label: "Часть VI",  title: "Кредит" },
  { id: "vneshniy-kontur",        label: "Часть VII", title: "Внешний контур" },
  { id: "rynki-otklik",           label: "Часть VIII", title: "Рынки — то, что мы объясняем" },
  { id: "realnoe-vremya",         label: "Часть IX",  title: "Реальное время" },
  { id: "panelnaya-lovushka",     label: "Часть X",   title: "Панель стран и её ловушка" },
  { id: "kriterii-rezultata",     label: "Часть XI",  title: "Что считается результатом" },
  { id: "pribor-sistema",         label: "Часть XII", title: "Прибор" },
  { id: "kripta-granica",         label: "Часть XIII", title: "Крипта" },
  { id: "izmerennye-rezultaty",   label: "Часть XIV", title: "Что измерено" },
];

window.BOOK_CHAPTERS = [
  /* ── Часть 0. Зачем эта книга ───────────────────────────────────────── */
  { id: "prognoz-proverka", part: "zachem-kniga", file: "prognoz-proverka.html", title: "Прогноз, который нельзя проверить", status: "todo" },
  { id: "shirina-tunnelya", part: "zachem-kniga", file: "shirina-tunnelya.html", title: "Ширина туннеля вместо его конца", status: "todo" },
  { id: "berri-metod", part: "zachem-kniga", file: "berri-metod.html", title: "Что делал Бёрри и чего он не делал", status: "todo" },

  /* ── Часть I. Язык неопределённости ─────────────────────────────────── */
  { id: "raspredelenie-chislo", part: "yazyk-neopredelennosti", file: "raspredelenie-chislo.html", title: "Распределение, а не число", status: "todo" },
  { id: "hvosty-raspredeleniya", part: "yazyk-neopredelennosti", file: "hvosty-raspredeleniya.html", title: "Хвосты", status: "todo" },
  { id: "uslovnoe-raspredelenie", part: "yazyk-neopredelennosti", file: "uslovnoe-raspredelenie.html", title: "Условное распределение", status: "todo" },
  { id: "sravnenie-raspredeleniy", part: "yazyk-neopredelennosti", file: "sravnenie-raspredeleniy.html", title: "Чем распределения сравнивают", status: "todo" },

  /* ── Часть II. Как отличить хороший прогноз от удачного ─────────────── */
  { id: "ocenochnaya-funkciya", part: "ocenka-prognoza", file: "ocenochnaya-funkciya.html", title: "Правильная оценочная функция", status: "done" },
  { id: "bazovyy-sopernik", part: "ocenka-prognoza", file: "bazovyy-sopernik.html", title: "Базовый соперник «ничего не знаю»", status: "todo" },
  { id: "cena-sopernik", part: "ocenka-prognoza", file: "cena-sopernik.html", title: "Второй соперник: только цена", status: "todo" },
  { id: "uluchshenie-bazovogo", part: "ocenka-prognoza", file: "uluchshenie-bazovogo.html", title: "Улучшение против базового", status: "todo" },
  { id: "lovushki-sravneniya", part: "ocenka-prognoza", file: "lovushki-sravneniya.html", title: "Ловушки сравнения", status: "todo" },

  /* ── Часть III. Спрос ───────────────────────────────────────────────── */
  { id: "sostav-sprosa", part: "kanal-sprosa", file: "sostav-sprosa.html", title: "Из чего складывается спрос", status: "todo" },
  { id: "razryv-vypuska", part: "kanal-sprosa", file: "razryv-vypuska.html", title: "Разрыв выпуска: чего мы не наблюдаем", status: "todo" },
  { id: "rynok-truda", part: "kanal-sprosa", file: "rynok-truda.html", title: "Рынок труда как термометр спроса", status: "todo" },
  { id: "operezhayushchie-oprosy", part: "kanal-sprosa", file: "operezhayushchie-oprosy.html", title: "Опережающие опросы", status: "todo" },
  { id: "oprovzhenie-sprosa", part: "kanal-sprosa", file: "oprovzhenie-sprosa.html", title: "Что опровергнет канал спроса", status: "todo" },

  /* ── Часть IV. Предложение ──────────────────────────────────────────── */
  { id: "proizvodstvo-izderzhki", part: "kanal-predlozheniya", file: "proizvodstvo-izderzhki.html", title: "Производство, издержки, узкие места", status: "todo" },
  { id: "smeshannyy-shok", part: "kanal-predlozheniya", file: "smeshannyy-shok.html", title: "Смешанный шок", status: "todo" },
  { id: "energiya-cepochki", part: "kanal-predlozheniya", file: "energiya-cepochki.html", title: "Энергия и цепочки поставок", status: "todo" },
  { id: "oprovzhenie-predlozheniya", part: "kanal-predlozheniya", file: "oprovzhenie-predlozheniya.html", title: "Что опровергнет канал предложения", status: "todo" },

  /* ── Часть V. Политика ──────────────────────────────────────────────── */
  { id: "centralnyy-bank", part: "kanal-politiki", file: "centralnyy-bank.html", title: "Что делает центральный банк и чем это меряется", status: "todo" },
  { id: "krivaya-dohodnosti", part: "kanal-politiki", file: "krivaya-dohodnosti.html", title: "Кривая доходности как высказывание о будущем", status: "todo" },
  { id: "lag-peredachi", part: "kanal-politiki", file: "lag-peredachi.html", title: "Лаг передачи", status: "todo" },
  { id: "oprovzhenie-politiki", part: "kanal-politiki", file: "oprovzhenie-politiki.html", title: "Что опровергнет канал политики", status: "todo" },

  /* ── Часть VI. Кредит ───────────────────────────────────────────────── */
  { id: "kredit-dolg-obsluzhivanie", part: "kanal-kredita", file: "kredit-dolg-obsluzhivanie.html", title: "Кредит, долг и способность его обслуживать", status: "todo" },
  { id: "kreditnyy-razryv", part: "kanal-kredita", file: "kreditnyy-razryv.html", title: "Кредитный разрыв", status: "todo" },
  { id: "banki-kreditory", part: "kanal-kredita", file: "banki-kreditory.html", title: "Банки против всех кредиторов", status: "todo" },
  { id: "prakticheskaya-polza", part: "kanal-kredita", file: "prakticheskaya-polza.html", title: "Почему этот канал не может говорить о практической пользе", status: "todo" },

  /* ── Часть VII. Внешний контур ───────────────────────────────────────── */
  { id: "torgovlya-schet-dollar", part: "vneshniy-kontur", file: "torgovlya-schet-dollar.html", title: "Торговля, счёт текущих операций, доллар", status: "todo" },
  { id: "mirovoy-faktor", part: "vneshniy-kontur", file: "mirovoy-faktor.html", title: "Общий мировой фактор", status: "todo" },
  { id: "oprovzhenie-vneshnego-kanala", part: "vneshniy-kontur", file: "oprovzhenie-vneshnego-kanala.html", title: "Что опровергнет внешний канал", status: "todo" },

  /* ── Часть VIII. Рынки — то, что мы объясняем ───────────────────────── */
  { id: "akcii-obligacii-syre", part: "rynki-otklik", file: "akcii-obligacii-syre.html", title: "Акции, облигации, доллар, сырьё", status: "todo" },
  { id: "dohodnost-gorizont", part: "rynki-otklik", file: "dohodnost-gorizont.html", title: "Доходность на горизонте", status: "todo" },
  { id: "volatilnost-rezhimy", part: "rynki-otklik", file: "volatilnost-rezhimy.html", title: "Волатильность и её режимы", status: "todo" },

  /* ── Часть IX. Реальное время ───────────────────────────────────────── */
  { id: "peresmotry-dannyh", part: "realnoe-vremya", file: "peresmotry-dannyh.html", title: "Данные переписывают прошлое", status: "todo" },
  { id: "nesmeshivaemye-ruki", part: "realnoe-vremya", file: "nesmeshivaemye-ruki.html", title: "Две руки, которые не смешиваются", status: "todo" },
  { id: "obyavlenie-recessii", part: "realnoe-vremya", file: "obyavlenie-recessii.html", title: "Когда объявляют рецессию", status: "todo" },

  /* ── Часть X. Панель стран и её ловушка ─────────────────────────────── */
  { id: "panel-stran", part: "panelnaya-lovushka", file: "panel-stran.html", title: "Зачем много стран", status: "todo" },
  { id: "effektivnye-nablyudeniya", part: "panelnaya-lovushka", file: "effektivnye-nablyudeniya.html", title: "Сорок эпизодов, которые не сорок наблюдений", status: "todo" },
  { id: "gruppirovka-vremeni", part: "panelnaya-lovushka", file: "gruppirovka-vremeni.html", title: "Группировка по времени, а не по стране", status: "todo" },

  /* ── Часть XI. Что считается результатом ────────────────────────────── */
  { id: "verdikt-rascheta", part: "kriterii-rezultata", file: "verdikt-rascheta.html", title: "Вердикт объявляют до расчёта", status: "todo" },
  { id: "moshnost-kriteriya", part: "kriterii-rezultata", file: "moshnost-kriteriya.html", title: "Мощность: может ли критерий сработать вообще", status: "todo" },
  { id: "neustanovlennyj-rezultat", part: "kriterii-rezultata", file: "neustanovlennyj-rezultat.html", title: "«Не установлено» — законный ответ", status: "todo" },
  { id: "mnozhestvennost-gipotez", part: "kriterii-rezultata", file: "mnozhestvennost-gipotez.html", title: "Множественность", status: "todo" },
  { id: "predregistraciya-proverka", part: "kriterii-rezultata", file: "predregistraciya-proverka.html", title: "Пред-регистрация и как её проверить", status: "todo" },

  /* ── Часть XII. Прибор ──────────────────────────────────────────────── */
  { id: "sostoyanie-kanalov", part: "pribor-sistema", file: "sostoyanie-kanalov.html", title: "Состояние, разложенное по каналам", status: "todo" },
  { id: "puti-veroyatnosti", part: "pribor-sistema", file: "puti-veroyatnosti.html", title: "Пути и их вероятности", status: "todo" },
  { id: "razlichayushchee-nablyudenie", part: "pribor-sistema", file: "razlichayushchee-nablyudenie.html", title: "Различающее наблюдение", status: "todo" },
  { id: "nadezhnost-kanalov", part: "pribor-sistema", file: "nadezhnost-kanalov.html", title: "Надёжность каждого канала", status: "todo" },
  { id: "sborka-pribora", part: "pribor-sistema", file: "sborka-pribora.html", title: "Собрать прибор самому", status: "todo" },

  /* ── Часть XIII. Крипта ─────────────────────────────────────────────── */
  { id: "kripta-otklik", part: "kripta-granica", file: "kripta-otklik.html", title: "Чем крипта отличается как отклик", status: "todo" },
  { id: "korotkaya-istoriya", part: "kripta-granica", file: "korotkaya-istoriya.html", title: "Короткая история", status: "todo" },
  { id: "granicy-utverzhdeniy", part: "kripta-granica", file: "granicy-utverzhdeniy.html", title: "Что можно утверждать и чего нельзя", status: "todo" },

  /* ── Часть XIV. Что измерено ────────────────────────────────────────── */
  { id: "rezultaty-rynok-gorizont", part: "izmerennye-rezultaty", file: "rezultaty-rynok-gorizont.html", title: "Результаты по парам «рынок × горизонт»", status: "todo" },
  { id: "makro-sverh-ceny", part: "izmerennye-rezultaty", file: "makro-sverh-ceny.html", title: "Где макро не дало ничего сверх цены", status: "todo" },
  { id: "chuzhaya-konstrukciya", part: "izmerennye-rezultaty", file: "chuzhaya-konstrukciya.html", title: "Разобранный случай: чужая конструкция", status: "todo" },
  { id: "otkrytye-voprosy", part: "izmerennye-rezultaty", file: "otkrytye-voprosy.html", title: "Что осталось открытым", status: "todo" },
];
