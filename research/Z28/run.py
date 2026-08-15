#!/usr/bin/env python3
# -*- coding: ascii -*-
"""Z28 -- baseline forecast versus a price-only volatility forecast.

The protocol is fixed in HYPOTHESIS.md at preregistration commit
ff77a79e22d351e41ed4caca5433d9ac5f8b6c61.  Console output is ASCII because
the target Windows console may use cp1251.

Run from the repository root:

    python research/Z28/run.py

The program writes research/Z28/result.json.  Redirect stdout and stderr to
research/Z28/full-run.txt to preserve the complete transcript.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence


HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
REPO = os.path.dirname(RESEARCH)
if RESEARCH not in sys.path:
    sys.path.insert(0, RESEARCH)

import sources as S  # noqa: E402


TASK = "Z28"
BASE_COMMIT = "1ecc3ea5740801c35b448b2c172d1db38955838b"
PREREG_COMMIT = "ff77a79e22d351e41ed4caca5433d9ac5f8b6c61"
PREREG_TIME = "2026-08-15T15:49:48+03:00"
SEED = 20260815
HORIZON = 12
WARMUP = 120
VOL_WINDOW = 12
ACF_MAX_LAG = 24
FIXED_OVERLAP_LAG = 11
BOOT_BLOCK = 12
BOOT_REPS = 20_000
TARGET_EFFECT = 1.0
Z95 = 1.96
TOL = 1e-12

YAHOO_START = "1927-12"
SHILLER_START = "1871-01"
CUT_MONTH = "2026-07"
COMMON_FIRST_ORIGIN = "1937-12"
LAST_ORIGIN = "2025-07"

RESULT_PATH = os.path.join(HERE, "result.json")


@dataclass(frozen=True)
class TimedValue:
    """A calculated value plus the exact month indices used to know it."""

    value: float
    available_index: int
    source_indices: tuple[int, ...]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def say(*parts: Any) -> None:
    text = " ".join(str(x) for x in parts)
    try:
        print(text)
    except UnicodeEncodeError:  # pragma: no cover - console dependent
        print(text.encode("ascii", "replace").decode("ascii"))
    sys.stdout.flush()


def head(title: str) -> None:
    say("")
    say("=" * 78)
    say(title)
    say("=" * 78)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def month_number(month: str) -> int:
    year, mon = int(month[:4]), int(month[5:7])
    require(1 <= mon <= 12, "invalid month: %s" % month)
    return year * 12 + mon - 1


def month_from_number(number: int) -> str:
    return "%04d-%02d" % (number // 12, number % 12 + 1)


def add_months(month: str, count: int) -> str:
    return month_from_number(month_number(month) + count)


def month_range(start: str, end: str) -> list[str]:
    a, b = month_number(start), month_number(end)
    require(a <= b, "month range is reversed")
    return [month_from_number(i) for i in range(a, b + 1)]


def finite(value: Any, label: str) -> float:
    out = float(value)
    require(math.isfinite(out), "%s is not finite" % label)
    return out


def version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=REPO, text=True, encoding="utf-8"
    ).strip()


class FetchTrace:
    """Record every body that a sources.py loader obtains."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._original = None

    def __enter__(self) -> "FetchTrace":
        self._original = S.fetch

        def traced(url: str, *args: Any, **kwargs: Any) -> bytes:
            started = utc_now()
            body = self._original(url, *args, **kwargs)
            finished = utc_now()
            redacted = S._redact(url) if hasattr(S, "_redact") else url
            self.calls.append({
                "tag": kwargs.get("tag"),
                "url": redacted,
                "started_at_utc": started,
                "finished_at_utc": finished,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            })
            return body

        S.fetch = traced
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        require(self._original is not None, "fetch tracer was not entered")
        S.fetch = self._original


def crps_weighted(values: Sequence[float], weights: Sequence[float],
                  outcome: float) -> float:
    require(len(values) == len(weights) and len(values) > 0,
            "weighted CRPS shape mismatch")
    require(abs(math.fsum(weights) - 1.0) <= TOL,
            "weighted CRPS weights do not sum to one")
    first = math.fsum(w * abs(x - outcome) for x, w in zip(values, weights))
    pair = math.fsum(
        wi * wj * abs(xi - xj)
        for xi, wi in zip(values, weights)
        for xj, wj in zip(values, weights)
    )
    return first - 0.5 * pair


def crps_empirical(values: Sequence[float], outcome: float) -> float:
    """O(m log m) CRPS for a uniform empirical ensemble."""
    xs = sorted(values)
    m = len(xs)
    require(m > 0, "empty empirical ensemble")
    first = math.fsum(abs(x - outcome) for x in xs) / m
    half_pair = math.fsum(
        (2 * rank - m - 1) * x for rank, x in enumerate(xs, 1)
    ) / (m * m)
    return first - half_pair


def crps_empirical_direct(values: Sequence[float], outcome: float) -> float:
    """O(m^2) reference implementation used only by instrument controls."""
    m = len(values)
    require(m > 0, "empty direct empirical ensemble")
    first = math.fsum(abs(x - outcome) for x in values) / m
    pair = math.fsum(abs(x - z) for x in values for z in values)
    return first - 0.5 * pair / (m * m)


def chapter_preflight() -> dict[str, Any]:
    outcomes = [-30.0, -20.0, -10.0, 0.0, 10.0, 20.0, 30.0]
    wide_weights = [0.05, 0.10, 0.15, 0.25, 0.20, 0.15, 0.10]
    narrow_values = [0.0, 10.0]
    narrow_weights = [0.70, 0.30]

    wide_at_minus20 = crps_weighted(outcomes, wide_weights, -20.0)
    narrow_at_minus20 = crps_weighted(narrow_values, narrow_weights, -20.0)
    wide_scores = [crps_weighted(outcomes, wide_weights, y) for y in outcomes]
    narrow_scores = [
        crps_weighted(narrow_values, narrow_weights, y) for y in outcomes
    ]
    expected_wide = math.fsum(
        w * score for w, score in zip(wide_weights, wide_scores)
    )
    expected_narrow = math.fsum(
        w * score for w, score in zip(wide_weights, narrow_scores)
    )
    expected = {
        "wide_at_minus20": 14.90,
        "narrow_at_minus20": 20.90,
        "expected_wide": 9.10,
        "expected_narrow": 11.20,
    }
    actual = {
        "wide_at_minus20": wide_at_minus20,
        "narrow_at_minus20": narrow_at_minus20,
        "expected_wide": expected_wide,
        "expected_narrow": expected_narrow,
    }
    errors = {key: actual[key] - expected[key] for key in expected}
    require(all(abs(error) <= TOL for error in errors.values()),
            "chapter CRPS preflight failed: %r" % errors)

    paired = [a - b for a, b in zip(wide_scores, narrow_scores)]
    paired_mean = math.fsum(w * x for w, x in zip(wide_weights, paired))
    paired_variance = math.fsum(
        w * (x - paired_mean) ** 2 for w, x in zip(wide_weights, paired)
    )
    require(all(abs(a - b) <= TOL for a, b in zip(
        paired, [-7.0, -6.0, -3.0, 3.0, 0.0, -5.0, -7.0]
    )), "chapter paired differences changed")
    require(abs(paired_variance - 13.89) <= TOL,
            "chapter feasibility variance changed")

    return {
        "tolerance": TOL,
        "expected": expected,
        "actual": actual,
        "errors": errors,
        "passed": True,
        "wide_outcomes": outcomes,
        "wide_weights": wide_weights,
        "narrow_values": narrow_values,
        "narrow_weights": narrow_weights,
        "paired_score_differences": paired,
        "paired_weighted_mean": paired_mean,
        "paired_weighted_variance": paired_variance,
        "paired_weighted_sd": math.sqrt(paired_variance),
    }


