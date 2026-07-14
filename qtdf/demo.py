"""The packaged end-to-end demo: `qtdf demo`.

Self-contained — the plan is embedded and the emulator uses its built-in
(fleet-calibrated) defaults, so this runs identically on a clean install with
zero repo files: virtual lot -> executive screen -> wafer map -> policy
pricing vs truth -> MCM assembly -> store integrity.
"""
from __future__ import annotations

import os
import shutil
import tempfile

DEMO_PLAN = {
    "plan_id": "demo-coherence-screen",
    "plan_version": "1.0.0",
    "record_type": "qubit_coherence_screen",
    "quantities": [
        {"quantity": "T1", "symbol": "T1", "unit": "us",
         "limit": {"op": ">=", "value": 150.0}},
        {"quantity": "T2", "symbol": "T2", "unit": "us"},
        {"quantity": "f_01", "symbol": "f01", "unit": "GHz"},
        {"quantity": "readout_error", "symbol": "eps_ro", "unit": "1",
         "limit": {"op": "<=", "value": 0.02}},
    ],
    "disposition": {
        "spec_id": "MCM-GRADE-v0",
        "response_quantity": "T1",
        "pass_bin": 1,
        "default_fail_bin": 9,
        "bin_map": [
            {"bin": 2, "when_failed": ["T1"]},
            {"bin": 3, "when_failed": ["readout_error"]},
            {"bin": 4, "when_failed": ["T1", "readout_error"]},
            {"bin": 5, "nonfunctional": True},
        ],
    },
}


