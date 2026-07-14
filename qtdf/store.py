"""QTDF store — append-only directory store with a line-oriented index.

Layout:
    <root>/records/<uuid>.json     one finalized record per file, immutable
    <root>/index.jsonl             one JSON line per record (query hot path)

Design points:
  - Append-only: ``add`` refuses a duplicate record_id; corrections are new
    records that set ``provenance.supersedes``. Nothing is ever rewritten.
  - Records are validated (hard errors) and hash-finalized on the way in, so
    everything inside the store is conformant and tamper-evident by
    construction. ``verify_all`` re-checks the hashes on demand.
  - The index holds the handful of fields analytics filter on. It is a cache:
    ``rebuild_index`` regenerates it from the record files at any time.

Stdlib only, same as the rest of qtdf-core.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator

from .core import finalize, verify_hash
from .validate import errors_only, validate

# fields lifted from a record into its index row
_INDEX_FIELDS = ("record_id", "record_type", "data_source")


def _index_row(record: dict) -> dict:
    row = {k: record.get(k) for k in _INDEX_FIELDS}
    row["device_id"] = record.get("device", {}).get("device_id")
    row["verdict"] = record.get("disposition", {}).get("verdict")
    row["run_id"] = (record.get("run") or {}).get("run_id")
    row["generated_at"] = record.get("provenance", {}).get("generated_at")
    row["content_hash"] = record.get("provenance", {}).get("content_hash")
    return row


class Store:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.records_dir = os.path.join(self.root, "records")
        self.index_path = os.path.join(self.root, "index.jsonl")
        os.makedirs(self.records_dir, exist_ok=True)

    # ------------------------------------------------------------------ #
    def _path_for(self, record_id: str) -> str:
        # record_id is 'urn:uuid:<uuid>'; the uuid is the filename
        return os.path.join(self.records_dir, record_id.split(":")[-1] + ".json")

    def add(self, record: dict) -> str:
        """Validate, finalize, and persist a record. Returns its record_id.

        Raises ValueError on hard validation errors or a duplicate record_id.
        """
        errors = errors_only(validate(record))
        if errors:
            raise ValueError("record failed validation:\n  " + "\n  ".join(errors))
        record_id = record["record_id"]
        path = self._path_for(record_id)
        if os.path.exists(path):
            raise ValueError(f"duplicate record_id (store is append-only): {record_id}")
        finalize(record)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        with open(self.index_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(_index_row(record), ensure_ascii=False) + "\n")
        return record_id

    def get(self, record_id: str) -> dict:
        with open(self._path_for(record_id), encoding="utf-8") as fh:
            return json.load(fh)

    # ------------------------------------------------------------------ #
    def index(self) -> Iterator[dict]:
        """Yield index rows (cheap — never opens record files)."""
        if not os.path.exists(self.index_path):
            return
        with open(self.index_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def query(self, *, load: bool = False, device_prefix: str | None = None,
              **eq_filters) -> Iterator[dict]:
        """Filter index rows by equality (and optional device_id prefix).

        eq_filters keys: any index field (record_type, data_source, verdict,
        run_id, ...). With ``load=True`` yields full records instead of rows.
        """
        for row in self.index():
            if any(row.get(k) != v for k, v in eq_filters.items()):
                continue
            if device_prefix and not str(row.get("device_id", "")).startswith(device_prefix):
                continue
            yield self.get(row["record_id"]) if load else row

    def count(self, **eq_filters) -> int:
        return sum(1 for _ in self.query(**eq_filters))

    # ------------------------------------------------------------------ #
    def verify_all(self) -> list[str]:
        """Re-hash every record; return a list of record_ids that fail."""
        bad = []
        for row in self.index():
            if not verify_hash(self.get(row["record_id"])):
                bad.append(row["record_id"])
        return bad

    def rebuild_index(self) -> int:
        """Regenerate index.jsonl from the record files. Returns row count."""
        rows = []
        for name in sorted(os.listdir(self.records_dir)):
            if name.endswith(".json"):
                with open(os.path.join(self.records_dir, name), encoding="utf-8") as fh:
                    rows.append(_index_row(json.load(fh)))
        with open(self.index_path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return len(rows)
