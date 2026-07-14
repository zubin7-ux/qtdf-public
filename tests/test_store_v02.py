"""QTDF v0.2 tests — store, quantity profiles, wafer/run blocks, v0.1 compat.

Run: python tests/test_store_v02.py
"""
from __future__ import annotations

import copy
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import qtdf
from qtdf.store import Store

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORD1 = os.path.join(REPO, "records", "ENG-RF-002_optAB_GSG.qtdf.json")


def _screen_record(device_id="DIE-0001", t1=82.0) -> dict:
    return {
        "qtdf_version": qtdf.QTDF_VERSION,
        "record_id": qtdf.new_record_id(),
        "record_type": "qubit_coherence_screen",
        "data_source": "measured",
        "device": {
            "device_id": device_id,
            "wafer": {"lot_id": "LOT-A", "wafer_id": "W03", "die_x": 4, "die_y": 7},
        },
        "carrier": {"provider": "cassette", "socket": "A1"},
        "fixture": {"fridge_id": "BF-1", "temperature_K": 0.012},
        "test": {"test_plan": "screen-v1"},
        "calibration": {"reference_impedance_ohm": 50.0},
        "run": {"run_id": "cooldown-2026-07-01"},
        "measurements": [
            {"quantity": "T1", "unit": "us", "value": t1,
             "limit": {"op": ">=", "value": 50.0}, "pass": t1 >= 50.0},
            {"quantity": "T2", "unit": "us", "value": t1 * 0.6, "limit": None, "pass": None},
        ],
        "disposition": {"verdict": "pass" if t1 >= 50.0 else "fail", "bin": 1 if t1 >= 50.0 else 2},
        "provenance": {"generated_at": qtdf.utc_now(), "tool": "unit-test"},
    }


# ---------------- profiles ----------------
def test_profile_missing_required_quantity_is_error():
    rec = _screen_record()
    rec["measurements"] = [m for m in rec["measurements"] if m["quantity"] != "T1"]
    problems = qtdf.errors_only(qtdf.validate(rec))
    assert any("requires quantity 'T1'" in p for p in problems)


def test_profile_unknown_record_type_skips_profile():
    rec = _screen_record()
    rec["record_type"] = "some_future_test"
    rec["measurements"] = []
    assert qtdf.is_valid(rec)  # only a novel-vocab warning


# ---------------- wafer / run blocks ----------------
def test_wafer_bad_types_rejected():
    rec = _screen_record()
    rec["device"]["wafer"]["die_x"] = "four"
    assert not qtdf.is_valid(rec)


def test_run_requires_run_id():
    rec = _screen_record()
    rec["run"] = {"cooldown_id": "cd-1"}
    assert not qtdf.is_valid(rec)


# ---------------- store ----------------
def test_store_add_get_query_verify_rebuild():
    with tempfile.TemporaryDirectory() as d:
        st = Store(d)
        ids = [st.add(_screen_record(device_id=f"DIE-{i:04d}", t1=40.0 + i))
               for i in range(6)]
        assert st.count() == 6
        # get round-trips and verifies
        rec = st.get(ids[0])
        assert qtdf.verify_hash(rec)
        # query: t1=40..45 -> DIE-0000..09 fail below 50
        fails = list(st.query(verdict="fail"))
        passes = list(st.query(verdict="pass"))
        assert len(fails) + len(passes) == 6
        assert all(r["verdict"] == "fail" for r in fails)
        # device_prefix + load
        loaded = list(st.query(device_prefix="DIE-000", load=True))
        assert len(loaded) == 6 and all("measurements" in r for r in loaded)
        # verify_all clean, index rebuild reproduces the same count
        assert st.verify_all() == []
        assert st.rebuild_index() == 6
        assert st.count() == 6


def test_store_refuses_duplicates_and_invalid():
    with tempfile.TemporaryDirectory() as d:
        st = Store(d)
        rec = _screen_record()
        st.add(rec)
        dup = copy.deepcopy(rec)
        try:
            st.add(dup)
            raise AssertionError("duplicate record_id must be refused")
        except ValueError as e:
            assert "append-only" in str(e)
        bad = _screen_record()
        bad["disposition"]["verdict"] = "maybe"
        try:
            st.add(bad)
            raise AssertionError("invalid record must be refused")
        except ValueError as e:
            assert "failed validation" in str(e)


# ---------------- v0.1 compatibility (the additive promise) ----------------
def test_v01_record_still_loads_validates_and_verifies():
    if not os.path.exists(RECORD1):
        print("  (skip: record #1 not generated)")
        return
    rec = qtdf.read_record(RECORD1)
    assert rec["qtdf_version"].startswith("0.1")
    assert qtdf.is_valid(rec), qtdf.errors_only(qtdf.validate(rec))
    assert qtdf.verify_hash(rec)


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
