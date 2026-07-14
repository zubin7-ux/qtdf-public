# QTDF — Quantum Test Data Format

**The test-data standard for the known-good-qubit era.** One JSON record per
device per test event; tamper-evident, vendor-neutral, replayable. Zero
dependencies, Python 3.10+, Apache-2.0.

Quantum computing went modular — multi-chip modules recreate semiconductor
history's known-good-die problem, and every bad die integrated poisons an
expensive assembly. Semiconductors solved this with a data layer (STDF,
adaptive test, yield learning) as much as with hardware. QTDF is that layer
for qubits.

## What's in the box

- **The schema** (`SCHEMA.md`): device genealogy (lot/wafer/die), carrier,
  fixture, calibration plane, run/cooldown grouping, measurements with
  limits, dispositions with audit trail. Canonical sha256 content hashes make
  every record tamper-evident. Additive versioning with tests, not promises.
- **The store**: append-only, indexed, queryable; `verify` re-hashes
  everything.
- **The executive**: declarative content-hashed test plans, carrier adapters
  (cassette or hand-wired — same records either way), and deterministic
  record identity, so a replayed capture reproduces a live run
  **byte-for-byte**. Any captured fridge session becomes a permanent CI
  fixture.
- **The virtual fridge** (`qtdf/vfridge`): a physics-informed wafer emulator
  (correlated variation, TLS bath, labeled defects, cooldown-to-cooldown
  telegraph) with ground truth kept in sidecars the pipeline cannot see —
  so escape/overkill of any screening flow is exactly computable.
- **Real measured data, no fridge required**: `ingest_ibm_snapshots.py`
  turns the real historical calibration snapshots bundled with
  qiskit-ibm-runtime into 3,600+ QTDF records across 68 devices in seconds
  (see NOTICE for provenance).

## Install

```bash
pip install qtdf            # zero dependencies
qtdf demo                   # screen a virtual lot, prove byte-identical
                            # replay, verify every hash — ~2 s
```

## Verify this repo

```bash
bash verify.sh              # every test suite + the demo, PASS/FAIL per step
```

## Try it on real data (no fridge, no account)

```bash
python3 -m venv .venv && .venv/bin/pip install qiskit-ibm-runtime
.venv/bin/python ingest_ibm_snapshots.py  # real-device fleet -> store/
python3 fleet_report.py                   # yield stats over the fleet
python3 calibrate_emulator.py             # fit the emulator to measured data
```

## Adopting QTDF in your lab

You do not need to replace your stack. Wherever your measurement code
already produces numbers, add a few lines: build a record dict per the
schema, `qtdf.finalize(record)`, `Store.add(record)`. Your data is now
standardized, hash-verified, and queryable — and a spec change re-grades
history with zero fridge time. Going deeper, wrap your instrument control
in one adapter class (`measure(slot, quantities)`) and the executive runs
your versioned test plans and captures every run for byte-identical replay.

## Layout

```
SCHEMA.md                 the human-readable spec (start here)
verify.sh                 the one-command check (CI runs exactly this)
qtdf/                     schema, validator, hashed store, CLI, demo
  vfridge/                virtual fridge (truth + measurement emulator)
  executive/              plans, adapters, backends, run/replay
plans/                    an example versioned test plan (JSON)
records/                  an example record: a real RF launch qualification
tests/                    every suite runs standalone
```

## The commercial layer

The open standard is how data gets recorded and moved; the intelligence on
top is a separate product, available to design partners: a dispositioning
engine that prices screening policies in dollars against exact ground truth,
yield analytics (wafer maps, SPC, cross-fridge gauge R&R, multi-chip-module
assembly-risk scoring), and machine-learned adaptive screening policies
benchmarked the same way. If you run a fridge, a foundry, or a module
program and want your economics in the loop: open an issue or reach out.

## Status

Schema 0.2.0 / package 0.3.0. 37 tests in this repo (the full internal suite
is larger); CI on Linux + macOS across Python 3.10–3.14; independently
reproduced from source on a second OS and Python version.

## License

Apache-2.0 — see LICENSE and NOTICE (IBM calibration-data provenance).