def validate_monthly(levels: dict[str, float], start: str, end: str,
                     label: str) -> tuple[list[str], list[float]]:
    expected = month_range(start, end)
    missing = [month for month in expected if month not in levels]
    require(not missing, "%s missing months: %s" % (label, missing[:12]))
    values = [finite(levels[month], "%s %s" % (label, month))
              for month in expected]
    bad = [month for month, value in zip(expected, values) if value <= 0]
    require(not bad, "%s has non-positive levels: %s" % (label, bad[:12]))
    return expected, values


def load_yahoo() -> dict[str, Any]:
    started = utc_now()
    with FetchTrace() as trace:
        series = S.yahoo("^GSPC", force=True)
    finished = utc_now()

    observed = [(date, finite(value, "Yahoo value"))
                for date, value in series.observed]
    observed.sort(key=lambda row: row[0])
    require(observed, "Yahoo returned an empty observed series")
    require(observed[0][0] == "1927-12-30",
            "Yahoo first bar changed: %s" % observed[0][0])
    require(series.meta.get("dataGranularity") == "1d",
            "Yahoo dataGranularity is not 1d: %r" % series.meta)
    require(len({date for date, _ in observed}) == len(observed),
            "Yahoo contains duplicate daily dates")

    monthly: dict[str, float] = {}
    selected_daily = 0
    for iso, value in observed:
        month = iso[:7]
        if YAHOO_START <= month <= CUT_MONTH:
            monthly[month] = value
            selected_daily += 1
    months, values = validate_monthly(
        monthly, YAHOO_START, CUT_MONTH, "Yahoo monthly close"
    )
    require(len(months) == 1184, "Yahoo monthly count is not preregistered 1184")
    require(len(trace.calls) == 1 and trace.calls[0].get("tag") == "yahoo",
            "Yahoo route did not make exactly one traced yahoo request")

    passport = {
        "route": "sources.yahoo",
        "call": "sources.yahoo('^GSPC', force=True)",
        "requested_interval": "1d",
        "range_parameter": None,
        "routing": "period1/period2",
        "value_rule": "adjclose if present, otherwise close; last daily value per month",
        "load_started_at_utc": started,
        "load_finished_at_utc": finished,
        "series_fetched_at": series.fetched_at,
        "source": series.source,
        "series_id": series.series_id,
        "title": series.title,
        "currency": series.units,
        "meta": series.meta,
        "fetches": trace.calls,
        "raw_observations": len(series.dates),
        "raw_numeric_observations": len(observed),
        "raw_missing_values": len(series.dates) - len(observed),
        "raw_first": observed[0][0],
        "raw_last": observed[-1][0],
        "selected_daily_observations": selected_daily,
        "monthly_observations": len(months),
        "monthly_first": months[0],
        "monthly_last": months[-1],
        "monthly_missing": 0,
        "daily_duplicates": 0,
        "body_validated": True,
    }
    return {
        "name": "yahoo_gspc",
        "months": months,
        "response_levels": values,
        "price_levels": values,
        "passport": passport,
    }


def joined_headers(rows: Sequence[Sequence[Any]], limit: int = 12
                   ) -> dict[int, str]:
    width = max(len(row) for row in rows[:limit])
    out: dict[int, str] = {}
    for col in range(width):
        words = [
            " ".join(str(row[col]).upper().split())
            for row in rows[:limit]
            if col < len(row) and isinstance(row[col], str)
            and str(row[col]).strip()
        ]
        out[col] = " ".join(words)
    return out


def unique_column(candidates: Iterable[int], label: str) -> int:
    cols = list(candidates)
    require(len(cols) == 1, "%s column is ambiguous: %r" % (label, cols))
    return cols[0]


def parse_shiller_month(value: Any) -> str | None:
    number = S._num(value)
    if number is None:
        return None
    year = int(number)
    month = int(round(round(number - year, 4) * 100))
    if not (1871 <= year <= 2100 and 1 <= month <= 12):
        return None
    return "%04d-%02d" % (year, month)


def load_shiller() -> dict[str, Any]:
    require(version("xlrd") is not None,
            "xlrd is required for Shiller formula cells")
    started = utc_now()
    with FetchTrace() as trace:
        sheets = S.shiller(force=True)
    finished = utc_now()

    require("Data" in sheets, "Shiller workbook has no Data sheet")
    rows = sheets["Data"]
    require(len(rows) > 1800, "Shiller Data sheet is unexpectedly short")
    headers = joined_headers(rows)
    rt_col = unique_column(
        (col for col, text in headers.items()
         if all(token in text for token in ("REAL", "TOTAL", "RETURN", "PRICE"))
         and "BOND" not in text and "CAPE" not in text),
        "Shiller Real Total Return Price",
    )
    p_col = unique_column(
        (col for col in headers
         if any(col < len(row) and isinstance(row[col], str)
                and row[col].strip().upper() == "P" for row in rows[:12])),
        "Shiller P",
    )
    cpi_col = unique_column(
        (col for col in headers
         if any(col < len(row) and isinstance(row[col], str)
                and row[col].strip().upper() == "CPI" for row in rows[:12])),
        "Shiller CPI",
    )
    header_row = max(
        i for i, row in enumerate(rows[:12])
        if rt_col < len(row) and isinstance(row[rt_col], str)
    )

    response_by_month: dict[str, float] = {}
    price_by_month: dict[str, float] = {}
    parsed_dates: list[str] = []
    duplicates: list[str] = []
    selected_missing: list[str] = []
    for row in rows[header_row + 1:]:
        month = parse_shiller_month(row[0] if row else None)
        if month is None:
            continue
        parsed_dates.append(month)
        if month in response_by_month or month in price_by_month:
            duplicates.append(month)
        if not (SHILLER_START <= month <= CUT_MONTH):
            continue
        rt = S._num(row[rt_col]) if rt_col < len(row) else None
        price = S._num(row[p_col]) if p_col < len(row) else None
        cpi = S._num(row[cpi_col]) if cpi_col < len(row) else None
        if rt is None or price is None or cpi is None:
            selected_missing.append(month)
            continue
        response_by_month[month] = finite(rt * cpi, "Shiller nominal TR")
        price_by_month[month] = finite(price, "Shiller P")

    require(parsed_dates, "Shiller workbook has no parsed monthly dates")
    require(not duplicates, "Shiller duplicate dates: %s" % duplicates[:12])
    require(not selected_missing,
            "Shiller selected formula/raw cells are empty: %s" % selected_missing[:12])
    months, response = validate_monthly(
        response_by_month, SHILLER_START, CUT_MONTH, "Shiller total return"
    )
    price_months, prices = validate_monthly(
        price_by_month, SHILLER_START, CUT_MONTH, "Shiller price"
    )
    require(months == price_months, "Shiller response and price months differ")
    require(len(months) == 1867,
            "Shiller monthly count is not preregistered 1867")
    require(len(trace.calls) == 2,
            "Shiller route did not make page plus workbook requests")
    require([call.get("tag") for call in trace.calls] ==
            ["shiller-page", "shiller"],
            "Shiller traced request order changed")

    passport = {
        "route": "sources.shiller",
        "call": "sources.shiller(force=True)",
        "link_rule": "ie_data.xls href discovered from shillerdata.com page",
        "response_rule": "Real Total Return Price * CPI",
        "price_predictor_rule": "raw nominal P column",
        "load_started_at_utc": started,
        "load_finished_at_utc": finished,
        "source": "Robert Shiller via shillerdata.com",
        "fetches": trace.calls,
        "workbook_sheets": list(sheets),
        "data_rows": len(rows),
        "data_columns": max(len(row) for row in rows),
        "header_row_zero_based": header_row,
        "columns_zero_based": {
            "date": 0,
            "price_P": p_col,
            "CPI": cpi_col,
            "real_total_return_price": rt_col,
        },
        "joined_headers": {str(key): value for key, value in headers.items()},
        "parsed_month_rows": len(parsed_dates),
        "workbook_first_month": min(parsed_dates),
        "workbook_last_month": max(parsed_dates),
        "monthly_observations": len(months),
        "monthly_first": months[0],
        "monthly_last": months[-1],
        "monthly_missing": len(selected_missing),
        "monthly_duplicates": len(duplicates),
        "xlrd_version": version("xlrd"),
        "body_validated": True,
    }
    return {
        "name": "shiller_total_return",
        "months": months,
        "response_levels": response,
        "price_levels": prices,
        "passport": passport,
    }


