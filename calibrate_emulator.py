#!/usr/bin/env python3
"""Calibrate the virtual fridge against the measured IBM fleet in the store.

Fits the emulator's T1 / readout distributions to a modern-process cohort
(chips with >= --min-qubits qubits, i.e. current-generation devices) so that
emulated wafers are statistically grounded in real measured data — the
"never synthetic in a vacuum" rule. Writes emulator_calibration.json, which
vfridge loads as its defaults.

    python calibrate_emulator.py [--store store] [--min-qubits 100]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qtdf.store import Store


def _quantile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    i = q * (len(xs) - 1)
    lo, hi = int(i), min(int(i) + 1, len(xs) - 1)
    return xs[lo] + (i - lo) * (xs[hi] - xs[lo])


def _sigma_ln(xs: list[float]) -> float:
    """Robust lognormal sigma from the p10-p90 span (z_0.9 = 1.2816)."""
    p10, p90 = _quantile(xs, 0.10), _quantile(xs, 0.90)
    return (math.log(p90) - math.log(p10)) / (2 * 1.2816)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="store")
    ap.add_argument("--min-qubits", type=int, default=100)
    ap.add_argument("--out", default="emulator_calibration.json")
    a = ap.parse_args()

    store = Store(a.store)
    per_chip = defaultdict(list)
    for rec in store.query(record_type="qubit_coherence_screen",
                           data_source="measured", load=True):
        per_chip[rec["device"]["genealogy"]["chip"]].append(rec)

    cohort = {c: rs for c, rs in per_chip.items() if len(rs) >= a.min_qubits}
    if not cohort:
        print("no chips meet the cohort threshold", file=sys.stderr)
        return 1

    t1s, t2s, ros = [], [], []
    for recs in cohort.values():
        for rec in recs:
            m = {x["quantity"]: x["value"] for x in rec["measurements"]}
            if isinstance(m.get("T1"), (int, float)) and m["T1"] > 0:
                t1s.append(m["T1"])
            if isinstance(m.get("T2"), (int, float)) and m["T2"] > 0:
                t2s.append(m["T2"])
            if isinstance(m.get("readout_error"), (int, float)) and m["readout_error"] > 0:
                ros.append(m["readout_error"])

    t1_med = statistics.median(t1s)
    t2_med = statistics.median(t2s)
    # back out a dephasing time consistent with the medians: 1/T2 = 1/(2 T1) + 1/Tphi
    inv_tphi = max(1.0 / t2_med - 0.5 / t1_med, 1e-6)
    cal = {
        "cohort": {"chips": sorted(cohort), "min_qubits": a.min_qubits,
                   "qubits": sum(len(v) for v in cohort.values())},
        "t1_median_us": round(t1_med, 1),
        "t1_sigma_ln": round(_sigma_ln(t1s), 3),
        "tphi_median_us": round(1.0 / inv_tphi, 1),
        "tphi_sigma_ln": round(_sigma_ln(t2s), 3),
        "ro_err_median": round(statistics.median(ros), 5),
        "ro_err_sigma_ln": round(_sigma_ln(ros), 3),
        "source_store": a.store,   # as given, never an absolute user path
    }
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(cal, fh, indent=1)
        fh.write("\n")

    print(f"cohort: {len(cohort)} chips, {cal['cohort']['qubits']} measured qubits")
    print(f"T1     : median {cal['t1_median_us']} us, sigma_ln {cal['t1_sigma_ln']}")
    print(f"Tphi   : median {cal['tphi_median_us']} us (from T2 median {round(t2_med, 1)} us)")
    print(f"ro_err : median {cal['ro_err_median']}, sigma_ln {cal['ro_err_sigma_ln']}")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
