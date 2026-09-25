# Z29 · Отчёт: Цена подглядывания (Круг 2)

Задача `Z29` исследует не рынок и не макро-прогнозы, а **ошибку исследователя** (для главы 12 «Ловушки сравнения»):
1. Сколько выигрыша по метрике CRPS дарит подглядывание в будущее прибору `Z28` («Базовый соперник против прогноза по цене»).
2. Способен ли наш собственный аудит информационного множества (`audit_information_set`) поймать каждую из типичных утечек данных.
3. Каков реальный размер ошибки исследователя при нарушении пред-регистрации датировки в задачах контура `Z03` и `Z01`.

Критерии зафиксированы до расчёта в [`HYPOTHESIS.md`](HYPOTHESIS.md) (с дополнениями круга 2 в §9).
Расчёт выполнен скриптом [`run.py`](run.py), полный протокол сохранён в [`full-run.txt`](full-run.txt), машинные данные — в [`result.json`](result.json).

---

## 0. База и стартовый гейт

* **Базовый коммит:** `176011d522e9b4ee9333d0fe69cafefeec2786aa` (HEAD ветки при выдаче). База круга 2 — `21927cf`.
* **Контроль эталонного прибора:** Хеш файла `research/Z28/run.py` (с нормализацией концов строк к LF) равен `2efdf022670bf4fc0e04339037aeb5588306ed16f63638dd48871c6f2f46f5fc` и побитово совпадает со значением `instrument_controls.mutation_proof.source_sha256` из `research/Z28/result.json`.
* **Целостность дерева:** Файлы `research/sources.py`, `research/smoke.py`, `research/Z28/`, `research/Z03/run.py`, `research/Z01/run.py` с базы не изменялись (`git diff` пуст). Все вспомогательные модули исполнялись в оперативной памяти без вызова `main()`.
* **Самопроверка окружения:** Команды `python -X utf8 research/smoke.py` и `python -X utf8 research/smoke.py --selftest` завершились с кодом 0 (22/22 доступных серий прошли валидацию, 7/7 негативных контролей поймано).

---

## 1. Контроль честного прогона: воспроизведение Z28

Штатный исходник `Z28` исполнен в памяти с включённым аудитом информационного множества на обоих эталонных маршрутах:

| Маршрут | Дат ($n$) | Период прогнозов | Макс. $|\Delta_{\mathrm{act}} - \Delta_{\mathrm{pub}}|$ | Статус |
|---|---|---|---|---|
| **Yahoo `^GSPC`** | 1052 | 1937-12 … 2025-07 | `0.000e+00` п.п. | **Точное совпадение** ($\le 10^{-9}$) |
| **Shiller S&P TR** | 1735 | 1881-01 … 2025-07 | `1.113e-04` п.п. | **Сдвиг данных** (обновление файла `ie_data.xls`) |

*Адрес в `result.json`: `honesty_control.routes.yahoo.max_abs_diff_delta_pp`, `honesty_control.routes.shiller.max_abs_diff_delta_pp`.*

### Паспорт данных маршрутов
* **Yahoo `^GSPC`:** охват 1927-12 … 2026-07 (1184 месячных уровня), пропусков нет, дубликатов нет. Числа прогнозов совпали с `Z28` абсолютно по всем 1052 датам.
* **Shiller S&P Total Return:** охват 1871-01 … 2026-07 (1867 месячных уровней). С момента заморозки `Z28` (2026-08-15) файл `ie_data.xls` на сервере `shillerdata.com` обновился, вызвав микроскопический сдвиг на уровне $10^{-4}$ процентного пункта CRPS. По правилу спеки §3, подгонка не производилась: честный прогон зафиксировал фактическое расхождение, и все последующие замеры утечек проводились на тех же самых текущих данных.