def centered_scale(values: Sequence[float], scale: float,
                   center: float | None = None) -> tuple[float, list[float]]:
    """Production price-only transform: preserve center and change width."""
    require(len(values) > 0, "centered scale received an empty ensemble")
    require(math.isfinite(scale) and scale > 0,
            "centered scale is not finite and positive")
    actual_center = statistics.fmean(values) if center is None else float(center)
    require(math.isfinite(actual_center), "centered scale center is not finite")
    transformed = [actual_center + scale * (x - actual_center)
                   for x in values]  # MUTATE_SCALE_TRANSFORM
    require(all(math.isfinite(x) for x in transformed),
            "centered scale produced a non-finite value")
    return actual_center, transformed


def audit_information_set(
    *,
    origin_index: int,
    scenario_points: Sequence[TimedValue],
    outcome_point: TimedValue,
    recent_vol_point: TimedValue,
    reference_vol_points: Sequence[TimedValue],
) -> dict[str, Any]:
    """Audit the exact production objects passed to scoring and scaling."""
    expected_scenarios = tuple(range(HORIZON, origin_index + 1))
    actual_scenarios = tuple(point.available_index for point in scenario_points)
    require(actual_scenarios == expected_scenarios,
            "scenario lookahead or omission: actual=%r expected=%r" %
            (actual_scenarios[-3:], expected_scenarios[-3:]))
    require(all(max(point.source_indices) <= origin_index
                for point in scenario_points),
            "scenario source lookahead")

    expected_recent_sources = tuple(
        range(origin_index - VOL_WINDOW + 1, origin_index + 1)
    )
    require(recent_vol_point.source_indices == expected_recent_sources,
            "recent-volatility source lookahead or omission")
    require(recent_vol_point.available_index <= origin_index,
            "recent-volatility availability lookahead")

    expected_reference = tuple(range(HORIZON, origin_index + 1))
    actual_reference = tuple(
        point.available_index for point in reference_vol_points
    )
    require(actual_reference == expected_reference,
            "reference-volatility lookahead or omission")
    require(all(max(point.source_indices) <= origin_index
                for point in reference_vol_points),
            "reference-volatility source lookahead")

    require(outcome_point.available_index == origin_index + HORIZON,
            "outcome availability is not exactly t+12")
    require(outcome_point.source_indices ==
            (origin_index, origin_index + HORIZON),
            "outcome does not use exactly origin and t+12")

    return {
        "origin_index": origin_index,
        "scenario_count": len(scenario_points),
        "max_scenario_available_minus_origin": (
            max(actual_scenarios) - origin_index
        ),
        "max_recent_vol_source_minus_origin": (
            max(recent_vol_point.source_indices) - origin_index
        ),
        "max_reference_available_minus_origin": (
            max(actual_reference) - origin_index
        ),
        "outcome_available_minus_origin": (
            outcome_point.available_index - origin_index
        ),
        "passed": True,
    }


def placebo_production_path(ensemble: Sequence[float], outcome: float,
                            center: float) -> dict[str, Any]:
    """Call the production transform at scale=1 and require exact identity."""
    placebo_center, placebo = centered_scale(ensemble, 1.0, center)
    max_element_error = max(
        abs(actual - expected) for actual, expected in zip(placebo, ensemble)
    )
    delta = crps_empirical(ensemble, outcome) - crps_empirical(placebo, outcome)
    require(abs(placebo_center - center) <= TOL,
            "scale=1 placebo production center changed")
    require(max_element_error <= TOL,
            "scale=1 placebo production transform changed")
    require(abs(delta) <= TOL,
            "scale=1 placebo production CRPS is not zero")
    return {
        "production_function": "centered_scale",
        "scale": 1.0,
        "max_element_error": max_element_error,
        "delta_pp": delta,
        "passed": True,
    }


