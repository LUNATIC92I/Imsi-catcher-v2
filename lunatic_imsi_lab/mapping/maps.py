"""Cartographie hors ligne des points de mesure.

Les points représentés sont exclusivement les positions **de l'équipement de
mesure** au moment de chaque observation. Le module ne calcule aucune
position de téléphone tiers et ne permet aucun suivi de personnes.

Rendu : projection locale équirectangulaire (en km) dessinée avec
Matplotlib — aucun fond de carte ni service en ligne requis. Un export
GeoJSON permet l'ouverture dans un SIG hors ligne (QGIS...).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from lunatic_imsi_lab.core.models import Alert, CellObservation, PositionKind


@dataclass
class MapPoint:
    latitude: float
    longitude: float
    timestamp: datetime
    rssi_dbm: float | None
    kind: PositionKind
    cell_label: str
    alert_ids: list[str]
    is_simulation: bool
    observation_id: str


def prepare_points(observations: Sequence[CellObservation], alerts: Sequence[Alert] = (),
                   serving_only: bool = True) -> list[MapPoint]:
    by_obs: dict[str, list[str]] = {}
    for a in alerts:
        for oid in a.observation_ids:
            by_obs.setdefault(oid, []).append(a.alert_id)
    pts = []
    for o in observations:
        if not o.has_position or (serving_only and not o.serving and o.id not in by_obs):
            continue
        pts.append(MapPoint(o.latitude, o.longitude, o.timestamp, o.rssi_dbm, o.position_kind,
                            o.cell_label, by_obs.get(o.id, []), o.provenance.is_simulation, o.id))
    return pts


def to_local_km(points: Sequence[MapPoint]) -> tuple[list[float], list[float], float, float]:
    """Projection locale autour du barycentre : renvoie x(est), y(nord) en km."""
    if not points:
        return [], [], 0.0, 0.0
    lat0 = sum(p.latitude for p in points) / len(points)
    lon0 = sum(p.longitude for p in points) / len(points)
    kx = 111.320 * math.cos(math.radians(lat0))
    xs = [(p.longitude - lon0) * kx for p in points]
    ys = [(p.latitude - lat0) * 110.574 for p in points]
    return xs, ys, lat0, lon0


def render_map(ax, points: Sequence[MapPoint], title: str = "Points de mesure") -> None:
    """Dessine la carte sur un axe Matplotlib (utilisé par l'IHM et les rapports)."""
    ax.clear()
    if not points:
        ax.text(0.5, 0.5, "Aucune position disponible", ha="center", va="center",
                transform=ax.transAxes, color="#9aa4b2")
        ax.set_title(title)
        return
    xs, ys, lat0, lon0 = to_local_km(points)
    vals = [p.rssi_dbm if p.rssi_dbm is not None else -120 for p in points]
    gps = [i for i, p in enumerate(points) if p.kind == PositionKind.GPS]
    est = [i for i, p in enumerate(points) if p.kind != PositionKind.GPS]
    sc = None
    if gps:
        sc = ax.scatter([xs[i] for i in gps], [ys[i] for i in gps], c=[vals[i] for i in gps],
                        cmap="viridis", vmin=-120, vmax=-40, s=18, marker="o",
                        label="Position GPS mesurée")
    if est:
        sc2 = ax.scatter([xs[i] for i in est], [ys[i] for i in est], c=[vals[i] for i in est],
                         cmap="viridis", vmin=-120, vmax=-40, s=40, marker="^",
                         edgecolors="#ff9f1c", linewidths=1.0, label="Position estimée")
        sc = sc or sc2
    al = [i for i, p in enumerate(points) if p.alert_ids]
    if al:
        ax.scatter([xs[i] for i in al], [ys[i] for i in al], s=110, facecolors="none",
                   edgecolors="#ff4d6d", linewidths=1.4, label="Point lié à une alerte")
    if sc is not None:
        cb = ax.figure.colorbar(sc, ax=ax, fraction=0.04, pad=0.02)
        cb.set_label("Niveau de signal (dBm)")
    ax.set_xlabel(f"Est (km) — origine {lat0:.5f}, {lon0:.5f}")
    ax.set_ylabel("Nord (km)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=0.25)
    if any(p.is_simulation for p in points):
        title = f"[SIMULATION] {title}"
    ax.set_title(title)
    ax.legend(loc="upper right", fontsize=7)


def to_geojson(points: Sequence[MapPoint]) -> dict:
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [p.longitude, p.latitude]},
        "properties": {"timestamp": p.timestamp.isoformat(), "rssi_dbm": p.rssi_dbm,
                       "position_kind": p.kind.value, "cell": p.cell_label,
                       "alerts": p.alert_ids, "is_simulation": p.is_simulation,
                       "observation_id": p.observation_id}} for p in points]}


def export_geojson(path: str | Path, points: Sequence[MapPoint]) -> Path:
    p = Path(path)
    p.write_text(json.dumps(to_geojson(points), indent=1, ensure_ascii=False), encoding="utf-8")
    return p
