#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kompozit-zamenitel ISM iz pyati regionalnyh obzorov FRB.

Vtoroy rezultat zadachi Z06: pereispolzuemyy ryad, kotoryy Z05 podstavit
vmesto tryoh vhodov ISM v os MACRO (cheatsheet-spec.md sec.1.4.4).

Vsyo v ASCII: konsol' etoy mashiny v cp1251, i padat' na em-dash pri pechati
otchyota -- glupyy sposob poteryat' rezultat.

Konstrukciya zafiksirovana v HYPOTHESIS.md sec.3 DO raschyota:

  shag 1  kazhdaya panel' standartizuetsya po obshchemu oknu W_ref
          (2004-06 .. posledniy obshchiy mesyac, bez kovidnyh mesyacev),
          gde prisutstvuyut vse pyat' paneley -- poetomu sigma sopostavimy;
  shag 2  na nesbalansirovannoy paneli MNK-ocenka z_jt = c_t + b_j + e_jt
          (dvustoronnie fiksirovannye effekty, normirovka sum_j b_j = 0);
  shag 3  c_t centriruetsya na W_ref.

Pochemu imenno tak: b_j pogloshchaet sobstvennyy uroven' paneli celikom,
i poyavlenie novoy paneli v mesyace T ne sdvigaet c_T otnositel'no c_{T-1}.
Naivnoe srednee dostupnyh paneley sdvinulo by uroven' rovno tam, gde smenilsya
sostav, i Bai-Perron nashyol by "strukturnyy razryv" v artefakte konstrukcii.

Dve alternativnye konstrukcii (tozhe pred-registrirovany, HYPOTHESIS.md sec.3.3):
  CHAIN -- cepnoe svyazyvanie prirashcheniy;
  BAL   -- prostoe srednee po sbalansirovannoy paneli s 2004-06.

Ryad pripshpilen k versii dannyh: composite() po umolchaniyu sveryaet zhivuyu
sborku s zafiksirovannoy (composite.csv + blok "pin" v composite-passport.json)
i pri rashozhdenii otkazyvaet, nazyvaya, chto imenno izmenilos'. Podrobno --
v sekcii "Pin" nizhe.

Primer:

    import composite as C
    s = C.composite()                  # Series; libo tot samyy ryad, libo otkaz
    print(s.describe())
    print(C.ladder_contribution(s, C.LADDER_V1))   # vklad c v [-1, +1]

    s = C.composite(pin="frozen")      # ryad, na kotorom poschitan REPORT.md
    s = C.composite(pin="off")         # svezhie dannye, soznatel'no
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

_HERE = os.path.dirname(os.path.abspath(__file__))
_RESEARCH = os.path.dirname(_HERE)
if _RESEARCH not in sys.path:
    sys.path.insert(0, _RESEARCH)

import sources as S  # noqa: E402  (put' nastraivaetsya vyshe)

__all__ = [
    "PANELS", "BASES", "W_REF_START", "COVID_START", "COVID_END",
    "PRIMARY_START", "LADDER_V1", "LADDER_PREREG_REJECTED_TAU_GDP",
    "panel_series", "composite", "composite_with_passport",
    "ladder_contribution", "level_step",
    "VintageDrift", "RejectedLadder", "pin", "frozen_composite",
    "series_digest",
]


# ---------------------------------------------------------------------------
# Konstanty konstrukcii -- vse iz HYPOTHESIS.md, ni odna ne podobrana po
# rezultatu.
# ---------------------------------------------------------------------------

#: Obshchee okno privedeniya masshtaba: s nego prisutstvuyut vse pyat' paneley.
W_REF_START = "2004-06-01"

#: Kovidnoe pravilo -- doslovno iz Z01/HYPOTHESIS.md sec.4 p.2.
COVID_START = "2020-03-01"
COVID_END = "2021-12-01"

#: Osnovnoe okno: pervyy mesyac, gde paneley ne men'she dvuh (Richmond).
PRIMARY_START = "1993-11-01"

#: Zafiksirovannyy ryad i ego pasport -- oni zhe pin versii dannyh (sm. nizhe).
CSV_PATH = os.path.join(_HERE, "composite.csv")
PASSPORT_PATH = os.path.join(_HERE, "composite-passport.json")

#: Konfiguraciya, k kotoroy otnositsya pin. Vsyo ostal'noe (drugie bazy,
#: konstrukcii, okna) -- diagnostika setki, pinom ne pokryta.
PINNED_CONFIG = {"base": "new_orders", "method": "FE", "drop_covid": True,
                 "start": None}

#: Tochnost', s kotoroy ryad zapisan v composite.csv. Sverka idyot imenno na
#: ney: polnoy tochnosti u zafiksirovannogo ryada net -- v fayl on lyog uzhe
#: okruglyonnym, i delat' vid, chto est', bylo by samoobmanom.
VALUE_FORMAT = "%.6f"


@dataclass(frozen=True)
class Panel:
    """Odna panel' kompozita: kak zagruzit' i kakie kolonki brat'."""

    key: str
    title: str
    start: str
    loader: str                    # imya zagruzchika v sources.py
    columns: dict[str, str]        # baza -> imya kolonki/ryada


PANELS: tuple[Panel, ...] = (
    Panel("philly", "FRB Philadelphia MBOS", "1968-05", "philfed_mbos",
          {"new_orders": "NOC", "headline": "GAC"}),
    Panel("richmond", "FRB Richmond Fifth District", "1993-11", "richmond_fed",
          {"new_orders": "sa_mfg_new_orders_c", "headline": "sa_mfg_composite"}),
    Panel("empire", "FRB New York Empire State", "2001-07", "empire_state",
          {"new_orders": "NOCDISA", "headline": "GACDISA"}),
    Panel("kansas_city", "FRB Kansas City Tenth District", "2001-07", "kansascity_fed",
          {"new_orders": "Versus a Month Ago (seasonally adjusted) / Volume of new orders",
           "headline": "Versus a Month Ago (seasonally adjusted) / Composite Index"}),
    Panel("dallas", "FRB Dallas (via FRED)", "2004-06", "fred",
          {"new_orders": "GROSAMFRBDAL", "headline": "BACTSAMFRBDAL"}),
)

BASES = ("new_orders", "headline", "both")

_PANEL_BY_KEY = {p.key: p for p in PANELS}