def route_forecasts(route: dict[str, Any]) -> dict[str, Any]:
    months: list[str] = route["months"]
    response: list[float] = route["response_levels"]
    prices: list[float] = route["price_levels"]
    n_levels = len(months)
    require(n_levels == len(response) == len(prices),
            "%s route arrays differ" % route["name"])

    annual: list[TimedValue | None] = [None] * n_levels
    log_returns: list[float | None] = [None] * n_levels
    rolling_vol: list[TimedValue | None] = [None] * n_levels

    for i in range(1, n_levels):
        log_returns[i] = math.log(prices[i] / prices[i - 1])
    for i in range(HORIZON, n_levels):
        annual[i] = TimedValue(
            value=100.0 * (response[i] / response[i - HORIZON] - 1.0),
            available_index=i,
            source_indices=(i - HORIZON, i),
        )
        source_indices = tuple(range(i - VOL_WINDOW + 1, i + 1))
        window = [log_returns[j] for j in source_indices]
        require(all(value is not None for value in window),
                "volatility window contains None")
        rolling_vol[i] = TimedValue(
            value=(statistics.stdev(float(value) for value in window)
                   * math.sqrt(12.0) * 100.0),
            available_index=i,
            source_indices=source_indices,
        )

    records: list[dict[str, Any]] = []
    internal: list[tuple[int, list[float], list[float], float, float]] = []
    information_audits: list[dict[str, Any]] = []
    for i in range(WARMUP, n_levels - HORIZON):
        require(months[i] == add_months(months[0], i),
                "monthly grid drifted at origin")
        require(months[i + HORIZON] == add_months(months[i], HORIZON),
                "outcome is not exactly 12 months ahead")
        scenario_points = tuple(
            annual[HORIZON:i + 1]
        )  # MUTATE_FUTURE_BOUNDARY
        require(all(point is not None for point in scenario_points),
                "baseline ensemble contains unavailable return")
        scenario_timed = tuple(
            point for point in scenario_points if point is not None
        )
        outcome_point = annual[i + HORIZON]
        recent_vol_point = rolling_vol[i]
        reference_points = tuple(rolling_vol[HORIZON:i + 1])
        require(outcome_point is not None, "outcome return is unavailable")
        require(recent_vol_point is not None,
                "recent volatility is unavailable")
        require(all(point is not None for point in reference_points),
                "reference volatility contains unavailable value")
        reference_timed = tuple(
            point for point in reference_points if point is not None
        )
        audit = audit_information_set(
            origin_index=i,
            scenario_points=scenario_timed,
            outcome_point=outcome_point,
            recent_vol_point=recent_vol_point,
            reference_vol_points=reference_timed,
        )
        information_audits.append(audit)

        ensemble = [point.value for point in scenario_timed]
        outcome = outcome_point.value
        recent_vol = recent_vol_point.value
        reference_total = 0.0
        for point in reference_timed:
            reference_total += point.value
        reference_vol = reference_total / len(reference_timed)
        require(reference_vol > 0 and math.isfinite(reference_vol),
                "reference volatility is invalid")
        scale = recent_vol / reference_vol
        require(scale > 0 and math.isfinite(scale), "scale is invalid")
        center, price_ensemble = centered_scale(ensemble, scale)
        baseline_score = crps_empirical(ensemble, outcome)
        price_score = crps_empirical(price_ensemble, outcome)
        delta = baseline_score - price_score

        records.append({
            "origin": months[i],
            "outcome_month": months[i + HORIZON],
            "ensemble_size": len(ensemble),
            "outcome_return_pp": outcome,
            "baseline_center_pp": center,
            "recent_vol_annualized_pp": recent_vol,
            "reference_vol_annualized_pp": reference_vol,
            "scale": scale,
            "crps_baseline_pp": baseline_score,
            "crps_price_pp": price_score,
            "delta_pp": delta,
        })
        if i in (WARMUP, (WARMUP + n_levels - HORIZON - 1) // 2,
                 n_levels - HORIZON - 1):
            internal.append((i, ensemble, price_ensemble, outcome, center))

    expected_n = n_levels - WARMUP - HORIZON
    require(len(records) == expected_n, "forecast count arithmetic failed")
    require(records[0]["origin"] == add_months(months[0], WARMUP),
            "first forecast origin changed")
    require(records[-1]["origin"] == LAST_ORIGIN,
            "last forecast origin changed")
    require(len(information_audits) == expected_n,
            "information-set audit count changed")

    direct_checks: list[dict[str, Any]] = []
    for i, ensemble, price_ensemble, outcome, center in internal:
        fast_base = crps_empirical(ensemble, outcome)
        direct_base = crps_empirical_direct(ensemble, outcome)
        fast_price = crps_empirical(price_ensemble, outcome)
        direct_price = crps_empirical_direct(price_ensemble, outcome)
        placebo = placebo_production_path(ensemble, outcome, center)
        require(abs(fast_base - direct_base) <= 1e-10,
                "fast/direct baseline CRPS mismatch")
        require(abs(fast_price - direct_price) <= 1e-10,
                "fast/direct price CRPS mismatch")
        direct_checks.append({
            "origin": months[i],
            "baseline_fast_minus_direct": fast_base - direct_base,
            "price_fast_minus_direct": fast_price - direct_price,
            "placebo_production_path": placebo,
            "passed": True,
        })

    information_set = {
        "production_values_audited": True,
        "value_type": "TimedValue",
        "origins_checked": len(information_audits),
        "max_scenario_available_minus_origin": max(
            row["max_scenario_available_minus_origin"]
            for row in information_audits
        ),
        "max_recent_vol_source_minus_origin": max(
            row["max_recent_vol_source_minus_origin"]
            for row in information_audits
        ),
        "max_reference_available_minus_origin": max(
            row["max_reference_available_minus_origin"]
            for row in information_audits
        ),
        "outcome_available_minus_origin_values": sorted({
            row["outcome_available_minus_origin"]
            for row in information_audits
        }),
        "passed": True,
    }
    return {
        "records": records,
        "diagnostics": {
            "information_set": information_set,
            "direct_crps_and_production_placebo": direct_checks,
            "passed": True,
        },
        "calculation": {
            "months": months,
            "annual_returns": annual,
        },
    }


def synthetic_control_route() -> dict[str, Any]:
    """A deterministic, network-free route with the production date shape."""
    months = month_range(YAHOO_START, CUT_MONTH)
    levels: list[float] = []
    for i in range(len(months)):
        log_level = (
            math.log(100.0) + 0.004 * i
            + 0.045 * math.sin(i / 5.0)
            + 0.018 * math.cos(i / 17.0)
        )
        levels.append(math.exp(log_level))
    return {
        "name": "synthetic_control_route",
        "months": months,
        "response_levels": levels,
        "price_levels": levels,
        "passport": {"network_used": False},
    }


def offline_control_selftest() -> dict[str, Any]:
    """Exercise the production forecast path without data loaders or network."""
    run = route_forecasts(synthetic_control_route())
    diagnostics = run["diagnostics"]
    require(diagnostics["passed"], "offline production diagnostics failed")
    require(diagnostics["information_set"]["passed"],
            "offline information-set control failed")
    require(all(row["placebo_production_path"]["passed"]
                for row in diagnostics["direct_crps_and_production_placebo"]),
            "offline production placebo failed")
    return {
        "forecast_origins": len(run["records"]),
        "information_set": diagnostics["information_set"],
        "placebo_origins": [
            row["origin"]
            for row in diagnostics["direct_crps_and_production_placebo"]
        ],
        "passed": True,
    }


def execute_source_mutant(source: str, target: str, replacement: str,
                          label: str, expected_error: str) -> dict[str, Any]:
    """Run one in-memory source mutation and require the control to reject it."""
    require(source.count(target) == 1,
            "%s mutation target count is not one" % label)
    mutated = source.replace(target, replacement)
    module_name = "z28_mutant_%s" % label.replace("-", "_")
    module = types.ModuleType(module_name)
    module.__file__ = os.path.abspath(__file__)
    module.__package__ = None
    sys.modules[module_name] = module
    try:
        exec(compile(mutated, module.__file__, "exec"), module.__dict__)
        try:
            module.offline_control_selftest()
        except AssertionError as exc:
            message = str(exc)
            require(expected_error in message,
                    "%s mutant failed for the wrong reason: %s" %
                    (label, message))
            return {
                "label": label,
                "mutation_detected": True,
                "expected_error_fragment": expected_error,
                "caught_error": message,
            }
        raise AssertionError("%s mutant survived the controls" % label)
    finally:
        sys.modules.pop(module_name, None)


