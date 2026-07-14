"""qtdf-exec — the cross-fridge test executive (stdlib only).

Plans (declarative, hashed) x adapters (carrier/backend/fridge) -> QTDF records
with deterministic identity; captures make any run a replayable CI fixture.
"""
from .adapters import CassetteCarrier, DeviceSlot, FridgeProfile, ManualCarrier
from .backends import (
    ReplayBackend,
    VFridgeBackend,
    read_capture,
    slots_from_capture,
    slots_from_wafer,
    write_capture,
)
from .plan import disposition, load_plan, plan_hash, validate_plan
from .run import execute, record_id_for, replay

__all__ = [
    "DeviceSlot", "FridgeProfile", "CassetteCarrier", "ManualCarrier",
    "VFridgeBackend", "ReplayBackend",
    "slots_from_wafer", "slots_from_capture", "read_capture", "write_capture",
    "load_plan", "plan_hash", "validate_plan", "disposition",
    "execute", "replay", "record_id_for",
]
