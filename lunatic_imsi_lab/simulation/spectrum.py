"""Spectres synthétiques reproductibles (aucune émission radio)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

from lunatic_imsi_lab.core.models import Provenance, SpectrumSweep


@dataclass
class SimEmitter:
    center_hz: float
    bandwidth_hz: float
    power_dbm: float               # puissance par bin au centre
    start_step: int = 0
    stop_step: int | None = None   # None = toujours présent
    jump_db: float = 0.0           # saut de puissance appliqué...
    jump_every: int = 0            # ...tous les N pas (0 = jamais)
    jump_window: tuple[int, int] | None = None
    label: str = ""

    def active(self, step: int) -> bool:
        return step >= self.start_step and (self.stop_step is None or step < self.stop_step)

    def level(self, step: int) -> float:
        lvl = self.power_dbm
        in_window = self.jump_window is None or self.jump_window[0] <= step < self.jump_window[1]
        if self.jump_every and in_window and step % self.jump_every == 0:
            lvl += self.jump_db
        return lvl


@dataclass
class SpectrumScenario:
    emitters: list[SimEmitter]
    noise_dbm: float = -100.0
    noise_std_db: float = 1.0
    seed: int = 7
    start: datetime = field(default_factory=lambda: datetime(2026, 1, 15, 8, 0,
                                                             tzinfo=timezone.utc))
    step_s: float = 10.0
    name: str = "default"

    def __post_init__(self) -> None:
        self._rng = np.random.default_rng(self.seed)

    @classmethod
    def default(cls, seed: int = 7) -> "SpectrumScenario":
        """Bande 1800 MHz (DL) : trois porteuses LTE stables, deux porteuses GSM."""
        return cls(emitters=[
            SimEmitter(1815e6, 10e6, -62, label="LTE 10 MHz"),
            SimEmitter(1840e6, 20e6, -66, label="LTE 20 MHz"),
            SimEmitter(1862.5e6, 5e6, -70, label="LTE 5 MHz"),
            SimEmitter(1870.2e6, 200e3, -58, label="GSM"),
            SimEmitter(1872.4e6, 200e3, -61, label="GSM"),
        ], seed=seed, name="default")

    @classmethod
    def with_anomaly(cls, seed: int = 7) -> "SpectrumScenario":
        sc = cls.default(seed)
        sc.name = "anomaly"
        sc.emitters.append(SimEmitter(1876.8e6, 200e3, -60, start_step=20, stop_step=40,
                                      label="porteuse 2G apparaissant (synthétique)"))
        sc.emitters[3].jump_db = 15.0
        sc.emitters[3].jump_every = 3
        sc.emitters[3].jump_window = (25, 40)
        return sc

    def sweep(self, step: int, start_hz: float = 1805e6, stop_hz: float = 1880e6,
              bin_hz: float = 25e3) -> SpectrumSweep:
        f = np.arange(start_hz, stop_hz, bin_hz)
        lin = np.power(10.0, (self.noise_dbm + self._rng.normal(0, self.noise_std_db, f.size))
                       / 10.0)
        for e in self.emitters:
            if not e.active(step):
                continue
            half = e.bandwidth_hz / 2
            # Gabarit trapézoïdal (flancs de 5 % de la largeur) — profil OFDM/GMSK simplifié.
            edge = max(e.bandwidth_hz * 0.05, bin_hz)
            shape = np.clip((half + edge - np.abs(f - e.center_hz)) / edge, 0, 1)
            if not np.any(shape):
                continue
            lvl = e.level(step) + self._rng.normal(0, 0.7)
            lin += shape * np.power(10.0, lvl / 10.0)
        prov = Provenance("SIMULATION", "synthetic-spectrum", True,
                          {"scenario": self.name, "seed": self.seed, "step": step,
                           "bin_hz": bin_hz})
        return SpectrumSweep(timestamp=self.start + timedelta(seconds=step * self.step_s),
                             frequencies_hz=f, power_dbm=10 * np.log10(lin), provenance=prov,
                             rbw_hz=bin_hz)

    def series(self, n: int, **kw) -> list[SpectrumSweep]:
        return [self.sweep(i, **kw) for i in range(n)]
