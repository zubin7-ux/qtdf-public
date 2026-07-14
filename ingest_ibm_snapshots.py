#!/usr/bin/env python3
"""Ingest IBM calibration snapshots -> QTDF store (real measured qubit data).

qiskit-ibm-runtime's fake_provider bundles static snapshots of REAL historical
calibrations of IBM production devices (T1/T2/frequency per qubit, readout
error). One QTDF record is emitted per qubit: record_type=qubit_coherence_screen,
data_source=measured. This grounds the coherence vocabulary in measured data and
fills the store with a fleet to build analytics against — no fridge required.

Dispositioning uses an explicitly-labeled DEMO spec (not a customer spec):
    T1 >= 75 us  AND  readout_error <= 0.03
Bins: 1 pass | 2 fail T1 | 3 fail readout | 4 fail both | 0 hold (incomplete cal)

Run with the repo venv (qtdf-core itself stays stdlib-only):
    .venv/bin/python ingest_ibm_snapshots.py [--store store] [--limit N]
"""
from __future__ import annotations

import argparse
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import qtdf
from qtdf.store import Store

DEMO_SPEC_ID = "DEMO-SCREEN-v0"
T1_MIN_US = 75.0
RO_ERR_MAX = 0.03


def iter_fake_backends(limit: int | None):
    """Yield (backend, data_source) for each snapshot.

    Most fake backends are static snapshots of REAL calibrations -> 'measured'.
    Some (e.g. fake_nighthawk) warn that their properties are placeholders, not
    representative device values -> honestly labeled 'emulated'. Mislabeling a
    synthetic snapshot as measured is exactly the failure QTDF exists to prevent.
    """
    import warnings

    from qiskit_ibm_runtime import fake_provider as fp

    classes = [
        obj for name, obj in vars(fp).items()
        if name.startswith("Fake") and "Provider" not in name and inspect.isclass(obj)
    ]
    n = 0
    for cls in sorted(classes, key=lambda c: c.__name__):
        if limit is not None and n >= limit:
            return
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                backend = cls()
            placeholder = any("not intended to represent" in str(w.message) for w in caught)
            yield backend, ("emulated" if placeholder else "measured")
            n += 1
        except Exception as e:  # noqa: BLE001 - skip snapshots that fail to load
            print(f"  skip {cls.__name__}: {e}", file=sys.stderr)


def _measurement(quantity, symbol, value, unit, limit=None, note=None):
    m = {"quantity": quantity, "symbol": symbol, "value": value, "unit": unit,
         "limit": limit, "pass": None}
    if limit is not None and isinstance(value, (int, float)):
        op, ref = limit["op"], limit["value"]
        m["pass"] = value <= ref if op == "<=" else value >= ref
    if note:
        m["note"] = note
    return m


