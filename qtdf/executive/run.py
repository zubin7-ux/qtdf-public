"""The executive — runs a plan over a load of devices, emits QTDF records.

Identity is deterministic BY DESIGN: record_id = uuid5(run_id, device_id) and
generated_at is stamped once per run and stored in the capture. Consequence:
replaying a capture reproduces every record byte-for-byte (same record_ids,
same content_hashes) — which turns any captured fridge session, real or
virtual, into a CI regression fixture for the entire pipeline.
"""
from __future__ import annotations

import uuid
from collections import Counter

import qtdf

from .backends import write_capture
from .plan import disposition, plan_hash

_NS = uuid.uuid5(uuid.NAMESPACE_URL, "qtdf-exec")


def record_id_for(run_id: str, device_id: str) -> str:
    """Deterministic record identity: same run + device -> same id, always."""
    return f"urn:uuid:{uuid.uuid5(_NS, f'{run_id}:{device_id}')}"


def execute(plan: dict, slots: list, carrier_meta: dict, backend, fridge,
            store, run_id: str, cooldown_id: str = "cd01",
            generated_at: str | None = None, operator: str = "EXEC",
            capture_path: str | None = None) -> dict:
    """Run every slot through the plan; add records to the store.

    Returns a summary dict (counts, plan_hash, run_id). If capture_path is
    given, writes a replayable capture of the whole run.
    """
    ph = plan_hash(plan)
    generated_at = generated_at or qtdf.utc_now()
    q_names = [q["quantity"] for q in plan["quantities"]]

    results, verdicts = {}, Counter()
    for slot in slots:
        values = backend.measure(slot, q_names)
        results[slot.device_id] = values
        rec = build_record(plan, ph, slot, values, carrier_meta, fridge,
                           run_id, cooldown_id, generated_at, operator,
                           backend)
        store.add(rec)
        verdicts[rec["disposition"]["verdict"]] += 1

    if capture_path:
        write_capture(capture_path, {
            "run_id": run_id, "cooldown_id": cooldown_id,
            "generated_at": generated_at, "operator": operator,
            "plan": plan, "plan_hash": ph,
            "data_source": backend.data_source,
            "backend_tool": backend.tool, "backend_method": backend.tool_method,
            "fridge": fridge.fixture(), "carrier": carrier_meta,
            "slots": [s.public() for s in slots],
            "results": results,
        })

    return {"run_id": run_id, "plan_hash": ph, "records": len(slots),
            "verdicts": dict(verdicts)}


def build_record(plan, ph, slot, values, carrier_meta, fridge, run_id,
                 cooldown_id, generated_at, operator, backend) -> dict:
    verdict, binno, reason, rules = disposition(plan, values)

    measurements = []
    for q in plan["quantities"]:
        v = values.get(q["quantity"])
        limit = q.get("limit") if v is not None else None
        ok = None
        if limit is not None:
            from .plan import evaluate_limit
            ok = evaluate_limit(limit, v)
        measurements.append({
            "quantity": q["quantity"], "symbol": q.get("symbol", q["quantity"]),
            "value": v, "unit": q["unit"], "limit": limit, "pass": ok,
        })

    carrier = {"provider": carrier_meta["provider"],
               "carrier_part": carrier_meta.get("carrier_part"),
               "socket": slot.socket}
    if "rf_environment_qualified" in carrier_meta:
        carrier["rf_environment_qualified"] = carrier_meta["rf_environment_qualified"]
    if carrier_meta.get("note"):
        carrier["note"] = carrier_meta["note"]

    calibration = {"reference_impedance_ohm": 50.0}
    if carrier_meta.get("loopback_standards"):
        calibration["loopback_standards"] = carrier_meta["loopback_standards"]
        calibration["note"] = "cassette loopback socket self-test assumed nominal"

    return {
        "qtdf_version": qtdf.QTDF_VERSION,
        "record_id": record_id_for(run_id, slot.device_id),
        "record_type": plan["record_type"],
        "data_source": backend.data_source,
        "device": {
            "device_id": slot.device_id,
            "part_number": slot.part_number,
            "description": slot.description,
            "wafer": slot.wafer,
            "genealogy": slot.genealogy,
        },
        "carrier": carrier,
        "fixture": fridge.fixture(),
        "test": {
            "test_plan": plan["plan_id"],
            "test_plan_version": plan["plan_version"],
            "executive": "qtdf-exec",
            "operator": operator,
        },
        "calibration": calibration,
        "run": {"run_id": run_id, "cooldown_id": cooldown_id, "plan_hash": ph},
        "measurements": measurements,
        "disposition": {
            "verdict": verdict, "bin": binno, "override": False, "reason": reason,
            "rules": rules,
            "reference": plan["disposition"]["spec_id"],
        },
        "provenance": {
            "generated_at": generated_at,
            "tool": backend.tool,
            "tool_method": backend.tool_method,
            "generator": "executive/run.py",
            "qtdf_library_version": qtdf.QTDF_VERSION,
        },
    }


def replay(capture: dict, store) -> dict:
    """Re-run a capture into a store; records are byte-identical to the live run."""
    from .backends import ReplayBackend, slots_from_capture
    from .adapters import FridgeProfile

    class _Fixture:
        def __init__(self, fx): self._fx = fx
        def fixture(self): return self._fx

    backend = ReplayBackend(capture)
    backend.tool = capture["backend_tool"]
    backend.tool_method = capture["backend_method"]
    return execute(
        plan=capture["plan"], slots=slots_from_capture(capture),
        carrier_meta=capture["carrier"], backend=backend,
        fridge=_Fixture(capture["fridge"]), store=store,
        run_id=capture["run_id"], cooldown_id=capture["cooldown_id"],
        generated_at=capture["generated_at"], operator=capture["operator"],
    )
