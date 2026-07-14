"""QTDF v0.1 validator — pure-Python structural + semantic checks.

``validate(record)`` returns a list of human-readable problem strings; an empty
list means the record conforms. Problems are split into hard errors (must fix)
and soft warnings (novel vocabulary, missing-but-recommended fields) — both are
returned; use ``errors_only()`` to gate persistence.

Kept dependency-free on purpose so it can run inside any test executive.
"""
from __future__ import annotations

from typing import Any

from .core import (
    CARRIER_PROVIDERS,
    DATA_SOURCES,
    LIMIT_OPS,
    QTDF_VERSION,
    RECORD_TYPES,
    VERDICTS,
)

WARN = "warning: "  # prefix marks a soft finding

# Per-record_type measurement profiles (v0.2). For a KNOWN record_type, the
# required quantities must appear in measurements[] (hard error if absent);
# recommended ones raise warnings. Unknown record_types skip profile checks.
QUANTITY_PROFILES: dict[str, dict[str, set]] = {
    "rf_launch_qualification": {
        "required": {"return_loss"},
        "recommended": {"insertion_loss"},
    },
    "qubit_coherence_screen": {
        "required": {"T1"},
        # at least one dephasing time + the qubit frequency + readout quality
        "recommended": {"T2", "T2_star", "f_01", "readout_error"},
    },
}


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _require(obj: dict, key: str, types: tuple, path: str, out: list) -> bool:
    if key not in obj:
        out.append(f"{path}.{key}: required field missing")
        return False
    if not isinstance(obj[key], types):
        names = "/".join(t.__name__ for t in types)
        out.append(f"{path}.{key}: expected {names}, got {type(obj[key]).__name__}")
        return False
    return True


def _check_limit_pass(m: dict) -> tuple[bool | None, str | None]:
    """Recompute pass/fail from value+limit. Returns (computed_pass, error)."""
    limit = m.get("limit")
    value = m.get("value")
    if limit is None:
        return None, None
    op = limit.get("op")
    if op not in LIMIT_OPS:
        return None, f"limit.op '{op}' not in {sorted(LIMIT_OPS)}"
    if op == "in_range":
        lo, hi = limit.get("low"), limit.get("high")
        if not (_is_num(lo) and _is_num(hi) and _is_num(value)):
            return None, "in_range limit needs numeric low/high and a numeric value"
        return (lo <= value <= hi), None
    ref = limit.get("value")
    if not (_is_num(ref) and _is_num(value)):
        return None, f"limit '{op}' needs numeric value + limit.value"
    ok = {
        "<=": value <= ref, ">=": value >= ref,
        "<": value < ref, ">": value > ref, "==": value == ref,
    }[op]
    return ok, None


