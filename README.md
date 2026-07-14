# QTDF — Quantum Test Data Format

An open, versioned record for qubit/device test data — the STDF analog for
quantum. This repo is the v0.1 reference: the spec, a zero-dependency Python
library, and the first real record (a full-wave RF launch qualification).

QTDF is the wedge in the "known-good-qubit" stack: free to adopt, works with any
fridge, and feeds the yield-learning / dispositioning layer above it. The cassette
makes the data better (automatic socket→device genealogy, a qualified RF
environment) but is never required — a hand-wired setup emits valid QTDF too.

## Layout

```
qtdf/
  SCHEMA.md                 # the human-readable v0.2 spec (start here)
  verify.sh                 # THE entry point: tests + store + demo, PASS/FAIL
  AGENTS.md                 # guidance for AI agents (don't explore store/)
  qtdf/                     # everything importable lives under qtdf.*
    core.py                 # schema version, canonical hashing, io, migration
    validate.py             # structural + semantic validator, quantity profiles
    touchstone.py           # minimal .s2p ingest + S-parameter helpers
    store.py                # append-only record store with index + query
    cli.py / demo.py        # the qtdf CLI and packaged end-to-end demo
    vfridge/                # virtual fridge: wafer truth model + cooldown measurement
      wafer.py              # correlated variation, TLS bath, labeled defects
      measure.py            # cooldown fluctuation, meas noise, QTDF emission
    executive/              # the cross-fridge test executive
      plan.py               # declarative JSON plans, content-hashed
      adapters.py           # CarrierProvider (cassette/manual), FridgeProfile
      backends.py           # vfridge + replay backends, capture I/O
      run.py                # execute/replay with deterministic record identity
    disposition/            # specs + policies, priced exactly   [commercial layer]
      policy.py             # Spec (a view over records), 5 screening policies
      engine.py             # multi-round evaluation vs truth, economics
    analytics/              # the yield-learning layer            [commercial layer]
      wafermap.py           # spatial yield from device.wafer coords
      spc.py                # x-bar control charts, drift detection
      gauge.py              # gauge R&R across fridges (%GRR, culprit)
      mcm.py                # P(module ok | dies): margins MC + collision rule
    learn/                  # machine-learned policies             [commercial layer]
      models.py             # stdlib logistic/linear SGD, AUC, calibration
      gym.py                # labeled episodes from vfridge (exhaustive, off-policy)
      policy.py             # score models + dollar-optimal thresholds
  plans/                    # versioned test plans (JSON)
  captures/                 # replayable run captures (generated)
  seed_from_eng_rf_002.py   # ingest the real ENG-RF-002 s2p -> record #1
  ingest_ibm_snapshots.py   # real IBM calibration snapshots -> store (needs venv)
  calibrate_emulator.py     # fit vfridge distributions to the measured fleet
  fleet_report.py           # fleet-level yield analytics over the store
  phase2_demo.py            # closed loop: emulated lot -> exact escape/overkill
  records/                  # record #1 standalone copy
  store/                    # measured fleet store: 3,649 records (generated)
  truth/                    # truth sidecars — NEVER inside a store
  tests/                    # 7 suites; each runs standalone
```

## Install

```bash
pip install .                     # zero dependencies, Python 3.10+ (pkg 0.3.0, schema 0.2.0)
qtdf demo                         # the whole pipeline on a virtual lot, ~2 s
qtdf validate my_record.json      # validate any QTDF record
qtdf show my_record.json          # summary + hash verification
qtdf query store --verdict pass --count
qtdf verify store                 # re-hash every record
qtdf diff a.json b.json           # semantic diff
```

## Quickstart (repo checkout)

```bash
# core is stdlib only, Python 3.10+
python tests/test_qtdf.py                 # v0.1 invariants -> 7/7
python tests/test_store_v02.py            # v0.2 store/profiles -> 7/7
python seed_from_eng_rf_002.py            # record #1 from the openEMS result

# the real-data fleet (one-time venv for the ingester only)
python3 -m venv .venv && .venv/bin/pip install qiskit-ibm-runtime
.venv/bin/python ingest_ibm_snapshots.py  # 3,648 real qubit records, 68 chips
python fleet_report.py                    # yield, T1/T2 stats, bin pareto

# the closed loop (no venv needed)
python calibrate_emulator.py              # fit emulator to the measured fleet
python tests/test_vfridge.py              # emulator invariants -> 9/9
python phase2_demo.py                     # exact escape/overkill vs truth

# the executive (no venv needed)
python tests/test_executive.py            # plans, carriers, replay -> 7/7
python phase3_demo.py                     # cassette load -> capture -> replay

# the disposition engine
python tests/test_disposition.py          # specs, policies, exact eval -> 8/8
python phase4_demo.py                     # 5 policies priced on one lot

# yield analytics + MCM scorer
python tests/test_analytics.py            # maps, SPC, R&R, scorer -> 7/7
python phase5_demo.py                     # wafer map, drift, R&R, assembly
```

```python
import qtdf
st = qtdf.Store("store")
st.count(record_type="qubit_coherence_screen", verdict="pass")
```

## Status

Phase 1 ✓ — QTDF v0.2, coherence vocabulary grounded on real measured IBM
calibration data (3,528 qubits, 67 chips), append-only store, quantity
profiles, wafer/run genealogy. v0.1 records load unchanged (tested).

