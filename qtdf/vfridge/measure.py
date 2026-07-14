"""Virtual cooldown — measurement of a truth wafer, emitting QTDF records.

This is the boundary a real fridge would occupy. It adds the two effects that
make screening statistically hard (and escape/overkill nonzero):

  1. cooldown-to-cooldown fluctuation: TLS reconfigure on thermal cycle, so a
     qubit's effective T1 this cooldown differs from its intrinsic value
     (lognormal factor, per qubit per cooldown);
  2. measurement noise: T1/T2 fit uncertainty (relative gaussian), readout
     error estimated from a finite number of shots (binomial), frequency
     essentially exact (sub-MHz).

Records carry data_source='emulated', carrier.provider='cassette' (socket
assigned at load), a run block per cooldown — and NO truth fields. Truth stays
in the sidecar; the pipeline cannot cheat.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

import qtdf

from .wafer import DieTruth, EmuConfig, QubitTruth, WaferTruth, stable_seed


@dataclass
class MeasConfig:
    shots_ro: int = 2000
    t1_rel_err: float = 0.06
    t2_rel_err: float = 0.08
    f_err_MHz: float = 0.2
    fluct_sigma_ln: float = 0.22     # TLS telegraph between cooldowns
    # systematic per-fridge calibration bias (0.0 = ideal identical fridges);
    # a fridge's bias is a stable property of its fridge_id
    fridge_t1_bias_ln: float = 0.0
    fridge_ro_bias_ln: float = 0.0


# demonstration MCM-grade screen spec (module builders want top-bin dies)
MCM_GRADE_V0 = {"spec_id": "MCM-GRADE-v0", "t1_min_us": 150.0, "ro_err_max": 0.02}


class Cooldown:
    """One thermal cycle of a set of dies loaded into cassette sockets."""

    def __init__(self, wafer: WaferTruth, cfg: EmuConfig, meas: MeasConfig,
                 cooldown_no: int = 1, fridge_id: str = "VF-1"):
        self.wafer = wafer
        self.cfg = cfg
        self.meas = meas
        self.cooldown_no = cooldown_no
        self.fridge_id = fridge_id
        self.run_id = f"emu:{wafer.lot_id}:{wafer.wafer_id}:cd{cooldown_no:02d}"
        m = meas or MeasConfig()
        self._t1_bias = (random.Random(stable_seed("fridge-bias", fridge_id, "t1"))
                         .lognormvariate(0.0, m.fridge_t1_bias_ln)
                         if m.fridge_t1_bias_ln else 1.0)
        self._ro_bias = (random.Random(stable_seed("fridge-bias", fridge_id, "ro"))
                         .lognormvariate(0.0, m.fridge_ro_bias_ln)
                         if m.fridge_ro_bias_ln else 1.0)
        # per-qubit T1 fluctuation factor, fixed for the whole cooldown.
        # Drawn per-qubit from a stable per-qubit seed (NOT from a shared
        # stream) so the factor is independent of which dies get measured.
        self._fluct = {}
        for d in wafer.dies:
            for q in d.qubits:
                r = random.Random(stable_seed(cfg.seed, self.run_id, d.die_id, q.q))
                self._fluct[(d.die_id, q.q)] = r.lognormvariate(0.0, meas.fluct_sigma_ln)

    # ------------------------------------------------------------------ #
    def measure_qubit(self, die: DieTruth, qt: QubitTruth, repeat: int = 0) -> dict:
        """Measured values this cooldown (None everywhere for a dead qubit).

        Noise is drawn from a stable per-(cooldown, die, qubit, repeat) seed,
        so the result is independent of measurement order and batch
        composition — different policies testing the same die in the same
        cooldown see identical data (fair comparison).

        ``repeat`` distinguishes REmeasurements within one cooldown: the
        TLS-telegraph fluctuation stays fixed (it is a cooldown property) but
        fit/shot noise redraws. This is what a gauge-R&R repeatability study
        needs — across-cooldown 'repeats' would confound gauge noise with the
        device's own telegraph. repeat=0 preserves the historical seed.
        """
        if not qt.functional:
            return {"f_01": None, "T1": None, "T2": None, "readout_error": None}
        parts = (self.cfg.seed, self.run_id, die.die_id, qt.q, "meas")
        if repeat:
            parts += (repeat,)
        if self.fridge_id != "VF-1":       # VF-1 keeps the historical stream
            parts += (self.fridge_id,)
        rng = random.Random(stable_seed(*parts))
        t1_cd = qt.t1_us * self._fluct[(die.die_id, qt.q)] * self._t1_bias
        t2_cd = min(qt.t2_us, 2.0 * t1_cd)
        ro_eff = min(qt.ro_err * self._ro_bias, 0.5)
        k = self.meas.shots_ro
        return {
            "f_01": round(qt.f01_GHz + rng.gauss(0.0, self.meas.f_err_MHz / 1000.0), 6),
            "T1": round(max(t1_cd * (1.0 + rng.gauss(0.0, self.meas.t1_rel_err)), 0.1), 2),
            "T2": round(max(t2_cd * (1.0 + rng.gauss(0.0, self.meas.t2_rel_err)), 0.1), 2),
            "readout_error": round(_binom(rng, k, ro_eff) / k, 5),
        }

    # ------------------------------------------------------------------ #
    def record(self, die: DieTruth, qt: QubitTruth, socket: str,
               spec: dict = MCM_GRADE_V0) -> dict:
        m = self.measure_qubit(die, qt)
        t1_ok = m["T1"] >= spec["t1_min_us"] if m["T1"] is not None else None
        ro_ok = m["readout_error"] <= spec["ro_err_max"] if m["readout_error"] is not None else None

        if m["T1"] is None:
            verdict, binno, reason = "fail", 5, "no qubit response (nonfunctional)"
        elif t1_ok and ro_ok:
            verdict, binno, reason = "pass", 1, None
        elif not t1_ok and ro_ok:
            verdict, binno, reason = "fail", 2, None
        elif t1_ok and not ro_ok:
            verdict, binno, reason = "fail", 3, None
        else:
            verdict, binno, reason = "fail", 4, None

        def meas_entry(quantity, value, unit, limit=None, ok=None):
            e = {"quantity": quantity, "symbol": quantity, "value": value,
                 "unit": unit, "limit": limit if value is not None else None,
                 "pass": ok if value is not None else None}
            return e

        return {
            "qtdf_version": qtdf.QTDF_VERSION,
            "record_id": qtdf.new_record_id(),
            "record_type": "qubit_coherence_screen",
            "data_source": "emulated",
            "device": {
                "device_id": f"{die.die_id}:Q{qt.q}",
                "part_number": "EMU-TRANSMON-4Q",
                "description": f"virtual transmon {qt.q} on die {die.die_id}",
                "wafer": {"lot_id": self.wafer.lot_id, "wafer_id": self.wafer.wafer_id,
                          "die_x": die.die_x, "die_y": die.die_y},
                "genealogy": {"vendor": "vfridge", "chip": die.die_id},
            },
            "carrier": {
                "provider": "cassette",
                "carrier_part": "CAS-400",
                "socket": socket,
                "rf_environment_qualified": True,
            },
            "fixture": {
                "fridge_id": self.fridge_id,
                "temperature_K": 0.012,
                "note": "virtual dilution refrigerator (vfridge emulator)",
            },
            "test": {
                "test_plan": f"coherence screen vs {spec['spec_id']}",
                "executive": "vfridge.measure.Cooldown",
                "band_GHz": None,
                "operator": "EMU",
            },
            "calibration": {
                "reference_impedance_ohm": 50.0,
                "loopback_standards": ["ENG-RF-001_GSG.s2p"],
                "note": "cassette loopback socket self-test assumed nominal",
            },
            "run": {"run_id": self.run_id,
                    "cooldown_id": f"cd{self.cooldown_no:02d}",
                    "plan_hash": None},
            "measurements": [
                meas_entry("T1", m["T1"], "us",
                           {"op": ">=", "value": spec["t1_min_us"]}, t1_ok),
                meas_entry("T2", m["T2"], "us"),
                meas_entry("f_01", m["f_01"], "GHz"),
                meas_entry("readout_error", m["readout_error"], "1",
                           {"op": "<=", "value": spec["ro_err_max"]}, ro_ok),
            ],
            "disposition": {
                "verdict": verdict, "bin": binno, "override": False, "reason": reason,
                "rules": [
                    {"rule_id": f"{spec['spec_id']}:T1", "quantity": "T1",
                     "limit": {"op": ">=", "value": spec["t1_min_us"]},
                     "result": "pass" if t1_ok else "fail"},
                    {"rule_id": f"{spec['spec_id']}:RO", "quantity": "readout_error",
                     "limit": {"op": "<=", "value": spec["ro_err_max"]},
                     "result": "pass" if ro_ok else "fail"},
                ],
                "reference": f"{spec['spec_id']} demonstration MCM screen spec",
            },
            "provenance": {
                "generated_at": qtdf.utc_now(),
                "tool": "vfridge",
                "tool_method": "emulated cooldown measurement",
                "generator": "vfridge/measure.py",
                "qtdf_library_version": qtdf.QTDF_VERSION,
            },
        }

    # ------------------------------------------------------------------ #
    def measure_dies(self, store, dies=None, spec: dict = MCM_GRADE_V0) -> int:
        """Measure dies (default: whole wafer) into a store. Returns #records."""
        n = 0
        for i, die in enumerate(dies if dies is not None else self.wafer.dies):
            socket = f"S{i % 24 + 1:02d}"      # 24-socket cassette, batches cycle
            for qt in die.qubits:
                store.add(self.record(die, qt, socket, spec))
                n += 1
        return n


def _binom(rng: random.Random, n: int, p: float) -> int:
    """Binomial draw via normal approximation (n*p >> 1 here), clamped."""
    mu, sd = n * p, (n * p * (1.0 - p)) ** 0.5
    return min(max(int(round(rng.gauss(mu, sd))), 0), n)