# ---------------------------------------------------------------------------
# Zagruzka paneley
# ---------------------------------------------------------------------------

def _month_start(iso: str) -> str:
    """Empire State otdayot daty koncom mesyaca (2001-07-31), ostal'nye --
    nachalom. Bez privedeniya paneli ne soydutsya ni v odnom mesyace."""
    return iso[:8] + "01"


_cache: dict[str, dict[str, S.Series]] = {}


def _load(loader: str, *, force: bool = False) -> dict[str, S.Series]:
    if not force and loader in _cache:
        return _cache[loader]
    fn = getattr(S, loader)
    out = fn(force=force)
    _cache[loader] = out
    return out


def panel_series(panel: str | Panel, base: str, *, force: bool = False) -> S.Series:
    """Odin ryad odnoy paneli, daty normalizovany na pervoe chislo mesyaca.

    ``base`` -- ``new_orders`` libo ``headline`` (``both`` sobiraetsya vyshe,
    iz dvuh ryadov).
    """
    p = panel if isinstance(panel, Panel) else _PANEL_BY_KEY[panel]
    if base not in p.columns:
        raise KeyError(f"panel {p.key}: net bazy {base!r}")
    col = p.columns[base]

    if p.loader == "fred":
        raw = S.fred(col, force=force)
    else:
        book = _load(p.loader, force=force)
        if col not in book:
            raise KeyError(
                f"panel {p.key}: v zagruzchike {p.loader} net kolonki {col!r}; "
                f"est' {sorted(book)[:8]} ... ({len(book)} vsego). "
                f"Veroyatno izmenilas' raskladka faila."
            )
        raw = book[col]

    seen: dict[str, float] = {}
    for d, v in zip(raw.dates, raw.values):
        if v is None:
            continue
        iso = _month_start(d)
        if iso in seen:
            raise ValueError(
                f"panel {p.key}/{base}: na {iso} prishlo bol'she odnogo "
                f"znacheniya -- normalizaciya dat skleila raznye mesyacy"
            )
        seen[iso] = float(v)

    dates = sorted(seen)
    return S.Series(
        series_id=f"Z06-{p.key}-{base}",
        source=p.title,
        title=f"{p.title}: {col}",
        freq="M",
        units="diffusion index",
        sa="SA",
        dates=dates,
        values=[seen[d] for d in dates],
        fetched_at=raw.fetched_at,
        meta={"panel": p.key, "base": base, "column": col, "loader": p.loader},
    )


# ---------------------------------------------------------------------------
# Vspomogatel'naya arifmetika (bez numpy -- ego v okruzhenii net)
# ---------------------------------------------------------------------------

def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _sd(xs: Sequence[float]) -> float:
    """Vyborochnoe standartnoe otklonenie (n-1)."""
    n = len(xs)
    if n < 2:
        raise ValueError("sd: nuzhno ne men'she dvuh nablyudeniy")
    m = _mean(xs)
    return (sum((x - m) ** 2 for x in xs) / (n - 1)) ** 0.5


def is_covid(iso: str) -> bool:
    return COVID_START <= iso <= COVID_END


def _months(start: str, end: str) -> list[str]:
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}-01")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


# ---------------------------------------------------------------------------
# Konstrukciya kompozita
# ---------------------------------------------------------------------------

@dataclass
class Passport:
    """Chto imenno voshlo v ryad -- sostav po mesyacam i proishozhdenie."""

    base: str
    method: str
    drop_covid: bool
    w_ref: tuple[str, str] = ("", "")
    panels: dict[str, dict[str, Any]] = field(default_factory=dict)
    membership: dict[str, list[str]] = field(default_factory=dict)
    sigma_c: float = 0.0
    n_months: int = 0
    fetched_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "method": self.method,
            "drop_covid": self.drop_covid,
            "w_ref": {"start": self.w_ref[0], "end": self.w_ref[1]},
            "panels": self.panels,
            "membership": self.membership,
            "sigma_c": self.sigma_c,
            "n_months": self.n_months,
            "fetched_at": self.fetched_at,
        }


def _standardised(base: str, *, drop_covid: bool, force: bool
                  ) -> tuple[dict[str, dict[str, float]], Passport]:
    """Panels -> {panel: {month: z}}, masshtab privedyon na obshchem okne."""
    if base == "both":
        parts = {}
        for sub in ("new_orders", "headline"):
            z, _ = _standardised(sub, drop_covid=drop_covid, force=force)
            parts[sub] = z
        merged: dict[str, dict[str, float]] = {}
        for sub, z in parts.items():
            for pk, series in z.items():
                for d, v in series.items():
                    merged.setdefault(pk, {}).setdefault(d, [])
                    merged[pk][d].append(v)  # type: ignore[union-attr]
        out = {pk: {d: _mean(vs) for d, vs in ser.items()}  # type: ignore[arg-type]
               for pk, ser in merged.items()}
        pp = Passport(base=base, method="", drop_covid=drop_covid)
        return out, pp

    raw: dict[str, S.Series] = {}
    for p in PANELS:
        raw[p.key] = panel_series(p, base, force=force)

    # Obshchee okno: s W_REF_START do poslednego mesyaca, gde est' VSE paneli.
    common_end = min(s.dates[-1] for s in raw.values())
    w_ref = [d for d in _months(W_REF_START, common_end)
             if not (drop_covid and is_covid(d))]
    w_ref_set = set(w_ref)

    pp = Passport(base=base, method="", drop_covid=drop_covid,
                  w_ref=(w_ref[0], w_ref[-1]),
                  fetched_at=max(s.fetched_at for s in raw.values()))

    out: dict[str, dict[str, float]] = {}
    for p in PANELS:
        s = raw[p.key]
        vals = {d: v for d, v in zip(s.dates, s.values) if v is not None}
        ref = [vals[d] for d in w_ref if d in vals]
        if len(ref) < 24:
            raise ValueError(
                f"panel {p.key}: na obshchem okne vsego {len(ref)} tochek -- "
                f"masshtab na takom okne privodit' nel'zya"
            )
        mu, sd = _mean(ref), _sd(ref)
        out[p.key] = {d: (v - mu) / sd for d, v in vals.items()}
        pp.panels[p.key] = {
            "title": p.title,
            "column": s.meta["column"],
            "loader": s.meta["loader"],
            "first": s.dates[0],
            "last": s.dates[-1],
            "n": len(vals),
            "mu_ref": mu,
            "sd_ref": sd,
            "n_ref": len(ref),
            "fetched_at": s.fetched_at,
        }
    return out, pp


