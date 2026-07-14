"""Virtual wafer — truth-level physics model of a transmon qubit wafer.

Generates lots/wafers/dies/qubits with physics-informed, spatially-correlated
variation and LABELED defects. This module is pure truth: intrinsic device
values as fabricated. Measurement noise, cooldown-to-cooldown fluctuation, and
QTDF emission live in vfridge.measure — a die never knows it is being tested.

Physics knobs (defaults calibrated against the measured IBM fleet via
calibrate_emulator.py):
  - Frequency: target + radial bowl (junction-oxide thickness gradient) +
    smooth correlated field + die-local targeting error. df/f ~ -dRn/(2 Rn).
  - T1: lognormal intrinsic (correlated + iid parts) suppressed by a bath of
    discrete TLS: Lorentzian coupling in detuning. Strongly-coupled TLS get a
    truth label 'tls_coupled'.
  - T2: 1/T2 = 1/(2 T1) + 1/Tphi with lognormal Tphi.
  - Hard defects with labels: 'junction_defect' (dead qubit),
    'readout_defect' (grossly elevated readout error).
  - Die-level truth flag 'freq_collision' when two qubits on a die land closer
    than the collision threshold.

Deterministic: the same EmuConfig (incl. seed) reproduces the same lot exactly.
Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
from dataclasses import dataclass, field, replace

TWO_PI = 2 * math.pi


def stable_seed(*parts) -> int:
    """Process-stable 64-bit seed from arbitrary parts.

    NEVER use tuple.__hash__() for seeding: Python salts string hashes per
    process, which silently breaks cross-process reproducibility.
    """
    text = ":".join(str(p) for p in parts)
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


@dataclass
class EmuConfig:
    seed: int = 1
    lot_id: str = "LOT-EMU-01"
    wafers: int = 1
    rows: int = 10
    cols: int = 10
    qubits_per_die: int = 4
    # frequency targeting (GHz)
    f_target_GHz: float = 4.80
    f_span_GHz: float = 0.40          # intra-die staggering span
    f_radial_frac: float = 0.010      # center->edge systematic
    f_corr_frac: float = 0.006        # smooth correlated across-wafer part
    f_iid_frac: float = 0.005         # die-local targeting error
    collision_min_MHz: float = 60.0
    # T1 (intrinsic, us)
    t1_median_us: float = 220.0
    t1_sigma_ln: float = 0.45         # total lognormal spread
    t1_corr_frac: float = 0.40        # fraction of variance that is wafer-correlated
    # TLS bath
    tls_per_GHz_per_die: float = 0.8
    tls_width_MHz: float = 15.0
    tls_strength: float = 6.0         # T1 suppression ~ (1+strength) at zero detuning
    tls_label_factor: float = 2.0     # suppression >= this -> 'tls_coupled' label
    # dephasing
    tphi_median_us: float = 150.0
    tphi_sigma_ln: float = 0.60
    # readout
    ro_err_median: float = 0.015
    ro_err_sigma_ln: float = 0.90
    # hard defects
    p_junction_defect: float = 0.015
    p_readout_defect: float = 0.010

    @classmethod
    def from_calibration(cls, path: str = "emulator_calibration.json", **overrides):
        """Load fleet-fitted defaults if the calibration file exists."""
        cfg = cls(**overrides)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                cal = json.load(fh)
            fields = ("t1_median_us", "t1_sigma_ln", "tphi_median_us",
                      "tphi_sigma_ln", "ro_err_median", "ro_err_sigma_ln")
            cfg = replace(cfg, **{k: cal[k] for k in fields if k in cal and k not in overrides})
        return cfg


@dataclass
class QubitTruth:
    q: int
    f01_GHz: float | None        # None = dead junction (no transition)
    t1_us: float | None
    t2_us: float | None
    ro_err: float | None
    defects: list = field(default_factory=list)

    @property
    def functional(self) -> bool:
        return self.f01_GHz is not None


@dataclass
class DieTruth:
    die_x: int
    die_y: int
    die_id: str
    qubits: list          # list[QubitTruth]
    defects: list = field(default_factory=list)   # die-level, e.g. freq_collision


@dataclass
class WaferTruth:
    lot_id: str
    wafer_id: str
    dies: list            # list[DieTruth]

    def qubit_count(self) -> int:
        return sum(len(d.qubits) for d in self.dies)


def _smooth_field(rng: random.Random, modes: int = 4):
    """Zero-mean smooth 2D field on [-1,1]^2 from a few random cosine modes."""
    comps = [(rng.uniform(0.6, 2.5), rng.uniform(0, TWO_PI),
              rng.uniform(0.6, 2.5), rng.uniform(0, TWO_PI),
              rng.uniform(-1.0, 1.0)) for _ in range(modes)]

    def f(u: float, v: float) -> float:
        s = sum(a * math.cos(kx * math.pi * u + px) * math.cos(ky * math.pi * v + py)
                for kx, px, ky, py, a in comps)
        return s / math.sqrt(modes)

    return f


def generate_wafer(cfg: EmuConfig, wafer_no: int) -> WaferTruth:
    wafer_id = f"W{wafer_no:02d}"
    rng = random.Random(stable_seed(cfg.seed, cfg.lot_id, wafer_no, "wafer"))

    f_field = _smooth_field(rng)     # frequency-correlated component
    t1_field = _smooth_field(rng)    # T1-correlated component (e.g. substrate lot)
    radial_sign = rng.choice((-1.0, 1.0))

    sig_corr = cfg.t1_sigma_ln * math.sqrt(cfg.t1_corr_frac)
    sig_iid = cfg.t1_sigma_ln * math.sqrt(1.0 - cfg.t1_corr_frac)
    band_lo = cfg.f_target_GHz - cfg.f_span_GHz / 2 - 0.15
    band_hi = cfg.f_target_GHz + cfg.f_span_GHz / 2 + 0.15

    dies = []
    for gy in range(cfg.rows):
        for gx in range(cfg.cols):
            u = 2.0 * gx / max(cfg.cols - 1, 1) - 1.0
            v = 2.0 * gy / max(cfg.rows - 1, 1) - 1.0
            r2 = (u * u + v * v) / 2.0
            die_id = f"{cfg.lot_id}:{wafer_id}:D{gx:02d}-{gy:02d}"

            # a die-local TLS bath (junction/interface environment)
            n_tls = _poisson(rng, cfg.tls_per_GHz_per_die * (band_hi - band_lo))
            tls_freqs = [rng.uniform(band_lo, band_hi) for _ in range(n_tls)]

            qubits = []
            for q in range(cfg.qubits_per_die):
                # intra-die frequency staggering (collision avoidance by design)
                f_nom = cfg.f_target_GHz + cfg.f_span_GHz * (
                    q / max(cfg.qubits_per_die - 1, 1) - 0.5)
                if rng.random() < cfg.p_junction_defect:
                    qubits.append(QubitTruth(q, None, None, None, None,
                                             ["junction_defect"]))
                    continue
                f01 = f_nom * (1.0
                               + radial_sign * cfg.f_radial_frac * r2
                               + cfg.f_corr_frac * f_field(u, v)
                               + rng.gauss(0.0, cfg.f_iid_frac))

                t1 = cfg.t1_median_us * math.exp(
                    sig_corr * t1_field(u, v) + rng.gauss(0.0, sig_iid))
                # TLS suppression: Lorentzian in detuning
                w = cfg.tls_width_MHz / 1000.0
                supp = 1.0 + sum(
                    cfg.tls_strength / (1.0 + ((f01 - ft) / w) ** 2)
                    for ft in tls_freqs)
                t1_eff = t1 / supp
                defects = ["tls_coupled"] if supp >= cfg.tls_label_factor else []

                tphi = cfg.tphi_median_us * math.exp(rng.gauss(0.0, cfg.tphi_sigma_ln))
                t2 = 1.0 / (0.5 / t1_eff + 1.0 / tphi)

                ro = cfg.ro_err_median * math.exp(rng.gauss(0.0, cfg.ro_err_sigma_ln))
                if rng.random() < cfg.p_readout_defect:
                    ro = rng.uniform(0.10, 0.45)
                    defects = defects + ["readout_defect"]
                ro = min(ro, 0.5)

                qubits.append(QubitTruth(q, round(f01, 6), round(t1_eff, 2),
                                         round(t2, 2), round(ro, 5), defects))

            die_defects = []
            live = [x for x in qubits if x.functional]
            for i in range(len(live)):
                for j in range(i + 1, len(live)):
                    if abs(live[i].f01_GHz - live[j].f01_GHz) * 1000.0 < cfg.collision_min_MHz:
                        die_defects = ["freq_collision"]
            dies.append(DieTruth(gx, gy, die_id, qubits, die_defects))

    return WaferTruth(cfg.lot_id, wafer_id, dies)


def generate_lot(cfg: EmuConfig) -> list:
    """All wafers of the lot: list[WaferTruth]. Deterministic in cfg."""
    return [generate_wafer(cfg, w + 1) for w in range(cfg.wafers)]


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth's method (lam is small here)."""
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


# ---------------------------------------------------------------------- #
# truth queries (used by the comparison harness, never by the pipeline)
# ---------------------------------------------------------------------- #
def qubit_truth_pass(qt: QubitTruth, spec: dict) -> bool:
    """Intrinsic-truth verdict of one qubit against a spec."""
    if not qt.functional:
        return False
    return qt.t1_us >= spec["t1_min_us"] and qt.ro_err <= spec["ro_err_max"]


def die_truth_pass(die: DieTruth, spec: dict) -> bool:
    """Known-good-die truth: every qubit passes and no die-level defect."""
    return not die.defects and all(qubit_truth_pass(q, spec) for q in die.qubits)


def truth_sidecar(wafers: list) -> dict:
    """device_id -> intrinsic truth. Written NEXT TO the store, never in it."""
    out = {}
    for w in wafers:
        for d in w.dies:
            out[d.die_id] = {"die_defects": d.defects}
            for q in d.qubits:
                out[f"{d.die_id}:Q{q.q}"] = {
                    "f01_GHz": q.f01_GHz, "t1_us": q.t1_us, "t2_us": q.t2_us,
                    "ro_err": q.ro_err, "defects": q.defects,
                }
    return out
