# Guidance for AI agents (and hurried humans)

This repository is **complete and tested**. If you were asked to "run",
"test", or "verify" it, do exactly one thing:

```bash
bash verify.sh
```

That runs every test suite, verifies store integrity, and runs the
end-to-end demo, printing PASS/FAIL per step. There is nothing to
architect, refactor, scaffold, or fix first. Python 3.10+ stdlib only —
no installs, no network.

## Rules that will save your context window

- **Never open, list, or grep files under `store/`** — it holds thousands
  of small JSON data records (~16 MB). Query it through the CLI instead:
  `python3 -m qtdf.cli query store --count`, `... verify store`.
- The same goes for `captures/`, `truth/`, and any `store_*/` or `sim_*/`
  directory: machine-generated data, not code.
- The human-readable spec is `SCHEMA.md`; the map of everything is
  `README.md`. Read those two before any source file.

## Layout (code lives under qtdf/)

- `qtdf/` — schema, validator, hashed store, CLI (`qtdf/cli.py`), demo
  - `qtdf/vfridge/` — virtual fridge (truth + measurement emulator)
  - `qtdf/executive/` — test plans, adapters, run/replay
  - `qtdf/disposition/` — specs, screening policies, exact evaluation
  - `qtdf/analytics/` — wafer maps, SPC, gauge R&R, MCM scorer
  - `qtdf/learn/` — machine-learned screening policies (gym, models, thresholds)
- `tests/` — 7 suites; each runs standalone: `python3 tests/test_qtdf.py`
- `phase2..5_demo.py` — narrative demonstrations (see README)

## Common tasks

- Run everything: `bash verify.sh`
- One suite: `python3 tests/test_executive.py`
- The 2-second pitch: `pip install . && qtdf demo`
- Validate a record: `python3 -m qtdf.cli validate <file.json>`