def _fit_fe(z: dict[str, dict[str, float]], months: list[str],
            fit_months: list[str] | None = None
            ) -> tuple[dict[str, float], dict[str, float]]:
    """MNK dlya z_jt = c_t + b_j: poperemennyy MNK do shodimosti.

    Normirovka sum_j b_j = 0. Model' additivnaya, poetomu poperemennyy MNK
    shoditsya geometricheski, a tochka edinstvenna s tochnost'yu do
    konstanty, kotoruyu i fiksiruet normirovka.

    ``fit_months`` -- mesyacy, po kotorym ocenivayutsya smeshcheniya paneley
    ``b_j``. Kovidnye mesyacy iz nih isklyuchayutsya: inache vybros 2020 goda
    popadaet v postoyannuyu paneli i tyanet za soboy VES' ryad, a ne tol'ko
    te mesyacy, kotorye pravilo isklyucheniya i sobiralos' vybrosit'.
    ``c_t`` posle etogo schitaetsya dlya VSEH mesyacev pri uzhe fiksirovannyh
    ``b_j`` -- kovidnye tochki ryada nuzhny Z05, prosto v kalibrovku ne idut.
    """
    keys = sorted(z)
    fit = list(months) if fit_months is None else list(fit_months)
    fit_set = set(fit)
    b = {k: 0.0 for k in keys}
    c = {t: 0.0 for t in fit}
    by_month = {t: [k for k in keys if t in z[k]] for t in fit}
    by_panel = {k: [t for t in z[k] if t in fit_set] for k in keys}

    for _ in range(10_000):
        delta = 0.0
        for t in fit:
            ks = by_month[t]
            if not ks:
                continue
            new = _mean([z[k][t] - b[k] for k in ks])
            delta = max(delta, abs(new - c[t]))
            c[t] = new
        for k in keys:
            ts = by_panel[k]
            if not ts:
                continue
            new = _mean([z[k][t] - c[t] for t in ts])
            delta = max(delta, abs(new - b[k]))
            b[k] = new
        shift = _mean([b[k] for k in keys])
        for k in keys:
            b[k] -= shift
        for t in fit:
            c[t] += shift
        if delta < 1e-12:
            break

    # Uroven' dlya vseh mesyacev pri fiksirovannyh smeshcheniyah paneley.
    out: dict[str, float] = {}
    for t in months:
        ks = [k for k in keys if t in z[k]]
        if ks:
            out[t] = _mean([z[k][t] - b[k] for k in ks])
    return out, b


def _fit_chain(z: dict[str, dict[str, float]], months: list[str]) -> dict[str, float]:
    """Cepnoe svyazyvanie: novaya panel' v prirashchenie ne vhodit."""
    c: dict[str, float] = {months[0]: 0.0}
    for prev, cur in zip(months, months[1:]):
        both = [k for k in z if prev in z[k] and cur in z[k]]
        step = _mean([z[k][cur] - z[k][prev] for k in both]) if both else 0.0
        c[cur] = c[prev] + step
    return c


def _fit_balanced(z: dict[str, dict[str, float]], months: list[str]) -> dict[str, float]:
    """Prostoe srednee po sbalansirovannoy paneli: sostav ne menyaetsya."""
    out: dict[str, float] = {}
    keys = sorted(z)
    for t in months:
        if all(t in z[k] for k in keys):
            out[t] = _mean([z[k][t] for k in keys])
    return out


def composite_with_passport(base: str = "new_orders", *, method: str = "FE",
                            drop_covid: bool = True, start: str | None = None,
                            force: bool = False, pin: str = "check"
                            ) -> tuple[S.Series, Passport]:
    """Ryad kompozita i ego pasport.

    ``method``: ``FE`` (osnovnoy), ``CHAIN``, ``BAL`` -- HYPOTHESIS.md sec.3.
    ``start``: nachalo ryada; po umolchaniyu PRIMARY_START dlya FE/CHAIN
    i W_REF_START dlya BAL.
    ``pin``: ``check`` (sverit' s zafiksirovannoy versiey dannyh i otkazat'
    pri rashozhdenii), ``frozen`` (vzyat' zafiksirovannyy ryad, v set' ne
    hodit'), ``off`` (zhivaya sborka bez sverki). Sm. sekciyu "Pin".
    """
    if base not in BASES:
        raise ValueError(f"base: ozhidalos' odno iz {BASES}, polucheno {base!r}")
    if method not in ("FE", "CHAIN", "BAL"):
        raise ValueError(f"method: ozhidalos' FE|CHAIN|BAL, polucheno {method!r}")
    if pin not in ("check", "frozen", "off"):
        raise ValueError(f"pin: ozhidalos' check|frozen|off, polucheno {pin!r}")

    applies = _pin_applies(base, method, drop_covid, start)
    if pin == "frozen":
        if not applies:
            raise ValueError(
                f"pin='frozen' est' tol'ko dlya postavlyaemoy konfiguracii "
                f"{PINNED_CONFIG}; zaprosheno base={base!r} method={method!r} "
                f"drop_covid={drop_covid} start={start!r}. Dlya nee -- pin='off'"
            )
        return frozen_composite(), _frozen_passport()

    z, pp = _standardised(base, drop_covid=drop_covid, force=force)
    pp.method = method
    if base == "both":
        # pasport dlya 'both' sobiraetsya iz podryadov
        sub, sub_pp = _standardised("new_orders", drop_covid=drop_covid, force=force)
        pp.w_ref = sub_pp.w_ref
        pp.panels = sub_pp.panels
        pp.fetched_at = sub_pp.fetched_at

    if start is None:
        start = W_REF_START if method == "BAL" else PRIMARY_START
    end = max(max(v) for v in z.values())
    months = _months(start, end)

    if method == "FE":
        live = [t for t in months if any(t in z[k] for k in z)]
        fit = [t for t in live if not (drop_covid and is_covid(t))]
        c, b = _fit_fe(z, live, fit)
        for k, v in b.items():
            pp.panels.setdefault(k, {})["fe_offset"] = v
    elif method == "CHAIN":
        c = _fit_chain(z, [t for t in months if any(t in z[k] for k in z)])
    else:
        c = _fit_balanced(z, months)

    # Yakor': srednee po W_ref = 0.
    w_ref = [d for d in _months(*pp.w_ref) if d in c and not (drop_covid and is_covid(d))]
    if not w_ref:
        raise ValueError("yakor': obshchee okno pusto")
    anchor = _mean([c[d] for d in w_ref])
    dates = sorted(c)
    values = [c[d] - anchor for d in dates]

    body = [v for d, v in zip(dates, values) if not (drop_covid and is_covid(d))]
    pp.sigma_c = _sd(body)
    pp.n_months = len(dates)
    pp.membership = {}
    for d in dates:
        pp.membership[d] = sorted(k for k in z if d in z[k])

    s = S.Series(
        series_id=f"Z06-COMPOSITE-{base}-{method}",
        source="Z06: FRB regional surveys composite (Philly, Richmond, Empire, KC, Dallas)",
        title=f"ISM-replacement composite ({base}, {method})",
        freq="M",
        units="sd of panel diffusion indices (0 = mean of 2004-06+ window)",
        sa="SA",
        dates=dates,
        values=values,
        fetched_at=pp.fetched_at,
        meta={"base": base, "method": method, "drop_covid": drop_covid,
              "sigma_c": pp.sigma_c, "w_ref": list(pp.w_ref),
              "panels": [p.key for p in PANELS]},
    )
    if pin == "check" and applies:
        _verify_pin(s, pp)
    return s, pp