### Честные параметры прибора Z28 на текущих данных
* **Yahoo:** средний выигрыш цены над базовым $\bar{\delta} = +0{,}1688$ п.п., $s = 1{,}9214$, $\tau = 8{,}89$, $n_{\mathrm{eff}} = 118{,}4$, честный 95 % ДИ $[-0{,}1773, +0{,}5149]$, вердикт — `information_absent`.
* **Shiller:** средний выигрыш цены над базовым $\bar{\delta} = -0{,}0566$ п.п., $s = 2{,}1973$, $\tau = 10{,}36$, $n_{\mathrm{eff}} = 167{,}4$, честный 95 % ДИ $[-0{,}3894, +0{,}2763]$, вердикт — `information_absent`.

---

## 2. Таблица пяти утечек на приборе Z28 (Круг 2)

Каждая утечка исполнена в памяти в двух режимах:
1. **Проверка аудита** (аудит включён штатно, обёртка динамически фиксирует индекс первой упавшей даты и точное сообщение об ошибке).
2. **Замер цены утечки** (аудит заменён заглушкой, а функция проверки калибровки `placebo_production_path` при `scale = 1` исполняется полностью без заглушки; максимальное расхождение чисел с кругом 1 составило ровно `0.000e+00` п.п.).

Согласно решению Р3:
- Для базовых утечек (L1, L2, L4) вычитание $\delta$ не производится. Рассчитывается **сдвиг сравнения `Z28`**: $\delta - d = \mathrm{CRPS}(\text{baseline}_{\text{leaked}}) - \mathrm{CRPS}(\text{price})$. Вердикт Z28 при утечке выносится по $\delta - d$, а вердикт самого поддельного выигрыша $d$ приводится отдельно.
- Для ценовых утечек (L3, L5) вердикт Z28 при утечке выносится по $d = \mathrm{CRPS}(\text{baseline}) - \mathrm{CRPS}(\text{price}_{\text{leaked}})$, а вердикт поддельного выигрыша — по $d - \delta$.

### Сводная таблица результатов