def run(seed: int = 42, rows: int = 10, cols: int = 10,
        store_dir: str | None = None, echo=print) -> int:
    from qtdf.executive import (
        CassetteCarrier, FridgeProfile, VFridgeBackend, execute, plan_hash,
        read_capture, replay, slots_from_wafer,
    )
    from qtdf.store import Store
    from qtdf.vfridge import EmuConfig, generate_wafer

    # the dispositioning/analytics layer ships separately (commercial); the
    # demo runs end-to-end either way, swapping the finale
    try:
        from qtdf.analytics import ModuleSpec, ascii_map, die_map_from_store, \
            radial_yield, score_module, select_modules
        from qtdf.disposition import (
            ConfirmPass, GrayZoneRetest, SinglePass, Spec, compare,
            measured_die_values,
        )
        commercial = True
    except ImportError:
        commercial = False

    tmp = None
    if store_dir is None:
        tmp = tempfile.mkdtemp(prefix="qtdf-demo-")
        store_dir = tmp
    try:
        store = Store(store_dir)
        cfg = EmuConfig.from_calibration(seed=seed, lot_id="LOT-DEMO",
                                         rows=rows, cols=cols, qubits_per_die=4)
        wafer = generate_wafer(cfg, 1)
        limits = {q["quantity"]: q["limit"]
                  for q in DEMO_PLAN["quantities"] if q.get("limit")}
        spec_id = DEMO_PLAN["disposition"]["spec_id"]
        echo(f"qtdf end-to-end demo — lot {cfg.lot_id}: {rows}x{cols} dies x 4 qubits"
             f" (seed {seed})")
        echo(f"plan {DEMO_PLAN['plan_id']} {plan_hash(DEMO_PLAN)[:18]}…  "
             f"spec {spec_id}: T1>={limits['T1']['value']}us, "
             f"ro<={limits['readout_error']['value']}\n")

        # 1 — screen the wafer through the executive (cassette carrier)
        carrier = CassetteCarrier(capacity=10 ** 6)
        slots = carrier.load(slots_from_wafer(wafer))
        run_id = "demo:screen:r1"
        cap_path = os.path.join(store_dir, "demo_capture.json")
        summary = execute(DEMO_PLAN, slots, carrier.meta(),
                          VFridgeBackend(wafer, cfg),
                          FridgeProfile("VF-1", 0.012), store, run_id=run_id,
                          capture_path=None if commercial else cap_path)
        echo(f"== screen: {summary['records']} qubit records, "
             f"verdicts {summary['verdicts']} ==\n")

        if not commercial:
            # open-build finale: prove the record/replay property live
            rep = Store(os.path.join(store_dir, "replay"))
            s2 = replay(read_capture(cap_path), rep)
            live = {r["record_id"]: r["content_hash"] for r in store.index()}
            back = {r["record_id"]: r["content_hash"] for r in rep.index()}
            echo("== record/replay: captured run replayed into a fresh store ==")
            echo(f"  byte-identical reproduction: {live == back}"
                 f"  ({s2['records']} records)")
            echo("  (any captured run — virtual or a real fridge session — is a"
                 " CI fixture)\n")
            echo("(wafer maps, policy pricing, and MCM assembly-risk scoring live"
                 " in the\n commercial layer; this open build carries the standard"
                 " + executive)\n")
            n = sum(1 for _ in store.index())
            bad = store.verify_all()
            echo(f"store: {n} records, "
                 f"{'all hashes verified' if not bad else f'{len(bad)} HASH FAILURES'}")
            return 0 if not bad and live == back else 1

        spec = Spec.from_plan(DEMO_PLAN)

        # 2 — wafer map (a VIEW: values re-dispositioned under the spec)
        dm = die_map_from_store(store, run_id, spec)
        echo(f"== wafer map ('.' = known-good-die under {spec.spec_id}) ==")
        echo(ascii_map(dm, rows, cols))
        rz = radial_yield(dm, rows, cols)
        (cy, cn), (ey, en) = rz["center"], rz["edge"]
        echo(f"radial: center {100 * cy:.0f}% ({cn} dies) vs edge {100 * ey:.0f}%"
             f" ({en} dies)\n")

        # 3 — screening policies priced exactly against truth
        echo("== screening policies priced vs truth "
             "(escape $50k, overkill $2k, test $200) ==")
        rows_ = compare([SinglePass(), ConfirmPass(2), GrayZoneRetest(0.15)],
                        [wafer], cfg, DEMO_PLAN, store, spec)
        for m in rows_:
            echo(f"  {m['policy']:14s} ship {m['shipped']:3d}  esc {m['escapes']:2d}"
                 f"  ovk {m['overkill']:2d}  cost {m['cost_die_cooldowns']:3d}"
                 f"  -> ${m['usd_total']:>9,.0f}")
        echo(f"  winner: {rows_[0]['policy']}  "
             f"(true good dies: {rows_[0]['true_good']}/{rows_[0]['dies']})\n")

        # 4 — MCM assembly. The strict-KGD bin is tiny AND same-index qubits
        # share one frequency plan across dies, so chains built only from that
        # bin usually collide at the >=25 MHz interface rule (this is why real
        # module builders stagger die frequency plans). So: assemble from all
        # functional dies and let the scorer price each chain's risk.
        vals = measured_die_values(store, run_id)
        kgd = [d for d, qv in vals.items() if spec.die_pass(qv)]
        functional = [
            {"die_id": d, "qubits": qv} for d, qv in sorted(vals.items())
            if all(v is not None for qv2 in qv for v in qv2.values())
        ]
        mspec = ModuleSpec(dies_per_module=3)
        modules = select_modules(functional, mspec, mc=400, seed=seed)
        echo(f"== MCM assembly ({mspec.dies_per_module}-die chains, "
             f">= {mspec.min_sep_MHz:.0f} MHz interface separation) ==")
        echo(f"  strict-KGD bin: {len(kgd)} dies (identical frequency plans -> "
             f"chains collide); assembling from {len(functional)} functional dies:")
        scored = sorted(
            ((score_module(m, mspec, mc=800, seed=seed), m) for m in modules),
            key=lambda x: -x[0])
        for i, (p, mod) in enumerate(scored[:3]):
            echo(f"  best module {i + 1}: P(meets spec) = {p:.2f}  "
                 f"[{', '.join(d['die_id'].rsplit(':', 1)[-1] for d in mod)}]")
        if len(scored) > 3:
            echo(f"  ... {len(scored) - 3} more assembled; "
                 f"worst P = {scored[-1][0]:.2f} — pick with eyes open")

        # 5 — integrity
        n = sum(1 for _ in store.index())
        bad = store.verify_all()
        echo(f"\nstore: {n} records, "
             f"{'all hashes verified' if not bad else f'{len(bad)} HASH FAILURES'}")
        return 0 if not bad else 1
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