def composite(base: str = "new_orders", *, method: str = "FE",
              drop_covid: bool = True, start: str | None = None,
              force: bool = False, pin: str = "check") -> S.Series:
    """Mesyachnyy ryad kompozita. Osnovnaya tochka vhoda dlya Z05.

    ``pin`` -- rezhim sverki s zafiksirovannoy versiey dannyh, sm. sekciyu
    "Pin" nizhe. Po umolchaniyu ``check``: libo rovno tot ryad, chto zapisan
    v composite.csv, libo VintageDrift s perechnem togo, chto izmenilos'.
    """
    return composite_with_passport(base, method=method, drop_covid=drop_covid,
                                   start=start, force=force, pin=pin)[0]


# ---------------------------------------------------------------------------
# Pin: privyazka ryada k versii dannyh
# ---------------------------------------------------------------------------
#
# Zachem. Ryad sobiraetsya iz zhivyh istochnikov, i oni peresmatrivayutsya.
# Progon 2026-08-01 pokazal eto pryamo: Richmond zadnim chislom peresmotrel
# istoriyu i opublikoval tochku 2026-07, iz-za chego obshchee okno privedeniya
# masshtaba W_ref sdvinulos' 2026-06 -> 2026-07 i sdvinulis' VSE 393 znacheniya
# (srednee |Delta| = 0.0101 = 0.0118 sigma_c, max |Delta| = 0.1246 = 0.145
# sigma_c). Sama sborka pri etom detreminirovana: dva progona s pustogo kesha
# dayut pobitovo odno i to zhe.
#
# Dreyf ot peresmotra istochnika -- ne oshibka. Oshibka -- kogda on molchit.
#
# Kak ustroeno. Pin -- eto DVA fayla ryadom s modulem, a ne tretiy spisok chisel:
#   composite.csv              -- sam zafiksirovannyy ryad (393 stroki);
#   composite-passport.json    -- klyuch "pin": granicy W_ref, poslednyaya data
#                                 i mu/sd kazhdoy paneli, sostav, sha256 ryada.
# Duplicirovat' te zhe chisla tret'im mestom v kode znachilo by zavesti tretiy
# istochnik pravdy; pin chitaetsya iz pasporta.
#
# Rezhimy:
#   pin="check"  (po umolchaniyu) -- sobrat' zhivoy ryad i sverit'. Sovpal ->
#                vernut'; ne sovpal -> VintageDrift s perechnem izmeneniy;
#   pin="frozen" -- vernut' zafiksirovannyy ryad iz composite.csv, v set' ne
#                hodit' vovse. Eto to, na chyom poschitan REPORT.md;
#   pin="off"    -- zhivoy ryad bez sverki, dlya togo, kto beryot svezhie dannye
#                soznatel'no (im pol'zuetsya run.py: on pin i perezapisyvaet).
#
# Sverka idyot po tochnosti, s kotoroy ryad zapisan (VALUE_FORMAT = "%.6f"):
# structurnye fakty (granicy W_ref, poslednyaya data kazhdoy paneli, dliny,
# sostav po mesyacam) -- tochno, znacheniya -- posle formatirovaniya. Sravnivat'
# syrye double bylo by lozhnoy strogost'yu: v fayle ih polnoy tochnosti net.


class VintageDrift(RuntimeError):
    """Zhivaya sborka razoshlas' s zafiksirovannoy versiey dannyh."""


def series_digest(dates: Sequence[str], values: Sequence[float]) -> str:
    """sha256 ryada v toy tochnosti, v kotoroy on zapisan v composite.csv."""
    body = "\n".join(f"{d},{VALUE_FORMAT % v}" for d, v in zip(dates, values))
    return hashlib.sha256(body.encode("ascii")).hexdigest()


_pin_cache: dict[str, Any] | None = None


