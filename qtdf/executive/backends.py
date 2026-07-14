"""Measurement backends + capture I/O.

VFridgeBackend drives the Phase 2 emulator; ReplayBackend re-emits a captured
run. Both satisfy the same duck-typed contract:

    measure(slot, quantities) -> {quantity: value_or_None}

A capture file is the full context of a run — plan, fridge, carrier meta,
slots, raw results, run identity and clock — sufficient to replay it into
byte-identical QTDF records. Captures are how a fridge session becomes a CI
fixture.
"""
from __future__ import annotations

import json

from qtdf.vfridge.measure import Cooldown, MeasConfig
from qtdf.vfridge.wafer import EmuConfig, WaferTruth

from .adapters import DeviceSlot

CAPTURE_VERSION = 1


# --------------------------------------------------------------------- #
# vfridge
# --------------------------------------------------------------------- #
def slots_from_wafer(wafer: WaferTruth, max_dies: int | None = None,
                     die_ids: set | None = None) -> list:
    """DeviceSlots for a wafer (first max_dies dies, or an explicit die set)."""
    dies = [d for d in wafer.dies if die_ids is None or d.die_id in die_ids]
    slots = []
    for die in dies[:max_dies]:
        for qt in die.qubits:
            slots.append(DeviceSlot(
                device_id=f"{die.die_id}:Q{qt.q}",
                handle=(die, qt),
                part_number="EMU-TRANSMON-4Q",
                description=f"virtual transmon {qt.q} on die {die.die_id}",
                wafer={"lot_id": wafer.lot_id, "wafer_id": wafer.wafer_id,
                       "die_x": die.die_x, "die_y": die.die_y},
                genealogy={"vendor": "vfridge", "chip": die.die_id},
            ))
    return slots


class VFridgeBackend:
    """Measures truth wafers through the Phase 2 cooldown model."""

    tool = "vfridge"
    tool_method = "emulated cooldown measurement"
    data_source = "emulated"

    def __init__(self, wafer: WaferTruth, cfg: EmuConfig,
                 meas: MeasConfig | None = None, cooldown_no: int = 1):
        self._cd = Cooldown(wafer, cfg, meas or MeasConfig(), cooldown_no=cooldown_no)

    def measure(self, slot: DeviceSlot, quantities: list) -> dict:
        die, qt = slot.handle
        values = self._cd.measure_qubit(die, qt)
        return {q: values.get(q) for q in quantities}


# --------------------------------------------------------------------- #
# capture + replay
# --------------------------------------------------------------------- #
class ReplayBackend:
    """Re-emits the raw results of a captured run, deterministically."""

    tool = "replay"
    tool_method = "captured-run replay"

    def __init__(self, capture: dict):
        self._results = capture["results"]
        self.data_source = capture["data_source"]

    def measure(self, slot: DeviceSlot, quantities: list) -> dict:
        stored = self._results[slot.device_id]
        return {q: stored.get(q) for q in quantities}


def write_capture(path: str, capture: dict) -> None:
    capture = dict(capture)
    capture["capture_version"] = CAPTURE_VERSION
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(capture, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def read_capture(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        capture = json.load(fh)
    if capture.get("capture_version") != CAPTURE_VERSION:
        raise ValueError(f"{path}: unsupported capture_version")
    return capture


def slots_from_capture(capture: dict) -> list:
    """Rebuild slots from a capture (handle = device_id; sockets preserved)."""
    return [DeviceSlot(handle=s["device_id"], **s) for s in capture["slots"]]
