"""Minimal Touchstone (.s2p) reader + S-parameter helpers, stdlib only.

Enough to ingest a QTDF RF record without pulling scikit-rf into the executive.
Supports the RI (real/imaginary) format written by skrf, with a GHz frequency
axis and a 50 ohm reference — which is what ENG-RF-002 emits. Falls back
loudly on formats it does not implement rather than guessing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Touchstone:
    freq_hz: list[float]
    # complex S-params as (re, im) tuples, keyed "s11","s21","s12","s22"
    s: dict[str, list[tuple[float, float]]]
    z0: float
    path: str

    def db(self, param: str) -> list[float]:
        """20*log10|S| for a given param over the whole sweep."""
        return [20.0 * math.log10(math.hypot(re, im)) if (re or im) else -999.0
                for re, im in self.s[param]]

    def db_at(self, param: str, freq_hz: float) -> float:
        """Linearly interpolated |S|_dB at a frequency (extrapolation clamps)."""
        f, y = self.freq_hz, self.db(param)
        if freq_hz <= f[0]:
            return y[0]
        if freq_hz >= f[-1]:
            return y[-1]
        for k in range(1, len(f)):
            if f[k] >= freq_hz:
                t = (freq_hz - f[k - 1]) / (f[k] - f[k - 1])
                return y[k - 1] + t * (y[k] - y[k - 1])
        return y[-1]

    def matched_bands_hz(self, param: str, thresh_db: float) -> list[tuple[float, float]]:
        """All contiguous [f_lo, f_hi] spans where |S|<=thresh_db.

        Returns a list because a real launch is often multi-lobed — reporting
        only first-to-last crossing hides in-band gaps. Empty list if never met.
        """
        y = self.db(param)
        f = self.freq_hz
        bands: list[tuple[float, float]] = []
        start: float | None = None
        for k in range(len(y)):
            if y[k] <= thresh_db and start is None:
                start = f[k]
            elif y[k] > thresh_db and start is not None:
                bands.append((start, f[k - 1]))
                start = None
        if start is not None:
            bands.append((start, f[-1]))
        return bands

    def matched_band_hz(self, param: str, thresh_db: float) -> tuple[float, float] | None:
        """The single contiguous span containing the deepest dip (or None)."""
        y = self.db(param)
        i_min = min(range(len(y)), key=lambda k: y[k])
        if y[i_min] > thresh_db:
            return None
        for lo, hi in self.matched_bands_hz(param, thresh_db):
            if lo <= self.freq_hz[i_min] <= hi:
                return (lo, hi)
        return None


_UNIT = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9}


def read_s2p(path: str) -> Touchstone:
    """Parse a 2-port RI Touchstone file. Raises on unsupported option lines."""
    freq_scale = 1e9  # default GHz
    fmt = "ri"
    z0 = 50.0
    freq_hz: list[float] = []
    s = {"s11": [], "s21": [], "s12": [], "s22": []}

    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("!"):
                continue
            if line.startswith("#"):
                toks = line[1:].lower().split()
                # e.g.  GHz S RI R 50.0
                if toks and toks[0] in _UNIT:
                    freq_scale = _UNIT[toks[0]]
                if "ri" in toks:
                    fmt = "ri"
                elif "ma" in toks or "db" in toks:
                    fmt = "ma" if "ma" in toks else "db"
                if "r" in toks:
                    z0 = float(toks[toks.index("r") + 1])
                continue
            parts = [float(x) for x in line.split()]
            # freq + 8 columns (4 complex params)
            if len(parts) < 9:
                raise ValueError(f"{path}: expected 9 columns for a 2-port row, got {len(parts)}")
            freq_hz.append(parts[0] * freq_scale)
            cols = parts[1:9]
            pairs = [(cols[i], cols[i + 1]) for i in range(0, 8, 2)]
            if fmt != "ri":
                raise NotImplementedError(f"{path}: only RI format is supported (got {fmt})")
            # Touchstone 2-port order: S11 S21 S12 S22
            for key, pair in zip(("s11", "s21", "s12", "s22"), pairs):
                s[key].append(pair)

    if not freq_hz:
        raise ValueError(f"{path}: no data rows found")
    return Touchstone(freq_hz=freq_hz, s=s, z0=z0, path=path)
