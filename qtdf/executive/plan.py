"""Test plans — declarative, versioned, content-hashed JSON documents.

A plan states WHAT to measure and HOW to disposition: the quantities (with
units and optional limits) and a bin map. The executive is generic; all
test-specific knowledge lives in the plan, and the plan's content hash is
stamped into every record's ``run.plan_hash`` — so a record always proves
exactly which plan produced it.

Plans are JSON (not YAML) to keep qtdf-exec stdlib-only.
"""
from __future__ import annotations

import hashlib
import json

from qtdf.core import LIMIT_OPS, canonical_json


def load_plan(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        plan = json.load(fh)
    problems = validate_plan(plan)
    if problems:
        raise ValueError(f"invalid plan {path}:\n  " + "\n  ".join(problems))
    return plan


def plan_hash(plan: dict) -> str:
    """sha256 over the canonical plan — the identity in run.plan_hash."""
    return "sha256:" + hashlib.sha256(canonical_json(plan).encode("utf-8")).hexdigest()


def validate_plan(plan: dict) -> list[str]:
    out: list[str] = []
    for key in ("plan_id", "plan_version", "record_type"):
        if not isinstance(plan.get(key), str):
            out.append(f"plan.{key}: required string")
    qs = plan.get("quantities")
    if not isinstance(qs, list) or not qs:
        out.append("plan.quantities: required non-empty list")
        qs = []
    for i, q in enumerate(qs):
        if not isinstance(q.get("quantity"), str):
            out.append(f"plan.quantities[{i}].quantity: required string")
        if not isinstance(q.get("unit"), str):
            out.append(f"plan.quantities[{i}].unit: required string")
        limit = q.get("limit")
        if limit is not None and limit.get("op") not in LIMIT_OPS:
            out.append(f"plan.quantities[{i}].limit.op: must be one of {sorted(LIMIT_OPS)}")
    d = plan.get("disposition", {})
    if not isinstance(d.get("spec_id"), str):
        out.append("plan.disposition.spec_id: required string")
    for i, b in enumerate(d.get("bin_map", [])):
        if not isinstance(b.get("bin"), int):
            out.append(f"plan.disposition.bin_map[{i}].bin: required int")
        if "when_failed" not in b and not b.get("nonfunctional"):
            out.append(f"plan.disposition.bin_map[{i}]: needs when_failed or nonfunctional")
    return out


def limited_quantities(plan: dict) -> list[dict]:
    return [q for q in plan["quantities"] if q.get("limit") is not None]


def evaluate_limit(limit: dict, value) -> bool | None:
    """None if value is missing; else the limit outcome."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    op, ref = limit["op"], limit.get("value")
    if op == "in_range":
        return limit["low"] <= value <= limit["high"]
    return {"<=": value <= ref, ">=": value >= ref,
            "<": value < ref, ">": value > ref, "==": value == ref}[op]


def disposition(plan: dict, values: dict) -> tuple[str, int, str | None, list[dict]]:
    """Apply the plan's limits + bin map to measured values.

    Returns (verdict, bin, reason, rules). Nonfunctional (no response on the
    response_quantity) takes priority; then pass/fail from the failed set.
    """
    d = plan["disposition"]
    limited = limited_quantities(plan)
    resp_q = d.get("response_quantity", limited[0]["quantity"] if limited else None)
    rules, failed = [], []
    for q in limited:
        ok = evaluate_limit(q["limit"], values.get(q["quantity"]))
        rules.append({
            "rule_id": f"{d['spec_id']}:{q['quantity']}",
            "quantity": q["quantity"], "limit": q["limit"],
            "result": "hold" if ok is None else ("pass" if ok else "fail"),
        })
        if ok is False:
            failed.append(q["quantity"])

    if resp_q is not None and values.get(resp_q) is None:
        binno = next((b["bin"] for b in d.get("bin_map", []) if b.get("nonfunctional")), 0)
        return "fail", binno, f"no response on {resp_q} (nonfunctional)", rules
    if any(r["result"] == "hold" for r in rules):
        return "hold", 0, "incomplete measurement", rules
    if not failed:
        return "pass", d.get("pass_bin", 1), None, rules
    fs = sorted(failed)
    binno = next((b["bin"] for b in d.get("bin_map", [])
                  if sorted(b.get("when_failed", [])) == fs),
                 d.get("default_fail_bin", 9))
    return "fail", binno, None, rules
