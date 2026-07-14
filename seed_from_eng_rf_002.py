#!/usr/bin/env python3
"""Seed QTDF record #1 from the real ENG-RF-002 optAB/GSG touchstone.

This is both the first golden reference record and a worked example of ingesting
a measurement into QTDF: it parses the .s2p, derives the pass/fail metrics from
the trace (nothing hand-typed), attaches provenance + a content hash, validates,
and writes records/ENG-RF-002_optAB_GSG.qtdf.json.

Usage:
    python seed_from_eng_rf_002.py [path/to/ENG-RF-002_optAB_GSG.s2p]
"""
from __future__ import annotations

import hashlib
import os
import platform
import sys

import qtdf
from qtdf.touchstone import read_s2p

DEFAULT_S2P = os.path.expanduser("~/Downloads/Eng-Rel-002/ENG-RF-002_optAB_GSG.s2p")
RL_TARGET_DB = -15.0
F_OP_HZ = 8.0e9

# Loopback RF standards that a cassette self-test would key on (ENG-RF-001).
LOOPBACK_STANDARDS = [
    "ENG-RF-001_GSG.s2p",
    "ENG-RF-001_GS.s2p",
    "ENG-RF-001_5-gnd.s2p",
]


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def build_record(s2p_path: str) -> dict:
    ts = read_s2p(s2p_path)
    s11_8 = ts.db_at("s11", F_OP_HZ)
    s21_8 = ts.db_at("s21", F_OP_HZ)
    # The launch is double-humped: report EVERY matched lobe, not first-to-last
    # crossing (which hides the ~6.8-7.5 GHz gap that sits above -15 dB).
    bands = ts.matched_bands_hz("s11", RL_TARGET_DB)
    bands_ghz = [[round(lo / 1e9, 3), round(hi / 1e9, 3)] for lo, hi in bands]
    rl_pass = s11_8 <= RL_TARGET_DB

    record = {
        "qtdf_version": qtdf.QTDF_VERSION,
        "record_id": qtdf.new_record_id(),
        "record_type": "rf_launch_qualification",
        "data_source": "simulation",

        "device": {
            "device_id": "CPN-100:optAB:GSG",
            "part_number": "CPN-100",
            "description": "pogo blind-mate coupon assembly, optAB launch, GSG ground config",
            "revision": "optAB",
            "genealogy": {
                "assembly": "CAS-400 cassette",
                "release": "ENG-REL-002",
            },
        },

        # The cassette tier: the modeled geometry IS the CPN blind-mate in the
        # CAS-400 cassette, so provider=cassette with a qualified RF environment.
        "carrier": {
            "provider": "cassette",
            "carrier_part": "CAS-400",
            "socket": None,
            "rf_environment_qualified": True,
            "note": "modeled fenced unit cell (ENG-REL-002 section 1.5); single socket",
        },

        "fixture": {
            "fridge_id": None,
            "temperature_K": None,
            "note": "full-wave EM model (openEMS FDTD); temperature-independent",
            "ports": 2,
            "launch": "GSG pogo blind-mate",
            "port_reference_impedance_ohm": ts.z0,
        },

        "test": {
            "test_plan": "ENG-RF-002 RF launch confirmation and tuning",
            "executive": "ENG-RF-002_openems_pogo.py",
            "executive_version": None,
            "band_GHz": [2.0, 12.0],
            "operator": "ENG",
            "reproduce": (
                "python ENG-RF-002_openems_pogo.py "
                "--case optAB --grounds GSG --exposed 0.20"
            ),
        },

        "calibration": {
            "reference_impedance_ohm": 50.0,
            "port_type": "coaxial TEM, de-embedded",
            "extracted_impedance_ohm": 57.0,
            "cal_error_dB": 1.0,
            "loopback_standards": LOOPBACK_STANDARDS,
            "note": "coax port extracts 57 ohm vs 50 target -> treat results as +/-1 dB",
        },

        "measurements": [
            {
                "quantity": "return_loss",
                "symbol": "|S11|",
                "value": round(s11_8, 2),
                "unit": "dB",
                "conditions": {"frequency_GHz": 8.0, "gap_mm": 1.8},
                "limit": {"op": "<=", "value": RL_TARGET_DB},
                "pass": rl_pass,
                "margin_dB": round(RL_TARGET_DB - s11_8, 2),
            },
            {
                "quantity": "insertion_loss",
                "symbol": "|S21|",
                "value": round(s21_8, 2),
                "unit": "dB",
                "conditions": {"frequency_GHz": 8.0, "gap_mm": 1.8},
                "limit": None,
                "pass": None,
                "note": "informational; >0 dB is the ~1 dB port-cal artifact",
            },
            {
                "quantity": "matched_bands",
                "symbol": "RL<=15 dB lobes",
                "value": bands_ghz,
                "unit": "GHz",
                "conditions": {"threshold_dB": RL_TARGET_DB},
                "limit": None,
                "pass": None,
                "note": (
                    "double-humped launch: two matched lobes with a gap (~-13 dB) "
                    "between them; 8 GHz operating point sits in the upper lobe. "
                    "ENG-RF-002 report's single 5.65-8.37 GHz span hides this gap."
                ),
            },
        ],

        "traces": [
            {
                "name": os.path.basename(s2p_path),
                "role": "s_parameters",
                "format": "touchstone_ri",
                "ports": 2,
                "points": len(ts.freq_hz),
                "path": os.path.basename(s2p_path),  # basename only: no user paths in records
                "sha256": sha256_file(s2p_path),
            }
        ],

        "disposition": {
            "verdict": "pass" if rl_pass else "fail",
            "bin": 1 if rl_pass else 0,
            "override": False,
            "reason": None,
            "rules": [
                {
                    "rule_id": "RL15@8GHz",
                    "quantity": "return_loss",
                    "limit": {"op": "<=", "value": RL_TARGET_DB},
                    "result": "pass" if rl_pass else "fail",
                }
            ],
            "reference": "-15 dB return loss at the 8 GHz operating band",
            "note": "verdict scoped to 8 GHz operating band, not the literal 0.1-12 GHz sweep",
        },

        "annotations": {
            "caveats": [
                "coax port Z_ref=57 ohm -> +/-1 dB calibration uncertainty",
                "perimeter ground fence is load-bearing; without it the cell resonates in-band",
                "low-frequency (<~2 GHz) is pulsed-FDTD excitation-limited, not physical",
            ],
            "stroke_robustness": {
                "quantity": "return_loss",
                "unit": "dB",
                "note": "|S11| @ 8 GHz holds across mate stroke (separate runs)",
                "points": [
                    {"gap_mm": 1.35, "S11_dB": -18.0},
                    {"gap_mm": 1.80, "S11_dB": round(s11_8, 2)},
                    {"gap_mm": 2.25, "S11_dB": -17.9},
                ],
            },
        },

        "provenance": {
            "generated_at": qtdf.utc_now(),
            "tool": "openEMS",
            "tool_method": "FDTD (full-wave)",
            "generator": "qtdf/seed_from_eng_rf_002.py",
            "qtdf_library_version": qtdf.QTDF_VERSION,
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
        },
    }
    return record


def main() -> int:
    s2p_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_S2P
    if not os.path.exists(s2p_path):
        print(f"error: touchstone not found: {s2p_path}", file=sys.stderr)
        return 2

    record = build_record(s2p_path)

    problems = qtdf.validate(record)
    errors = qtdf.errors_only(problems)
    for p in problems:
        print(f"  {p}")
    if errors:
        print(f"\nFAILED validation: {len(errors)} error(s)", file=sys.stderr)
        return 1

    qtdf.finalize(record)
    assert qtdf.verify_hash(record), "content hash failed to verify after finalize"

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "records")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "ENG-RF-002_optAB_GSG.qtdf.json")
    qtdf.write_record(record, out_path)

    m = record["measurements"][0]
    print(f"\nWrote {out_path}")
    print(f"  verdict            : {record['disposition']['verdict'].upper()}")
    print(f"  |S11| @ 8 GHz      : {m['value']} dB  (limit <= {RL_TARGET_DB} dB, margin {m['margin_dB']} dB)")
    print(f"  matched lobes      : {record['measurements'][2]['value']} GHz")
    print(f"  content_hash       : {record['provenance']['content_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