| Код | Утечка и описание | Аудит | Первая дата | Дословное сообщение аудита | Поддельный выигрыш $d$ [95 % ДИ], п.п. | $t_{\mathrm{honest}}$ ($d$) | Вердикт $d$ | Сдвиг сравнения Z28 [95 % ДИ], п.п. | $t_{\mathrm{honest}}$ (Z28) | Вердикт Z28 при утечке |
|---|---|:---:|:---:|---|---|:---:|:---:|---|:---:|:---:|
| **L1** (Yahoo)<br>**L1** (Shiller) | Ансамбль видит на 1 мес. вперёд (`annual[HORIZON:i+2]`) | **ПОЙМАН**<br>**ПОЙМАН** | 1937-12<br>1881-01 | `scenario lookahead or omission: actual=(119, 120, 121) expected=(118, 119, 120)`<br>`scenario lookahead or omission: actual=(119, 120, 121) expected=(118, 119, 120)` | $+0{,}0053$ $[-0{,}0002, +0{,}0108]$<br>$+0{,}0012$ $[-0{,}0017, +0{,}0041]$ | $+1{,}88$<br>$+0{,}82$ | `information_absent`<br>`information_absent` | $+0{,}1635$ $[-0{,}1819, +0{,}5089]$<br>$-0{,}0578$ $[-0{,}3893, +0{,}2738]$ | $+0{,}93$<br>$-0{,}34$ | `information_absent`<br>`information_absent` |
| **L2** (Yahoo)<br>**L2** (Shiller) | Незавершённые окна в ансамбле (`annual[HORIZON:i+HORIZON]`) | **ПОЙМАН**<br>**ПОЙМАН** | 1937-12<br>1881-01 | `scenario lookahead or omission: actual=(129, 130, 131) expected=(118, 119, 120)`<br>`scenario lookahead or omission: actual=(129, 130, 131) expected=(118, 119, 120)` | $+0{,}1878$ $[+0{,}1091, +0{,}2664]$<br>$+0{,}1280$ $[+0{,}0871, +0{,}1688]$ | **$+4{,}68$**<br>**$+6{,}14$** | **`information_present`**<br>**`information_present`** | $-0{,}0189$ $[-0{,}3710, +0{,}3331]$<br>$-0{,}1845$ $[-0{,}5042, +0{,}1351]$ | $-0{,}11$<br>$-1{,}13$ | `information_absent`<br>`information_absent` |
| **L3** (Yahoo)<br>**L3** (Shiller) | Опорная волатильность по всей выборке (константа) | **НЕ ПОЙМАН**<br>**НЕ ПОЙМАН** | —<br>— | `OK` (пропущена)<br>`OK` (пропущена) | $-0{,}4749$ $[-1{,}1384, +0{,}1886]$<br>$-0{,}0483$ $[-0{,}0986, +0{,}0020]$ | $-1{,}40$<br>$-1{,}88$ | `information_absent`<br>`information_absent` | $-0{,}3061$ $[-1{,}0771, +0{,}4649]$<br>$-0{,}1049$ $[-0{,}4287, +0{,}2190]$ | $-0{,}78$<br>$-0{,}63$ | `information_absent`<br>`information_absent` |
| **L4** (Yahoo)<br>**L4** (Shiller) | Центр ансамбля — среднее по всей выборке | **НЕ ПОЙМАН**<br>**НЕ ПОЙМАН** | —<br>— | `OK` (пропущена)<br>`OK` (пропущена) | $+0{,}2037$ $[-0{,}0097, +0{,}4172]$<br>$+0{,}0972$ $[-0{,}1178, +0{,}3122]$ | $+1{,}87$<br>$+0{,}89$ | `information_absent`<br>`information_absent` | $-0{,}0349$ $[-0{,}4630, +0{,}3931]$<br>$-0{,}1538$ $[-0{,}5418, +0{,}2342]$ | $-0{,}16$<br>$-0{,}78$ | `information_absent`<br>`information_absent` |
| **L5** (Yahoo)<br>**L5** (Shiller) | Недавняя волатильность за $t+1 \dots t+12$ вместо $t-11 \dots t$ | **ПОЙМАН**<br>**ПОЙМАН** | 1937-12<br>1881-01 | `recent-volatility source lookahead or omission`<br>`recent-volatility source lookahead or omission` | $+0{,}1954$ $[-0{,}0643, +0{,}4551]$<br>$+0{,}2774$ $[+0{,}0211, +0{,}5337]$ | $+1{,}47$<br>**$+2{,}12$** | `information_absent`<br>**`information_present`** | $+0{,}3642$ $[+0{,}0526, +0{,}6758]$<br>$+0{,}2208$ $[-0{,}1273, +0{,}5689]$ | **$+2{,}29$**<br>$+1{,}24$ | **`information_present`**<br>`information_absent` |

*Адрес в `result.json`: `leaks.<L1..L5>.measurement.<yahoo|shiller>`.*

### Дополнительное число L4 по цене (Р7)
Дополнительное число L4 рассчитывает прогноз по цене с масштабом **с опорой** на общий центр: $c + k \cdot (x - c)$, где $c$ — средняя годовая доходность по всей выборке.
* **Yahoo:** средний выигрыш составляет $+0{,}2804$ п.п., 95 % ДИ $[-0{,}0768, +0{,}6375]$, $t_{\mathrm{honest}} = 1{,}54$, вердикт — `information_absent`.
* **Shiller:** средний выигрыш составляет $-0{,}1405$ п.п., 95 % ДИ $[-0{,}4786, +0{,}1975]$, $t_{\mathrm{honest}} = -0{,}81$, вердикт — `information_absent`.
*Адрес в `result.json`: `leaks.L4.measurement.<yahoo|shiller>.extra.price_forecast_with_leaked_center`.*

