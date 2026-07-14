#!/usr/bin/env python3
"""Fleet report — the Phase 1 payoff demo, stdlib only.

Reads a QTDF store and prints fleet-level yield analytics over whatever is in
it (measured IBM snapshots + the openEMS simulation record coexist; the report
never mixes data sources silently).

    python fleet_report.py [--store store]
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qtdf.store import Store


def pct(part: int, whole: int) -> str:
    return f"{100.0 * part / whole:5.1f}%" if whole else "  n/a"


def quantile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    i = q * (len(xs) - 1)
    lo, hi = int(i), min(int(i) + 1, len(xs) - 1)
    return xs[lo] + (i - lo) * (xs[hi] - xs[lo])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="store")
    a = ap.parse_args()
    store = Store(a.store)

    rows = list(store.index())
    if not rows:
        print("store is empty")
        return 1

    by_source = Counter(r["data_source"] for r in rows)
    print(f"QTDF store: {store.root}")
    print(f"records            : {len(rows)}")
    print(f"by data_source     : " + ", ".join(f"{k}={v}" for k, v in sorted(by_source.items())))

    bad = store.verify_all()
    print(f"hash verification  : {'ALL OK' if not bad else f'{len(bad)} FAILED'}")

    # ---- measured coherence fleet ----
    screens = [r for r in store.query(record_type="qubit_coherence_screen",
                                      data_source="measured", load=True)]
    if not screens:
        return 0

    chips = defaultdict(list)
    t1s, t2s, ro_errs = [], [], []
    verdicts = Counter()
    bins = Counter()
    for rec in screens:
        chip = rec["device"]["genealogy"]["chip"]
        verdicts[rec["disposition"]["verdict"]] += 1
        bins[rec["disposition"]["bin"]] += 1
        m = {x["quantity"]: x["value"] for x in rec["measurements"]}
        chips[chip].append((m.get("T1"), rec["disposition"]["verdict"]))
        if isinstance(m.get("T1"), (int, float)):
            t1s.append(m["T1"])
        if isinstance(m.get("T2"), (int, float)):
            t2s.append(m["T2"])
        if isinstance(m.get("readout_error"), (int, float)):
            ro_errs.append(m["readout_error"])

    n = len(screens)
    print(f"\n== measured qubit fleet ==")
    print(f"qubits             : {n} across {len(chips)} chips")
    print(f"verdicts           : " + ", ".join(
        f"{k}={v} ({pct(v, n).strip()})" for k, v in verdicts.most_common()))
    print(f"bin pareto         : " + ", ".join(
        f"bin{k}={v}" for k, v in sorted(bins.items())))
    if t1s:
        print(f"T1 (us)            : median {statistics.median(t1s):7.1f}   "
              f"p10 {quantile(t1s, 0.10):7.1f}   p90 {quantile(t1s, 0.90):7.1f}   "
              f"min {min(t1s):6.1f}   max {max(t1s):7.1f}")
    if t2s:
        print(f"T2 (us)            : median {statistics.median(t2s):7.1f}   "
              f"p10 {quantile(t2s, 0.10):7.1f}   p90 {quantile(t2s, 0.90):7.1f}")
    if ro_errs:
        print(f"readout error      : median {statistics.median(ro_errs):.4f}   "
              f"p90 {quantile(ro_errs, 0.90):.4f}")

    # ---- per-chip yield, best & worst ----
    def chip_yield(items):
        good = sum(1 for t1, v in items if v == "pass")
        return good / len(items)

    ranked = sorted(chips.items(), key=lambda kv: chip_yield(kv[1]), reverse=True)
    print(f"\n== chip yield (demo spec: T1>=75us & ro_err<=0.03) ==")
    print(f"{'chip':28s} {'qubits':>6s} {'yield':>7s}  {'median T1 (us)':>14s}")
    show = ranked[:8] + ([("...", [])] if len(ranked) > 16 else []) + ranked[-8:]
    for chip, items in show:
        if chip == "...":
            print("  ...")
            continue
        t1vals = [t1 for t1, _ in items if isinstance(t1, (int, float))]
        med = f"{statistics.median(t1vals):14.1f}" if t1vals else " " * 14
        print(f"{chip:28s} {len(items):6d} {pct(sum(1 for _, v in items if v == 'pass'), len(items)):>7s} {med}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
