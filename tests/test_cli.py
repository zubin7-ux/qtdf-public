"""CLI tests — every subcommand through a real subprocess.

Run: python tests/test_cli.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORD1 = os.path.join(REPO, "records", "ENG-RF-002_optAB_GSG.qtdf.json")


def cli(*argv, cwd=REPO):
    return subprocess.run([sys.executable, "-m", "qtdf.cli", *argv],
                          capture_output=True, text=True, cwd=cwd)


def test_version():
    r = cli("version")
    assert r.returncode == 0 and "0.2.0" in r.stdout


def test_validate_good_and_bad():
    r = cli("validate", RECORD1)
    assert r.returncode == 0 and r.stdout.startswith("OK"), r.stdout
    with open(RECORD1, encoding="utf-8") as fh:
        rec = json.load(fh)
    rec["disposition"]["verdict"] = "maybe"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(rec, fh)
        bad = fh.name
    try:
        r = cli("validate", bad)
        assert r.returncode == 1 and "INVALID" in r.stdout
    finally:
        os.unlink(bad)


def test_show_reports_verdict_and_hash():
    r = cli("show", RECORD1)
    assert r.returncode == 0
    assert "verdict  : pass" in r.stdout
    assert "verified OK" in r.stdout


def test_demo_query_verify_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "store")
        r = cli("demo", "--rows", "5", "--cols", "5", "--store", store)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "all hashes verified" in r.stdout
        if "MCM assembly" in r.stdout:                     # full build
            assert "wafer map" in r.stdout
        else:                                              # open build
            assert "byte-identical reproduction: True" in r.stdout
        r = cli("query", store, "--count")
        assert r.returncode == 0 and int(r.stdout.strip()) >= 100
        r = cli("query", store, "--verdict", "pass", "--limit", "5")
        assert r.returncode == 0 and "qubit_coherence_screen" in r.stdout
        r = cli("verify", store)
        assert r.returncode == 0 and "all hashes verified" in r.stdout


def test_diff_semantic():
    with open(RECORD1, encoding="utf-8") as fh:
        rec = json.load(fh)
    rec["measurements"][0]["value"] = round(rec["measurements"][0]["value"] * 1.1, 3)
    rec["disposition"]["verdict"] = "fail"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(rec, fh)
        other = fh.name
    try:
        r = cli("diff", RECORD1, other)
        assert r.returncode == 0
        assert "->" in r.stdout and "verdict" in r.stdout
        r = cli("diff", RECORD1, RECORD1)
        assert "no semantic differences" in r.stdout
    finally:
        os.unlink(other)


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