def _check_passport_ladder(pp: dict[str, Any]) -> None:
    """Lestnica v pasporte obyazana byt' POSTAVLYAEMOY, a ne lyuboy.

    Proverka ne teoreticheskaya: imenno zdes' i lezhala zabrakovannaya lestnica
    po tau_GDP. Podmenit' klyuch obratno -- odna stroka, i bez etoy sverki ona
    proshla by molcha: ryad-to ne menyaetsya.
    """
    lad = pp.get("ladder")
    if not isinstance(lad, dict):
        raise VintageDrift(
            f"{os.path.basename(PASSPORT_PATH)}: net klyucha 'ladder'")
    bad: list[str] = []
    if lad.get("version") != LADDER_V1["version"]:
        bad.append(f"    version: {lad.get('version')!r} protiv "
                   f"{LADDER_V1['version']!r}")
    if lad.get("thresholds") != LADDER_V1["thresholds"]:
        bad.append(f"    thresholds: {lad.get('thresholds')} protiv "
                   f"{LADDER_V1['thresholds']}")
    if lad.get("steps") != LADDER_V1["steps"]:
        bad.append(f"    steps: {lad.get('steps')} protiv {LADDER_V1['steps']}")
    if lad.get("rejected"):
        bad.append("    v klyuche 'ladder' lezhit lestnica s pometkoy "
                   "rejected -- eto ZABRAKOVANNAYA")
    if bad:
        raise VintageDrift(
            f"{os.path.basename(PASSPORT_PATH)} -> 'ladder' ne sovpadaet s "
            f"postavlyaemoy lestnicey composite.LADDER_V1:\n" + "\n".join(bad)
            + "\n  Postavlyaemaya -- dvuhstupenchataya po LINII RECESSII "
              "tau_REC = -0.2004.\n"
              "  Zabrakovannaya (po tau_GDP) zhivyot v klyuche "
              "'ladder_prereg_rejected_tau_GDP'\n"
              "  i v postavku ne vhodit. Privesti v poryadok: python repin.py"
        )


def _check_csv_ladder(dates: Sequence[str], values: Sequence[float],
                      steps: Sequence[str]) -> None:
    """Kolonka L_step obyazana byt' pereschityvaema iz LADDER_V1.

    Bez etoy sverki v L_step mozhno vernut' lyubuyu lestnicu, i sha256 ryada
    etogo ne zametit: on schitaetsya po date+composite. Imenno takim i byl
    defekt do 2026-08-01 -- 110 mesyacev iz 393 nesli chuzhuyu stupen'.
    """
    bad = [(d, want, got) for d, v, got in zip(dates, values, steps)
           if (want := f"{level_step(v, LADDER_V1):+.1f}") != got]
    if bad:
        d, want, got = bad[0]
        raise VintageDrift(
            f"{os.path.basename(CSV_PATH)}: kolonka L_step ne sootvetstvuet "
            f"postavlyaemoy lestnice {LADDER_V1['version']} -- rashozhdenie na "
            f"{len(bad)} strokah iz {len(dates)}, pervoe na {d} "
            f"(v fayle {got}, po lestnice {want}). Perechitat': python repin.py"
        )


def pin(*, reload: bool = False) -> dict[str, Any]:
    """Blok "pin" iz composite-passport.json."""
    global _pin_cache
    if _pin_cache is not None and not reload:
        return _pin_cache
    with open(PASSPORT_PATH, encoding="utf-8") as fh:
        pp = json.load(fh)
    if "pin" not in pp:
        raise VintageDrift(
            f"v {os.path.basename(PASSPORT_PATH)} net bloka 'pin': pasport "
            f"sobran staroy versiey. Peresoberite: python repin.py"
        )
    _check_passport_ladder(pp)
    _pin_cache = pp["pin"]
    return _pin_cache


def frozen_composite() -> S.Series:
    """Zafiksirovannyy ryad iz composite.csv. Bez seti i bez peresborki.

    Imenno na nyom poschitan REPORT.md: 393 mesyaca 1993-11 .. 2026-07,
    sigma_c = 0.8577.
    """
    p = pin()
    dates, values, steps = _frozen_rows()
    _check_csv_ladder(dates, values, steps)
    got = series_digest(dates, values)
    want = p["series"]["sha256"]
    if got != want:
        raise VintageDrift(
            f"{os.path.basename(CSV_PATH)} ne sootvetstvuet pinu v pasporte: "
            f"sha256 {got[:16]}... protiv {want[:16]}.... Odin iz dvuh faylov "
            f"pravili v odinochku -- eto i est' ta samaya tihaya podmena ryada"
        )
    return S.Series(
        series_id=f"Z06-COMPOSITE-{PINNED_CONFIG['base']}-{PINNED_CONFIG['method']}",
        source="Z06: FRB regional surveys composite (Philly, Richmond, Empire, KC, Dallas)",
        title=(f"ISM-replacement composite ({PINNED_CONFIG['base']}, "
               f"{PINNED_CONFIG['method']}), pinned {p['frozen_at']}"),
        freq="M",
        units="sd of panel diffusion indices (0 = mean of 2004-06+ window)",
        sa="SA",
        dates=dates,
        values=values,
        fetched_at=p["series"].get("fetched_at", ""),
        meta={"base": PINNED_CONFIG["base"], "method": PINNED_CONFIG["method"],
              "drop_covid": PINNED_CONFIG["drop_covid"],
              "sigma_c": p["series"]["sigma_c"], "w_ref": [p["w_ref"]["start"],
                                                           p["w_ref"]["end"]],
              "panels": [pk.key for pk in PANELS],
              "pinned": True, "frozen_at": p["frozen_at"],
              "sha256": p["series"]["sha256"]},
    )


def _pin_applies(base: str, method: str, drop_covid: bool,
                 start: str | None) -> bool:
    return (base == PINNED_CONFIG["base"] and method == PINNED_CONFIG["method"]
            and drop_covid is PINNED_CONFIG["drop_covid"]
            and start == PINNED_CONFIG["start"])