def validate(record: dict) -> list[str]:
    """Return a list of problems ('' -> conforms). Warnings are prefixed."""
    out: list[str] = []
    R = "record"

    # -- envelope --
    if _require(record, "qtdf_version", (str,), R, out):
        if record["qtdf_version"].split(".")[0] != QTDF_VERSION.split(".")[0]:
            out.append(f"{R}.qtdf_version: incompatible MAJOR (have {QTDF_VERSION})")
    _require(record, "record_id", (str,), R, out)
    if _require(record, "record_type", (str,), R, out):
        if record["record_type"] not in RECORD_TYPES:
            out.append(f"{WARN}{R}.record_type '{record['record_type']}' is novel (not in recommended vocab)")
    if _require(record, "data_source", (str,), R, out):
        if record["data_source"] not in DATA_SOURCES:
            out.append(f"{R}.data_source must be one of {sorted(DATA_SOURCES)}")

    # -- device genealogy --
    if _require(record, "device", (dict,), R, out):
        dev = record["device"]
        _require(dev, "device_id", (str,), f"{R}.device", out)
        # v0.2: optional wafer/lot genealogy for known-good-die analytics
        wafer = dev.get("wafer")
        if wafer is not None:
            if not isinstance(wafer, dict):
                out.append(f"{R}.device.wafer: must be an object or null")
            else:
                for k in ("lot_id", "wafer_id"):
                    if wafer.get(k) is not None and not isinstance(wafer[k], str):
                        out.append(f"{R}.device.wafer.{k}: must be a string or null")
                for k in ("die_x", "die_y"):
                    if wafer.get(k) is not None and not _is_num(wafer[k]):
                        out.append(f"{R}.device.wafer.{k}: must be numeric or null")

    # -- v0.2: optional run/session grouping (a cooldown = one run, many records) --
    run = record.get("run")
    if run is not None:
        if not isinstance(run, dict):
            out.append(f"{R}.run: must be an object or null")
        elif not isinstance(run.get("run_id"), str):
            out.append(f"{R}.run.run_id: required string when run block is present")

    # -- carrier (the cassette tier) --
    if _require(record, "carrier", (dict,), R, out):
        c = record["carrier"]
        if _require(c, "provider", (str,), f"{R}.carrier", out):
            if c["provider"] not in CARRIER_PROVIDERS:
                out.append(f"{R}.carrier.provider must be one of {sorted(CARRIER_PROVIDERS)}")
            if c["provider"] == "cassette" and not c.get("socket"):
                out.append(f"{WARN}{R}.carrier: cassette provider without a socket loses auto-genealogy")

    # -- fixture (fridge / wiring). null == not applicable/unknown, allowed. --
    if _require(record, "fixture", (dict,), R, out):
        f = record["fixture"]
        if f.get("temperature_K") is not None and not _is_num(f["temperature_K"]):
            out.append(f"{R}.fixture.temperature_K: must be numeric kelvin or null")

    # -- test + calibration --
    _require(record, "test", (dict,), R, out)
    _require(record, "calibration", (dict,), R, out)

    # -- measurements --
    if _require(record, "measurements", (list,), R, out):
        for i, m in enumerate(record["measurements"]):
            mp = f"{R}.measurements[{i}]"
            if not isinstance(m, dict):
                out.append(f"{mp}: must be an object")
                continue
            _require(m, "quantity", (str,), mp, out)
            _require(m, "unit", (str,), mp, out)
            if "value" not in m:
                out.append(f"{mp}.value: required field missing")
            computed, err = _check_limit_pass(m)
            if err:
                out.append(f"{mp}.{err}")
            if computed is not None and "pass" in m and m["pass"] != computed:
                out.append(f"{mp}.pass={m['pass']} contradicts value vs limit (computed {computed})")

        # v0.2: per-record_type quantity profile
        profile = QUANTITY_PROFILES.get(record.get("record_type", ""))
        if profile:
            present = {m.get("quantity") for m in record["measurements"] if isinstance(m, dict)}
            for q in sorted(profile["required"] - present):
                out.append(f"{R}.measurements: record_type requires quantity '{q}'")
            missing_rec = profile["recommended"] - present
            if profile["recommended"] and missing_rec == profile["recommended"]:
                out.append(
                    f"{WARN}{R}.measurements: none of the recommended quantities "
                    f"{sorted(profile['recommended'])} are present"
                )

    # -- disposition --
    if _require(record, "disposition", (dict,), R, out):
        d = record["disposition"]
        if _require(d, "verdict", (str,), f"{R}.disposition", out):
            if d["verdict"] not in VERDICTS:
                out.append(f"{R}.disposition.verdict must be one of {sorted(VERDICTS)}")
        # a fail/override should say why
        if d.get("override") and not d.get("reason"):
            out.append(f"{R}.disposition: override set without a reason")

    # -- provenance --
    if _require(record, "provenance", (dict,), R, out):
        p = record["provenance"]
        _require(p, "generated_at", (str,), f"{R}.provenance", out)
        _require(p, "tool", (str,), f"{R}.provenance", out)
        if not p.get("content_hash"):
            out.append(f"{WARN}{R}.provenance.content_hash absent (call core.finalize before persisting)")

    return out


def errors_only(problems: list[str]) -> list[str]:
    """Filter a validate() result down to hard errors (drop warnings)."""
    return [p for p in problems if not p.startswith(WARN)]


def is_valid(record: dict) -> bool:
    """True iff the record has no hard errors."""
    return not errors_only(validate(record))