def qubit_record(backend, q: int, runtime_version: str,
                 data_source: str = "measured") -> dict:
    qp = backend.qubit_properties(q)
    t1_us = qp.t1 * 1e6 if qp and qp.t1 is not None else None
    t2_us = qp.t2 * 1e6 if qp and qp.t2 is not None else None
    f01_ghz = qp.frequency / 1e9 if qp and qp.frequency is not None else None

    ro_err = None
    try:
        meas = backend.target.get("measure")
        if meas and (q,) in meas:
            props = meas[(q,)]
            ro_err = getattr(props, "error", None)
    except Exception:  # noqa: BLE001
        pass

    measurements = [
        _measurement("T1", "T1", round(t1_us, 2) if t1_us is not None else None,
                     "us", {"op": ">=", "value": T1_MIN_US}
                     if t1_us is not None else None),
        _measurement("T2", "T2", round(t2_us, 2) if t2_us is not None else None,
                     "us", note="CPMG/echo per IBM calibration"),
        _measurement("f_01", "f01", round(f01_ghz, 6) if f01_ghz is not None else None,
                     "GHz"),
        _measurement("readout_error", "eps_ro",
                     round(ro_err, 5) if ro_err is not None else None,
                     "1", {"op": "<=", "value": RO_ERR_MAX}
                     if ro_err is not None else None),
    ]

    t1_ok = measurements[0]["pass"]
    ro_ok = measurements[3]["pass"]
    if t1_ok is None or ro_ok is None:
        verdict, binno, reason = "hold", 0, "incomplete calibration data"
    elif t1_ok and ro_ok:
        verdict, binno, reason = "pass", 1, None
    elif not t1_ok and ro_ok:
        verdict, binno, reason = "fail", 2, None
    elif t1_ok and not ro_ok:
        verdict, binno, reason = "fail", 3, None
    else:
        verdict, binno, reason = "fail", 4, None

    online = getattr(backend, "online_date", None)

    return {
        "qtdf_version": qtdf.QTDF_VERSION,
        "record_id": qtdf.new_record_id(),
        "record_type": "qubit_coherence_screen",
        "data_source": data_source,
        "device": {
            "device_id": f"IBM:{backend.name}:Q{q}",
            "part_number": backend.name,
            "description": f"transmon qubit {q} of {backend.num_qubits} on {backend.name}",
            "genealogy": {
                "vendor": "IBM",
                "chip": backend.name,
                "num_qubits": backend.num_qubits,
                "online_date": online.isoformat() if online else None,
            },
        },
        "carrier": {
            "provider": "custom",
            "carrier_part": None,
            "socket": None,
            "note": "IBM production packaging; carrier details not published",
        },
        "fixture": {
            "fridge_id": backend.name,
            "temperature_K": None,
            "note": "IBM production dilution refrigerator; temperature not published",
            "ports": None,
        },
        "test": {
            "test_plan": "IBM standard calibration cycle",
            "executive": "IBM internal",
            "band_GHz": None,
            "operator": "IBM",
            "note": "static snapshot of a real calibration, bundled with qiskit-ibm-runtime",
        },
        "calibration": {
            "reference_impedance_ohm": None,
            "note": "vendor-calibrated; per-qubit cal metadata not exposed in snapshot",
        },
        "run": {
            "run_id": f"ibm-cal-snapshot:{backend.name}",
            "cooldown_id": None,
            "plan_hash": None,
            "source_package": f"qiskit-ibm-runtime {runtime_version}",
        },
        "measurements": measurements,
        "disposition": {
            "verdict": verdict,
            "bin": binno,
            "override": False,
            "reason": reason,
            "rules": [
                {"rule_id": f"{DEMO_SPEC_ID}:T1", "quantity": "T1",
                 "limit": {"op": ">=", "value": T1_MIN_US},
                 "result": "pass" if t1_ok else ("fail" if t1_ok is not None else "hold")},
                {"rule_id": f"{DEMO_SPEC_ID}:RO", "quantity": "readout_error",
                 "limit": {"op": "<=", "value": RO_ERR_MAX},
                 "result": "pass" if ro_ok else ("fail" if ro_ok is not None else "hold")},
            ],
            "reference": f"{DEMO_SPEC_ID} — demonstration screen spec, not a customer spec",
        },
        "provenance": {
            "generated_at": qtdf.utc_now(),
            "tool": "IBM calibration",
            "tool_method": "vendor calibration cycle (snapshot)",
            "generator": "qtdf/ingest_ibm_snapshots.py",
            "qtdf_library_version": qtdf.QTDF_VERSION,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="store")
    ap.add_argument("--limit", type=int, default=None, help="max backends (default all)")
    a = ap.parse_args()

    import qiskit_ibm_runtime
    rt_ver = qiskit_ibm_runtime.__version__

    store = Store(a.store)
    n_rec = n_backends = n_err = n_emul = 0
    for backend, data_source in iter_fake_backends(a.limit):
        n_backends += 1
        if data_source == "emulated":
            n_emul += 1
            print(f"  note: {backend.name} snapshot is placeholder data -> emulated")
        for q in range(backend.num_qubits):
            try:
                store.add(qubit_record(backend, q, rt_ver, data_source))
                n_rec += 1
            except Exception as e:  # noqa: BLE001
                n_err += 1
                print(f"  ERROR {backend.name} Q{q}: {e}", file=sys.stderr)

    print(f"ingested {n_rec} records from {n_backends} backends "
          f"({n_emul} labeled emulated, {n_err} errors) -> {store.root}")
    return 0 if n_err == 0 and n_rec > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
