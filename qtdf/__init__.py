"""QTDF — Quantum Test Data Format (v0.1 reference implementation)."""
from .core import (
    QTDF_VERSION,
    content_hash,
    finalize,
    migrate,
    new_record_id,
    read_record,
    utc_now,
    verify_hash,
    write_record,
)
from .store import Store
from .validate import errors_only, is_valid, validate

# package (distribution) version — distinct from QTDF_VERSION, the schema
# version stamped into records. 0.3.0 = the qtdf.* namespace consolidation.
__version__ = "0.3.0"

__all__ = [
    "QTDF_VERSION",
    "content_hash",
    "finalize",
    "migrate",
    "new_record_id",
    "read_record",
    "utc_now",
    "verify_hash",
    "write_record",
    "validate",
    "errors_only",
    "is_valid",
    "Store",
]