def mutation_control_proof(verbose: bool = True) -> dict[str, Any]:
    """Prove both rewritten controls via green-red-green source mutations."""
    with open(__file__, "r", encoding="ascii") as handle:
        source = handle.read()

    future_old = (
        "        scenario_points = tuple(\n"
        "            annual[HORIZON:i " + "+ 1]\n"
        "        )  # MUTATE_FUTURE_BOUNDARY"
    )
    future_new = (
        "        scenario_points = tuple(\n"
        "            annual[HORIZON:i " + "+ 2]\n"
        "        )  # MUTATE_FUTURE_BOUNDARY"
    )
    transform_old = (
        "    transformed = [actual_center + scale * (x "
        + "- actual_center)\n"
        "                   for x in values]  # MUTATE_SCALE_TRANSFORM"
    )
    transform_new = (
        "    transformed = [actual_center + scale * (x "
        + "+ actual_center)\n"
        "                   for x in values]  # MUTATE_SCALE_TRANSFORM"
    )

    baseline = offline_control_selftest()
    if verbose:
        say("GREEN before mutation: production controls PASS")

    future = execute_source_mutant(
        source, future_old, future_new, "future-leak", "scenario lookahead"
    )
    if verbose:
        say("RED future-leak mutant: CAUGHT -", future["caught_error"])

    restored_after_future = offline_control_selftest()
    if verbose:
        say("GREEN after future restore: production controls PASS")

    transform = execute_source_mutant(
        source, transform_old, transform_new, "scale-transform",
        "scale=1 placebo production transform changed",
    )
    if verbose:
        say("RED scale-transform mutant: CAUGHT -", transform["caught_error"])

    restored_after_transform = offline_control_selftest()
    if verbose:
        say("GREEN after transform restore: production controls PASS")
        say("MUTATION PROOF: PASS (2/2 mutants caught)")

    return {
        "mode": "offline in-memory source mutation; no network",
        "source_sha256": hashlib.sha256(
            source.encode("ascii")
        ).hexdigest(),
        "sequence": [
            "green_before_mutation",
            "red_future_leak_caught",
            "green_after_future_restore",
            "red_scale_transform_caught",
            "green_after_transform_restore",
        ],
        "baseline": baseline,
        "mutants": [future, transform],
        "restored_after_future": restored_after_future,
        "restored_after_transform": restored_after_transform,
        "mutants_caught": 2,
        "mutants_expected": 2,
        "passed": True,
    }


def sample_acf(values: Sequence[float], max_lag: int) -> dict[int, float]:
    mean = statistics.fmean(values)
    centered = [value - mean for value in values]
    denominator = math.fsum(value * value for value in centered)
    require(denominator > 0, "ACF denominator is zero")
    return {
        lag: math.fsum(centered[i] * centered[i + lag]
                       for i in range(len(values) - lag)) / denominator
        for lag in range(1, max_lag + 1)
    }


