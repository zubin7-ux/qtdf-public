# QTDF v0.2 — Quantum Test Data Format

A neutral, versioned record for a single test of a single device on a single
fixture. QTDF is to quantum device test what STDF is to semiconductor test: an
open lingua franca that any fridge, prober, or executive can emit, so that the
yield-learning and dispositioning layer above it has something uniform to eat.

**Design rules**
- **One record = one test event.** Immutable once written. Corrections are new
  records that point back via `supersedes` (append-only, like a ledger).
- **Measurement vs prediction is never ambiguous.** `data_source` is required
  and is one of `measured | simulation | emulated`. A sim can never be mistaken
  for a DUT.
- **Every record is self-describing and tamper-evident.** `provenance.content_hash`
  is a sha256 over the canonical record (minus the hash itself).
- **The carrier is first-class.** `carrier.provider` (`cassette | manual | custom`)
  is where the two data-quality tiers live: a `cassette` record carries automatic
  socket→device genealogy and a qualified RF environment; a `manual` record is
  fully valid but leans on operator-entered metadata.
- **Open vocab, gentle enforcement.** Unknown `record_type` is a warning, not an
  error, so the format grows without a spec revision. Structural/semantic breaks
  (bad enum, pass/limit contradiction, missing required field) are hard errors.

## Top-level structure

| field | type | req | meaning |
|---|---|---|---|
| `qtdf_version` | string | ✓ | schema semver, e.g. `0.1.0` |
| `record_id` | string | ✓ | `urn:uuid:…`, globally unique |
| `record_type` | string | ✓ | `rf_launch_qualification`, `qubit_coherence_screen`, `readout_fidelity`, `gate_benchmarking`, `spectroscopy`, `continuity`, … |
| `data_source` | enum | ✓ | `measured` \| `simulation` \| `emulated` |
| `device` | object | ✓ | genealogy of the DUT; optional `wafer` block (v0.2): `lot_id`, `wafer_id`, `die_x`, `die_y` for known-good-die analytics |
| `carrier` | object | ✓ | how it reached the fridge (the cassette tier) |
| `run` | object | – | (v0.2) session grouping: `run_id` (required within block), `cooldown_id`, `plan_hash` — one cooldown emits many records sharing a run |
| `fixture` | object | ✓ | fridge / wiring / ports |
| `test` | object | ✓ | plan, executive, band, operator |
| `calibration` | object | ✓ | reference impedance, standards, cal error |
| `measurements` | array | ✓ | typed results with limits (see below) |
| `traces` | array | – | bulk data refs (touchstone, HDF5…) with sha256 |
| `disposition` | object | ✓ | verdict + bin + rules (the dispositioning standard) |
| `annotations` | object | – | caveats, side studies, free notes |
| `provenance` | object | ✓ | tool, timestamp, environment, `content_hash`, `supersedes` |

## measurements[]

The heart of the record. One entry per measured quantity; the same shape holds
an S-parameter, a T1, or a gate fidelity.

```json
{
  "quantity": "return_loss",
  "symbol": "|S11|",
  "value": -18.62,
  "unit": "dB",
  "conditions": { "frequency_GHz": 8.0, "gap_mm": 1.8 },
  "limit": { "op": "<=", "value": -15.0 },
  "pass": true,
  "margin_dB": 3.62
}
```

- `value` may be a scalar or an array (e.g. matched-band lobes `[[lo,hi],…]`).
- `limit.op` ∈ `<= >= < > == in_range` (`in_range` uses `low`/`high`).
- `pass` is optional but if present **must** agree with `value` vs `limit` — the
  validator recomputes it and flags contradictions. Set `null` for informational
  quantities that have no limit.
- `value: null` is legal and means "not obtained" (e.g. incomplete calibration);
  such measurements carry `limit: null` and typically drive a `hold` verdict.

### Quantity profiles (v0.2)

For a known `record_type`, required quantities are enforced (hard error) and
recommended ones warned on:

| record_type | required | recommended |
|---|---|---|
| `rf_launch_qualification` | `return_loss` | `insertion_loss` |
| `qubit_coherence_screen` | `T1` | `T2`, `T2_star`, `f_01`, `readout_error` |

Coherence vocabulary (grounded on real IBM calibration snapshots): `T1` (us),
`T2` / `T2_star` (us), `f_01` (GHz), `readout_error` (dimensionless),
`anharmonicity` (GHz), `gate_error_1q` / `gate_error_2q` (dimensionless).
Unknown record_types skip profile checks (open vocab).

## disposition — the standard nobody owns yet

```json
{
  "verdict": "pass",              // pass | fail | hold | scrap | rework
  "bin": 1,                        // integer bin (semiconductor-style)
  "override": false,               // engineering override of the derived verdict
  "reason": null,                  // required if override is true
  "rules": [
    { "rule_id": "RL15@8GHz", "quantity": "return_loss",
      "limit": { "op": "<=", "value": -15.0 }, "result": "pass" }
  ],
  "reference": "-15 dB return loss at the 8 GHz operating band"
}
```

The verdict is normally derived from the rules; `override` + `reason` records a
human disposition without erasing the underlying data.

## provenance

```json
{
  "generated_at": "2026-07-09T…Z",
  "tool": "openEMS", "tool_method": "FDTD (full-wave)",
  "generator": "your_lab/ingest_rf_qualification.py",
  "qtdf_library_version": "0.1.0",
  "environment": { "python": "3.x", "platform": "…" },
  "supersedes": null,
  "content_hash": "sha256:…"
}
```

## Versioning & migration

`qtdf_version` is semver. MINOR bumps are additive/compatible; readers migrate
old→new via `qtdf.migrate` (v0.1 is the floor). A record from a different MAJOR
is refused rather than silently misread. Labs keep test data for years, so
backward-compatible reads are a hard requirement, not a nicety.

## Reference implementation

`qtdf/` (stdlib only): `core` (hash/io/migrate), `validate` (structural +
semantic), `touchstone` (.s2p ingest). `records/ENG-RF-002_optAB_GSG.qtdf.json`
is the first real record, generated from the ENG-RF-002 full-wave result.