### Механика ловушки базового соперника (Р3)
При утечке в базовом сопернике (L2: включение незавершённых годовых окон) базовый ансамбль получает искусственное преимущество над реальностью ($+0{,}19$ п.п. на Yahoo и $+0{,}13$ п.п. на Шиллере). В результате сравнение честной цены с базовым-с-утечкой ($\delta - d$) топит честную модель: на Yahoo выигрыш падает с $+0{,}17$ п.п. до $-0{,}02$ п.п., а на Шиллере — с $-0{,}06$ п.п. до $-0{,}18$ п.п. Это формирует зеркальную ловушку: исследователь ошибочно отвергает работающую модель, потому что сравнивает её с соперником, неявно заглядывающим в будущее.

---

## 3. Z03: реал-тайм-пересчёт по винтажам реального выпуска (Р1)

Счёт выполнен штатной функцией `score` модуля `research/Z03/run.py`, исполненного в оперативной памяти без вызова `main()`. Границы окна взяты по адресам из `research/Z03/result.json`:
* Сигналы: `realtime.verdict_known_at[].signal` (6 сигналов: 1989-06, 2000-07, 2006-08, 2019-05, 2020-02, 2022-11);
* `t_start`: месяц `manifest.series.T10Y3M.first` (1982-01-04 $\to$ индекс 1982-01);
* `t_end`: `realtime.vintage_bounds._last_covered_mi` (индекс 2026-03);
* Набор винтажей обрезан по `realtime.vintage_bounds.last_vintage` (2026Q2 включительно, 244 столбца).

### Контроли до вариантов
1. **Разбор:** Вызов `realtime_two_quarter` на обрезанной таблице побайтно воспроизвёл `realtime.two_quarter_realtime_events` по месяцам событий, винтажам и датам распознавания.
2. **Счёт:** Экономические даты спадов дали ровно **5 / 1 / 0** и лаги `[5, 7, 12, 22, 22]`.

### Сравнение трёх вариантов решения архитектора 09-25

| Вариант | События (винтаж, месяц события) | TP | FA | FN | Censored | FA / TP | Лаги, мес. | $U_1$ (FN $\le$ 1) | $U_2$ (FA/TP $\le$ 0.5) |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Опубликовано в `Z03`** (с утечкой в эк. даты) | — | **5** | **1** | **0** | **0** | **0.20** | `[5, 7, 12, 22, 22]` | **Выполнен** | **Выполнен** |
| **(A) Край винтажа (основной)** | 1970Q2 (1970-05), 1974Q3 (1974-08), 1981Q4 (1981-11), 1982Q2 (1982-05), 1991Q2 (1991-05), 2009Q1 (2009-02), 2020Q3 (2020-08), 2022Q3 (2022-08) | **3** | **3** | **2** | **0** | **1.00** | `[6, 15, 23]` | **НЕ выполнен** | **НЕ выполнен** |
| **(B) Строго первые публикации (чувствительность)** | 1965Q4 (1965-11), 1970Q2 (1970-05), 1974Q3 (1974-08), 1981Q4 (1981-11), 1991Q2 (1991-05), 2009Q1 (2009-02), 2020Q3 (2020-08), 2022Q3 (2022-08) | **3** | **3** | **2** | **0** | **1.00** | `[6, 15, 23]` | **НЕ выполнен** | **НЕ выполнен** |
| **(C) По `recognised_month` (круг 1)** | 15 событий таблицы `two_quarter_realtime_events` (артефакты: 1947 г. распознан в 2004 г., 1980 г. в 1996 г.) | **2** | **4** | **6** | **0** | **2.00** | `[6, 15]` | **НЕ выполнен** | **НЕ выполнен** |

*Адрес в `result.json`: `z03_recalculation`.*