def _verify_pin(s: S.Series, pp: Passport) -> None:
    """Sverit' zhivuyu sborku s pinom. Rashozhdenie -> VintageDrift s otchyotom."""
    p = pin()   # zaodno sveryaet pasportnuyu lestnicu s LADDER_V1
    _frozen_dates, _frozen_vals, _frozen_steps = _frozen_rows()
    _check_csv_ladder(_frozen_dates, _frozen_vals, _frozen_steps)
    changed: list[str] = []

    # 0. Lestnica v pine obyazana sovpadat' s LADDER_V1 v kode: dva mesta,
    #    odno chislo. Rashozhdenie zdes' opasnee lyubogo dreyfa dannyh.
    if p.get("ladder_version") != LADDER_V1["version"]:
        changed.append(
            f"  lestnica: pasport nesyot '{p.get('ladder_version')}', kod -- "
            f"'{LADDER_V1['version']}'")
    if p.get("ladder_thresholds") != LADDER_V1["thresholds"]:
        changed.append(
            f"  porogi lestnicy: pasport {p.get('ladder_thresholds')}, "
            f"kod {LADDER_V1['thresholds']}")

    # 1. Granicy okna privedeniya masshtaba.
    if [pp.w_ref[0], pp.w_ref[1]] != [p["w_ref"]["start"], p["w_ref"]["end"]]:
        changed.append(
            f"  W_ref: bylo [{p['w_ref']['start']} .. {p['w_ref']['end']}], "
            f"stalo [{pp.w_ref[0]} .. {pp.w_ref[1]}]")

    # 2. Poslednyaya data kazhdoy paneli -- imenno ona dvigaet W_ref.
    for key in sorted(set(p["panels"]) | set(pp.panels)):
        was = p["panels"].get(key, {})
        now = pp.panels.get(key, {})
        if not was:
            changed.append(f"  panel' {key}: poyavilas' (v pine eyo net)")
            continue
        if not now:
            changed.append(f"  panel' {key}: ischezla (v pine byla)")
            continue
        if was["last"] != now["last"]:
            changed.append(
                f"  panel' {key}: poslednyaya tochka {was['last']} -> {now['last']}")
        if was["n"] != now["n"]:
            changed.append(f"  panel' {key}: nablyudeniy {was['n']} -> {now['n']}")
        for fld in ("mu_ref", "sd_ref", "n_ref"):
            a, b = was.get(fld), now.get(fld)
            if a is None or b is None or a == b:
                continue
            if isinstance(a, float) and abs(b - a) <= 1e-12 * max(1.0, abs(a)):
                continue
            changed.append(f"  panel' {key}: {fld} {a!r} -> {b!r}")

    # 3. Sam ryad -- v toy tochnosti, v kotoroy on zapisan.
    vals = [v for v in s.values if v is not None]
    if len(s.dates) != p["series"]["n"]:
        changed.append(f"  dlina ryada: {p['series']['n']} -> {len(s.dates)}")
    if s.dates and (s.dates[0] != p["series"]["first"]
                    or s.dates[-1] != p["series"]["last"]):
        changed.append(
            f"  granicy ryada: [{p['series']['first']} .. {p['series']['last']}]"
            f" -> [{s.dates[0]} .. {s.dates[-1]}]")
    got = series_digest(s.dates, vals)
    if got != p["series"]["sha256"]:
        changed.append(f"  sha256 ryada: {p['series']['sha256'][:16]}... -> "
                       f"{got[:16]}...")
        frozen = dict(zip(_frozen_dates, _frozen_vals))
        common = [d for d in s.dates if d in frozen]
        live = dict(zip(s.dates, vals))
        deltas = [(abs(live[d] - frozen[d]), d) for d in common]
        if deltas:
            worst, worst_d = max(deltas)
            avg = sum(x for x, _ in deltas) / len(deltas)
            sig = pp.sigma_c or 1.0
            n_diff = sum(1 for x, _ in deltas
                         if VALUE_FORMAT % x != VALUE_FORMAT % 0.0)
            changed.append(
                f"  znacheniya: razoshlis' {n_diff} iz {len(common)} obshchih "
                f"mesyacev; srednee |Delta| = {avg:.6f} ({avg / sig:.4f} sigma_c), "
                f"max |Delta| = {worst:.6f} ({worst / sig:.4f} sigma_c) na {worst_d}")

    if not changed:
        return

    raise VintageDrift(
        "ZHIVAYA SBORKA RAZOSHLAS' S ZAFIKSIROVANNOY VERSIEY DANNYH.\n"
        f"Pin: {p['version']}, zafiksirovan {p['frozen_at']} "
        f"(progon Z06, REPORT.md poschitan na nyom).\n"
        "Chto izmenilos':\n" + "\n".join(changed) + "\n"
        "\nEto ne polomka koda: regional'nye obzory FRB peresmatrivayutsya\n"
        "zadnim chislom, i lyubaya novaya tochka dvigaet okno W_ref, a s nim\n"
        "ves' ryad. Dal'she -- vybor, i on soznatel'nyy:\n"
        "  composite(pin='frozen')  -- ryad, na kotorom poschitan REPORT.md;\n"
        "  composite(pin='off')     -- svezhie dannye, chisla otchyota k nim\n"
        "                              ne otnosyatsya;\n"
        "  python repin.py --rebuild -- perepinit' na svezhuyu versiyu; togda\n"
        "                              chisla REPORT.md nado pereschityvat',\n"
        "                              a eto pereschyot vsey zadachi Z06."
    )


def _frozen_passport() -> Passport:
    """Pasport zafiksirovannogo ryada -- iz togo zhe fayla, chto i pin."""
    with open(PASSPORT_PATH, encoding="utf-8") as fh:
        raw = json.load(fh)
    pp = Passport(base=raw["base"], method=raw["method"],
                  drop_covid=raw["drop_covid"],
                  w_ref=(raw["w_ref"]["start"], raw["w_ref"]["end"]),
                  panels=raw["panels"], membership=raw["membership"],
                  sigma_c=raw["sigma_c"], n_months=raw["n_months"],
                  fetched_at=raw["fetched_at"])
    return pp


def _frozen_rows() -> tuple[list[str], list[float], list[str]]:
    dates: list[str] = []
    values: list[float] = []
    steps: list[str] = []
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            dates.append(row["date"])
            values.append(float(row["composite"]))
            steps.append(row["L_step"])
    return dates, values, steps


# ---------------------------------------------------------------------------
# Perevod urovnya kompozita vo vklad c iz [-1, +1] (cheatsheet-spec sec.1.4.1)
# ---------------------------------------------------------------------------

