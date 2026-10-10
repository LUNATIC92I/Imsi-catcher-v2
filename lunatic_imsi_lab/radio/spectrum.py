"""Analyse spectrale de mesures de puissance (aucun décodage de contenu).

Le moteur travaille uniquement sur des densités de puissance : il identifie
des émissions (fréquence centrale, largeur occupée, puissance), compare des
balayages successifs et détecte des variations temporelles inhabituelles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

import numpy as np
from scipy import ndimage

from lunatic_imsi_lab.config import Band
from lunatic_imsi_lab.core.models import SpectrumSweep
from lunatic_imsi_lab.core.units import channel_power_dbm, noise_floor_dbm


@dataclass
class Emission:
    center_hz: float
    bandwidth_hz: float
    peak_dbm: float
    channel_power_dbm: float
    snr_db: float
    start_hz: float
    stop_hz: float
    band: str | None = None

    @property
    def center_mhz(self) -> float:
        return self.center_hz / 1e6


@dataclass
class SweepComparison:
    max_increase_db: float
    max_decrease_db: float
    mean_abs_delta_db: float
    new_emissions: list[Emission] = field(default_factory=list)
    lost_emissions: list[Emission] = field(default_factory=list)
    changed_emissions: list[tuple[Emission, Emission, float]] = field(default_factory=list)


@dataclass
class PowerVariation:
    timestamp: datetime
    center_hz: float
    power_dbm: float
    baseline_dbm: float
    zscore: float
    delta_db: float


def detect_emissions(sweep: SpectrumSweep, threshold_db: float = 10.0,
                     min_bandwidth_hz: float = 50e3, smooth_bins: int = 3,
                     bands: Sequence[Band] | None = None,
                     noise_percentile: float = 10.0) -> list[Emission]:
    """Détecte les zones contiguës dépassant le plancher de bruit de ``threshold_db``.

    Le plancher est estimé par un bas percentile (10 % par défaut) : dans une
    bande cellulaire, les porteuses peuvent occuper plus de la moitié du
    spectre, la médiane n'est alors plus représentative du bruit."""
    f, p = sweep.frequencies_hz, sweep.power_dbm
    floor = noise_floor_dbm(p, noise_percentile)
    smoothed = ndimage.median_filter(p, size=max(1, smooth_bins), mode="nearest")
    labels, n = ndimage.label(smoothed > floor + threshold_db)
    bin_hz = float(np.median(np.diff(f)))
    out: list[Emission] = []
    for idx in range(1, n + 1):
        mask = labels == idx
        sel_f, sel_p = f[mask], p[mask]
        bw = sel_f[-1] - sel_f[0] + bin_hz
        if bw < min_bandwidth_hz:
            continue
        lin = np.power(10.0, sel_p / 10.0)
        center = float(np.sum(sel_f * lin) / np.sum(lin))   # centroïde énergétique
        peak = float(np.max(sel_p))
        band = None
        if bands:
            b = next((b for b in bands if b.contains(center / 1e6)), None)
            band = b.name if b else None
        out.append(Emission(center_hz=center, bandwidth_hz=float(bw), peak_dbm=peak,
                            channel_power_dbm=channel_power_dbm(sel_p), snr_db=peak - floor,
                            start_hz=float(sel_f[0]), stop_hz=float(sel_f[-1]), band=band))
    return out


def _on_grid(ref: SpectrumSweep, other: SpectrumSweep) -> np.ndarray:
    if ref.frequencies_hz.shape == other.frequencies_hz.shape and np.allclose(
            ref.frequencies_hz, other.frequencies_hz):
        return other.power_dbm
    lo = max(ref.start_hz, other.start_hz)
    hi = min(ref.stop_hz, other.stop_hz)
    if lo >= hi:
        raise ValueError("les balayages ne se recouvrent pas")
    return np.interp(ref.frequencies_hz, other.frequencies_hz, other.power_dbm,
                     left=np.nan, right=np.nan)


def _match(a: Emission, candidates: list[Emission]) -> Emission | None:
    for c in candidates:
        if abs(c.center_hz - a.center_hz) <= max(a.bandwidth_hz, c.bandwidth_hz) / 2:
            return c
    return None


