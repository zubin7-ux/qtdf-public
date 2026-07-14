#!/usr/bin/env python3
"""Phase 3 demo: one cassette load through the executive, captured, replayed.

Flow: versioned plan -> cassette carrier (24 dies, sockets auto-assigned) ->
vfridge backend -> QTDF records with run identity + plan hash -> capture file
-> replay into a second store -> prove byte-identical reproduction.

    python phase3_demo.py
"""
from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from qtdf.executive import (
    CassetteCarrier,
    FridgeProfile,
    VFridgeBackend,
    execute,
    load_plan,
    read_capture,
    replay,
    slots_from_wafer,
)
from qtdf.store import Store
from qtdf.vfridge import EmuConfig, generate_wafer


def main() -> int:
    for d in ("store_exec", "store_replay"):
        if os.path.exists(d):
            shutil.rmtree(d)
    os.makedirs("captures", exist_ok=True)

    plan = load_plan("plans/coherence_screen_v1.json")
    cfg = EmuConfig.from_calibration(seed=42, lot_id="LOT-EMU-26H", wafers=1)
    wafer = generate_wafer(cfg, 1)

    carrier = CassetteCarrier(capacity=24)
    slots = carrier.load(slots_from_wafer(wafer, max_dies=24))
    fridge = FridgeProfile("VF-1", temperature_K=0.012,
                           note="virtual dilution refrigerator")

    cap_path = os.path.join("captures", "LOT-EMU-26H_W01_load01.json")
    live = Store("store_exec")
    summary = execute(plan, slots, carrier.meta(),
                      VFridgeBackend(wafer, cfg), fridge, live,
                      run_id="exec:LOT-EMU-26H:W01:load01",
                      capture_path=cap_path)

    print(f"plan               : {plan['plan_id']} v{plan['plan_version']}")
    print(f"plan_hash          : {summary['plan_hash'][:23]}...")
    print(f"load               : 24 dies / {summary['records']} qubits, "
          f"sockets S01-S24, cassette {carrier.cassette_id}")
    print(f"run                : {summary['run_id']}")
    print(f"verdicts           : {summary['verdicts']}")
    print(f"capture            : {cap_path}")

    rep = Store("store_replay")
    replay(read_capture(cap_path), rep)

    live_rows = {r["record_id"]: r["content_hash"] for r in live.index()}
    rep_rows = {r["record_id"]: r["content_hash"] for r in rep.index()}
    identical = live_rows == rep_rows
    print(f"\nreplay             : {len(rep_rows)} records "
          f"-> byte-identical: {identical}")
    if not identical:
        return 1
    print("=> any captured run (virtual today, real fridge later) is a CI fixture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
