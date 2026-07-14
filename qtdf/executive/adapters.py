"""Adapter interfaces — where hardware (real or virtual) meets the executive.

Three seams, kept deliberately narrow:
  - CarrierProvider: how devices physically reach the fridge. Assigns sockets,
    contributes genealogy + RF-environment metadata. The cassette is one
    implementation; a hand-wired setup is the degenerate one. Same records
    come out either way — the cassette just makes the metadata automatic
    and the RF environment qualified.
  - MeasurementBackend (duck-typed): measure(slot, quantities) -> {q: value}.
    vfridge and replay backends live in executive.backends; a QCoDeS-driven
    hardware backend slots in here later without touching the executive.
  - FridgeProfile: fixture metadata.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DeviceSlot:
    """One testable device position in a load."""
    device_id: str
    handle: object = None            # backend-understood reference
    socket: str | None = None        # assigned by the carrier
    part_number: str | None = None
    description: str | None = None
    wafer: dict | None = None        # QTDF device.wafer block
    genealogy: dict = field(default_factory=dict)

    def public(self) -> dict:
        """Serializable form (no handle) — what goes into a capture file."""
        return {"device_id": self.device_id, "socket": self.socket,
                "part_number": self.part_number, "description": self.description,
                "wafer": self.wafer, "genealogy": self.genealogy}


@dataclass
class FridgeProfile:
    fridge_id: str
    temperature_K: float | None = None
    note: str | None = None

    def fixture(self) -> dict:
        return {"fridge_id": self.fridge_id, "temperature_K": self.temperature_K,
                "note": self.note}


class CassetteCarrier:
    """CAS-400 cassette: sockets are assigned per die, genealogy is automatic,
    the RF environment is the qualified ENG-RF-002 launch, and the loopback
    standards give the self-test hook."""

    provider = "cassette"

    def __init__(self, cassette_id: str = "CAS-400", capacity: int = 24,
                 loopback_standards: tuple = ("ENG-RF-001_GSG.s2p",)):
        self.cassette_id = cassette_id
        self.capacity = capacity
        self.loopback_standards = list(loopback_standards)

    def load(self, slots: list) -> list:
        """Assign sockets die-by-die. One load = one cooldown = one run.
        Raises if the load exceeds cassette capacity (caller batches)."""
        die_order: list[str] = []
        for s in slots:
            die = s.device_id.rsplit(":Q", 1)[0]
            if die not in die_order:
                die_order.append(die)
        if len(die_order) > self.capacity:
            raise ValueError(
                f"load of {len(die_order)} dies exceeds cassette capacity {self.capacity}")
        socket_of = {die: f"S{i + 1:02d}" for i, die in enumerate(die_order)}
        for s in slots:
            s.socket = socket_of[s.device_id.rsplit(":Q", 1)[0]]
        return slots

    def meta(self) -> dict:
        return {"provider": self.provider, "carrier_part": self.cassette_id,
                "rf_environment_qualified": True,
                "loopback_standards": self.loopback_standards}


class ManualCarrier:
    """Bare wirebond / hand-wired: fully valid, operator-maintained metadata,
    no qualified RF environment, no sockets."""

    provider = "manual"

    def __init__(self, note: str = "hand-wired; operator-entered device map"):
        self.note = note

    def load(self, slots: list) -> list:
        return slots                     # sockets stay None

    def meta(self) -> dict:
        return {"provider": self.provider, "carrier_part": None,
                "note": self.note}
