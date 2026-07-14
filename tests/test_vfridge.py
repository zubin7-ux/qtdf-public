"""vfridge tests — determinism, physics sanity, truth separation, QTDF validity.

Run: python tests/test_vfridge.py
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import qtdf
from qtdf.store import Store
from qtdf.vfridge import (
    MCM_GRADE_V0,
    Cooldown,
    EmuConfig,
    MeasConfig,
    die_truth_pass,
    generate_wafer,
    qubit_truth_pass,
    truth_sidecar,
)


def _cfg(**kw) -> EmuConfig:
    base = dict(seed=7, rows=8, cols=8, qubits_per_die=4)
    base.update(kw)
    return EmuConfig(**base)


def test_determinism_same_seed_same_wafer():
    a = generate_wafer(_cfg(), 1)
    b = generate_wafer(_cfg(), 1)
    assert truth_sidecar([a]) == truth_sidecar([b])


def test_determinism_across_processes_golden():
    """Golden values pinned from a separate process. Guards against seeding
    via salted string hashes (tuple.__hash__), which is only stable within
    one process — the bug this test exists to catch."""
    w = generate_wafer(_cfg(), 1)
    q = w.dies[0].qubits[0]
    assert (q.f01_GHz, q.t1_us, q.t2_us, q.ro_err) == (4.64691, 185.53, 112.89, 0.0277), \
        (q.f01_GHz, q.t1_us, q.t2_us, q.ro_err)


def test_different_seed_different_wafer():
    a = generate_wafer(_cfg(seed=7), 1)
    b = generate_wafer(_cfg(seed=8), 1)
    assert truth_sidecar([a]) != truth_sidecar([b])


def test_t1_distribution_matches_config():
    # big wafer for statistics; no TLS/defects so the raw lognormal shows
    cfg = _cfg(rows=20, cols=20, tls_per_GHz_per_die=0.0,
               p_junction_defect=0.0, p_readout_defect=0.0)
    w = generate_wafer(cfg, 1)
    t1s = [q.t1_us for d in w.dies for q in d.qubits]
    med = statistics.median(t1s)
    assert abs(math.log(med / cfg.t1_median_us)) < 0.15, med
    sig = statistics.stdev(math.log(x) for x in t1s)
    assert abs(sig - cfg.t1_sigma_ln) < 0.12, sig


def test_defect_rates_and_labels():
    cfg = _cfg(rows=20, cols=20, p_junction_defect=0.05)
    w = generate_wafer(cfg, 1)
    qs = [q for d in w.dies for q in d.qubits]
    dead = [q for q in qs if not q.functional]
    rate = len(dead) / len(qs)
    assert 0.03 < rate < 0.07, rate                     # binomial tolerance
    assert all("junction_defect" in q.defects for q in dead)
    assert all(q.t1_us is None and q.f01_GHz is None for q in dead)
    # TLS labels exist and correspond to suppressed T1 (labeled worse on average)
    tls = [q for q in qs if "tls_coupled" in q.defects]
    clean = [q for q in qs if q.functional and not q.defects]
    if tls and clean:
        assert (statistics.median(q.t1_us for q in tls)
                < statistics.median(q.t1_us for q in clean))


def test_within_cooldown_repeats_redraw_fit_noise_only():
    cfg = _cfg(p_junction_defect=0.0, p_readout_defect=0.0)
    w = generate_wafer(cfg, 1)
    die = w.dies[0]
    qt = next(q for q in die.qubits if q.functional)
    cd = Cooldown(w, cfg, MeasConfig())
    r0, r1 = cd.measure_qubit(die, qt), cd.measure_qubit(die, qt, repeat=1)
    assert r0 != r1                                  # fit noise redraws
    assert cd.measure_qubit(die, qt) == r0           # repeat=0 stays stable
    # repeats scatter around the SAME cooldown-T1 (telegraph fixed): the
    # spread of within-cooldown repeats is fit-noise-sized, not telegraph-sized
    vals = [cd.measure_qubit(die, qt, repeat=i)["T1"] for i in range(30)]
    mean = sum(vals) / len(vals)
    spread = (sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5
    assert spread / mean < 0.12, spread / mean       # ~6% fit noise, not ~22%


def test_measurement_noise_present_and_unbiased():
    cfg = _cfg(p_junction_defect=0.0, p_readout_defect=0.0)
    w = generate_wafer(cfg, 1)
    die = w.dies[0]
    qt = next(q for q in die.qubits if q.functional)
    vals = []
    for cd_no in range(1, 41):
        cd = Cooldown(w, cfg, MeasConfig(), cooldown_no=cd_no)
        vals.append(cd.measure_qubit(die, qt)["T1"])
    assert len(set(vals)) > 1, "no noise?"
    # mean over many cooldowns near intrinsic truth (lognormal mean bias is
    # exp(sigma^2/2) ~ 2.5% at 0.22 — allow a loose band)
    mean = statistics.mean(vals)
    assert abs(math.log(mean / qt.t1_us)) < 0.20, (mean, qt.t1_us)


def test_records_valid_emulated_and_truth_free():
    cfg = _cfg(rows=3, cols=3)
    w = generate_wafer(cfg, 1)
    cd = Cooldown(w, cfg, MeasConfig())
    with tempfile.TemporaryDirectory() as d:
        st = Store(d)
        n = cd.measure_dies(st)
        assert n == 9 * cfg.qubits_per_die
        assert st.verify_all() == []
        for rec in st.query(load=True):
            assert rec["data_source"] == "emulated"
            assert rec["carrier"]["provider"] == "cassette"
            assert rec["device"]["wafer"]["lot_id"] == cfg.lot_id
            assert rec["run"]["run_id"].endswith("cd01")
            assert "truth" not in json.dumps(rec).lower().replace("truth_", "x")


def test_truth_verdicts_and_dead_die():
    cfg = _cfg(p_junction_defect=1.0)      # every junction dead
    w = generate_wafer(cfg, 1)
    assert all(not die_truth_pass(d, MCM_GRADE_V0) for d in w.dies)
    assert all(not qubit_truth_pass(q, MCM_GRADE_V0)
               for d in w.dies for q in d.qubits)


def test_fridge_bias_systematic_and_off_by_default():
    cfg = _cfg(p_junction_defect=0.0, p_readout_defect=0.0)
    w = generate_wafer(cfg, 1)
    die = w.dies[0]
    qt = next(q for q in die.qubits if q.functional)
    # default: no bias -> VF-1 and VF-2 differ only by noise draw, and a
    # zero-bias config equals the historical VF-1 stream exactly
    base = Cooldown(w, cfg, MeasConfig(), cooldown_no=1).measure_qubit(die, qt)
    again = Cooldown(w, cfg, MeasConfig(fridge_t1_bias_ln=0.0),
                     cooldown_no=1).measure_qubit(die, qt)
    assert base == again
    # with bias on, two fridges disagree SYSTEMATICALLY: the T1 ratio is the
    # same for every qubit measured (it is a fridge property, not noise)
    m = MeasConfig(fridge_t1_bias_ln=0.3, t1_rel_err=0.0, fluct_sigma_ln=0.0)
    cda = Cooldown(w, cfg, m, cooldown_no=1, fridge_id="VF-A")
    cdb = Cooldown(w, cfg, m, cooldown_no=1, fridge_id="VF-B")
    ratios = set()
    for d in w.dies[:4]:
        for q in d.qubits:
            ta = cda.measure_qubit(d, q)["T1"]
            tb = cdb.measure_qubit(d, q)["T1"]
            ratios.add(round(ta / tb, 3))
    assert len(ratios) == 1 and 1.0 not in ratios


def test_calibration_file_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "cal.json")
        with open(path, "w") as fh:
            json.dump({"t1_median_us": 314.0, "ro_err_median": 0.005}, fh)
        cfg = EmuConfig.from_calibration(path, seed=1)
        assert cfg.t1_median_us == 314.0 and cfg.ro_err_median == 0.005
        # explicit override beats the calibration file
        cfg2 = EmuConfig.from_calibration(path, seed=1, t1_median_us=99.0)
        assert cfg2.t1_median_us == 99.0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
