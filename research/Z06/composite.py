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

Primer:

    import composite as C
    s = C.composite()                  # Series, ryad kompozita
    print(s.describe())
    print(C.ladder_contribution(s, C.LADDER_V1))   # vklad c v [-1, +1]
"""

from __future__ import annotations

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
    "PRIMARY_START", "LADDER_V1",
    "panel_series", "composite", "composite_with_passport",
    "ladder_contribution", "level_step",
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
                            force: bool = False) -> tuple[S.Series, Passport]:
    """Ryad kompozita i ego pasport.

    ``method``: ``FE`` (osnovnoy), ``CHAIN``, ``BAL`` -- HYPOTHESIS.md sec.3.
    ``start``: nachalo ryada; po umolchaniyu PRIMARY_START dlya FE/CHAIN
    i W_REF_START dlya BAL.
    """
    if base not in BASES:
        raise ValueError(f"base: ozhidalos' odno iz {BASES}, polucheno {base!r}")
    if method not in ("FE", "CHAIN", "BAL"):
        raise ValueError(f"method: ozhidalos' FE|CHAIN|BAL, polucheno {method!r}")

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
    return s, pp


def composite(base: str = "new_orders", *, method: str = "FE",
              drop_covid: bool = True, start: str | None = None,
              force: bool = False) -> S.Series:
    """Mesyachnyy ryad kompozita. Osnovnaya tochka vhoda dlya Z05."""
    return composite_with_passport(base, method=method, drop_covid=drop_covid,
                                   start=start, force=force)[0]


# ---------------------------------------------------------------------------
# Perevod urovnya kompozita vo vklad c iz [-1, +1] (cheatsheet-spec sec.1.4.1)
# ---------------------------------------------------------------------------

#: Otkalibrovannaya lestnica. Znacheniya podstavlyayutsya run.py posle
#: raschyota; zdes' lezhit forma, a ne chisla iz vozduha.
LADDER_V1: dict[str, Any] = {
    "version": "",
    "base": "",
    "method": "",
    "units": "",
    "steps": [],       # [(nizhnyaya granica ili None, verhnyaya ili None, L)]
    "tau": {},
}


def level_step(value: float, ladder: dict[str, Any]) -> float:
    """Uroven' kompozita -> L (analog chetyryoh stupeney sec.1.4.1)."""
    if not ladder.get("steps"):
        raise ValueError(
            "lestnica ne zapolnena: podstav'te otkalibrovannuyu iz "
            "Z06/result.json -> ladder"
        )
    for lo, hi, L in ladder["steps"]:
        if (lo is None or value > lo) and (hi is None or value <= hi):
            return float(L)
    raise ValueError(f"uroven' {value} ne popal ni v odnu stupen'")


def ladder_contribution(series: S.Series, ladder: dict[str, Any],
                        *, delta_months: int = 3) -> S.Series:
    """Vklad vhoda: c = 0.6*sign(Delta_3m) + 0.4*L (cheatsheet-spec sec.1.4.1).

    Formula ne menyaetsya -- menyaetsya tol'ko lestnica L, i tol'ko ona
    otkalibrovana v Z06.
    """
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
        out_v.append(0.6 * sign + 0.4 * level_step(vals[d], ladder))
    return S.Series(
        series_id=f"{series.series_id}-CONTRIB",
        source=series.source,
        title=f"{series.title}: contribution c in [-1, +1]",
        freq="M", units="contribution", sa=series.sa,
        dates=out_d, values=out_v, fetched_at=series.fetched_at,
        meta={"ladder": ladder.get("version", ""), "delta_months": delta_months},
    )


if __name__ == "__main__":
    s, pp = composite_with_passport()
    print(s.describe())
    print(f"sigma_c = {pp.sigma_c:.4f}, mesyacev = {pp.n_months}")
    print("sostav na starte:", pp.membership[s.dates[0]])
    print("sostav na konce :", pp.membership[s.dates[-1]])