def compare_sweeps(before: SpectrumSweep, after: SpectrumSweep, threshold_db: float = 10.0,
                   change_db: float = 6.0) -> SweepComparison:
    """Compare deux balayages (le second est rééchantillonné si besoin)."""
    p_after = _on_grid(before, after)
    delta = p_after - before.power_dbm
    valid = ~np.isnan(delta)
    if not np.any(valid):
        raise ValueError("aucun point commun entre les balayages")
    d = delta[valid]
    em_before = detect_emissions(before, threshold_db)
    em_after = detect_emissions(after, threshold_db)
    cmp = SweepComparison(max_increase_db=float(np.max(d)), max_decrease_db=float(np.min(d)),
                          mean_abs_delta_db=float(np.mean(np.abs(d))))
    for e in em_after:
        m = _match(e, em_before)
        if m is None:
            cmp.new_emissions.append(e)
        elif abs(e.channel_power_dbm - m.channel_power_dbm) >= change_db:
            cmp.changed_emissions.append((m, e, e.channel_power_dbm - m.channel_power_dbm))
    for e in em_before:
        if _match(e, em_after) is None:
            cmp.lost_emissions.append(e)
    return cmp


def waterfall(sweeps: Sequence[SpectrumSweep]) -> tuple[np.ndarray, np.ndarray, list[datetime]]:
    """Matrice temps × fréquence sur la grille du premier balayage."""
    if not sweeps:
        raise ValueError("aucun balayage")
    ref = sweeps[0]
    rows = [ref.power_dbm] + [_on_grid(ref, s) for s in sweeps[1:]]
    return ref.frequencies_hz, np.vstack(rows), [s.timestamp for s in sweeps]


def band_power_series(sweeps: Sequence[SpectrumSweep], start_hz: float,
                      stop_hz: float) -> np.ndarray:
    """Puissance intégrée d'une plage de fréquences pour chaque balayage."""
    out = []
    for s in sweeps:
        mask = (s.frequencies_hz >= start_hz) & (s.frequencies_hz <= stop_hz)
        out.append(channel_power_dbm(s.power_dbm, mask) if np.any(mask) else np.nan)
    return np.asarray(out, dtype=float)


def robust_zscores(values: np.ndarray) -> np.ndarray:
    """z-score robuste (médiane / MAD). Les séries constantes donnent 0."""
    v = np.asarray(values, dtype=float)
    med = np.nanmedian(v)
    mad = np.nanmedian(np.abs(v - med)) * 1.4826
    if not np.isfinite(mad) or mad < 1e-9:
        return np.zeros_like(v)
    return (v - med) / mad


def detect_power_variations(sweeps: Sequence[SpectrumSweep], threshold_db: float = 10.0,
                            z_threshold: float = 4.0, min_delta_db: float = 6.0,
                            min_sweeps: int = 5) -> list[PowerVariation]:
    """Variations de puissance inhabituelles par émission, dans le temps.

    Nécessite au moins ``min_sweeps`` balayages ; sinon la liste est vide (les
    données sont insuffisantes pour établir une référence)."""
    if len(sweeps) < min_sweeps:
        return []
    # Union des émissions observées sur la période.
    emissions: list[Emission] = []
    for s in sweeps:
        for e in detect_emissions(s, threshold_db):
            if _match(e, emissions) is None:
                emissions.append(e)
    results: list[PowerVariation] = []
    for e in emissions:
        series = band_power_series(sweeps, e.start_hz, e.stop_hz)
        z = robust_zscores(series)
        base = float(np.nanmedian(series))
        for i, s in enumerate(sweeps):
            delta = series[i] - base
            if abs(z[i]) >= z_threshold and abs(delta) >= min_delta_db:
                results.append(PowerVariation(timestamp=s.timestamp, center_hz=e.center_hz,
                                              power_dbm=float(series[i]), baseline_dbm=base,
                                              zscore=float(z[i]), delta_db=float(delta)))
    return results
