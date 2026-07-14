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

- **Never open, list, or grep files under `store/` or any `store_*/`
  directory** (created by the ingester/demos) — thousands of small JSON data
  records, not code. Query through the CLI instead:
  `python3 -m qtdf.cli query store --count`, `... verify store`.
- The human-readable spec is `SCHEMA.md`; the map of everything is
  `README.md`. Read those two before any source file.

## Layout (code lives under qtdf/)

- `qtdf/` — schema, validator, hashed store, CLI (`qtdf/cli.py`), demo
  - `qtdf/vfridge/` — virtual fridge (truth + measurement emulator)
  - `qtdf/executive/` — test plans, adapters, run/replay
- `tests/` — each suite runs standalone: `python3 tests/test_qtdf.py`

## Common tasks

- Run everything: `bash verify.sh`
- One suite: `python3 tests/test_executive.py`
- The 2-second pitch: `pip install . && qtdf demo`
- Validate a record: `python3 -m qtdf.cli validate <file.json>`
