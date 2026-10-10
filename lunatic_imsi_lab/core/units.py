"""Calculs de puissance et conversions canal ↔ fréquence.

Toutes les moyennes de puissance sont effectuées dans le domaine linéaire (mW)
et non en dB, ce qui est une erreur classique dans les outils d'analyse.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np

from lunatic_imsi_lab.core.models import Technology


# ---------------------------------------------------------------------------
# Puissance
# ---------------------------------------------------------------------------

def dbm_to_mw(dbm: float | np.ndarray) -> float | np.ndarray:
    return np.power(10.0, np.asarray(dbm, dtype=float) / 10.0) if isinstance(dbm, np.ndarray) \
        else 10.0 ** (float(dbm) / 10.0)


def mw_to_dbm(mw: float | np.ndarray) -> float | np.ndarray:
    arr = np.asarray(mw, dtype=float)
    if np.any(arr <= 0):
        raise ValueError("la puissance linéaire doit être strictement positive")
    out = 10.0 * np.log10(arr)
    return out if isinstance(mw, np.ndarray) else float(out)


def watts_to_dbm(watts: float) -> float:
    return mw_to_dbm(watts * 1000.0)


def mean_power_dbm(values_dbm: Iterable[float]) -> float:
    """Moyenne énergétique (linéaire) d'une série de puissances en dBm."""
    arr = np.asarray([v for v in values_dbm if v is not None], dtype=float)
    if arr.size == 0:
        raise ValueError("aucune valeur de puissance")
    return float(10.0 * np.log10(np.mean(np.power(10.0, arr / 10.0))))


def channel_power_dbm(power_dbm_bins: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Puissance totale d'un canal = somme linéaire des bins (dBm/bin)."""
    bins = np.asarray(power_dbm_bins, dtype=float)
    if mask is not None:
        bins = bins[np.asarray(mask, dtype=bool)]
    if bins.size == 0:
        raise ValueError("aucun bin dans le canal")
    return float(10.0 * np.log10(np.sum(np.power(10.0, bins / 10.0))))


def noise_floor_dbm(power_dbm_bins: np.ndarray, percentile: float = 50.0) -> float:
    """Estimation robuste du plancher de bruit (percentile, médiane par défaut)."""
    return float(np.percentile(np.asarray(power_dbm_bins, dtype=float), percentile))


def snr_db(signal_dbm: float, noise_dbm: float) -> float:
    return float(signal_dbm - noise_dbm)


def thermal_noise_dbm(bandwidth_hz: float, noise_figure_db: float = 0.0,
                      temperature_k: float = 290.0) -> float:
    """Bruit thermique kTB (+ facteur de bruit) en dBm."""
    if bandwidth_hz <= 0:
        raise ValueError("bande passante invalide")
    k = 1.380649e-23
    return float(10 * np.log10(k * temperature_k * bandwidth_hz * 1000.0) + noise_figure_db)


# ---------------------------------------------------------------------------
# Canaux → fréquences descendantes (DL)
# ---------------------------------------------------------------------------

# Bandes LTE usuelles : bande -> (F_DL_low MHz, N_offs_DL, N_min, N_max)
LTE_BANDS: dict[int, tuple[float, int, int, int]] = {
    1: (2110.0, 0, 0, 599),
    2: (1930.0, 600, 600, 1199),
    3: (1805.0, 1200, 1200, 1949),
    4: (2110.0, 1950, 1950, 2399),
    5: (869.0, 2400, 2400, 2649),
    7: (2620.0, 2750, 2750, 3449),
    8: (925.0, 3450, 3450, 3799),
    12: (729.0, 5010, 5010, 5179),
    13: (746.0, 5180, 5180, 5279),
    20: (791.0, 6150, 6150, 6449),
    28: (758.0, 9210, 9210, 9659),
    38: (2570.0, 37750, 37750, 38249),
    40: (2300.0, 38650, 38650, 39649),
    41: (2496.0, 39650, 39650, 41589),
}


def lte_band_for_earfcn(earfcn: int) -> int | None:
    for band, (_, _, nmin, nmax) in LTE_BANDS.items():
        if nmin <= earfcn <= nmax:
            return band
    return None


def earfcn_to_mhz(earfcn: int) -> float:
    band = lte_band_for_earfcn(earfcn)
    if band is None:
        raise ValueError(f"EARFCN {earfcn} hors des bandes prises en charge")
    f_low, n_offs, _, _ = LTE_BANDS[band]
    return round(f_low + 0.1 * (earfcn - n_offs), 3)


def gsm_arfcn_to_mhz(arfcn: int, pcs1900: bool = False) -> float:
    """Fréquence descendante GSM. Les ARFCN 512-810 sont ambigus (DCS/PCS) :
    DCS 1800 est retenu par défaut, sauf si ``pcs1900`` est vrai."""
    if 1 <= arfcn <= 124:
        return round(935.0 + 0.2 * arfcn, 3)
    if arfcn == 0:
        return 935.0
    if 975 <= arfcn <= 1023:
        return round(935.0 + 0.2 * (arfcn - 1024), 3)
    if 128 <= arfcn <= 251:
        return round(869.2 + 0.2 * (arfcn - 128), 3)
    if 512 <= arfcn <= 810 and pcs1900:
        return round(1930.2 + 0.2 * (arfcn - 512), 3)
    if 512 <= arfcn <= 885:
        return round(1805.2 + 0.2 * (arfcn - 512), 3)
    raise ValueError(f"ARFCN GSM {arfcn} non pris en charge")


def uarfcn_to_mhz(uarfcn: int) -> float:
    """UARFCN DL (bandes sans décalage : I, II-plage générale, VIII...)."""
    if not 0 <= uarfcn <= 16383:
        raise ValueError(f"UARFCN {uarfcn} invalide")
    return round(uarfcn * 0.2, 3)


def nrarfcn_to_mhz(nrarfcn: int) -> float:
    """Raster de fréquence global NR (3GPP TS 38.104 §5.4.2.1)."""
    if 0 <= nrarfcn < 600000:
        return round(0.005 * nrarfcn, 3)
    if 600000 <= nrarfcn < 2016667:
        return round(3000.0 + 0.015 * (nrarfcn - 600000), 3)
    if 2016667 <= nrarfcn <= 3279165:
        return round(24250.08 + 0.06 * (nrarfcn - 2016667), 3)
    raise ValueError(f"NR-ARFCN {nrarfcn} invalide")


def channel_to_mhz(technology: Technology, channel: int | None) -> float | None:
    """Conversion générique ; renvoie ``None`` si la conversion est impossible."""
    if channel is None:
        return None
    try:
        if technology == Technology.GSM:
            return gsm_arfcn_to_mhz(channel)
        if technology == Technology.UMTS:
            return uarfcn_to_mhz(channel)
        if technology == Technology.LTE:
            return earfcn_to_mhz(channel)
        if technology == Technology.NR:
            return nrarfcn_to_mhz(channel)
    except ValueError:
        return None
    return None