Phase 2 ✓ — vfridge: virtual wafer with spatially-correlated variation, TLS
bath, labeled defects, calibrated against the measured fleet; cooldown
measurement with TLS-telegraph fluctuation + fit/shot noise; truth kept in a
sidecar the pipeline cannot see. The closed loop computes EXACT escape and
overkill for any screen policy. Byte-identical across processes
(golden-pinned); measurement noise is keyed per (cooldown, die, qubit) so
values are independent of batch composition — fair cross-policy comparison.

Phase 3 ✓ — qtdf-exec: declarative content-hashed JSON plans (hash stamped
into run.plan_hash), CarrierProvider adapters (cassette with per-die socket
assignment + capacity enforcement; manual as the degenerate case), swappable
measurement backends, and record/replay with deterministic identity
(record_id = uuid5(run_id, device_id)): a replayed capture reproduces the
live run byte-for-byte — verified down to file bytes in tests. Any captured
run, virtual today or a real fridge later, is a CI fixture.

Phase 4 ✓ — the disposition engine. Specs are frozen objects and disposition
is a VIEW: the engine re-bins stored measurement values under any spec
without remeasuring. Five screening policies (single-pass, best-of-N,
confirm-Nx, guard-band, gray-zone retest) evaluated multi-round through the
executive and priced exactly against truth. Demo lot at illustrative MCM
economics: confirm-2x wins ($105k) — retesting passers is cheap when the
pass population is small; best-of-2 is worst ($379k, adverse selection
quantified). Known gap (deliberate): Spec expresses per-qubit limits only;
die-level pairwise rules (freq_collision) belong to the Phase 5 MCM scorer.

Phase 5 ✓ — the yield-learning layer. Wafer maps from device.wafer coords
(dispositioned as a view, any spec). SPC x-bar charts: an injected 15% T1
process drift at lot 4 is flagged at exactly lots 4-6. Gauge R&R across
three virtual fridges with within-cooldown repeats (the emulator gained a
`repeat` axis: fit noise redraws, TLS telegraph stays fixed — across-cooldown
"repeats" would confound gauge noise with device telegraph) correctly
isolates the secretly-noisy fridge; fridge-to-fridge AV physically includes
per-cooldown telegraph. The MCM scorer answers the money question:
P(module meets spec | measured dies) = margin Monte Carlo x deterministic
interface-collision filter, with derating (screen at 140 us what must hold
110 us at operation). Demo: scorer-assembled modules predicted 0.94 ->
realized 2/2; random grouping predicted ~0 -> realized 0/2.

Phase 6 ✓ — packaging. `pip install` with zero dependencies; `qtdf` CLI
(validate / show / query / verify / diff / demo / version); `qtdf demo` runs
the entire pipeline — virtual lot -> executive screen -> wafer map -> policies
priced vs truth -> MCM assembly — self-contained (embedded plan) in ~2 s on a
clean machine. Verified: fresh venv, install, run from an unrelated cwd. The
demo's finale is the thesis in one line: from a 100-die lot with 7 true
MCM-grade dies, the best 3-die chain scores P(meets spec) = 0.10 — known-good-
die infrastructure is the difference between that and shipping modules.

Release pass (pkg 0.3.0, July 2026) ✓ — everything folded under the
`qtdf.*` namespace (imports changed, schema/records did not: schema stays
0.2.0 and v0.1/v0.2 records load unchanged); user paths scrubbed from all
shipped artifacts (record #1 re-finalized, store index rebuilt); Apache-2.0
LICENSE + NOTICE (with IBM data provenance); `verify.sh` single-command
verification; `AGENTS.md` so AI agents run instead of "architecting"; git +
CI (Linux/macOS × Python 3.10–3.14). Independent reproduction: confirmed
July 2026 on a non-macOS OS and non-3.14 Python (details to be recorded).

qtdf.learn (July 2026, commercial layer) — the first genuinely machine-learned
component: logistic score models trained in the vfridge gym (held-out AUC
0.97/0.98/0.99 for rounds 1/2/3) plus decision thresholds fitted directly in
dollars (multi-start coordinate descent on exact training cost). Benchmarked
through the same executive path as every hand-written policy, plus a 100-lot
(9,427-die) scale audit. Findings at module-grade economics (escape $50k):
2-cooldown discrimination cannot clear the escape bar — no ship rule is
profitable and ship-nothing beats every shipper by 26%; a 3rd confirming
cooldown DOES unlock shipping, but only for the ~0.2% of dies the margin-
aware model isolates (learned-3r: 15 ships, 0 escapes, beats ship-nothing) —
binary confirm-3x ships 5.4% poison at scale and its small-sample wins are
luck. At lab-grade economics ($8k) the learned policy ties the best hand
policy within 0.4% with half the escapes. Same models, different operating
points: thresholds re-derive from the customer's cost structure in seconds.

Deferred: JSON Schema export for other languages (first non-Python partner).

## License

Apache-2.0 (see LICENSE, NOTICE) on this repository: the QTDF schema,
validator, store, executive, virtual fridge, and CLI — open because a test
-data standard is only useful if everyone can adopt it. The dispositioning
engine and yield analytics (`qtdf/disposition/`, `qtdf/analytics/`) are the
commercial layer and are not part of the public distribution; this working
repository contains them for development.
