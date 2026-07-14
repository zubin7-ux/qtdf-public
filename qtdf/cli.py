"""qtdf — the command line for QTDF stores and records.

    qtdf validate FILE...        validate record files (exit 1 on hard errors)
    qtdf show FILE               human-readable record summary + hash check
    qtdf query STORE [filters]   list/count records in a store
    qtdf verify STORE            re-hash every record in a store
    qtdf diff A B                semantic diff of two records
    qtdf demo                    the end-to-end pipeline on a virtual lot
    qtdf version                 library + schema version

Stdlib only, like everything in qtdf-core.
"""
from __future__ import annotations

import argparse
import json
import sys


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------ #
def cmd_validate(args) -> int:
    import qtdf
    worst = 0
    for path in args.files:
        problems = qtdf.validate(_load(path))
        errors = [p for p in problems if not p.startswith("warning: ")]
        warnings = [p for p in problems if p.startswith("warning: ")]
        status = "OK" if not errors else "INVALID"
        print(f"{status:8s} {path}"
              + (f"  ({len(warnings)} warning{'s' * (len(warnings) != 1)})"
                 if warnings else ""))
        for p in errors + (warnings if args.verbose else []):
            print(f"         - {p}")
        worst = max(worst, 1 if errors else 0)
    return worst


def cmd_show(args) -> int:
    import qtdf
    rec = _load(args.file)
    dev, disp, run = rec.get("device", {}), rec.get("disposition", {}), rec.get("run") or {}
    w = dev.get("wafer") or {}
    print(f"record   : {rec.get('record_id')}  (qtdf {rec.get('qtdf_version')})")
    print(f"type     : {rec.get('record_type')}  [{rec.get('data_source')}]")
    print(f"device   : {dev.get('device_id')}"
          + (f"  (lot {w.get('lot_id')} wafer {w.get('wafer_id')}"
             f" die {w.get('die_x')},{w.get('die_y')})" if w else ""))
    c = rec.get("carrier", {})
    print(f"carrier  : {c.get('provider')}"
          + (f" {c.get('carrier_part')}" if c.get("carrier_part") else "")
          + (f" socket {c.get('socket')}" if c.get("socket") else ""))
    f = rec.get("fixture", {})
    print(f"fixture  : {f.get('fridge_id')}"
          + (f" @ {f.get('temperature_K')} K" if f.get("temperature_K") is not None else ""))
    if run:
        ph = run.get("plan_hash") or ""
        print(f"run      : {run.get('run_id')}  {run.get('cooldown_id') or ''}"
              + (f"  plan {ph[:18]}…" if ph else ""))
    print(f"verdict  : {disp.get('verdict')} (bin {disp.get('bin')})"
          + (f" — {disp['reason']}" if disp.get("reason") else ""))
    print("measurements:")
    for m in rec.get("measurements", []):
        lim = m.get("limit")
        lim_s = f"{lim['op']} {lim['value']}" if lim else ""
        ok = {True: "PASS", False: "FAIL", None: "    "}[m.get("pass")]
        val = m.get("value")
        if isinstance(val, float):
            val_s = f"{val:12.5g}"
        elif isinstance(val, (list, dict)):        # array values (e.g. band lobes)
            s = json.dumps(val)
            val_s = s if len(s) <= 28 else s[:25] + "..."
        else:
            val_s = f"{val!s:>12}"
        print(f"  {m.get('quantity', ''):16s} {val_s} {m.get('unit', ''):4s}"
              f" {lim_s:12s} {ok}")
    print(f"hash     : {'verified OK' if qtdf.verify_hash(rec) else 'MISMATCH'}")
    return 0


