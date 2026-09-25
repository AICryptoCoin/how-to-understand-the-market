# How to Understand the Market: Measure, Don't Guess

*«Как понимать рынок — измерять, а не угадывать»*: a free, non-commercial
Russian-language book on reading the economy with data, and the open
measurement pipeline behind it.

**Author:** Volodymyr Biesov, Principal Investigator, European University.
**Co-author:** Claude, an AI model developed by Anthropic. See the
[AI co-authorship statement](#ai-co-authorship-statement).

> **Status (September 2026): early stage.** The scientific model is fixed, the
> ten-country data panel is surveyed and measured, ten pre-registered
> measurement tasks are complete, and four chapters of the new edition (8 to 11,
> on telling a good forecast from a lucky one) are written and accepted. The core measurement (a forecast that knows the state
> of the economy against a forecast that knows nothing) has not been run yet,
> and the analyser is not implemented. Details in [Status](#status).

## Abstract

Most market commentary reads the macroeconomy as a story: the cycle is
turning, buy this, sell that. This project asks a narrower and testable
question instead: **how much does knowing the state of the economy, measured
only with the data that were actually available at the time, narrow the spread
of future market outcomes, and at which horizons?** We do not promise to see
the end of the tunnel. We measure the width of the tunnel and how much it
shrinks when the state is known. Any answer is a result: "no narrowing at three
months, this much at twelve" is a finding, not a failure.

The book teaches a reader with no background in economics what they need in
order to understand that measurement and, more importantly, to **repeat it
themselves**: what a distribution is and why its mean is almost useless, how a
proper scoring rule tells a good forecast from a lucky one, how each causal
channel of the economy (demand, supply, policy, credit, the external sector) is
measured and what observation would refute it, why data revisions and
cross-country panels are traps, and why a result the data cannot settle is
reported with numbers (the estimate, the interval, the smallest effect the
data could detect and the data that would settle it) rather than with a
label. Every number the method rests on is shown in the book together with its
source and the route to it. The same measurements feed a free software
analyser, a "market clock", that reports the state of the economy channel by
channel with its measured reliability, instead of a buy or sell signal.

## Who it is for, and on what terms

- **Non-commercial.** The book will not be sold. It is written for
  Russian-speaking readers in the CIS countries, where accessible,
  evidence-based economics education is scarce, and it will be released free of
  charge.
- **The analyser will be free as well.** The AI-assisted market-state analyser
  built on these measurements will be released as a free product.
- **Everything is meant to be checked.** The reader sees the data and knows
  where to get them. Each empirical claim links to a task folder with a
  pre-registered hypothesis, the code, the raw run log and the report.

## Research questions

1. For each market (equities, government bonds, the dollar, commodities, with
   crypto as a separate part) and each horizon (3, 6 and 12 months and the
   cycle, roughly two years), how much does a forecast that knows the economic
   state improve on the "know nothing" baseline, and is the improvement
   distinguishable from zero at the available statistical power?
2. Does macro information add anything beyond the price itself? A second
   competitor uses only past price dynamics, volatility and levels. The book's
   central thesis thereby becomes a measurement, and a negative answer will be
   printed as such.
3. Which causal channels carry the information and which are silent? Channels
   are never collapsed into one number, and a channel the data cannot settle
   is reported with its estimate, interval, smallest detectable effect and
   the data that would settle it, never as a bare "don't know".
4. How much of the information survives in real time, that is, with vintage
   data as first published, and how much exists only in revised data?
5. On a panel of ten countries whose recessions are synchronised, how many
   effectively independent observations are there, and does any information
   remain once the common global factor is removed?

## Design and methodology

The scientific model behind the work, kept in the private working repository,
in brief:

- **State** is a set of named causal channels (demand, supply, policy, credit,
  external), each measured separately, each with its own refutable consequence
  and its own confidence. Channels are not summed into a single index; that
  summation is exactly the step that destroyed information in the inherited
  construction described below.
- **Outcome** is the full distribution of future returns per market and
  horizon, with the tails reported separately. Not the mean.
- **Measurement** builds two distributional forecasts for the same date: a
  "know nothing" baseline estimated only from history available at that date,
  and a conditional forecast that knows the state. They are compared with a
  **proper scoring rule**. The primary score is CRPS (continuous ranked
  probability score), because it is measured in the units of the outcome,
  percentage points of return, and can therefore be explained to a reader. The
  logarithmic score is printed alongside wherever the forecast has a density;
  the empirical-ensemble forecasts of the first task, Z28, have none, so there
  it was not computed. The improvement over the
  baseline is the measured tunnel width, per market and horizon, with an
  interval.
- **A price-only competitor** serves as the second baseline (research
  question 2).
- **A panel of ten countries**: United States, Canada, United Kingdom, Japan,
  Germany, France, Italy, Spain, Australia and South Korea, selected by the
  availability of a common data skeleton (OECD leading indicator, OECD macro
  series, OECD real-time vintages from 1999). Three safeguards are mandatory:
  the effective number of independent observations is printed next to the
  nominal one in every table; reliability is estimated by clustering on time,
  not on country; the common global factor is removed and the residual
  cross-country information is tested separately.
- **Real time, two hands that never mix.** Vintage data (only countries with
  revision archives; the only basis for claims about lead time and practical
  use) and revised data (all countries; good for mechanisms and for comparison
  with the literature, never for claims of practical use).
- **The verdict is declared before computation.** Each market-by-horizon cell
  receives one of three verdicts: information present, information absent at
  adequate power, or not established. **Power is computed before the run**, so
  cells that cannot distinguish anything are declared in advance and are never
  used for claims. A cell that cannot distinguish is never left as a bare
  label either: its estimate, interval, smallest detectable effect and the
  amount of data that would settle it are printed with it (the author's
  decision of 24 September 2026).
- **Pre-registration discipline.** Hypothesis, transformations, confirmation
  and refutation criteria are committed as a separate commit before the first
  data request, and the report prints the commit hashes and timestamps so the
  order can be verified from the git history
  ([`research/Z28/REPORT.md`](research/Z28/REPORT.md), section 1, is an
  example). Deviations are documented with a reason independent of the result,
  and the pre-registered version is computed anyway. Negative results are
  published on equal footing. Key numbers are reproduced independently, with
  different code and a separate data download, before acceptance.

What is deliberately **not** in the model: allocation rules, position sizes,
trading signals, and any promise that the narrowing will be large. It may be
zero, and the book is structured to print that.

## What has been measured so far

The project started from an inherited "investment clock" construction (the
BofA Merrill Lynch Investment Clock, as adapted in a Russian-language course of
2023). That construction was formalised and put through pre-registered tests.
It did not survive them, and on 2026-08-03 it was reclassified from foundation
to research material; the current model was then derived from scratch. The
tests are kept as results rather than discarded:

| Task | Claim tested | Outcome |
|---|---|---|
| Z01 | The NAHB housing index leads unemployment by 10 months and the 10-year yield by 18 | Refuted for unemployment: the peak is at 17 months, although the link itself is strong (p = 0.003 after correction for the lag search). Undetermined for the yield. Reproduced by an independent pipeline to the third decimal. On a clean out-of-sample split (Z29) the in-sample lead is 17 months and the out-of-sample peak is at lag 0 |
| Z02 | The twelve-link "H-O-P-E" ordering of the cycle is stable | Refuted: the threshold is met in none of six post-1970 cycles (median rank correlation 0.29), bootstrap intervals cover zero |
| Z03 | Yield-curve inversion predicts recession | Undetermined: it depends on the definitions. The false-alarm rate was measured for the first time (2 false per 4 correct in the main configuration); lag median 13 months, range 8 to 16; the 2022 to 2024 episode is a false alarm under all 24 definitions. Dated by when a recession was first visible in real-time GDP releases, the side check scores 3 correct, 3 false and 2 missed, not the published 5, 1 and 0 (Z29) |
| Z04 | Dis-inversion is a sharper signal than inversion | Undetermined: only two paired episodes exist, the criterion cannot fire at n = 2, about twenty episodes would be needed |
| Z05 | The state classifier predicts the sign of prescribed asset pairs | Refuted: hit rate 0.49 at 1 month and 0.48 at 3 months against a 0.55 threshold, 0 of 14 pairs; the specification was also found internally contradictory. Reproduced independently to the fourth decimal |
| Z06 | Published ISM thresholds separate growth regimes (tested on a composite of five regional Fed surveys, since ISM is proprietary) | Refuted: no identifiable zero-growth line (90 % interval of 4.07 sigma against less than 1.0 required), structural break in 2009. The composite does recognise recessions (AUC 0.92) |
| Z25 | The post-2009 weakening of the survey-to-output link is a property of the survey class | Undetermined by the pre-registered rule; hard data lost the link just as the surveys did (composite +0.72 to +0.04). A post-hoc, explicitly labelled competitor, no recessions in the 57 post-2009 quarters, explains 42 % |
| Z26 | The repaired construction v2 has a calibration satisfying both of its requirements | None: of 506 cells, 36 satisfy A, 7 satisfy B, 0 satisfy both |
| Z27 | Which constraint makes the instrument silent | The curve-shape validator: with it the share of defined states is 0.018, without it 0.290. Requirement B is unattainable in all 864 cells |
| Z28 | A price-only forecast (recent volatility) of the 12-month S&P 500 return distribution beats the "know nothing" baseline | No information: the CRPS difference is positive, but the 95 % interval covers zero at adequate power for a 1 pp effect. The same verdict on the independent Shiller data route |
| Z29 | How much fake skill look-ahead gives on the Z28 instrument, and whether the information-set audit catches it | Measured, not a verdict. An ensemble that includes unfinished 12-month windows beats the honest baseline by 0.19 pp of CRPS on Yahoo (95 % interval 0.11 to 0.27, t = 4.7) and by 0.13 pp on the Shiller route, turning "no information" into "information"; the same leak placed in the baseline makes the honest price forecast look worse than it is (+0.17 becomes -0.02). Future volatility in the price forecast gives +0.36 pp on Yahoo (t = 2.3). The audit catches the three leaks that carry their own time labels and misses the two built from constants computed over the whole sample. Recounted in real time: Z03 scores 3 correct, 3 false and 2 missed instead of 5, 1 and 0; on a clean split Z01's unemployment lead moves from 19 to 17 months and the out-of-sample peak stays at lag 0. Reproduced by the architect's own code |

Each task folder in `research/Z##/` holds `HYPOTHESIS.md` (the
pre-registration), `run.py`, `result.json`, `full-run.txt` (the raw run log)
and `REPORT.md`.

Data groundwork completed alongside, and kept in the private working
repository: a source map of about 185 indicators with history depth measured
from response bodies; a content-checked smoke test of 42 key series; and
reconnaissance of the ten-country panel, its vintage archives and
business-cycle chronologies.

## Data sources

All series are loaded through one module,
[`research/sources.py`](research/sources.py), one function per source, with
caching and SSL handled centrally. Free registration keys are needed for FRED,
BEA and Census; everything else is keyless. **No series is excluded because of
its licence or price.** The terms of each source — free or by subscription —
are tracked per series in the private working repository, so the reader sees
what is free and what sits behind a subscription.

| Group | Sources |
|---|---|
| US macro, primary | [FRED](https://fred.stlouisfed.org/) and [ALFRED](https://alfred.stlouisfed.org/) vintages (St. Louis Fed) · [BEA NIPA API](https://apps.bea.gov/api/signup/) · [Census Economic Indicators Time Series](https://www.census.gov/data/developers/data-sets/economic-indicators.html) · [BLS API](https://www.bls.gov/developers/) · [U.S. Treasury yield curve](https://home.treasury.gov/resource-center/data-chart-center/interest-rates) |
| Federal Reserve surveys and indexes | [Empire State survey (New York Fed)](https://www.newyorkfed.org/survey/empire/empiresurvey_overview) · [Philadelphia Fed MBOS](https://www.philadelphiafed.org/surveys-and-data/regional-economic-analysis/manufacturing-business-outlook-survey) · [Richmond Fed surveys](https://www.richmondfed.org/research/regional_economy/surveys_of_business_conditions) · [Kansas City Fed manufacturing survey](https://www.kansascityfed.org/surveys/manufacturing-survey/) · [Dallas Fed TMOS](https://www.dallasfed.org/research/surveys/tmos) · [Chicago Fed CFNAI](https://www.chicagofed.org/research/data/cfnai/current-data) and [NFCI](https://www.chicagofed.org/research/data/nfci/current-data) · [New York Fed Survey of Consumer Expectations](https://www.newyorkfed.org/microeconomics/sce) and [reference rates](https://www.newyorkfed.org/markets/reference-rates) · Atlanta Fed and Cleveland Fed data files |
| Real-time (vintage) data | [Philadelphia Fed Real-Time Data Set for Macroeconomists](https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-for-macroeconomists) · [OECD Original Release Data and Revisions](https://sdmx.oecd.org/public/rest/) via the SDMX API, ten countries from 1999 · [Dallas Fed international real-time database](https://www.dallasfed.org/research/international), vintages 1962 to 1998 for 26 countries · ALFRED |
| International | [OECD Data Explorer](https://data-explorer.oecd.org/) (leading indicators, main economic indicators) · [BIS Data Portal](https://data.bis.org/) (credit-to-GDP gaps) · [ECB Data Portal](https://data.ecb.europa.eu/) · [Eurostat](https://ec.europa.eu/eurostat/web/main/data/database) · [World Bank](https://data.worldbank.org/) · [Bank of England database](https://www.bankofengland.co.uk/boeapps/database/) · [DBnomics](https://db.nomics.world/) mirrors, freshness checked per provider |
| Business-cycle chronologies | [NBER](https://www.nber.org/research/data/us-business-cycle-expansions-and-contractions) · [CEPR-EABCN euro-area chronology](https://eabcn.org/dbc/peaksandtroughs/chronology-euro-area-business-cycles) · national committees where they exist (C.D. Howe Institute for Canada, ESRI for Japan, Statistics Korea) |
| Housing, financial stress, positioning | [NAHB Housing Market Index](https://www.nahb.org/news-and-economics/housing-economics/indices/housing-market-index) · [OFR Financial Stress Index](https://www.financialresearch.gov/financial-stress-index/) · [CFTC Commitments of Traders](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm) |
| Markets and long history | [Yahoo Finance](https://finance.yahoo.com/) · [Stooq](https://stooq.com/) · [Shiller data](https://shillerdata.com/), S&P 500 since 1871 · [Kenneth French data library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html) · [Damodaran](https://pages.stern.nyu.edu/~adamodar/) · [Twelve Data](https://twelvedata.com/), subscription, terms recorded |
| Crypto | [CoinGecko API](https://www.coingecko.com/en/api) · [Binance public API](https://developers.binance.com/) |
| Energy | [EIA Open Data](https://www.eia.gov/opendata/): the loader is written, but no key has been issued yet, so the source is not in the pipeline |

Two rules of the source map: a source counts as working only by the **body** of
the response, never by the HTTP status (several mirrors answer HTTP 200 with a
JavaScript stub), and a row is entered only after a live server response, with
the actual first and last dates.

## Deliverables

1. **The book** (Russian, HTML, opens from `book/index.html` without a server).
   Fifty-six chapters in fifteen parts plus a sources appendix are planned,
   derived top-down from the model: for every step of the measurement the plan
   asks what the reader must know to understand it and what the reader must be
   able to do to check it. Four of the five chapters of part II, "How to tell
   a good forecast from a lucky one", are written and accepted: chapter 8, "A
   proper scoring rule"; chapter 9, "The 'know nothing' baseline"; chapter
   10, "The second competitor: price only"; chapter 11, "Improvement over
   the baseline". Chapter 12, "Comparison traps", is next. The previous
   edition (38 chapters, about 334 000 words, 198 figures) was written around
   the inherited construction and is kept in the private working repository as
   material.
2. **The measurement pipeline** in `research/`: the loader, the smoke test
   with its self-test, and the task folders. Reproducible from a clean clone
   plus three free API keys.
3. **The analyser** ("market clock"), a free software product built on the
   measured results, to be developed in a separate repository once the
   measurements exist. Its output is fixed by the model (kept in the private
   working repository): the state channel by channel with measured
   reliability, the probabilities of paths over the horizon, and a
   **discriminating observation** the user can wait for. Its safeguard is fixed
   as well: the language model in the interface restates measured numbers and
   generates no claims of its own.

## Status

Early stage, stated plainly: the framing changed on 2026-08-03 after the
inherited construction failed its tests, and the new edition of the book is four
chapters in.

| Component | State |
|---|---|
| Model of the work | Fixed on 2026-08-04 (kept in the private working repository) |
| Data panel | Ten countries selected and measured; the 2008 recession is covered for all ten through OECD first-release data; vintage density and history depth measured |
| Measurement tasks | 11 complete (Z01 to Z06, Z25 to Z29), each with a pre-registration file. The conditional forecast that knows the economic state, the core measurement, has not been run yet. Z29 measured the cost of look-ahead on the Z28 instrument, the numbers chapter 12 is built on |
| Book, new edition | 4 of 56 chapters written (8 to 11, part II); chapter 12 is next |
| Book, previous edition | 38 chapters, kept in the private working repository as material |
| Analyser | Not started; no product code lives in this repository |

## How the work is done

Every substantive decision is made by the author and logged with its date and
reason in the project's private decision journal.

- **Volodymyr Biesov, the author and project operator,** sets the question
  and the scope, makes every substantive decision, reviews chapters as the
  reader, and owns all legal and publication matters.
- **Claude (Anthropic)** works as the architect: it designs the model and the
  chapter plan, writes the specifications of tasks and chapters, accepts
  delivered work by re-running every check itself, builds the acceptance
  instruments and keeps the documentation. It wrote chapter 8; since
  September 2026 the chapters are written by the local LLM under its
  specifications.
- **A local LLM** works in its own isolated working copy: data
  reconnaissance, the measurement tasks, controls and re-checks, and, since
  September 2026, the prose of the chapters under the architect's
  specifications.
- **Acceptance is double and independent.** The local LLM recomputes what can
  be recomputed (numbers, links, instruments, page geometry); the architect
  checks what only a full read can check (does the chapter teach what it
  promises, is every claim backed, has it drifted back to the old
  construction) and then re-runs every recomputation itself. A fresh instance
  of the local LLM audits each finished chapter.

Acceptance instruments for the book (run from `book/`):

```bash
python tools/linkify.py --check && python tools/audit.py && python tools/audit.py --selftest
```

Thirteen defect detectors must report zero and the self-test must pass. Every
number of a chapter is bound to its place and to its source field by
`tools/numbind.py` with a per-chapter manifest in `tools/numbers/`, for all
four chapters. The binding proves it is alive twice: by catching random swaps
of one number for another (`tools/mutate_numbers.py`) and by failing wherever a
source field is perturbed (`--liveness`). A second instrument,
`tools/numbind_sense.py`, checks that each binding points at the field the
sentence talks about (the route and the month named around the number), and
that a derived table column either holds on the printed numbers of its row or
says in its caption that it was computed from unrounded values. Page
geometry is judged by ink with `tools/geometry-check.js`, run by
`tools/geometry-run.py`, and the instrument has to prove it is alive by
catching a deliberate mutation.

Measurement pipeline (run from `research/`, keys in `.env.research` at the
repository root):

```bash
python smoke.py && python smoke.py --selftest
```

Expected: 42 of 42 series pass by content, and the self-test catches all 7
known-bad cases.

## AI co-authorship statement

This work is co-authored by a human and an AI system, and the division of
labour is stated explicitly.

- **AI system.** Claude, developed by Anthropic, used through Claude Code.
  The git history records the contribution commit by commit with a
  `Co-Authored-By: Claude ...` trailer naming the specific Claude model used
  for that commit.
- **What Claude did.** The scientific model, the chapter plan, the
  specifications of all measurement tasks and chapters, acceptance of
  delivered work, the acceptance instruments, the project documentation, and
  the prose of chapter 8.
- **What the local LLM did.** Under Claude's specifications, it aggregated
  data, executed the measurement and reconnaissance tasks, wrote the prose of
  chapters 9 to 11 and recomputed numbers at acceptance; a fresh instance
  audited each chapter.
- **What the human author, Volodymyr Biesov, did and does.** Framed the
  question, made and logged every substantive decision, reviewed every
  chapter, and decides what is published. The human author bears full
  responsibility for the content.
- **What this does not mean.** Claude is not a legal author and holds no rights
  in the work. Anthropic has not reviewed, sponsored or endorsed this project;
  the collaboration is with the model.

A book that teaches readers to check claims should show how it was made. The
practice is documented in the project's private decision journal, including
the cases in which the architect's own judgement was wrong and was corrected
by measurement.

## Repository map

The working language of the repository is Russian; this README is the English
entry point. This repository publishes the README, the finished chapters of
the book, and the completed measurement pipeline with its results. The
project's planning, decision journal and data-reconnaissance documents are
kept in the private working repository.

| Path | What it is |
|---|---|
| [`book/index.html`](book/index.html), `book/*.html` | The book; [`book/assets/chapters.js`](book/assets/chapters.js) is the chapter registry |
| `book/assets/` | Stylesheet, script and the chapter registry needed to render the book |
| `book/tools/` | Acceptance instruments: `audit.py` (thirteen detectors), `linkify.py`, `mathcheck.py`, `numbind.py` with per-chapter manifests in `numbers/`, `numbind_sense.py`, `mutate_numbers.py`, `geometry-check.js` with `geometry-run.py` |
| [`research/sources.py`](research/sources.py), [`research/smoke.py`](research/smoke.py) | Loader (one function per source) and the content-checked smoke test |
| `research/Z01/` to `research/Z29/` | Completed measurement tasks: pre-registration, code, run log, report |

Kept in the private working repository and not published here: the scientific
model, the chapter plan, the project's decision journal, the data-source map,
the panel-reconnaissance reports, the book's style guide and chapter
specifications, and the architect's internal working instructions
(`CLAUDE.md`); and, for rights reasons, slide-by-slide notes on the original
commercial course, the formal specification and indicator catalogue extracted
from it, and the previous edition of the book with its plans and audits.

## Reproducing

1. Clone the repository. Python 3.11 or later; the loader uses the standard
   library plus `certifi`, and `xlrd` for the spreadsheet sources (Shiller,
   Dallas Fed).
2. Get free keys from FRED, BEA and Census and put them in `.env.research` at
   the repository root as `FRED_API_KEY`, `BEA_API_KEY` and `CENSUS_API_KEY`.
   The file is git-ignored.
3. Run the smoke test from `research/`: expected 42 of 42, self-test 7 of 7.
4. Re-run any task, for example `python research/Z28/run.py`, and compare its
   output with the committed `result.json` and `full-run.txt`.
5. Verify the pre-registration order of any task from the history:

```bash
git log --format='%h %ci %s' -- research/Z28/
```

Commit hashes quoted inside task reports refer to the private working
repository. This public repository is a filtered mirror of it, so hashes
differ, but the order of pre-registration, first run and report is preserved
in the commit timestamps above.

## Rights and licence

The book is non-commercial and will be distributed free of charge. A formal
licence for the text and the code will be attached by the author before
release; until then all rights are reserved. Third-party data remain under
their own terms, recorded per series in the private working repository; the
book cites the source and the route for every number instead of redistributing
the series. Material derived from the original commercial course is kept out of
this public repository, including its history.

## Authors

- **Volodymyr Biesov**, Principal Investigator, European University;
  [AICryptoCoin](https://github.com/AICryptoCoin) on GitHub.
- **Claude** (Anthropic), AI co-author, in the role described in the
  [AI co-authorship statement](#ai-co-authorship-statement).
