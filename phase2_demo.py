#!/usr/bin/env python3
"""Phase 2 closed-loop demo: emulated lot -> QTDF store -> disposition vs TRUTH.

Generates a calibrated virtual lot, screens it through a cooldown into a QTDF
store, then joins the pipeline's verdicts against the truth sidecar to compute
the numbers a fridge can never give you exactly: ESCAPE (bad die shipped) and
OVERKILL (good die killed). Also demonstrates the classic adaptive-test move —
retesting failed dies in a second cooldown — and prices its escape/overkill
trade-off.

    python phase2_demo.py [--store store_emu] [--seed 42]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qtdf.store import Store
from qtdf.vfridge import (
    MCM_GRADE_V0,
    Cooldown,
    EmuConfig,
    MeasConfig,
    die_truth_pass,
    generate_lot,
    truth_sidecar,
)


def die_verdicts_from_store(store: Store, run_prefix: str) -> dict:
    """die_id -> measured known-good-die verdict (all its qubits pass)."""
    per_die = defaultdict(list)
    for row in store.index():
        if row["run_id"] and row["run_id"].startswith(run_prefix):
            die_id = row["device_id"].rsplit(":Q", 1)[0]
            per_die[die_id].append(row["verdict"])
    return {d: all(v == "pass" for v in vs) for d, vs in per_die.items()}


def confusion(truth: dict, measured: dict):
    tp = sum(1 for d, ok in measured.items() if ok and truth[d])
    escape = sum(1 for d, ok in measured.items() if ok and not truth[d])
    overkill = sum(1 for d, ok in measured.items() if not ok and truth[d])
    tn = sum(1 for d, ok in measured.items() if not ok and not truth[d])
    return tp, escape, overkill, tn


def report(tag: str, tp: int, escape: int, overkill: int, tn: int):
    shipped = tp + escape
    good = tp + overkill
    print(f"\n== {tag} ==")
    print(f"confusion          : TP={tp}  escape={escape}  overkill={overkill}  TN={tn}")
    print(f"escape rate        : {escape}/{shipped} shipped = "
          f"{100.0 * escape / shipped if shipped else 0:.2f}%")
    print(f"overkill rate      : {overkill}/{good} true-good = "
          f"{100.0 * overkill / good if good else 0:.2f}%")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="store_emu")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    if os.path.exists(a.store):
        shutil.rmtree(a.store)          # demo store is regenerated every run
    store = Store(a.store)

    cfg = EmuConfig.from_calibration(seed=a.seed, lot_id="LOT-EMU-26H",
                                     wafers=2, rows=10, cols=10, qubits_per_die=4)
    meas = MeasConfig()
    spec = MCM_GRADE_V0

    wafers = generate_lot(cfg)
    n_qubits = sum(w.qubit_count() for w in wafers)
    print(f"lot {cfg.lot_id}: {len(wafers)} wafers x {cfg.rows}x{cfg.cols} dies "
          f"x {cfg.qubits_per_die}q = {n_qubits} qubits")
    print(f"emulator calibration: T1 median {cfg.t1_median_us} us "
          f"(sigma_ln {cfg.t1_sigma_ln}), ro median {cfg.ro_err_median}")
    print(f"screen spec: {spec['spec_id']} — T1>={spec['t1_min_us']} us, "
          f"ro_err<={spec['ro_err_max']}")

    # truth sidecar lives NEXT TO the store, never inside it
    truth = truth_sidecar(wafers)
    os.makedirs("truth", exist_ok=True)
    truth_path = os.path.join("truth", f"{cfg.lot_id}.json")
    with open(truth_path, "w", encoding="utf-8") as fh:
        json.dump(truth, fh, indent=1)
    die_truth = {d.die_id: die_truth_pass(d, spec)
                 for w in wafers for d in w.dies}
    n_true_good = sum(die_truth.values())
    print(f"truth (sidecar)    : {n_true_good}/{len(die_truth)} dies are "
          f"intrinsically MCM-grade -> {truth_path}")

    # ---- cooldown 1: screen everything ----
    n_rec = 0
    cds = {}
    for w in wafers:
        cd = Cooldown(w, cfg, meas, cooldown_no=1)
        n_rec += cd.measure_dies(store, spec=spec)
        cds[w.wafer_id] = w
    print(f"cooldown 1         : {n_rec} QTDF records -> {store.root}")

    measured1 = die_verdicts_from_store(store, run_prefix=f"emu:{cfg.lot_id}")
    tp, esc, ovk, tn = confusion(die_truth, measured1)
    report("single-cooldown screen (die level, known-good-die)", tp, esc, ovk, tn)

    # ---- adaptive retest: second cooldown for cd1-failed dies only ----
    failed_ids = {d for d, ok in measured1.items() if not ok}
    n_retest = 0
    for w in wafers:
        retest = [d for d in w.dies if d.die_id in failed_ids]
        if retest:
            cd2 = Cooldown(w, cfg, meas, cooldown_no=2)
            n_retest += cd2.measure_dies(store, dies=retest, spec=spec)
    print(f"\nretest cooldown    : {len(failed_ids)} failed dies remeasured "
          f"({n_retest} records)")

    # best-of-two policy: pass if either cooldown passes
    measured2 = dict(measured1)
    per_die_cd2 = defaultdict(list)
    for row in store.index():
        if row["run_id"] and ":cd02" in row["run_id"]:
            per_die_cd2[row["device_id"].rsplit(":Q", 1)[0]].append(row["verdict"])
    for die_id, vs in per_die_cd2.items():
        if all(v == "pass" for v in vs):
            measured2[die_id] = True
    tp2, esc2, ovk2, tn2 = confusion(die_truth, measured2)
    report("after retest (best-of-two policy)", tp2, esc2, ovk2, tn2)
    print(f"\nretest recovered {ovk - ovk2} good dies (overkill "
          f"{ovk}->{ovk2}) at a cost of {esc2 - esc} extra escapes ({esc}->{esc2})")

    bad = store.verify_all()
    print(f"\nstore integrity    : {len(list(store.index()))} records, "
          f"{'ALL hashes OK' if not bad else f'{len(bad)} FAILED'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
