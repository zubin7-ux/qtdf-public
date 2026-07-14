"""vfridge — virtual fridge/wafer emulator with known ground truth.

Truth generation (wafer), measurement + QTDF emission (measure). Stdlib only.
"""
from .measure import MCM_GRADE_V0, Cooldown, MeasConfig
from .wafer import (
    DieTruth,
    EmuConfig,
    QubitTruth,
    WaferTruth,
    die_truth_pass,
    generate_lot,
    generate_wafer,
    qubit_truth_pass,
    truth_sidecar,
)

__all__ = [
    "EmuConfig", "MeasConfig", "Cooldown", "MCM_GRADE_V0",
    "QubitTruth", "DieTruth", "WaferTruth",
    "generate_wafer", "generate_lot",
    "qubit_truth_pass", "die_truth_pass", "truth_sidecar",
]
