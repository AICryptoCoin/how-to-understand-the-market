#!/usr/bin/env python3
"""Z29: The Price of Lookahead (Cena podglyadyvaniya) - Round 2.

Autonomously measures researcher lookahead error on the Z28 instrument:
1. Honesty control: executes Z28 in memory to verify reproduction of result.json.
2. Five mutations L1-L5: audits each mutation, measures fake gains and Z28 shift.
   Audit messages and first dates are dynamically measured.
   Placebo production path at scale=1 is executed live without dummy bypass.
3. Recalculates Z03 realtime scoring across 3 variants:
   (A) Vintage edge (primary)
   (B) First publication (sensitivity)
   (C) Recognised month (round 1 legacy)
4. Audits Z01 out-of-sample lag selection via ALFRED without FRED API key:
   Reproduces published split and calculates clean partition (t <= 2009-12).
5. Documents Shiller dividend interpolation lookahead.

Strictly ASCII-clean script. All outputs formatted in UTF-8.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import types
from typing import Any, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
RESEARCH_DIR = os.path.join(REPO_ROOT, "research")
if RESEARCH_DIR not in sys.path:
    sys.path.insert(0, RESEARCH_DIR)

import sources as S  # noqa: E402

Z28_DIR = os.path.join(RESEARCH_DIR, "Z28")
Z03_DIR = os.path.join(RESEARCH_DIR, "Z03")
Z01_DIR = os.path.join(RESEARCH_DIR, "Z01")

Z95 = 1.96
TARGET_EFFECT = 1.0

LOG_PATH = os.path.join(HERE, "full-run.txt")


def say(*parts: Any) -> None:
    text = " ".join(str(p) for p in parts)
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))
    sys.stdout.flush()
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as lf:
            lf.write(text + "\n")
    except OSError:
        pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_in_memory_module(py_path: str, module_name: str) -> types.ModuleType:
    with open(py_path, "r", encoding="utf-8") as f:
        code = f.read()
    mod = types.ModuleType(module_name)
    mod.__file__ = py_path
    mod.__package__ = None
    sys.modules[module_name] = mod
    exec(compile(code, py_path, "exec"), mod.__dict__)
    return mod


def read_z28_clean_source() -> str:
    path = os.path.join(Z28_DIR, "run.py")
    with open(path, "r", encoding="ascii") as handle:
        return handle.read()


def make_z28_module(
    source: str,
    label: str,
    *,
    bypass_audit: bool = False,
) -> types.ModuleType:
    module_name = "z28_mod_%s" % label.replace("-", "_")
    module = types.ModuleType(module_name)
    module.__file__ = os.path.join(Z28_DIR, "run.py")
    module.__package__ = None
    sys.modules[module_name] = module
    try:
        exec(compile(source, module.__file__, "exec"), module.__dict__)
        if bypass_audit:
            # R5: Only bypass audit_information_set. Real placebo_production_path executes live!
            module.audit_information_set = (
                lambda **kwargs: {
                    "origin_index": kwargs.get("origin_index", 0),
                    "scenario_count": len(kwargs.get("scenario_points", ())),
                    "max_scenario_available_minus_origin": 0,
                    "max_recent_vol_source_minus_origin": 0,
                    "max_reference_available_minus_origin": 0,
                    "outcome_available_minus_origin": 0,
                    "passed": True,
                    "bypassed": True,
                }
            )
        return module
    except Exception:
        sys.modules.pop(module_name, None)
        raise


def compute_metrics(
    values: Sequence[float],
    z28_dep_func: Any,
    z28_verdict_func: Any,
) -> dict[str, Any]:
    n = len(values)
    mean = statistics.fmean(values)
    s = statistics.stdev(values)
    dep = z28_dep_func(values)
    tau = float(dep["tau"])
    n_eff = float(dep["n_eff"])

    hw_honest = Z95 * s / math.sqrt(n_eff)
    ci_honest = [mean - hw_honest, mean + hw_honest]

    hw_naive = Z95 * s / math.sqrt(n)
    ci_naive = [mean - hw_naive, mean + hw_naive]

    t_honest = mean / (s / math.sqrt(n_eff))
    t_naive = mean / (s / math.sqrt(n))

    required_n = math.ceil((Z95 * s / TARGET_EFFECT) ** 2)
    powered = n_eff >= required_n
    vrd = z28_verdict_func(mean, ci_honest, powered)

    return {
        "n": n,
        "mean": mean,
        "s": s,
        "tau": tau,
        "n_eff": n_eff,
        "half_width_honest": hw_honest,
        "ci95_honest": ci_honest,
        "half_width_naive": hw_naive,
        "ci95_naive": ci_naive,
        "t_honest": t_honest,
        "t_naive": t_naive,
        "powered": powered,
        "verdict": vrd,
    }


def step_control(clean_source: str) -> dict[str, Any]:
    say("")
    say("=" * 78)
    say("1. HONEST CONTROL: REPRODUCING Z28 IN MEMORY")
    say("=" * 78)

    base_mod = make_z28_module(clean_source, "clean_control", bypass_audit=False)
    z28_res_path = os.path.join(Z28_DIR, "result.json")
    with open(z28_res_path, "r", encoding="utf-8") as f:
        z28_pub = json.load(f)

    expected_sha = z28_pub["instrument_controls"]["mutation_proof"]["source_sha256"]
    calc_sha = hashlib.sha256(
        clean_source.replace("\r\n", "\n").encode("ascii")
    ).hexdigest()
    say("Z28 source sha256: %s" % calc_sha)
    require(calc_sha == expected_sha, "Z28 source SHA256 mismatch")

    say("Loading Yahoo ^GSPC route...")
    yahoo_route = base_mod.load_yahoo()
    say("Loading Shiller Total Return route...")
    shiller_route = base_mod.load_shiller()

    say("Executing Yahoo honest route_forecasts (audit enabled)...")
    yahoo_fc = base_mod.route_forecasts(yahoo_route)
    say("Executing Shiller honest route_forecasts (audit enabled)...")
    shiller_fc = base_mod.route_forecasts(shiller_route)

    control_out: dict[str, Any] = {
        "source_sha256": calc_sha,
        "routes": {},
    }

    for rkey, fc, rdata in [
        ("yahoo", yahoo_fc, yahoo_route),
        ("shiller", shiller_fc, shiller_route),
    ]:
        pub_per_date = z28_pub["routes"][rkey]["per_date"]
        act_records = fc["records"]
        n_act, n_pub = len(act_records), len(pub_per_date)
        require(n_act == n_pub, "%s count mismatch: %d vs %d" % (rkey, n_act, n_pub))

        diffs = [
            abs(float(act["delta_pp"]) - float(pub["delta_pp"]))
            for act, pub in zip(act_records, pub_per_date)
        ]
        max_diff = max(diffs)
        match_exact = max_diff <= 1e-9

        say(
            "Route %-8s: n=%4d, max |delta_act - delta_pub| = %.3e pp -> %s"
            % (rkey, n_act, max_diff, "EXACT MATCH (<= 1e-9)" if match_exact else "DATA SHIFT")
        )

        stat_act = compute_metrics(
            [r["delta_pp"] for r in act_records],
            base_mod.dependence,
            base_mod.verdict,
        )

        control_out["routes"][rkey] = {
            "n_dates": n_act,
            "max_abs_diff_delta_pp": max_diff,
            "match_within_1e9": match_exact,
            "first_origin": act_records[0]["origin"],
            "last_origin": act_records[-1]["origin"],
            "mean_delta_pp": stat_act["mean"],
            "sd_delta_pp": stat_act["s"],
            "tau": stat_act["tau"],
            "n_eff": stat_act["n_eff"],
            "ci95_honest": stat_act["ci95_honest"],
            "verdict": stat_act["verdict"],
            "current_passport": rdata["passport"],
            "published_passport": z28_pub["data_passports"][rkey],
            "records": act_records,
        }

    return {
        "control": control_out,
        "yahoo_route": yahoo_route,
        "shiller_route": shiller_route,
        "base_mod": base_mod,
    }


def step_leaks(
    clean_source: str,
    control_data: dict[str, Any],
) -> dict[str, Any]:
    say("")
    say("=" * 78)
    say("2. FIVE LOOKAHEAD LEAKS ON Z28 INSTRUMENT (ROUND 2)")
    say("=" * 78)

    base_mod = control_data["base_mod"]
    yahoo_route = control_data["yahoo_route"]
    shiller_route = control_data["shiller_route"]

    # Load round 1 result.json to verify discrepancy (P5)
    r1_results = {}
    r1_path = os.path.join(HERE, "result.json")
    if os.path.exists(r1_path):
        try:
            with open(r1_path, "r", encoding="utf-8") as f:
                r1_data = json.load(f)
                r1_results = r1_data.get("leaks", {})
        except Exception:
            pass

    leaks_spec: dict[str, dict[str, str]] = {
        "L1": {
            "title": "Ensemble peeks 1 month ahead",
            "target": (
                "        scenario_points = tuple(\n"
                "            annual[HORIZON:i + 1]\n"
                "        )  # MUTATE_FUTURE_BOUNDARY"
            ),
            "replacement": (
                "        scenario_points = tuple(\n"
                "            annual[HORIZON:i + 2]\n"
                "        )  # MUTATE_FUTURE_BOUNDARY"
            ),
            "leak_type": "baseline_ensemble",
            "description": "annual[HORIZON:i + 1] -> annual[HORIZON:i + 2]",
        },
        "L2": {
            "title": "Ensemble includes incomplete 12-month return windows",
            "target": (
                "        scenario_points = tuple(\n"
                "            annual[HORIZON:i + 1]\n"
                "        )  # MUTATE_FUTURE_BOUNDARY"
            ),
            "replacement": (
                "        scenario_points = tuple(\n"
                "            annual[HORIZON:i + HORIZON]\n"
                "        )  # MUTATE_FUTURE_BOUNDARY"
            ),
            "leak_type": "baseline_ensemble",
            "description": "annual[HORIZON:i + 1] -> annual[HORIZON:i + HORIZON]",
        },
        "L3": {
            "title": "Reference volatility is whole-sample constant mean",
            "target": (
                "        reference_total = 0.0\n"
                "        for point in reference_timed:\n"
                "            reference_total += point.value\n"
                "        reference_vol = reference_total / len(reference_timed)"
            ),
            "replacement": (
                "        reference_vol = statistics.fmean(\n"
                "            p.value for p in rolling_vol if p is not None\n"
                "        )"
            ),
            "leak_type": "price_volatility",
            "description": "reference_vol = constant whole-sample mean rolling_vol",
        },
        "L4": {
            "title": "Ensemble centered at whole-sample mean return",
            "target": (
                "        center, price_ensemble = centered_scale(ensemble, scale)\n"
                "        baseline_score = crps_empirical(ensemble, outcome)"
            ),
            "replacement": (
                "        whole_center = statistics.fmean(\n"
                "            p.value for p in annual if p is not None\n"
                "        )\n"
                "        center, price_ensemble = centered_scale(\n"
                "            ensemble, scale, center=whole_center\n"
                "        )\n"
                "        leaked_base_ensemble = [\n"
                "            x - statistics.fmean(ensemble) + whole_center for x in ensemble\n"
                "        ]\n"
                "        baseline_score = crps_empirical(leaked_base_ensemble, outcome)"
            ),
            "leak_type": "baseline_center",
            "description": "scale transform around whole-sample mean return: c + k*(x - c)",
        },
        "L5": {
            "title": "Recent volatility is future realized volatility over t+1..t+12",
            "target": (
                "        recent_vol_point = rolling_vol[i]"
            ),
            "replacement": (
                "        future_window = [\n"
                "            log_returns[j] for j in range(i + 1, i + HORIZON + 1)\n"
                "        ]\n"
                "        recent_vol_point = TimedValue(\n"
                "            value=(statistics.stdev(float(v) for v in future_window)\n"
                "                   * math.sqrt(12.0) * 100.0),\n"
                "            available_index=i + HORIZON,\n"
                "            source_indices=tuple(range(i + 1, i + HORIZON + 1)),\n"
                "        )"
            ),
            "leak_type": "price_volatility",
            "description": "recent_vol = realized stdev over t+1..t+12",
        },
    }

    leaks_out: dict[str, Any] = {}

    for code in ["L1", "L2", "L3", "L4", "L5"]:
        spec = leaks_spec[code]
        say("")
        say("--- [%s] %s ---" % (code, spec["title"]))
        require(clean_source.count(spec["target"]) == 1, "%s target count not 1" % code)
        mutated_source = clean_source.replace(spec["target"], spec["replacement"])

        # R4: Audit check with dynamic origin_index recording
        audit_res: dict[str, Any] = {}
        for rkey, rdata in [("yahoo", yahoo_route), ("shiller", shiller_route)]:
            audit_mod = make_z28_module(mutated_source, "%s_%s_audit" % (code, rkey), bypass_audit=False)
            orig_audit = audit_mod.audit_information_set
            last_attempted: list[int | None] = [None]

            def make_audit_wrapper(fn: Any, cell: list[int | None]) -> Any:
                def wrapper(**kwargs: Any) -> Any:
                    cell[0] = kwargs.get("origin_index")
                    return fn(**kwargs)
                return wrapper

            audit_mod.audit_information_set = make_audit_wrapper(orig_audit, last_attempted)
            caught = False
            first_origin = None
            err_msg = None
            try:
                audit_mod.route_forecasts(rdata)
            except AssertionError as exc:
                caught = True
                err_msg = str(exc)
                idx = last_attempted[0]
                first_origin = rdata["months"][idx] if idx is not None else None

            audit_res[rkey] = {
                "caught": caught,
                "first_origin": first_origin,
                "error_message": err_msg,
            }
            say("  Audit [%-7s]: %s (first origin: %s) -> %s" % (
                rkey,
                "CAUGHT" if caught else "BLIND (passed)",
                str(first_origin),
                err_msg or "OK",
            ))

        # R5: Measurement with audit bypassed, real placebo_production_path executing
        meas_mod = make_z28_module(mutated_source, "%s_meas" % code, bypass_audit=True)
        meas_out: dict[str, Any] = {}

        for rkey, rdata in [("yahoo", yahoo_route), ("shiller", shiller_route)]:
            fc_leaked = meas_mod.route_forecasts(rdata)
            leaked_records = fc_leaked["records"]
            honest_records = control_data["control"]["routes"][rkey]["records"]
            honest_deltas = [r["delta_pp"] for r in honest_records]
            honest_verdict = control_data["control"]["routes"][rkey]["verdict"]

            # Compute difference with round 1 numbers (P5)
            r1_prev_records = r1_results.get(code, {}).get("measurement", {}).get(rkey, {}).get("fake_gain_metrics", {})
            r1_prev_mean = r1_prev_records.get("mean")

            extra: dict[str, Any] = {}

            if spec["leak_type"] in ("baseline_ensemble", "baseline_center"):
                # R3: Baseline leaks (L1, L2, L4)
                # d: Fake gain of leaked baseline over honest baseline
                d = [
                    rh["crps_baseline_pp"] - rl["crps_baseline_pp"]
                    for rh, rl in zip(honest_records, leaked_records)
                ]
                stat_d = compute_metrics(d, base_mod.dependence, base_mod.verdict)

                # Z28 shift: delta - d = crps(baseline_leaked) - crps(price)
                z28_shift = [
                    rl["crps_baseline_pp"] - rh["crps_price_pp"]
                    for rh, rl in zip(honest_records, leaked_records)
                ]
                stat_z28_shift = compute_metrics(z28_shift, base_mod.dependence, base_mod.verdict)

                # Round 1 comparison: d - delta
                stat_r1 = compute_metrics(
                    [di - hd for di, hd in zip(d, honest_deltas)],
                    base_mod.dependence,
                    base_mod.verdict,
                )

                max_diff_r1 = abs(stat_d["mean"] - r1_prev_mean) if r1_prev_mean is not None else 0.0

                z28_verdict_under_leak = stat_z28_shift["verdict"]
                fake_gain_verdict = stat_d["verdict"]

                say(
                    "  [%-7s] Fake gain d: %+6.3f pp, 95%% CI [%+6.3f, %+6.3f], t_h=%+5.2f, vrd=%s"
                    % (
                        rkey,
                        stat_d["mean"],
                        stat_d["ci95_honest"][0],
                        stat_d["ci95_honest"][1],
                        stat_d["t_honest"],
                        stat_d["verdict"],
                    )
                )
                say(
                    "  [%-7s] Z28 under leak (delta - d): %+6.3f pp, 95%% CI [%+6.3f, %+6.3f], t_h=%+5.2f, vrd=%s"
                    % (
                        rkey,
                        stat_z28_shift["mean"],
                        stat_z28_shift["ci95_honest"][0],
                        stat_z28_shift["ci95_honest"][1],
                        stat_z28_shift["t_honest"],
                        stat_z28_shift["verdict"],
                    )
                )

                if code == "L4":
                    price_gains = [
                        rh["crps_baseline_pp"] - rl["crps_price_pp"]
                        for rh, rl in zip(honest_records, leaked_records)
                    ]
                    stat_price = compute_metrics(
                        price_gains,
                        base_mod.dependence,
                        base_mod.verdict,
                    )
                    extra["price_forecast_with_leaked_center"] = stat_price
                    extra["description"] = "scale transform around whole-sample mean return: c + k*(x - c)"

                meas_out[rkey] = {
                    "fake_gain_metrics": stat_d,
                    "z28_shift_metrics": stat_z28_shift,
                    "z28_verdict_under_leak": z28_verdict_under_leak,
                    "fake_gain_verdict": fake_gain_verdict,
                    "honest_verdict": honest_verdict,
                    "round_1_comparison": stat_r1,
                    "max_diff_vs_round_1": max_diff_r1,
                    "extra": extra,
                }
            else:
                # R3: Price leaks (L3, L5)
                # d: Z28 under leak = crps(baseline) - crps(price_leaked)
                d = [
                    rh["crps_baseline_pp"] - rl["crps_price_pp"]
                    for rh, rl in zip(honest_records, leaked_records)
                ]
                stat_d = compute_metrics(d, base_mod.dependence, base_mod.verdict)

                # Fake gain: d - delta = crps(price_honest) - crps(price_leaked)
                d_minus_delta = [
                    di - hd for di, hd in zip(d, honest_deltas)
                ]
                stat_d_minus_delta = compute_metrics(
                    d_minus_delta,
                    base_mod.dependence,
                    base_mod.verdict,
                )

                max_diff_r1 = abs(stat_d["mean"] - r1_prev_mean) if r1_prev_mean is not None else 0.0

                z28_verdict_under_leak = stat_d["verdict"]
                fake_gain_verdict = stat_d_minus_delta["verdict"]

                say(
                    "  [%-7s] Z28 under leak d: %+6.3f pp, 95%% CI [%+6.3f, %+6.3f], t_h=%+5.2f, vrd=%s"
                    % (
                        rkey,
                        stat_d["mean"],
                        stat_d["ci95_honest"][0],
                        stat_d["ci95_honest"][1],
                        stat_d["t_honest"],
                        stat_d["verdict"],
                    )
                )
                say(
                    "  [%-7s] Fake gain (d - delta): %+6.3f pp, 95%% CI [%+6.3f, %+6.3f], t_h=%+5.2f, vrd=%s"
                    % (
                        rkey,
                        stat_d_minus_delta["mean"],
                        stat_d_minus_delta["ci95_honest"][0],
                        stat_d_minus_delta["ci95_honest"][1],
                        stat_d_minus_delta["t_honest"],
                        stat_d_minus_delta["verdict"],
                    )
                )

                meas_out[rkey] = {
                    "fake_gain_metrics": stat_d,
                    "fake_gain_over_honest_price": stat_d_minus_delta,
                    "z28_shift_metrics": stat_d,
                    "z28_verdict_under_leak": z28_verdict_under_leak,
                    "fake_gain_verdict": fake_gain_verdict,
                    "honest_verdict": honest_verdict,
                    "round_1_comparison": stat_d_minus_delta,
                    "max_diff_vs_round_1": max_diff_r1,
                    "extra": extra,
                }

            say("  [%-7s] Max difference vs round 1: %.3e pp" % (rkey, max_diff_r1))

        leaks_out[code] = {
            "spec": spec,
            "audit": audit_res,
            "measurement": meas_out,
        }

    return leaks_out


def step_z03() -> dict[str, Any]:
    say("")
    say("=" * 78)
    say("3. Z03: REALTIME RECALCULATION BY ARCHITECT SPECIFICATION (ROUND 2)")
    say("=" * 78)

    # Load Z03 module in memory without running main()
    z03_py = os.path.join(Z03_DIR, "run.py")
    z03_mod = load_in_memory_module(z03_py, "z03_mem_mod")

    z03_res_path = os.path.join(Z03_DIR, "result.json")
    with open(z03_res_path, "r", encoding="utf-8") as f:
        z03_pub = json.load(f)

    # Address each parameter from Z03 result.json
    sig_strs = [d["signal"] for d in z03_pub["realtime"]["verdict_known_at"]]
    signals = [z03_mod.mi(s + "-01") for s in sig_strs]
    t10_first = z03_pub["manifest"]["series"]["T10Y3M"]["first"]
    t_start = z03_mod.mi(t10_first)
    last_vint = z03_pub["realtime"]["vintage_bounds"]["last_vintage"]
    t_end = z03_pub["realtime"]["vintage_bounds"]["_last_covered_mi"]

    say("Signals (%d): %s" % (len(signals), ", ".join(sig_strs)))
    say("Window: t_start=%s (from T10Y3M.first %s) .. t_end=%s (from _last_covered_mi)" % (
        z03_mod.mi_str(t_start), t10_first, z03_mod.mi_str(t_end)
    ))
    say("Last covered vintage: %s" % last_vint)

    # Fetch ROUTPUT realtime dataset
    rtds = S.philfed_realtime("routputqvqd")
    raw_sheet = rtds.get("ROUTPUT") or next(iter(rtds.values()))

    # Truncate columns beyond last_vintage
    header = raw_sheet[0]
    cut_col = None
    vint_cols: list[tuple[int, int, str]] = []
    for c, name in enumerate(header):
        if isinstance(name, str) and name.upper().startswith("ROUTPUT"):
            tail = name.upper().replace("ROUTPUT", "")
            if len(tail) == 4 and tail[2] == "Q":
                yy, q = int(tail[:2]), int(tail[3])
                year = 1900 + yy if yy >= 40 else 2000 + yy
                vname = "%04dQ%d" % (year, q)
                vq = year * 4 + (q - 1)
                vint_cols.append((c, vq, vname))
                if vname == last_vint:
                    cut_col = c + 1
    vint_cols.sort(key=lambda cq: cq[1])
    require(cut_col is not None, "Could not find last_vintage column %s" % last_vint)
    truncated_sheet = [row[:cut_col] for row in raw_sheet]
    vint_cols = [x for x in vint_cols if x[2] <= last_vint]
    say("Truncated sheet to vintage %s: %d columns (from %d)" % (last_vint, cut_col, len(header)))

    # Control 1: realtime_two_quarter on truncated sheet reproduces published events byte-for-byte
    rt_events, rt_warn, rt_bounds = z03_mod.realtime_two_quarter(truncated_sheet)
    pub_events = z03_pub["realtime"]["two_quarter_realtime_events"]
    require(len(rt_events) == len(pub_events), "Control 1 event count mismatch: %d vs %d" % (len(rt_events), len(pub_events)))
    for i, (act, pub) in enumerate(zip(rt_events, pub_events)):
        for k in ("event_month", "first_vintage", "recognised_month"):
            require(act[k] == pub[k], "Control 1 mismatch at #%d key %s: %r vs %r" % (i, k, act[k], pub[k]))
    say("Control 1 (parsing): EXACT MATCH with Z03 result.json two_quarter_realtime_events")

    # Control 2: Economic dates score gives exactly 5/1/0 and lags [5, 7, 12, 22, 22]
    ev_economic = [e["_event_mi"] for e in rt_events]
    sc_econ = z03_mod.score(signals, ev_economic, w=z03_mod.W_MAIN, t_start=t_start, t_end=t_end)
    require(sc_econ["TP"] == 5, "Control 2 TP mismatch: %r" % sc_econ["TP"])
    require(sc_econ["FA"] == 1, "Control 2 FA mismatch: %r" % sc_econ["FA"])
    require(sc_econ["FN"] == 0, "Control 2 FN mismatch: %r" % sc_econ["FN"])
    require(sc_econ["lags"] == [5, 7, 12, 22, 22], "Control 2 lags mismatch: %r" % sc_econ["lags"])
    say("Control 2 (scoring): EXACT MATCH with published 5/1/0, lags [5, 7, 12, 22, 22]")

    # Extract parsed vintages dictionary: vq -> (vname, vals)
    vint_data: dict[int, tuple[str, dict[int, float]]] = {}
    for col, vq, vname in vint_cols:
        vals: dict[int, float] = {}
        for row in truncated_sheet[1:]:
            if not row or not isinstance(row[0], str) or ":Q" not in row[0]:
                continue
            y, q = row[0].split(":Q")
            v = S._num(row[col]) if col < len(row) else None
            if v is not None:
                vals[int(y) * 4 + int(q) - 1] = v
        vint_data[vq] = (vname, vals)

    # -------------------------------------------------------------------------
    # Variant A: Edge of vintage (primary)
    # -------------------------------------------------------------------------
    events_A: list[dict[str, Any]] = []
    is_in_recession_A = False
    for vq in sorted(vint_data):
        vname, vals = vint_data[vq]
        qs = sorted(vals.keys())
        if len(qs) < 3:
            continue
        q_last, q_prev = qs[-1], qs[-2]
        fall_last = (q_last - 1 in vals) and (vals[q_last] < vals[q_last - 1])
        fall_prev = (q_prev - 1 in vals) and (vals[q_prev] < vals[q_prev - 1])
        if fall_last and fall_prev:
            if not is_in_recession_A:
                # Event month: midpoint of vintage quarter
                m_idx = (vq // 4) * 12 + (vq % 4) * 3 + 1
                events_A.append({
                    "vintage": vname,
                    "event_month": z03_mod.mi_str(m_idx),
                    "_event_mi": m_idx,
                    "q_prev": z03_mod.qi_str(q_prev),
                    "q_last": z03_mod.qi_str(q_last),
                })
                is_in_recession_A = True
        else:
            is_in_recession_A = False

    months_A = [e["_event_mi"] for e in events_A]
    sc_A = z03_mod.score(signals, months_A, w=z03_mod.W_MAIN, t_start=t_start, t_end=t_end)
    u1_A = sc_A["FN"] <= 1
    u2_A = sc_A["fa_per_tp"] is not None and sc_A["fa_per_tp"] <= 0.5

    say("")
    say("Variant (A) Vintage Edge (Primary):")
    say("  Events (%d): %s" % (
        len(events_A),
        ", ".join("%s (%s)" % (e["vintage"], e["event_month"]) for e in events_A)
    ))
    say("  Score: TP=%d, FA=%d, FN=%d, censored=%d, FA/TP=%s, lags=%r" % (
        sc_A["TP"], sc_A["FA"], sc_A["FN"], sc_A["censored"], str(sc_A["fa_per_tp"]), sc_A["lags"]
    ))
    say("  U1 (FN <= 1): %s, U2 (FA/TP <= 0.5): %s" % (u1_A, u2_A))

    # -------------------------------------------------------------------------
    # Variant B: Strictly first publications (sensitivity)
    # -------------------------------------------------------------------------
    all_qs: set[int] = set()
    for _, vals in vint_data.values():
        all_qs.update(vals.keys())

    first_pub: dict[int, tuple[int, str, bool]] = {}
    for q in sorted(all_qs):
        for vq in sorted(vint_data):
            vname, vals = vint_data[vq]
            if q in vals and (q - 1) in vals:
                first_pub[q] = (vq, vname, vals[q] < vals[q - 1])
                break

    hits_B: list[int] = []
    for q in sorted(first_pub):
        if q - 1 in first_pub and first_pub[q][2] and first_pub[q - 1][2]:
            hits_B.append(q)

    firsts_B: list[int] = []
    prev_b = None
    for q in hits_B:
        if prev_b is None or q - prev_b > 1:
            firsts_B.append(q)
        prev_b = q

    events_B: list[dict[str, Any]] = []
    for q in firsts_B:
        vq, vname, _ = first_pub[q]
        m_idx = (vq // 4) * 12 + (vq % 4) * 3 + 1
        events_B.append({
            "vintage": vname,
            "event_month": z03_mod.mi_str(m_idx),
            "_event_mi": m_idx,
            "q_prev": z03_mod.qi_str(q - 1),
            "q_last": z03_mod.qi_str(q),
        })

    months_B = [e["_event_mi"] for e in events_B]
    sc_B = z03_mod.score(signals, months_B, w=z03_mod.W_MAIN, t_start=t_start, t_end=t_end)
    u1_B = sc_B["FN"] <= 1
    u2_B = sc_B["fa_per_tp"] is not None and sc_B["fa_per_tp"] <= 0.5

    say("")
    say("Variant (B) Strictly First Publications (Sensitivity):")
    say("  Events (%d): %s" % (
        len(events_B),
        ", ".join("%s (%s)" % (e["vintage"], e["event_month"]) for e in events_B)
    ))
    say("  Score: TP=%d, FA=%d, FN=%d, censored=%d, FA/TP=%s, lags=%r" % (
        sc_B["TP"], sc_B["FA"], sc_B["FN"], sc_B["censored"], str(sc_B["fa_per_tp"]), sc_B["lags"]
    ))
    say("  U1 (FN <= 1): %s, U2 (FA/TP <= 0.5): %s" % (u1_B, u2_B))

    # -------------------------------------------------------------------------
    # Variant C: As in Round 1 (recognised_month legacy)
    # -------------------------------------------------------------------------
    events_C = [
        {
            "event_month": e["event_month"],
            "first_vintage": e["first_vintage"],
            "recognised_month": e["recognised_month"],
            "_event_mi": z03_mod.mi(e["recognised_month"] + "-01"),
            "within_vintage_coverage": e["within_vintage_coverage"],
            "recognition_lag_months": e["recognition_lag_months"],
        }
        for e in pub_events
    ]
    months_C = [e["_event_mi"] for e in events_C]
    sc_C = z03_mod.score(signals, months_C, w=z03_mod.W_MAIN, t_start=t_start, t_end=t_end)
    u1_C = sc_C["FN"] <= 1
    u2_C = sc_C["fa_per_tp"] is not None and sc_C["fa_per_tp"] <= 0.5

    say("")
    say("Variant (C) Round 1 Legacy (by recognised_month):")
    say("  Score: TP=%d, FA=%d, FN=%d, censored=%d, FA/TP=%s, lags=%r" % (
        sc_C["TP"], sc_C["FA"], sc_C["FN"], sc_C["censored"], str(sc_C["fa_per_tp"]), sc_C["lags"]
    ))
    say("  U1 (FN <= 1): %s, U2 (FA/TP <= 0.5): %s" % (u1_C, u2_C))

    return {
        "reproduction_control": {
            "score": sc_econ,
            "matched_published": True,
        },
        "variant_A_vintage_edge": {
            "description": "Primary: two consecutive negative quarters at vintage edge",
            "events": events_A,
            "score": sc_A,
            "U1": u1_A,
            "U2": u2_A,
        },
        "variant_B_first_publication": {
            "description": "Sensitivity: growth on first appearance of each quarter",
            "events": events_B,
            "score": sc_B,
            "U1": u1_B,
            "U2": u2_B,
        },
        "variant_C_round_1_legacy": {
            "description": "Round 1 legacy: scored by recognised_month",
            "events": events_C,
            "score": sc_C,
            "U1": u1_C,
            "U2": u2_C,
            "artifacts_noted": [
                "1947 pair recognised in 2004-02 (outside coverage)",
                "1980 pair recognised in 1996-02 (191 month lag)",
            ],
        },
    }


def step_z01() -> dict[str, Any]:
    say("")
    say("=" * 78)
    say("4. Z01: OUT-OF-SAMPLE RECALCULATION VIA ALFRED (ROUND 2)")
    say("=" * 78)

    # Load Z01 module in memory without running main()
    z01_py = os.path.join(Z01_DIR, "run.py")
    z01_mod = load_in_memory_module(z01_py, "z01_mem_mod")

    z01_res_path = os.path.join(Z01_DIR, "result.json")
    with open(z01_res_path, "r", encoding="utf-8") as f:
        z01_pub = json.load(f)

    vintage_date = "2026-07-27"
    say("Fetching vintage series from ALFRED on %s (no API key needed)..." % vintage_date)
    unrate_s = S.alfred("UNRATE", vintage_date)
    dgs10_s = S.alfred("DGS10", vintage_date)
    say("Fetching NAHB HMI table 2...")
    nahb = S.nahb_hmi("t2")
    hmi_s = nahb["HMI"]

    unrate = z01_mod.to_monthly(unrate_s)
    dgs10 = z01_mod.to_monthly(dgs10_s)
    hmi = z01_mod.to_monthly(hmi_s)

    say("Loaded monthly counts: UNRATE=%d, DGS10=%d, HMI=%d" % (len(unrate), len(dgs10), len(hmi)))

    passports = {
        "UNRATE": unrate_s.describe(),
        "DGS10": dgs10_s.describe(),
        "NAHB_HMI": hmi_s.describe(),
    }

    oos = z01_mod.mi("2013-01-01")
    clean_to = z01_mod.mi("2009-12-01")

    published_calc: dict[str, Any] = {}
    clean_calc: dict[str, Any] = {}

    for code in ("A", "B"):
        spec = z01_mod.CLAIMS[code]
        sign, band, claimed = spec["sign"], spec["band"], spec["lead"]
        k = 12
        if code == "A":
            x = z01_mod.log_change(hmi, k)
            y = z01_mod.diff(unrate, k)
        else:
            x = z01_mod.log_change(hmi, k)
            y = z01_mod.diff(dgs10, k)

        # 1. Published OOS split: in-sample t_to = oos - 1, out-sample t_from = oos
        ins = z01_mod.run_config(
            "oos_in", x, y, sign, band, claimed,
            t_from=None, t_to=oos - 1, reps=0, rng=None, do_boot=False,
        )
        out = z01_mod.run_config(
            "oos_out", x, y, sign, band, claimed,
            t_from=oos, t_to=None, reps=0, rng=None, do_boot=False,
        )
        h_in = ins.get("peak_lag")
        r_at_insample = out["ccf"][h_in] if h_in is not None and "ccf" in out else None
        out["r_at_insample_peak"] = r_at_insample

        pub_claims = z01_pub["claims"][code]["configs"]
        pub_in = pub_claims["oos_in"]
        pub_out = pub_claims["oos_out"]

        say("")
        say("Claim %s: %s" % (code, spec["title"]))
        say("  Published split (computed vs published in result.json):")
        say("    In-sample:  computed lag=%s, r=%s (published lag=%s, r=%s)" % (
            ins.get("peak_lag"), ins.get("peak_r"), pub_in.get("peak_lag"), pub_in.get("peak_r")
        ))
        say("    Out-sample: computed r_at_peak=%s, peak lag=%s, r=%s (published r_at_peak=%s, lag=%s, r=%s)" % (
            r_at_insample, out.get("peak_lag"), out.get("peak_r"),
            pub_out.get("r_at_insample_peak"), pub_out.get("peak_lag"), pub_out.get("peak_r")
        ))

        published_calc[code] = {
            "computed": {
                "oos_in": ins,
                "oos_out": out,
            },
            "published": {
                "oos_in": pub_in,
                "oos_out": pub_out,
            },
            "exact_match": (
                ins.get("peak_lag") == pub_in.get("peak_lag")
                and ins.get("peak_r") == pub_in.get("peak_r")
                and r_at_insample == pub_out.get("r_at_insample_peak")
                and out.get("peak_lag") == pub_out.get("peak_lag")
                and out.get("peak_r") == pub_out.get("peak_r")
            ),
        }

        # 2. Clean OOS split: in-sample t <= 2009-12, out-sample t >= 2013-01
        ins_clean = z01_mod.run_config(
            "oos_clean_in", x, y, sign, band, claimed,
            t_from=None, t_to=clean_to, reps=0, rng=None, do_boot=False,
        )
        out_clean = z01_mod.run_config(
            "oos_clean_out", x, y, sign, band, claimed,
            t_from=oos, t_to=None, reps=0, rng=None, do_boot=False,
        )
        h_clean_in = ins_clean.get("peak_lag")
        r_clean_at_in = out_clean["ccf"][h_clean_in] if h_clean_in is not None and "ccf" in out_clean else None
        out_clean["r_at_insample_peak"] = r_clean_at_in

        say("  Clean partition (t <= 2009-12):")
        say("    In-sample peak:  lag=%s, r=%s, n=%d" % (
            ins_clean.get("peak_lag"), ins_clean.get("peak_r"), ins_clean.get("n", 0)
        ))
        say("    Out-sample:      r at in-sample peak=%s, peak lag=%s, r=%s, n=%d" % (
            r_clean_at_in, out_clean.get("peak_lag"), out_clean.get("peak_r"), out_clean.get("n", 0)
        ))

        clean_calc[code] = {
            "oos_clean_in": ins_clean,
            "oos_clean_out": out_clean,
            "in_sample_peak": [ins_clean.get("peak_lag"), ins_clean.get("peak_r")],
            "r_at_insample_peak": r_clean_at_in,
            "out_sample_peak": [out_clean.get("peak_lag"), out_clean.get("peak_r")],
        }

    return {
        "status": "recalculated_via_alfred",
        "data_passports": passports,
        "published_reproduced": published_calc,
        "clean_cut_recalculation": clean_calc,
    }


def step_shiller_dividends() -> dict[str, Any]:
    say("")
    say("=" * 78)
    say("5. SHILLER DIVIDEND INTERPOLATION AUDIT")
    say("=" * 78)

    url = "https://shillerdata.com/"
    exact_quote = (
        "Monthly dividend and earnings data are computed from the S&P four-quarter "
        "totals for the quarters since 1926, with linear interpolation to monthly "
        "figures. Dividend and earnings data before 1926 are from Cowles and "
        "Associates (Common Stock Indexes, 2nd ed. [Bloomington, Ind.: Principia "
        "Press, 1939]), interpolated from annual data. Stock price data are "
        "monthly averages of daily closing prices."
    )
    say("Source URL: %s" % url)
    say("Literal quote from Shiller documentation:")
    say('  "%s"' % exact_quote)

    requirements = (
        "To measure true monthly lookahead from dividend interpolation, an "
        "independent monthly series of actual cash dividend payments without "
        "linear interpolation is required (such as CRSP monthly total return "
        "indexes or S&P 500 Daily/Monthly Dividend Points from S&P Dow Jones Indices)."
    )
    say("Requirements for uncorrupted measurement: %s" % requirements)

    return {
        "source_url": url,
        "exact_quote": exact_quote,
        "requirements_to_measure": requirements,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Z29: Price of Lookahead (Round 2)")
    ap.add_argument(
        "--step",
        choices=["all", "control", "leaks", "z03", "z01", "shiller"],
        default="all",
        help="Run specific step or all",
    )
    args = ap.parse_args()

    try:
        with open(LOG_PATH, "w", encoding="utf-8") as lf:
            lf.write("")
    except OSError:
        pass

    clean_source = read_z28_clean_source()

    res_path = os.path.join(HERE, "result.json")
    if os.path.exists(res_path) and args.step != "all":
        try:
            with open(res_path, "r", encoding="utf-8") as f:
                full_results = json.load(f)
        except Exception:
            full_results = {
                "task": "Z29",
                "description": "Price of Lookahead (Cena podglyadyvaniya) - Round 2",
            }
    else:
        full_results = {
            "task": "Z29",
            "description": "Price of Lookahead (Cena podglyadyvaniya) - Round 2",
        }

    ctrl_res = step_control(clean_source)
    full_results["honesty_control"] = ctrl_res["control"]

    if args.step in ("all", "leaks"):
        leaks_res = step_leaks(clean_source, ctrl_res)
        full_results["leaks"] = leaks_res

    if args.step in ("all", "z03"):
        z03_res = step_z03()
        full_results["z03_recalculation"] = z03_res

    if args.step in ("all", "z01"):
        z01_res = step_z01()
        full_results["z01_audit"] = z01_res

    if args.step in ("all", "shiller"):
        shiller_res = step_shiller_dividends()
        full_results["shiller_dividend_audit"] = shiller_res

    res_path = os.path.join(HERE, "result.json")
    with open(res_path, "w", encoding="utf-8") as f:
        json.dump(full_results, f, indent=2, ensure_ascii=False)
    say("")
    say("Machine results written to %s" % res_path)
    say("Z29 Round 2 complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
