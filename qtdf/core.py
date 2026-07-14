"""QTDF core — Quantum Test Data Format, reference implementation (v0.1).

Zero external dependencies (Python stdlib only). A QTDF record is a plain dict
that round-trips to JSON. This module supplies:
  - the version + controlled vocabularies,
  - canonical serialization + content hashing (tamper-evident provenance),
  - read/write helpers,
  - a forward-migration hook.

Validation lives in ``qtdf.validate``; touchstone ingest in ``qtdf.touchstone``.
"""
from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import json
import uuid
from typing import Any

# Schema semver. Bump MINOR for additive/compatible changes, MAJOR for breaking.
# v0.2.0 (additive over 0.1): optional `device.wafer` genealogy (lot/wafer/die x,y),
# optional top-level `run` grouping (cooldown/session), per-record_type required-
# quantity profiles in the validator, and the qubit_coherence_screen vocabulary.
# v0.1 records remain valid v0.2 records — hashes and validity are unchanged.
QTDF_VERSION = "0.2.0"

# --- Controlled vocabularies (recommended, not closed; validator warns on novel) ---

# What kind of test the record captures. Open vocab, but these are the seeds.
RECORD_TYPES = frozenset({
    "rf_launch_qualification",   # S-parameter qualification of an RF transition/fixture
    "qubit_coherence_screen",    # T1 / T2* / T2echo
    "readout_fidelity",
    "gate_benchmarking",         # RB / XEB
    "spectroscopy",              # f_01, anharmonicity, TLS
    "continuity",                # DC / wiring integrity
})

# Whether the numbers are physically measured or predicted. CRITICAL to keep
# straight — a test-data standard must never let a sim be mistaken for a DUT.
DATA_SOURCES = frozenset({"measured", "simulation", "emulated"})

# How the device under test reached the fridge. This is the cassette tier.
CARRIER_PROVIDERS = frozenset({
    "cassette",   # CPN cassette: socket->device_id is automatic, RF env qualified
    "manual",     # bare wirebond / hand-wired: metadata entered by operator
    "custom",     # third-party carrier via an adapter
})

# Dispositioning verdicts (the disposition standard). Overall verdict may be
# derived from measurement passes OR set by engineering override (with reason).
VERDICTS = frozenset({"pass", "fail", "hold", "scrap", "rework"})

# Comparison operators for a measurement limit.
LIMIT_OPS = frozenset({"<=", ">=", "<", ">", "==", "in_range"})


# --------------------------------------------------------------------------- #
# Identity + timestamps
# --------------------------------------------------------------------------- #
def new_record_id() -> str:
    """Return a fresh urn:uuid record identifier."""
    return f"urn:uuid:{uuid.uuid4()}"


def utc_now() -> str:
    """ISO-8601 UTC timestamp, second precision, 'Z' suffix."""
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# Canonicalization + content hashing
# --------------------------------------------------------------------------- #
def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no insignificant whitespace.

    Two records with the same content hash to the same string regardless of key
    insertion order, so ``content_hash`` is a stable identity for the payload.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(record: dict) -> str:
    """sha256 over the record with ``provenance.content_hash`` excluded.

    The hash cannot cover itself, so we strip it before hashing. Returns a
    'sha256:...' prefixed hex digest.
    """
    stripped = copy.deepcopy(record)
    prov = stripped.get("provenance")
    if isinstance(prov, dict):
        prov.pop("content_hash", None)
    digest = hashlib.sha256(canonical_json(stripped).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def finalize(record: dict) -> dict:
    """Stamp ``provenance.content_hash`` in place and return the record.

    Call once, immediately before persisting. A record is immutable after
    finalize; corrections are new records that set ``supersedes``.
    """
    record.setdefault("provenance", {})
    record["provenance"]["content_hash"] = content_hash(record)
    return record


def verify_hash(record: dict) -> bool:
    """True iff the stored content hash matches a fresh recomputation."""
    stored = record.get("provenance", {}).get("content_hash")
    return bool(stored) and stored == content_hash(record)


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #
def write_record(record: dict, path: str) -> None:
    """Write a record as pretty JSON (finalize first if not already hashed)."""
    if not record.get("provenance", {}).get("content_hash"):
        finalize(record)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def read_record(path: str) -> dict:
    """Read a record from JSON and migrate it to the current QTDF_VERSION."""
    with open(path, encoding="utf-8") as fh:
        return migrate(json.load(fh))


# --------------------------------------------------------------------------- #
# Migration
# --------------------------------------------------------------------------- #
def migrate(record: dict) -> dict:
    """Forward-migrate an older-minor record to QTDF_VERSION.

    v0.1 is the floor, so this is currently a version-gate: it refuses a record
    whose MAJOR differs from ours. As the schema evolves, add step functions
    here (0.1 -> 0.2 -> ...) so historical records keep loading — backward
    compatibility is a product feature, labs keep data for years.
    """
    ver = str(record.get("qtdf_version", "0.0.0"))
    major = ver.split(".")[0]
    if major != QTDF_VERSION.split(".")[0]:
        raise ValueError(
            f"record qtdf_version {ver} is a different MAJOR than {QTDF_VERSION}; "
            "no migration path is defined"
        )
    return record
