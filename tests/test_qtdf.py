"""QTDF v0.1 tests — run with:  python -m pytest tests/  (or plain python).

Covers the invariants a test-data standard must never break:
  - a well-formed record validates clean,
  - JSON round-trip is lossless,
  - the content hash is stable, and changes iff the payload changes,
  - the validator catches contradictions (pass/fail vs limit, bad enums),
  - a version from a foreign MAJOR is refused.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import qtdf
from qtdf.core import content_hash


def _minimal_record() -> dict:
    return {
        "qtdf_version": qtdf.QTDF_VERSION,
        "record_id": qtdf.new_record_id(),
        "record_type": "qubit_coherence_screen",
        "data_source": "measured",
        "device": {"device_id": "DIE-0001"},
        "carrier": {"provider": "cassette", "socket": "A1"},
        "fixture": {"fridge_id": "BF-1", "temperature_K": 0.012},
        "test": {"test_plan": "screen-v1"},
        "calibration": {"reference_impedance_ohm": 50.0},
        "measurements": [
            {
                "quantity": "T1",
                "unit": "us",
                "value": 82.0,
                "limit": {"op": ">=", "value": 50.0},
                "pass": True,
            }
        ],
        "disposition": {"verdict": "pass", "bin": 1},
        "provenance": {"generated_at": qtdf.utc_now(), "tool": "unit-test"},
    }


def test_minimal_validates_clean():
    assert qtdf.is_valid(_minimal_record())


def test_roundtrip_lossless_and_hash_stable():
    rec = qtdf.finalize(_minimal_record())
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "r.json")
        qtdf.write_record(rec, p)
        back = qtdf.read_record(p)
    assert back == rec
    assert qtdf.verify_hash(back)


def test_hash_changes_with_payload():
    rec = qtdf.finalize(_minimal_record())
    h0 = rec["provenance"]["content_hash"]
    mutated = copy.deepcopy(rec)
    mutated["measurements"][0]["value"] = 81.9
    assert content_hash(mutated) != h0
    # hash excludes itself: rewriting the hash field must not affect recomputation
    mutated2 = copy.deepcopy(rec)
    mutated2["provenance"]["content_hash"] = "sha256:deadbeef"
    assert content_hash(mutated2) == h0


def test_validator_catches_pass_limit_contradiction():
    rec = _minimal_record()
    rec["measurements"][0]["pass"] = False  # value 82 >= 50 is actually a pass
    problems = qtdf.errors_only(qtdf.validate(rec))
    assert any("contradicts" in p for p in problems)


def test_validator_catches_bad_verdict():
    rec = _minimal_record()
    rec["disposition"]["verdict"] = "maybe"
    assert not qtdf.is_valid(rec)


def test_novel_record_type_is_warning_not_error():
    rec = _minimal_record()
    rec["record_type"] = "some_future_test"
    problems = qtdf.validate(rec)
    assert any(p.startswith("warning: ") and "record_type" in p for p in problems)
    assert qtdf.is_valid(rec)  # warning only, still valid


def test_foreign_major_refused():
    rec = qtdf.finalize(_minimal_record())
    rec["qtdf_version"] = "9.0.0"
    try:
        qtdf.migrate(rec)
    except ValueError:
        return
    raise AssertionError("migrate should refuse a foreign MAJOR version")


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