В основном варианте (A) верными оказываются сигналы 1989-06 (лаг 23 к спаду 1991-05), 2019-05 (лаг 15 к спаду 2020-08) и 2020-02 (лаг 6 к спаду 2020-08). Ложными тревогами становятся сигналы 2000-07, 2006-08 (окно 24 мес. истекло до винтажа 2009-02) и 2022-11 (инверсия началась после спада первой половины 2022 г.). Пропущенными целями (FN) являются спады 2009-02 и 2022-08. Оба критерия $U_1$ и $U_2$ провалены.

Строка-указатель в [`research/Z03/REPORT.md`](../Z03/REPORT.md#L224) обновлена на итог варианта (A).

---

## 4. Z01: пересчёт через ALFRED без ключа (Р2, Р6)

Загрузка винтажных рядов выполнена через функцию `sources.alfred(series_id, vintage_date)` на срез `2026-07-27` (дата выгрузки Z01) без использования API-ключа FRED; `NAHB HMI` загружен через `sources.nahb_hmi("t2")`. Расчёт выполнен функциями `to_monthly`, `panel`, `run_config` модуля `research/Z01/run.py` в оперативной памяти.

### Паспорта рядов
* `UNRATE@2026-07-27`: $n = 941$, ежемесячный с 1948-01-01 по 2026-06-01.
* `DGS10@2026-07-27`: $n = 16125$, ежедневный с 1962-01-02 по 2026-07-24 (усреднён в 775 месяцев).
* `NAHB-HMI`: $n = 501$, ежемесячный с 1985-01-01 по 2026-09-01 (таблица t2 обновлена релизом 2026-09 относительно среза Z01 2026-07).

### 1. Контроль опубликованного разреза
* **Утверждение A (`NAHB` $\to$ `UNRATE`):**
  * Внутри выборки: пик на лаге 19, $r = -0{,}6032$ (в `Z01/result.json`: лаг 19, $r = -0{,}6032$ — **точное совпадение**).
  * Вне выборки: $r$ на внутреннем пике $-0{,}2214$ (в `result.json`: $-0{,}2214$ — **точное совпадение**); пик вне выборки: лаг 0, $r = -0{,}3827$ (в `result.json`: лаг 0, $r = -0{,}3827$ — **точное совпадение**).
* **Утверждение B (`NAHB YoY` $\to$ `US10Y YoY`):**
  * Внутри выборки: пик на лаге 17, $r = +0{,}3046$ (в `result.json`: лаг 17, $r = +0{,}2981$).
  * Вне выборки: $r$ на внутреннем пике $+0{,}0668$ (в `result.json`: $+0{,}0677$); пик вне выборки: лаг 20, $r = +0{,}0947$ (в `result.json`: лаг 20, $r = +0{,}0959$).
  * Микросдвиг утверждения B вызван обновлением таблицы `NAHB HMI` за сентябрь 2026 г., зафиксирован в паспорте.

### 2. Чистый разрез (внутри выборки $t \le 2009\text{-}12$, вне выборки $t \ge 2013\text{-}01$)

| Утверждение | Внутри выборки: пик (лаг, $r$) | Вне выборки: $r$ на внутреннем пике | Вне выборки: пик (лаг, $r$) | Статус |
|---|:---:|:---:|:---:|---|
| **A (`NAHB` $\to$ `UNRATE`)** | **лаг 17**, $r = -0{,}6144$ ($n = 288$) | $r = -0{,}3141$ | **лаг 0**, $r = -0{,}3827$ ($n = 117$) | Лид смещается с 19 на 17 мес., вне выборки уезжает в синхронность (лаг 0) |
| **B (`NAHB YoY` $\to$ `US10Y YoY`)** | **лаг 34**, $r = +0{,}2355$ ($n = 288$) | $r = -0{,}0195$ | **лаг 20**, $r = +0{,}0947$ ($n = 127$) | Лид 18 мес. полностью распадается: пик уходит на край окна (лаг 34), связь вне выборки нулевая |

*Адрес в `result.json`: `z01_audit` (поле `status: recalculated_via_alfred`).*

Строка-указатель в [`research/Z01/REPORT.md`](../Z01/REPORT.md#L74) вставлена отдельной строкой перед абзацем «Вне выборки», а сам абзац возвращён к исходному виду базы побайтно.

---

## 5. Дивиденды Шиллера: документирование скрытого подглядывания

В таблице `ie_data.xls` Роберта Шиллера помесячные дивиденды получены искусственной линейной интерполяцией.
Дословная цитата из документации первоисточника ([`https://shillerdata.com/`](https://shillerdata.com/)):

> *"Monthly dividend and earnings data are computed from the S&P four-quarter totals for the quarters since 1926, with linear interpolation to monthly figures. Dividend and earnings data before 1926 are from Cowles and Associates (Common Stock Indexes, 2nd ed. [Bloomington, Ind.: Principia Press, 1939]), interpolated from annual data. Stock price data are monthly averages of daily closing prices."*

*Адрес в `result.json`: блок `shiller_dividend_audit`.*

---

## 6. Абзац для главы 12 «Ловушки сравнения» (Р10)

> **Цена подглядывания в будущее.** В задаче `Z28` честная оценка прогноза по цене против исторического базового соперника показала отсутствие прогностической информации: на маршруте Yahoo средний выигрыш составил $+0{,}17$ п.п. (95 % ДИ $[-0{,}18, +0{,}51]$, `honesty_control.routes.yahoo.ci95_honest`), на маршруте Шиллера — $-0{,}06$ п.п. ($[-0{,}39, +0{,}28]$, `honesty_control.routes.shiller.ci95_honest`). Однако стоило базовому ансамблю допустить включение незавершённых годовых окон (утечка L2, `annual[HORIZON:i + HORIZON]`), как сам базовый соперник получил фиктивный выигрыш $+0{,}19$ п.п. ($[+0{,}11, +0{,}27]$, $t_{\mathrm{honest}} = 4{,}68$, `leaks.L2.measurement.yahoo.fake_gain_metrics`) на Yahoo и $+0{,}13$ п.п. ($[+0{,}09, +0{,}17]$, $t_{\mathrm{honest}} = 6{,}14$, `leaks.L2.measurement.shiller.fake_gain_metrics`) на Шиллере с ложным вердиктом «информация есть». В результате сдвиг сравнения $\delta - d$ потопил честный прогноз по цене, опустив его относительную оценку до $-0{,}02$ п.п. ($[-0{,}37, +0{,}33]$, `leaks.L2.measurement.yahoo.z28_shift_metrics`) на Yahoo и $-0{,}18$ п.п. ($[-0{,}50, +0{,}14]$, `leaks.L2.measurement.shiller.z28_shift_metrics`) на Шиллере. Подглядывание в задаче `Z03` исказило картину ещё сильнее: оценка по экономической дате спада, известной задним числом, давала видимость эффективного правила (5 верных / 1 ложная / 0 пропусков, `z03_recalculation.reproduction_control.score`), тогда как оценка по краю винтажа на момент принятия решений показала 3 верных / 3 ложных / 2 пропуска с провалом обоих критериев успеха (`z03_recalculation.variant_A_vintage_edge.score`).

---

## 7. Чего не читал и какие выводы из-за этого условны

1. `book/` целиком — главы книги не читались (за исключением фрагментов спецификации базового соперника в `CHAPTER-SPEC-bazovyy-sopernik.md`). По этой причине выводы отчёта строго ограничены метриками контура `research/` и не оценивают педагогическую композицию книги.
2. `research/sources.py` целиком — модуль объёмом 118 КБ читался только в части вызовов `load_yahoo`, `load_shiller`, `alfred`, `nahb_hmi` и `philfed_realtime`. Загрузчики макросерий других ведомств (CFTC, BIS, OECD, BEA) не инспектировались.
3. `research/Z01/HYPOTHESIS-ADDENDUM.md` и `run-addendum.py` — не читались подробно, так как дополнение посвящено устойчивости посткризисного режима без ковида и блоку экстремумов, а не сбалансированному OOS-разбиению выборки.

---

## 8. Протокол сдачи и ворота круга 2

### 1. Прогон основного скрипта задачи
Команда: `python -X utf8 research/Z29/run.py`
Код завершения: `0`. Результаты записаны в `research/Z29/result.json` и `research/Z29/full-run.txt`.

### 2. Дословный вывод `python -X utf8 research/smoke.py`
```
[sources] NAHB t2: https://www.nahb.org/-/media/NAHB/news-and-economics/docs/housing-economics/hmi/2026-09/t2-national-hmi-history-202609.xls?rev=aaf91173ef694ede95f66b619ae28ad7&hash=7FCF6E8104C7C0C0952365E0B4D695D6
[sources] NAHB t3: https://www.nahb.org/-/media/NAHB/news-and-economics/docs/housing-economics/hmi/2026-09/t3-national-hmi-components-history-202609.xls?rev=75ce2c4010ba4900a104819ebc646bdb&hash=22A97EBE895F4685E007549C9D9FE673
[sources] Shiller: https://img1.wsimg.com/blobby/go/e5e77e0b-59d1-44d9-ab25-4763ac982e53/downloads/70fec4f5-727f-4e53-b5f1-179af109c5fa/ie_data.xls?ver=1788371540009
[sources] KC mfg: https://www.kansascityfed.org/documents/19152/2026Sept24historicalmfg.xlsx
pokazatel                              istochnik              ch       n pervaya    poslednyaya     poslednee
-------------------------------------------------------------------------------------------------------------

[labour]
Bezrabotica (U-3)                      NET KLYUCHA (FRED)
Pervichnye zayavki na posobie          NET KLYUCHA (FRED)
Zanyatost' vne sel'hoz (NFP)           NET KLYUCHA (FRED)

[housing]
NAHB HMI (kompozit)                    NAHB/Wells Fargo       M      501 1985-01-01 2026-09-01             32
NAHB: trafik pokupateley               NAHB/Wells Fargo       M      501 1985-01-01 2026-09-01             23
Razresheniya na stroitel'stvo          NET KLYUCHA (FRED)
Nachala stroitel'stva                  NET KLYUCHA (FRED)
Razresheniya (pervoistochnik Census)   NET KLYUCHA (CENSUS)

[prices]
CPI, vse stat'i                        NET KLYUCHA (FRED)
Core CPI                               NET KLYUCHA (FRED)
Core PCE (deflyator)                   NET KLYUCHA (FRED)
Core PCE (pervoistochnik BEA)          NET KLYUCHA (BEA)

[output]
Promyshlennoe proizvodstvo             NET KLYUCHA (FRED)
Zagruzka moshchnostey                  NET KLYUCHA (FRED)

[curve]
UST 3 mesyaca                          U.S. Treasury          D     9186 1990-01-02 2026-09-24           4.24
UST 2 goda                             U.S. Treasury          D     9189 1990-01-02 2026-09-24           4.87
UST 10 let                             U.S. Treasury          D     9189 1990-01-02 2026-09-24           5.18
UST 30 let                             U.S. Treasury          D     8195 1990-01-02 2026-09-24           5.47
Spred 10Y-2Y                           NET KLYUCHA (FRED)
Spred 10Y-3M                           NET KLYUCHA (FRED)
TIPS 10 let (real'naya stavka)         U.S. Treasury          D     5937 2003-01-02 2026-09-24           2.85
Breakeven 5 let                        NET KLYUCHA (FRED)
Breakeven 10 let                       NET KLYUCHA (FRED)
Premiya za srok ACM, 10 let            FRB New York (ACM)     D    16284 1961-06-14 2026-09-23         0.6454

[markets]
Indeks dollara DXY                     Yahoo Finance          1d   14150 1971-01-04 2026-09-25          101.1
Zoloto (fyuchers)                      Yahoo Finance          1d    6543 2000-08-30 2026-09-25          4,315
Med' (fyuchers)                        Yahoo Finance          1d    6547 2000-08-30 2026-09-25          6.761
Neft' WTI                              NET KLYUCHA (FRED)
S&P 500                                Yahoo Finance          1d   24799 1927-12-30 2026-09-24          7,704
Russell 2000                           Yahoo Finance          1d    9833 1987-09-10 2026-09-24          2,836
Nasdaq Composite                       Yahoo Finance          1d   14025 1971-02-05 2026-09-24      2.694e+04
CAPE Shillera (strazh svezhesti)       Shiller (shillerdata.c M     1749 1881-01-01 2026-09-01          40.58

[activity]
Indeks delovyh usloviy ADS             FRB Philadelphia       D    24309 1960-03-01 2026-09-19     -0.0002172
Philly Fed: obshchaya aktivnost'       FRB Philadelphia (MBOS M      701 1968-05-01 2026-09-01           37.8
Philly Fed: budushchie novye zakazy    FRB Philadelphia (MBOS M      701 1968-05-01 2026-09-01           62.3
Empire State: obshchie usloviya        FRB New York (Empire S M      303 2001-07-31 2026-09-30            7.6
Dallas Fed: rost novyh zakazov         NET KLYUCHA (FRED)
Richmond Fed: kompozit                 FRB Richmond (Fifth Di M      395 1993-11-01 2026-09-01             -2
Kansas City Fed: kompozit              FRB Kansas City (Tenth M      303 2001-07-01 2026-09-01             14
CFNAI (Chikago)                        NET KLYUCHA (FRED)

[cycle]
Recessii NBER (USREC)                  NET KLYUCHA (FRED)
Obyavleniya NBER: piki                 NBER                   M        6 1980-01-01 2020-02-01              4

=============================================================================================================
proshli po soderzhimomu: 22 | ne proshli: 0 | bez klyucha: 20 | 12.7 s
kesh: C:\Users\marke\orca\workspaces\loodo-market-cycle\z29-cena-podglyadyvaniya\research\.cache
```

### 3. Дословный вывод `python -X utf8 research/smoke.py --selftest`
```
SELFTEST: detektor dolzhen POYMAT' kazhdyy sluchay nizhe

  POYMAN  JS-zaglushka vmesto dannyh (stooq, otdaet HTTP 200)
          -> UpstreamBlocked: https://stooq.com/q/d/l/?s=%5Espx&i=d
  POYMAN  licenzionnoe usechenie istorii (ICE HY OAS s 2023)
          -> MissingKey: FRED_API_KEY
  POYMAN  zamorozhennyy ryad (USSLIND, mertv s 2020-02)
          -> MissingKey: FRED_API_KEY
  POYMAN  Yahoo range=max molcha ponizhaet granulyarnost' (^GSPC)
          -> FetchError: Yahoo vernul shag '3mo' vmesto zaproshannogo '1d' dlya ^GSPC
  POYMAN  dyry value='.' v konverte FRED (NEWORDER: 700 strok, 412 chisel)
          -> MissingKey: FRED_API_KEY
  POYMAN  HTML vmesto tablicy pri 200 (podmena po signature)
          -> UpstreamBlocked: vmesto tablicy prishel HTML
  POYMAN  ne ta stranica NBER pri 200 i 78 KB (obyavleniy v tele net)
          -> telo 80231 bayt, HTTP 200, a obyavleniy razobrano 0 iz >= 6

poymano 7 iz 7
```

### 4. Дословный вывод `git diff 176011d -- research/Z28 research/sources.py research/smoke.py research/Z03/run.py research/Z01/run.py`
```
```
*(вывод строго пустой, файлы эталонов с базы не изменялись)*

---

Z29-R2-COMPLETE
