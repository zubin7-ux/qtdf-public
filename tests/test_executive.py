"""Executive tests — plan hashing, dispositioning, carriers, live-vs-replay.

Run: python tests/test_executive.py
"""
from __future__ import annotations

import copy
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import qtdf
from qtdf.executive import (
    CassetteCarrier,
    FridgeProfile,
    ManualCarrier,
    VFridgeBackend,
    execute,
    load_plan,
    plan_hash,
    read_capture,
    record_id_for,
    replay,
    slots_from_wafer,
)
from qtdf.executive.plan import disposition
from qtdf.store import Store
from qtdf.vfridge import EmuConfig, generate_wafer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN_PATH = os.path.join(REPO, "plans", "coherence_screen_v1.json")


def _wafer(seed=7, rows=3, cols=3, q=2):
    cfg = EmuConfig(seed=seed, rows=rows, cols=cols, qubits_per_die=q)
    return generate_wafer(cfg, 1), cfg


# ---------------- plan ----------------
def test_plan_loads_and_hash_is_content_sensitive():
    plan = load_plan(PLAN_PATH)
    h1 = plan_hash(plan)
    assert h1.startswith("sha256:")
    p2 = copy.deepcopy(plan)
    p2["quantities"][0]["limit"]["value"] = 151.0
    assert plan_hash(p2) != h1
    # key order must not matter (canonicalization)
    p3 = dict(reversed(list(plan.items())))
    assert plan_hash(p3) == h1


def test_disposition_bins():
    plan = load_plan(PLAN_PATH)
    ok = {"T1": 200.0, "T2": 100.0, "f_01": 4.8, "readout_error": 0.01}
    assert disposition(plan, ok)[:2] == ("pass", 1)
    assert disposition(plan, {**ok, "T1": 100.0})[:2] == ("fail", 2)
    assert disposition(plan, {**ok, "readout_error": 0.05})[:2] == ("fail", 3)
    assert disposition(plan, {**ok, "T1": 100.0, "readout_error": 0.05})[:2] == ("fail", 4)
    v, b, reason, _ = disposition(plan, {"T1": None, "T2": None,
                                         "f_01": None, "readout_error": None})
    assert (v, b) == ("fail", 5) and "nonfunctional" in reason


# ---------------- carriers ----------------
def test_cassette_assigns_sockets_per_die_and_enforces_capacity():
    w, _ = _wafer(rows=3, cols=3, q=2)          # 9 dies, 18 qubits
    slots = slots_from_wafer(w)
    car = CassetteCarrier(capacity=24)
    car.load(slots)
    per_die = {}
    for s in slots:
        die = s.device_id.rsplit(":Q", 1)[0]
        per_die.setdefault(die, set()).add(s.socket)
    assert all(len(socks) == 1 for socks in per_die.values())
    assert len({next(iter(s)) for s in per_die.values()}) == 9
    try:
        CassetteCarrier(capacity=4).load(slots)
        raise AssertionError("capacity must be enforced")
    except ValueError:
        pass


def test_manual_carrier_records_validate_without_sockets():
    w, cfg = _wafer()
    slots = ManualCarrier().load(slots_from_wafer(w, max_dies=2))
    with tempfile.TemporaryDirectory() as d:
        st = Store(d)
        s = execute(load_plan(PLAN_PATH), slots, ManualCarrier().meta(),
                    VFridgeBackend(w, cfg), FridgeProfile("BF-LAB-1", 0.010),
                    st, run_id="exec:test:manual")
        assert s["records"] == 4
        rec = next(st.query(load=True))
        assert rec["carrier"]["provider"] == "manual"
        assert rec["carrier"]["socket"] is None


# ---------------- the core property: live == replay, byte for byte ----------
def test_live_and_replay_are_byte_identical():
    w, cfg = _wafer(rows=4, cols=4, q=3)
    slots = CassetteCarrier().load(slots_from_wafer(w, max_dies=16))
    plan = load_plan(PLAN_PATH)
    with tempfile.TemporaryDirectory() as d:
        live, rep = Store(os.path.join(d, "live")), Store(os.path.join(d, "rep"))
        cap_path = os.path.join(d, "cap.json")
        s1 = execute(plan, slots, CassetteCarrier().meta(),
                     VFridgeBackend(w, cfg), FridgeProfile("VF-1", 0.012),
                     live, run_id="exec:test:load01", capture_path=cap_path)
        s2 = replay(read_capture(cap_path), rep)
        assert s1["records"] == s2["records"] == 48
        assert s1["plan_hash"] == s2["plan_hash"]
        live_rows = {r["record_id"]: r["content_hash"] for r in live.index()}
        rep_rows = {r["record_id"]: r["content_hash"] for r in rep.index()}
        assert live_rows == rep_rows            # ids AND hashes identical
        # and the record FILES are byte-identical too
        for rid in live_rows:
            f = rid.split(":")[-1] + ".json"
            with open(os.path.join(live.records_dir, f), "rb") as a, \
                 open(os.path.join(rep.records_dir, f), "rb") as b:
                assert a.read() == b.read()


def test_two_live_runs_same_run_id_same_identity():
    w, cfg = _wafer()
    plan = load_plan(PLAN_PATH)
    slots = CassetteCarrier().load(slots_from_wafer(w, max_dies=2))
    with tempfile.TemporaryDirectory() as d:
        a, b = Store(os.path.join(d, "a")), Store(os.path.join(d, "b"))
        fixed = "2026-07-09T00:00:00Z"
        for st in (a, b):
            execute(plan, slots, CassetteCarrier().meta(),
                    VFridgeBackend(w, cfg), FridgeProfile("VF-1", 0.012),
                    st, run_id="exec:test:x", generated_at=fixed)
        assert ({r["content_hash"] for r in a.index()}
                == {r["content_hash"] for r in b.index()})


def test_record_id_deterministic():
    assert record_id_for("run:a", "dev:1") == record_id_for("run:a", "dev:1")
    assert record_id_for("run:a", "dev:1") != record_id_for("run:b", "dev:1")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