def dependence(values: Sequence[float]) -> dict[str, Any]:
    raw_limit = min(ACF_MAX_LAG, (len(values) - 1) // 2)
    limit = raw_limit if raw_limit % 2 == 0 else raw_limit - 1
    require(limit >= 2, "not enough observations for paired ACF")
    acf = sample_acf(values, limit)
    included: list[int] = []
    pairs: list[dict[str, Any]] = []
    stopped_at: int | None = None
    for odd in range(1, limit, 2):
        pair_sum = acf[odd] + acf[odd + 1]
        use = stopped_at is None and pair_sum > 0
        pairs.append({
            "lags": [odd, odd + 1],
            "sum": pair_sum,
            "included": use,
        })
        if use:
            included.extend([odd, odd + 1])
        elif stopped_at is None:
            stopped_at = odd

    tau_unfloored = 1.0 + 2.0 * math.fsum(acf[lag] for lag in included)
    tau = max(1.0, tau_unfloored)
    fixed_lags = list(range(1, min(FIXED_OVERLAP_LAG, limit) + 1))
    fixed_tau_unfloored = 1.0 + 2.0 * math.fsum(acf[lag] for lag in fixed_lags)
    fixed_tau = max(1.0, fixed_tau_unfloored)
    reached_max_lag = bool(included) and included[-1] == limit
    return {
        "acf": [{"lag": lag, "rho": acf[lag]} for lag in sorted(acf)],
        "pair_rule": pairs,
        "included_lags": included,
        "stopped_at_lag": stopped_at,
        "tau_unfloored": tau_unfloored,
        "tau": tau,
        "n_eff": len(values) / tau,
        "multiplier_n_over_n_eff": tau,
        "difference_from_twelve": tau - 12.0,
        "ratio_to_twelve": tau / 12.0,
        "truncation_reached_max_lag": reached_max_lag,
        "censored_at_preregistered_cap": reached_max_lag,
        "multiplier_is_lower_bound_when_censored": reached_max_lag,
        "n_eff_is_upper_bound_when_censored": reached_max_lag,
        "fixed_11": {
            "included_lags": fixed_lags,
            "tau_unfloored": fixed_tau_unfloored,
            "tau": fixed_tau,
            "n_eff": len(values) / fixed_tau,
        },
    }


def quantile(sorted_values: Sequence[float], probability: float) -> float:
    require(sorted_values, "empty quantile input")
    position = (len(sorted_values) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def block_bootstrap_ci(values: Sequence[float], seed: int) -> list[float]:
    n = len(values)
    full_blocks, remainder = divmod(n, BOOT_BLOCK)
    full_sums = [
        math.fsum(values[(start + j) % n] for j in range(BOOT_BLOCK))
        for start in range(n)
    ]
    partial_sums = [
        math.fsum(values[(start + j) % n] for j in range(remainder))
        for start in range(n)
    ] if remainder else []
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(BOOT_REPS):
        total = math.fsum(full_sums[rng.randrange(n)]
                          for _ in range(full_blocks))
        if remainder:
            total += partial_sums[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    return [quantile(means, 0.025), quantile(means, 0.975)]


def scale_decomposition(
    records: Sequence[dict[str, Any]],
    calculation: dict[str, Any],
) -> dict[str, Any]:
    """Post-review diagnostic: level, synchronization, and interaction."""
    months: Sequence[str] = calculation["months"]
    annual: Sequence[TimedValue | None] = calculation["annual_returns"]
    month_to_index = {month: i for i, month in enumerate(months)}
    scales = [float(row["scale"]) for row in records]
    median_scale = quantile(sorted(scales), 0.5)
    require(median_scale > 0, "decomposition median scale is not positive")

    level_deltas: list[float] = []
    synchronization_deltas: list[float] = []
    interactions: list[float] = []
    identity_errors: list[float] = []
    for row in records:
        origin_index = month_to_index[row["origin"]]
        points = annual[HORIZON:origin_index + 1]
        require(all(point is not None for point in points),
                "decomposition ensemble contains unavailable return")
        ensemble = [point.value for point in points if point is not None]
        center = float(row["baseline_center_pp"])
        outcome = float(row["outcome_return_pp"])
        baseline_score = float(row["crps_baseline_pp"])

        _, level_ensemble = centered_scale(ensemble, median_scale, center)
        level_delta = baseline_score - crps_empirical(level_ensemble, outcome)

        synchronization_scale = float(row["scale"]) / median_scale
        _, synchronization_ensemble = centered_scale(
            ensemble, synchronization_scale, center
        )
        synchronization_delta = (
            baseline_score
            - crps_empirical(synchronization_ensemble, outcome)
        )
        interaction = (
            float(row["delta_pp"]) - level_delta - synchronization_delta
        )
        identity_error = (
            float(row["delta_pp"])
            - (level_delta + synchronization_delta + interaction)
        )
        level_deltas.append(level_delta)
        synchronization_deltas.append(synchronization_delta)
        interactions.append(interaction)
        identity_errors.append(identity_error)

    max_identity_error = max(abs(value) for value in identity_errors)
    require(max_identity_error <= 1e-12,
            "scale decomposition identity failed")
    return {
        "status": "post_hoc_review_diagnostic_not_used_for_verdict",
        "median_dynamic_scale": median_scale,
        "level_only": {
            "definition": "constant scale median(a_t)",
            "mean_delta_pp": statistics.fmean(level_deltas),
        },
        "synchronization_only": {
            "definition": "dynamic scale a_t / median(a_t); median one",
            "mean_delta_pp": statistics.fmean(synchronization_deltas),
        },
        "interaction": {
            "definition": "actual minus level-only minus synchronization-only",
            "mean_delta_pp": statistics.fmean(interactions),
        },
        "actual_mean_delta_pp": statistics.fmean(
            float(row["delta_pp"]) for row in records
        ),
        "components_are_not_additive_without_interaction": True,
        "max_abs_identity_error_pp": max_identity_error,
    }


def verdict(mean: float, ci: Sequence[float], powered: bool) -> str:
    if mean > 0 and ci[0] > 0:
        return "information_present"
    if ci[1] < 0:
        return "information_absent"
    if ci[0] <= 0 <= ci[1] and powered:
        return "information_absent"
    return "not_established"


def summarize(records: Sequence[dict[str, Any]], seed: int,
              calculation: dict[str, Any]) -> dict[str, Any]:
    deltas = [float(row["delta_pp"]) for row in records]
    baseline_scores = [float(row["crps_baseline_pp"]) for row in records]
    price_scores = [float(row["crps_price_pp"]) for row in records]
    scales = [float(row["scale"]) for row in records]
    n = len(deltas)
    require(n >= 3, "too few score differences")
    mean = statistics.fmean(deltas)
    sd = statistics.stdev(deltas)
    dep = dependence(deltas)
    n_eff = float(dep["n_eff"])
    half_width = Z95 * sd / math.sqrt(n_eff)
    ci = [mean - half_width, mean + half_width]
    naive_half_width = Z95 * sd / math.sqrt(n)
    naive_ci = [mean - naive_half_width, mean + naive_half_width]
    fixed_n_eff = float(dep["fixed_11"]["n_eff"])
    fixed_half_width = Z95 * sd / math.sqrt(fixed_n_eff)
    fixed_ci = [mean - fixed_half_width, mean + fixed_half_width]
    required = math.ceil((Z95 * sd / TARGET_EFFECT) ** 2)
    powered = n_eff >= required
    mde = Z95 * sd / math.sqrt(n_eff)
    boot_ci = block_bootstrap_ci(deltas, seed)
    sorted_scales = sorted(scales)
    scale_lt_one = sum(scale < 1.0 for scale in scales)
    decomposition = scale_decomposition(records, calculation)

    return {
        "n_nominal": n,
        "first_origin": records[0]["origin"],
        "last_origin": records[-1]["origin"],
        "mean_crps_baseline_pp": statistics.fmean(baseline_scores),
        "mean_crps_price_pp": statistics.fmean(price_scores),
        "mean_delta_pp": mean,
        "sd_delta_pp": sd,
        "dependence": dep,
        "ci95_overlap_adjusted_pp": ci,
        "ci95_naive_pp": naive_ci,
        "ci95_fixed_lags_1_11_pp": fixed_ci,
        "ci95_circular_block_bootstrap_pp": boot_ci,
        "bootstrap": {
            "block_months": BOOT_BLOCK,
            "repetitions": BOOT_REPS,
            "seed": seed,
            "determines_verdict": False,
        },
        "power": {
            "target_effect_pp": TARGET_EFFECT,
            "required_n_eff_observed_sd": required,
            "achieved_n_eff": n_eff,
            "achieved_mde_pp": mde,
            "sufficient": powered,
        },
        "scale": {
            "min": sorted_scales[0],
            "p25": quantile(sorted_scales, 0.25),
            "median": quantile(sorted_scales, 0.50),
            "p75": quantile(sorted_scales, 0.75),
            "max": sorted_scales[-1],
            "mean": statistics.fmean(scales),
            "count_lt_one": scale_lt_one,
            "share_lt_one": scale_lt_one / n,
        },
        "scale_decomposition": decomposition,
        "verdict": verdict(mean, ci, powered),
    }


def pearson(left: Sequence[float], right: Sequence[float]) -> float:
    require(len(left) == len(right) and len(left) >= 2,
            "Pearson arrays differ or are too short")
    lm, rm = statistics.fmean(left), statistics.fmean(right)
    lc = [x - lm for x in left]
    rc = [x - rm for x in right]
    numerator = math.fsum(x * y for x, y in zip(lc, rc))
    denominator = math.sqrt(
        math.fsum(x * x for x in lc) * math.fsum(y * y for y in rc)
    )
    require(denominator > 0, "Pearson denominator is zero")
    return numerator / denominator


def common_comparison(yahoo_run: dict[str, Any],
                      shiller_run: dict[str, Any]) -> dict[str, Any]:
    yahoo_records = yahoo_run["records"]
    shiller_records = shiller_run["records"]
    yahoo = {row["origin"]: row for row in yahoo_records
             if COMMON_FIRST_ORIGIN <= row["origin"] <= LAST_ORIGIN}
    shiller = {row["origin"]: row for row in shiller_records
               if COMMON_FIRST_ORIGIN <= row["origin"] <= LAST_ORIGIN}
    require(list(yahoo) == list(shiller), "common route dates do not match")
    require(len(yahoo) == 1052, "common route count is not preregistered 1052")
    yahoo_rows = list(yahoo.values())
    shiller_rows = list(shiller.values())
    yahoo_stats = summarize(yahoo_rows, SEED, yahoo_run["calculation"])
    shiller_stats = summarize(
        shiller_rows, SEED, shiller_run["calculation"]
    )
    yd = [float(row["delta_pp"]) for row in yahoo_rows]
    sd = [float(row["delta_pp"]) for row in shiller_rows]
    signed = yahoo_stats["mean_delta_pp"] - shiller_stats["mean_delta_pp"]
    return {
        "first_origin": COMMON_FIRST_ORIGIN,
        "last_origin": LAST_ORIGIN,
        "n": len(yahoo_rows),
        "yahoo": yahoo_stats,
        "shiller": shiller_stats,
        "signed_mean_delta_gap_yahoo_minus_shiller_pp": signed,
        "absolute_mean_delta_gap_pp": abs(signed),
        "per_date_delta_correlation": pearson(yd, sd),
        "mean_absolute_per_date_delta_gap_pp": statistics.fmean(
            abs(a - b) for a, b in zip(yd, sd)
        ),
        "multiplier_gap_yahoo_minus_shiller": (
            yahoo_stats["dependence"]["multiplier_n_over_n_eff"]
            - shiller_stats["dependence"]["multiplier_n_over_n_eff"]
        ),
    }


def print_summary(label: str, stats: dict[str, Any]) -> None:
    dep = stats["dependence"]
    fixed = dep["fixed_11"]
    power = stats["power"]
    scale = stats["scale"]
    decomposition = stats["scale_decomposition"]
    say(label)
    say("  dates:", stats["first_origin"], "..", stats["last_origin"],
        "n=", stats["n_nominal"])
    say("  mean CRPS baseline/price: %.6f / %.6f" %
        (stats["mean_crps_baseline_pp"], stats["mean_crps_price_pp"]))
    say("  mean delta: %.6f; sd: %.6f" %
        (stats["mean_delta_pp"], stats["sd_delta_pp"]))
    say("  ACF lags:", dep["included_lags"],
        "tau=%.6f n_eff=%.3f factor=%.6f" %
        (dep["tau"], dep["n_eff"], dep["multiplier_n_over_n_eff"]))
    if dep["censored_at_preregistered_cap"]:
        say("  WARNING: tau reached lag cap %d; multiplier is censored lower bound"
            % ACF_MAX_LAG)
    say("  overlap CI95: [%.6f, %.6f]" % tuple(stats["ci95_overlap_adjusted_pp"]))
    say("  fixed lags 1..11: tau=%.6f n_eff=%.3f CI95=[%.6f, %.6f]" %
        (fixed["tau"], fixed["n_eff"],
         stats["ci95_fixed_lags_1_11_pp"][0],
         stats["ci95_fixed_lags_1_11_pp"][1]))
    say("  naive CI95:   [%.6f, %.6f]" % tuple(stats["ci95_naive_pp"]))
    say("  block CI95:   [%.6f, %.6f]" %
        tuple(stats["ci95_circular_block_bootstrap_pp"]))
    say("  power: n_req=%d n_eff=%.3f mde=%.6f sufficient=%s" %
        (power["required_n_eff_observed_sd"], power["achieved_n_eff"],
         power["achieved_mde_pp"], power["sufficient"]))
    say("  scale: median=%.6f mean=%.6f lt1=%d/%d (%.4f%%)" %
        (scale["median"], scale["mean"], scale["count_lt_one"],
         stats["n_nominal"], 100.0 * scale["share_lt_one"]))
    say("  decomposition level/synchronization/interaction: "
        "%+.6f / %+.6f / %+.6f" %
        (decomposition["level_only"]["mean_delta_pp"],
         decomposition["synchronization_only"]["mean_delta_pp"],
         decomposition["interaction"]["mean_delta_pp"]))
    say("  verdict:", stats["verdict"])


def atomic_json(path: str, payload: dict[str, Any]) -> None:
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temp, path)


def previous_numeric_projection_hash() -> str | None:
    try:
        with open(RESULT_PATH, "r", encoding="utf-8") as handle:
            previous = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    value = previous.get("reproducibility", {}).get(
        "numeric_projection_sha256"
    )
    return value if isinstance(value, str) else None


def numeric_projection(payload: dict[str, Any]) -> dict[str, Any]:
    """Stable result content; exclude timestamps, URLs, and environment."""
    keys = (
        "schema_version",
        "task",
        "scope",
        "base_commit",
        "preregistration",
        "parameters",
        "ex_ante_feasibility",
        "crps_preflight",
        "routes",
        "common_span_comparison",
        "instrument_suspicion",
        "instrument_controls",
        "all_instrument_controls_passed",
        "main_verdict",
        "independent_verdict",
        "vintage_statement",
        "limitations",
    )
    return {key: payload[key] for key in keys}


def numeric_projection_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        numeric_projection(payload),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def main() -> int:
    run_started = utc_now()
    previous_hash = previous_numeric_projection_hash()
    head("Z28 PRE-REGISTERED RUN")
    say("base:", BASE_COMMIT)
    say("prereg:", PREREG_COMMIT, PREREG_TIME)
    say("head before run:", git("rev-parse", "HEAD"))

    head("0. CRPS PREFLIGHT BEFORE DATA")
    preflight = chapter_preflight()
    for key in ("wide_at_minus20", "narrow_at_minus20",
                "expected_wide", "expected_narrow"):
        say("  %-20s %.12f expected %.2f error %+.3g" %
            (key, preflight["actual"][key], preflight["expected"][key],
             preflight["errors"][key]))
    say("  status: PASS")

    head("0B. FALSIFIABLE CONTROL MUTATIONS BEFORE DATA")
    mutation_proof = mutation_control_proof(verbose=True)

    head("1. DATA THROUGH research/sources.py")
    yahoo = load_yahoo()
    say("Yahoo: raw=%d monthly=%d %s..%s" %
        (yahoo["passport"]["raw_numeric_observations"],
         yahoo["passport"]["monthly_observations"],
         yahoo["passport"]["monthly_first"],
         yahoo["passport"]["monthly_last"]))
    say("Yahoo URL:", yahoo["passport"]["fetches"][0]["url"])

    shiller = load_shiller()
    say("Shiller: rows=%d monthly=%d %s..%s workbook_last=%s" %
        (shiller["passport"]["data_rows"],
         shiller["passport"]["monthly_observations"],
         shiller["passport"]["monthly_first"],
         shiller["passport"]["monthly_last"],
         shiller["passport"]["workbook_last_month"]))
    say("Shiller URL:", shiller["passport"]["fetches"][1]["url"])
    say("Shiller cols:", shiller["passport"]["columns_zero_based"])

    head("2. FORECASTS")
    say("rule: W=12, expanding empirical ensemble, centered scale, no caps")
    yahoo_run = route_forecasts(yahoo)
    say("Yahoo forecast dates:", len(yahoo_run["records"]))
    shiller_run = route_forecasts(shiller)
    say("Shiller forecast dates:", len(shiller_run["records"]))

    head("3. OVERLAP-AWARE RESULTS")
    yahoo_stats = summarize(
        yahoo_run["records"], SEED, yahoo_run["calculation"]
    )
    shiller_stats = summarize(
        shiller_run["records"], SEED, shiller_run["calculation"]
    )
    print_summary("Yahoo native (primary)", yahoo_stats)
    print_summary("Shiller native (independent)", shiller_stats)

    head("4. COMMON-SPAN ROUTE GAP")
    comparison = common_comparison(yahoo_run, shiller_run)
    print_summary("Yahoo common", comparison["yahoo"])
    print_summary("Shiller common", comparison["shiller"])
    say("  signed mean gap Yahoo-Shiller: %.6f" %
        comparison["signed_mean_delta_gap_yahoo_minus_shiller_pp"])
    say("  absolute mean gap: %.6f" %
        comparison["absolute_mean_delta_gap_pp"])
    say("  per-date delta correlation: %.6f" %
        comparison["per_date_delta_correlation"])

    yahoo_mean = yahoo_stats["mean_delta_pp"]
    shiller_mean = shiller_stats["mean_delta_pp"]
    common_yahoo_mean = comparison["yahoo"]["mean_delta_pp"]
    common_shiller_mean = comparison["shiller"]["mean_delta_pp"]
    suspicious = {
        "both_native_means_nonpositive": yahoo_mean <= 0 and shiller_mean <= 0,
        "common_span_signs_differ": common_yahoo_mean * common_shiller_mean < 0,
    }
    suspicious["triggered"] = any(suspicious.values())
    controls_passed = (
        preflight["passed"]
        and mutation_proof["passed"]
        and yahoo_run["diagnostics"]["passed"]
        and shiller_run["diagnostics"]["passed"]
    )

    head("5. INSTRUMENT CONTROLS")
    say("  chapter preflight:", preflight["passed"])
    say("  mutation proof:", mutation_proof["passed"],
        "caught=%d/%d" % (mutation_proof["mutants_caught"],
                           mutation_proof["mutants_expected"]))
    say("  Yahoo provenance/direct/production-placebo:",
        yahoo_run["diagnostics"]["passed"])
    say("  Shiller provenance/direct/production-placebo:",
        shiller_run["diagnostics"]["passed"])
    say("  suspicious outcome:", suspicious)
    say("  all controls passed:", controls_passed)
    require(controls_passed, "instrument controls failed")

    run_finished = utc_now()
    result = {
        "schema_version": 2,
        "task": TASK,
        "scope": "instrument_test_not_book_market_evidence",
        "base_commit": BASE_COMMIT,
        "preregistration": {
            "commit": PREREG_COMMIT,
            "committed_at": PREREG_TIME,
            "file": "research/Z28/HYPOTHESIS.md",
            "before_data_run": True,
        },
        "run": {
            "started_at_utc": run_started,
            "finished_at_utc": run_finished,
            "head": git("rev-parse", "HEAD"),
            "python": sys.version,
            "platform": platform.platform(),
            "dependencies": {
                "certifi": version("certifi"),
                "xlrd": version("xlrd"),
            },
            "seed": SEED,
        },
        "parameters": {
            "cut_month": CUT_MONTH,
            "horizon_months": HORIZON,
            "warmup_monthly_returns": WARMUP,
            "volatility_window_months": VOL_WINDOW,
            "volatility_ddof": 1,
            "volatility_annualization": "sqrt(12)*100",
            "scale_reference": "expanding arithmetic mean of trailing-12m vol",
            "scale_center": "expanding mean of available 12m outcomes",
            "scale_caps": None,
            "acf_max_lag": ACF_MAX_LAG,
            "acf_truncation": "paired initial-positive sequence",
            "fixed_overlap_sensitivity_lag": FIXED_OVERLAP_LAG,
            "z95": Z95,
            "target_effect_pp": TARGET_EFFECT,
            "bootstrap_block_months": BOOT_BLOCK,
            "bootstrap_repetitions": BOOT_REPS,
            "bootstrap_seed": SEED,
        },
        "ex_ante_feasibility": {
            "calibration": "chapter-8 teaching distribution, not market data",
            "paired_variance": preflight["paired_weighted_variance"],
            "paired_sd": preflight["paired_weighted_sd"],
            "target_effect_pp": TARGET_EFFECT,
            "required_n_eff": math.ceil(
                (Z95 * preflight["paired_weighted_sd"] / TARGET_EFFECT) ** 2
            ),
            "yahoo_nominal_n": 1052,
            "yahoo_structural_n_over_12": 1052 / 12,
            "shiller_nominal_n": 1735,
            "shiller_structural_n_over_12": 1735 / 12,
            "criterion_can_trigger_on_both_routes": True,
        },
        "crps_preflight": preflight,
        "data_passports": {
            "yahoo": yahoo["passport"],
            "shiller": shiller["passport"],
        },
        "routes": {
            "yahoo": {
                "role": "primary",
                "response": "price return",
                "predictor": "price volatility",
                "statistics": yahoo_stats,
                "diagnostics": yahoo_run["diagnostics"],
                "per_date": yahoo_run["records"],
            },
            "shiller": {
                "role": "independent reproduction",
                "response": "nominal total return (real TR price * CPI)",
                "predictor": "raw nominal P volatility",
                "statistics": shiller_stats,
                "diagnostics": shiller_run["diagnostics"],
                "per_date": shiller_run["records"],
            },
        },
        "common_span_comparison": comparison,
        "instrument_suspicion": suspicious,
        "instrument_controls": {
            "chapter_preflight_passed": preflight["passed"],
            "mutation_proof": mutation_proof,
            "production_transform": "centered_scale",
            "production_information_value_type": "TimedValue",
            "does_not_change_measurement_or_verdict": True,
        },
        "all_instrument_controls_passed": controls_passed,
        "main_verdict": yahoo_stats["verdict"],
        "independent_verdict": shiller_stats["verdict"],
        "vintage_statement": (
            "Prices are not retrospectively revised; this task therefore does "
            "not earn vintage-data rigor for later macro work."
        ),
        "limitations": [
            "No macro-conditional forecast is present.",
            "Yahoo is price return; Shiller is total return with dividends.",
            "Pre-1957 Shiller index history is reconstructed.",
            "Only the preregistered 12-month volatility rule is tested.",
            "The expanding volatility reference retains early-crash levels; "
            "Delta mixes persistent width level, temporal synchronization, "
            "and their CRPS interaction.",
            "Alternative volatility anchors were not selected post hoc.",
            "A dependence multiplier that reaches lag 24 is censored at the "
            "preregistered cap.",
        ],
    }
    current_hash = numeric_projection_hash(result)
    result["reproducibility"] = {
        "algorithm": "SHA-256 of canonical JSON numeric_projection",
        "excludes": [
            "run timestamps and environment",
            "data passport timestamps, URLs, and fetch metadata",
            "this reproducibility object",
        ],
        "numeric_projection_sha256": current_hash,
        "previous_result_numeric_projection_sha256": previous_hash,
        "matches_previous_result": (
            previous_hash == current_hash if previous_hash is not None else None
        ),
    }
    atomic_json(RESULT_PATH, result)

    head("6. FINAL")
    say("main verdict:", result["main_verdict"])
    say("independent verdict:", result["independent_verdict"])
    say("instrument test only; NOT evidence for the central market thesis")
    say("vintage rigor: NOT earned; prices are not retrospectively revised")
    say("numeric projection SHA256:", current_hash)
    say("previous numeric projection SHA256:", previous_hash)
    say("matches previous result:",
        result["reproducibility"]["matches_previous_result"])
    say("result:", RESULT_PATH)
    say("run finished UTC:", run_finished)
    return 0


def cli() -> int:
    if sys.argv[1:] == ["--mutation-controls"]:
        head("Z28 OFFLINE CONTROL MUTATION PROOF")
        proof = mutation_control_proof(verbose=True)
        say("source SHA256:", proof["source_sha256"])
        say("network used: False")
        return 0
    require(not sys.argv[1:], "unknown arguments: %r" % sys.argv[1:])
    return main()


if __name__ == "__main__":
    try:
        raise SystemExit(cli())
    except Exception as exc:  # noqa: BLE001
        say("")
        say("Z28 FAILED:", type(exc).__name__, str(exc))
        raise
