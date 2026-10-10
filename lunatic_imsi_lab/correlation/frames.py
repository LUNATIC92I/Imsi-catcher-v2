"""Traitement tabulaire des mesures avec pandas."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from lunatic_imsi_lab.core.models import CellObservation


def to_dataframe(observations: Sequence[CellObservation]) -> pd.DataFrame:
    """Une ligne par observation ; index temporel UTC."""
    cols = ["timestamp", "cell", "technology", "mcc", "mnc", "area_code", "cell_id", "channel",
            "frequency_mhz", "rssi_dbm", "quality_db", "serving", "source", "is_simulation"]
    if not observations:
        return pd.DataFrame(columns=cols).set_index("timestamp")
    df = pd.DataFrame([{
        "timestamp": o.timestamp, "cell": o.cell_label, "technology": o.technology.value,
        "mcc": o.mcc, "mnc": o.mnc, "area_code": o.area_code, "cell_id": o.cell_id,
        "channel": o.channel, "frequency_mhz": o.frequency_mhz, "rssi_dbm": o.rssi_dbm,
        "quality_db": o.quality_db, "serving": o.serving, "source": o.provenance.label,
        "is_simulation": o.provenance.is_simulation} for o in observations])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.set_index("timestamp").sort_index()


def _energy_mean(values: pd.Series) -> float:
    """Moyenne de puissance dans le domaine linéaire (mW)."""
    v = values.dropna().to_numpy(dtype=float)
    return float(10 * np.log10(np.mean(10 ** (v / 10)))) if v.size else np.nan


def cell_statistics(observations: Sequence[CellObservation]) -> pd.DataFrame:
    """Statistiques par cellule : nombre, puissance (min / médiane / max / moyenne
    énergétique / écart-type), qualité médiane, première et dernière observation."""
    df = to_dataframe(observations)
    if df.empty:
        return pd.DataFrame()
    g = df.reset_index().groupby("cell", sort=False)
    stats = g.agg(technology=("technology", "first"), channel=("channel", "first"),
                  frequency_mhz=("frequency_mhz", "first"), count=("rssi_dbm", "size"),
                  rssi_min=("rssi_dbm", "min"), rssi_median=("rssi_dbm", "median"),
                  rssi_max=("rssi_dbm", "max"), rssi_std=("rssi_dbm", "std"),
                  quality_median=("quality_db", "median"), first_seen=("timestamp", "min"),
                  last_seen=("timestamp", "max"), serving=("serving", "sum"))
    stats["rssi_energy_mean"] = g["rssi_dbm"].apply(_energy_mean)
    return stats.sort_values("count", ascending=False)


def resample_power(observations: Sequence[CellObservation], rule: str = "5min") -> pd.DataFrame:
    """Puissance moyenne (domaine linéaire) par cellule et par intervalle de temps."""
    df = to_dataframe(observations)
    if df.empty:
        return pd.DataFrame()
    return (df.groupby("cell")["rssi_dbm"].resample(rule).apply(_energy_mean)
            .unstack(level=0).sort_index())