def cmd_query(args) -> int:
    from qtdf.store import Store
    filters = {}
    for key in ("record_type", "data_source", "verdict", "run_id"):
        v = getattr(args, key)
        if v is not None:
            filters[key] = v
    rows = Store(args.store).query(device_prefix=args.device_prefix, **filters)
    if args.count:
        print(sum(1 for _ in rows))
        return 0
    n = 0
    for row in rows:
        print(f"{row['verdict'] or '-':5s} {row['record_type'] or '-':26s} "
              f"{row['device_id'] or '-'}")
        n += 1
        if args.limit and n >= args.limit:
            print(f"... (--limit {args.limit} reached)")
            break
    return 0


def cmd_verify(args) -> int:
    from qtdf.store import Store
    st = Store(args.store)
    bad = st.verify_all()
    n = sum(1 for _ in st.index())
    if bad:
        print(f"{len(bad)}/{n} records FAILED hash verification:")
        for rid in bad[:20]:
            print(f"  {rid}")
        return 1
    print(f"{n} records, all hashes verified")
    return 0


def cmd_diff(args) -> int:
    a, b = _load(args.a), _load(args.b)
    if a.get("device", {}).get("device_id") != b.get("device", {}).get("device_id"):
        print(f"device   : {a['device']['device_id']}  vs  {b['device']['device_id']}")
    ma = {m["quantity"]: m for m in a.get("measurements", [])}
    mb = {m["quantity"]: m for m in b.get("measurements", [])}
    changed = False
    for q in sorted(set(ma) | set(mb)):
        va, vb = (ma.get(q) or {}).get("value"), (mb.get(q) or {}).get("value")
        if va == vb:
            continue
        changed = True
        delta = ""
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and va:
            delta = f"  ({100.0 * (vb - va) / abs(va):+.1f}%)"
        print(f"{q:16s}: {va} -> {vb}{delta}")
    da, db = a.get("disposition", {}), b.get("disposition", {})
    if (da.get("verdict"), da.get("bin")) != (db.get("verdict"), db.get("bin")):
        changed = True
        print(f"verdict         : {da.get('verdict')}(bin {da.get('bin')})"
              f" -> {db.get('verdict')}(bin {db.get('bin')})")
    pa = (a.get("run") or {}).get("plan_hash")
    pb = (b.get("run") or {}).get("plan_hash")
    if pa != pb:
        changed = True
        print(f"plan_hash       : {'differs' if pa and pb else 'added/removed'}"
              f" ({(pa or '-')[:18]}… -> {(pb or '-')[:18]}…)")
    if not changed:
        print("no semantic differences (values, verdict, plan)")
    return 0


def cmd_demo(args) -> int:
    from qtdf.demo import run
    return run(seed=args.seed, rows=args.rows, cols=args.cols,
               store_dir=args.store)


def cmd_version(_args) -> int:
    import qtdf
    print(f"qtdf {qtdf.__version__} (schema {qtdf.QTDF_VERSION})")
    return 0


# ------------------------------------------------------------------ #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qtdf", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="validate record files")
    p.add_argument("files", nargs="+")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="also print warnings")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("show", help="summarize one record")
    p.add_argument("file")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("query", help="filter a store's index")
    p.add_argument("store")
    p.add_argument("--record-type", dest="record_type")
    p.add_argument("--data-source", dest="data_source")
    p.add_argument("--verdict")
    p.add_argument("--run-id", dest="run_id")
    p.add_argument("--device-prefix", dest="device_prefix")
    p.add_argument("--count", action="store_true")
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(fn=cmd_query)

    p = sub.add_parser("verify", help="re-hash every record in a store")
    p.add_argument("store")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("diff", help="semantic diff of two records")
    p.add_argument("a")
    p.add_argument("b")
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("demo", help="end-to-end pipeline on a virtual lot")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--rows", type=int, default=10)
    p.add_argument("--cols", type=int, default=10)
    p.add_argument("--store", default=None,
                   help="keep the demo store here (default: temp dir)")
    p.set_defaults(fn=cmd_demo)

    p = sub.add_parser("version", help="print schema/library version")
    p.set_defaults(fn=cmd_version)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