#: POSTAVLYAEMAYA lestnica -- ta, kotoruyu beryot Z05.
#:
#: Odin porog: **LINIYA RECESSII** tau_REC = -0.2004 (= -0.234 sigma_c).
#: Podpis' imenno takaya, i eto ne pridirka k slovu: porog poluchen Yudenom
#: protiv razmetki NBER (USREC, AUC 0.9155), a NE regressiey na rost. Nazvat'
#: ego "liniey nulevogo rosta" znachilo by uvezti v speku chislo s chuzhoy
#: podpis'yu -- rovno tu oshibku, kotoruyu Z06 i izmeril (REPORT sec.10.2).
#:
#: Pred-registrirovannyy zapasnoy variant rezal po tau_GDP; tot zhe progon ego
#: i zabrakoval (interval shiriny 4.07 sigma_c, 97.2 % / 2.8 % po mesyacam).
#: On lezhit nizhe pod imenem LADDER_PREREG_REJECTED_TAU_GDP i v postavku
#: NE vhodit.
#:
#: Chisla -- iz result.json -> ladder_practical (progon 2026-07-28, zerno
#: 20260728). Reshenie prinyato POSLE raschyota: HYPOTHESIS.md sec.10 Zapis' 4.
LADDER_V1: dict[str, Any] = {
    "version": "Z06-v1-practical",
    "kind": "2-step",
    "post_hoc": True,
    "base": "new_orders",
    "method": "FE",
    "units": "urovni kompozita (sd paneley); v skobkah -- v sigma_c",
    "threshold_name": "liniya recessii (tau_REC)",
    "threshold_origin": "Yuden protiv razmetki NBER (USREC), AUC 0.9155, n=370",
    "not_a_zero_growth_line": True,
    "sigma_c": 0.8576927115012422,
    #: [(nizhnyaya granica ili None, verhnyaya ili None, L)]
    "steps": [
        [-0.2004379668757319, None, 1.0],
        [None, -0.2004379668757319, -1.0],
    ],
    "thresholds": [-0.2004379668757319],
    "tau": {"tau_REC": -0.2004379668757319},
    "tau_sigma": {"tau_REC": -0.23369438050242963},
    "ci90": {"tau_REC": [-0.5612663139635263, -0.18912377672497938]},
    "month_counts": {"1.0": 272, "-1.0": 121},
}

#: ZABRAKOVANNAYA lestnica -- pred-registrirovannyy zapasnoy variant (sec.4.3)
#: po tau_GDP. Imya dlinnoe naroko: vzyat' eyo po oshibke vmesto LADDER_V1
#: nel'zya. Hranitsya radi vosproizvodimosti otchyota, a ne radi primeneniya.
#: Rashozhdenie s postavlyaemoy: 110 mesyacev iz 390 dayut raznyy vklad c.
LADDER_PREREG_REJECTED_TAU_GDP: dict[str, Any] = {
    "version": "Z06-v1",
    "kind": "two",
    "rejected": True,
    "rejected_why": ("tau_GDP ne identificiruem: shirina 90% intervala "
                     "4.07 sigma_c protiv trebuemyh <1.0; stupen' po nemu "
                     "delit istoriyu 382 / 11 (97.2% / 2.8%)"),
    "base": "new_orders",
    "method": "FE",
    "units": "urovni kompozita (sd paneley); v skobkah -- v sigma_c",
    "sigma_c": 0.8576927115012422,
    "steps": [
        [-1.6805696557314669, None, 1.0],
        [None, -1.6805696557314669, -1.0],
    ],
    "tau": {"tau_MFG": -0.3180357578644856,
            "tau_GDP": -1.6805696557314669,
            "tau_REC": -0.2004379668757319},
    "tau_sigma": {"tau_MFG": -0.3708038480446211,
                  "tau_GDP": -1.959407644714529,
                  "tau_REC": -0.23369438050242963},
    "ci90": {"tau_MFG": [-1.3494127499915503, 0.07142946351669625],
             "tau_GDP": [-4.4515009516002, -0.9576694400597762],
             "tau_REC": [-0.5612663139635263, -0.18912377672497938]},
    "month_counts": {"1.0": 382, "-1.0": 11},
}


class RejectedLadder(ValueError):
    """Popytka schitat' vklad po ZABRAKOVANNOY lestnice."""


def _refuse_rejected(ladder: dict[str, Any], allow_rejected: bool) -> None:
    """Zabrakovannaya lestnica obyazana padat', a ne schitat'sya molcha.

    Do 2026-08-02 zashchity ne bylo vovse: pometka ``rejected`` stoyala tol'ko
    v konstante LADDER_PREREG_REJECTED_TAU_GDP i v pasporte, a v
    ``result.json -> 'ladder'`` -- ne stoyala. Vyzov
    ``ladder_contribution(s, result['ladder'])`` otrabatyval bez edinoy oshibki
    i tiho otdaval vklad po porogu tau_GDP = -1.6806, kotoryy tot zhe progon
    Z06 i zabrakoval: rashozhdenie s postavlyaemoy -- 110 mesyacev iz 390.
    Klyuch s samym ochevidnym imenem vyol v brak, i eto ne lovilos' nichem.

    ``allow_rejected=True`` -- edinstvennaya dver', i otkryvat' eyo est'
    ravno odna prichina: vosproizvesti chislo otchyota po zabrakovannoy
    lestnice (raspredelenie mesyacev po eyo stupenyam v Z06/run.py sec.8).
    """
    if not ladder.get("rejected") or allow_rejected:
        return
    why = ladder.get("rejected_why") or "prichina v lestnice ne zapisana"
    raise RejectedLadder(
        f"lestnica {ladder.get('version', '?')!r} pomechena rejected -- eto "
        f"ZABRAKOVANNAYA lestnica po tau_GDP, v postavku ona ne vhodit.\n"
        f"  pochemu zabrakovana: {why}\n"
        f"  brat' nado POSTAVLYAEMUYU: result.json -> 'ladder_practical'\n"
        f"    (ona zhe composite.LADDER_V1, ona zhe "
        f"composite-passport.json -> 'ladder')\n"
        f"    -- dvuhstupenchataya po LINII RECESSII tau_REC = -0.2004.\n"
        f"  Vnimanie na imena: v result.json korotkiy klyuch 'ladder' nesyot "
        f"imenno ZABRAKOVANNUYU,\n"
        f"  a postavlyaemaya lezhit v 'ladder_practical'. Imenno poetomu zdes' "
        f"otkaz, a ne chislo.\n"
        f"  Esli vklad po zabrakovannoy nuzhen radi vosproizvedeniya otchyota "
        f"-- prosite yavno:\n"
        f"    level_step(..., allow_rejected=True) / "
        f"ladder_contribution(..., allow_rejected=True)"
    )


def level_step(value: float, ladder: dict[str, Any], *,
               allow_rejected: bool = False) -> float:
    """Uroven' kompozita -> L (analog chetyryoh stupeney sec.1.4.1)."""
    _refuse_rejected(ladder, allow_rejected)
    if not ladder.get("steps"):
        raise ValueError(
            "lestnica ne zapolnena: postavlyaemaya lezhit v composite.LADDER_V1 "
            "(ona zhe result.json -> ladder_practical, ona zhe "
            "composite-passport.json -> ladder). Klyuch result.json -> ladder "
            "-- ETO ZABRAKOVANNAYA lestnica po tau_GDP, v postavku ona ne vhodit"
        )
    for lo, hi, L in ladder["steps"]:
        if (lo is None or value > lo) and (hi is None or value <= hi):
            return float(L)
    raise ValueError(f"uroven' {value} ne popal ni v odnu stupen'")


def ladder_contribution(series: S.Series, ladder: dict[str, Any],
                        *, delta_months: int = 3,
                        allow_rejected: bool = False) -> S.Series:
    """Vklad vhoda: c = 0.6*sign(Delta_3m) + 0.4*L (cheatsheet-spec sec.1.4.1).

    Formula ne menyaetsya -- menyaetsya tol'ko lestnica L, i tol'ko ona
    otkalibrovana v Z06.

    Zabrakovannaya lestnica (pometka ``rejected``) zdes' NE schitaetsya:
    otkaz vydayotsya do pervogo znacheniya, chtoby ne poluchilos' ryada,
    kotoryy vyglyadit gotovym. Sm. ``_refuse_rejected``.
    """
    _refuse_rejected(ladder, allow_rejected)
    vals = {d: v for d, v in zip(series.dates, series.values) if v is not None}
    dates = sorted(vals)
    idx = {d: i for i, d in enumerate(dates)}
    out_d: list[str] = []
    out_v: list[float | None] = []
    for d in dates:
        i = idx[d]
        if i < delta_months:
            continue
        delta = vals[d] - vals[dates[i - delta_months]]
        sign = 0.0 if delta == 0 else (1.0 if delta > 0 else -1.0)
        out_d.append(d)
        out_v.append(0.6 * sign
                     + 0.4 * level_step(vals[d], ladder,
                                        allow_rejected=allow_rejected))
    return S.Series(
        series_id=f"{series.series_id}-CONTRIB",
        source=series.source,
        title=f"{series.title}: contribution c in [-1, +1]",
        freq="M", units="contribution", sa=series.sa,
        dates=out_d, values=out_v, fetched_at=series.fetched_at,
        meta={"ladder": ladder.get("version", ""), "delta_months": delta_months},
    )


#: Harakternye mesyacy dlya demonstracii vklada: po odnomu na kazhdyy sluchay,
#: kotoryy formula dolzhna razlichat'.
DEMO_MONTHS: tuple[tuple[str, str], ...] = (
    ("1994-06-01", "podyom 1994 goda, dvuhpanel'naya epoha"),
    ("1995-06-01", "proval 1995 goda: nizhe linii recessii, recessii NBER net"),
    ("2001-11-01", "posledniy mesyac recessii 2001 po NBER"),
    ("2004-06-01", "mesyac, kogda v kompozit voshyol Dallas"),
    ("2008-12-01", "krizis 2008; samyy nizkiy mesyac vne kovida -- 2009-03, -2.8656"),
    ("2009-06-01", "razvorot posle krizisa: uroven' nizhe linii, znak uzhe vverh"),
    ("2020-04-01", "kovidnyy vybros (v kalibrovku ne shyol, v ryade ostalsya)"),
    ("2022-06-01", "nachalo serii nizhe linii recessii bez recessii NBER"),
    ("2024-12-01", "konec toy zhe serii -- 31 mesyac podryad"),
    ("2026-07-01", "poslednyaya tochka zafiksirovannogo ryada"),
)


def _demo() -> None:
    print("=" * 78)
    print("1. Zhivaya sborka protiv zafiksirovannoy versii dannyh (pin='check')")
    print("=" * 78)
    try:
        composite_with_passport()
        print("sovpalo pobitovo: zhivaya sborka ravna zafiksirovannomu ryadu")
    except VintageDrift as exc:
        print(exc)

    print("")
    print("=" * 78)
    print("2. Zafiksirovannyy ryad (pin='frozen') -- na nyom poschitan REPORT.md")
    print("=" * 78)
    s, pp = composite_with_passport(pin="frozen")
    print(s.describe())
    print(f"sigma_c = {pp.sigma_c:.4f}, mesyacev = {pp.n_months}")
    print("sostav na starte:", pp.membership[s.dates[0]])
    print("sostav na konce :", pp.membership[s.dates[-1]])

    print("")
    print("=" * 78)
    print("3. Lestnica i vklad c = 0.6*sign(Delta_3m) + 0.4*L")
    print("=" * 78)
    lad = LADDER_V1
    tau = lad["thresholds"][0]
    print(f"lestnica {lad['version']}: porog {tau:+.4f} = "
          f"{tau / lad['sigma_c']:+.3f} sigma_c -- {lad['threshold_name']}")
    print(f"proishozhdenie: {lad['threshold_origin']}")
    for lo, hi, L in lad["steps"]:
        lo_s = f"{lo:+.4f}" if lo is not None else "  -inf"
        hi_s = f"{hi:+.4f}" if hi is not None else "  +inf"
        print(f"  {lo_s} < c <= {hi_s}   L = {L:+.1f}")

    contrib = ladder_contribution(s, lad)
    cv = dict(zip(contrib.dates, contrib.values))
    lv = dict(zip(s.dates, s.values))
    print("")
    print(f"{'mesyac':12s} {'uroven':>9s} {'sigma_c':>8s} {'L':>5s} {'vklad c':>8s}"
          f"  poyasnenie")
    for d, why in DEMO_MONTHS:
        v = lv.get(d)
        if v is None:
            continue
        c = cv.get(d)
        c_s = f"{c:+8.2f}" if c is not None else "     n/d"
        print(f"{d:12s} {v:+9.4f} {v / pp.sigma_c:+8.3f} "
              f"{level_step(v, lad):+5.1f} {c_s}  {why}")

    counts: dict[float, int] = {}
    for v in contrib.values:
        if v is not None:
            counts[v] = counts.get(v, 0) + 1
    print("")
    print(f"raspredelenie vklada po {len(contrib.dates)} mesyacam "
          f"(pervye 3 mesyaca ryada bez Delta_3m):")
    for c in sorted(counts, reverse=True):
        print(f"  c = {c:+.2f}: {counts[c]:3d} mes. "
              f"({counts[c] / len(contrib.dates) * 100:.1f}%)")


if __name__ == "__main__":
    _demo()
