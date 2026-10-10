"""Corrélation : chronologie, regroupement d'anomalies, comparaison à la
référence, distinction changements persistants / événements ponctuels, export.
"""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence

from lunatic_imsi_lab import SIMULATION_LABEL
from lunatic_imsi_lab.core.models import Alert, CellObservation
from lunatic_imsi_lab.detection.baseline import Baseline


@dataclass
class TimelineEvent:
    timestamp: datetime
    kind: str            # "first_seen" | "last_seen" | "alert" | "serving_change"
    cell_key: tuple | None
    description: str
    source: str
    is_simulation: bool = False
    ref: str = ""

    def to_dict(self) -> dict:
        return {"timestamp": self.timestamp.isoformat(), "kind": self.kind,
                "cell_key": list(self.cell_key) if self.cell_key else None,
                "description": self.description, "source": self.source,
                "is_simulation": self.is_simulation, "ref": self.ref}


def build_timeline(observations: Sequence[CellObservation],
                   alerts: Sequence[Alert] = ()) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    first: dict[tuple, CellObservation] = {}
    last: dict[tuple, CellObservation] = {}
    serving_prev: CellObservation | None = None
    for o in sorted(observations, key=lambda o: o.timestamp):
        first.setdefault(o.cell_key, o)
        last[o.cell_key] = o
        if o.serving:
            if serving_prev is None or serving_prev.cell_key != o.cell_key:
                prev = serving_prev.cell_label if serving_prev else "—"
                events.append(TimelineEvent(o.timestamp, "serving_change", o.cell_key,
                                            f"Cellule de service : {prev} → {o.cell_label}",
                                            o.provenance.label, o.provenance.is_simulation, o.id))
            serving_prev = o
    for k, o in first.items():
        events.append(TimelineEvent(o.timestamp, "first_seen", k,
                                    f"Première observation : {o.cell_label}",
                                    o.provenance.label, o.provenance.is_simulation, o.id))
    for k, o in last.items():
        events.append(TimelineEvent(o.timestamp, "last_seen", k,
                                    f"Dernière observation : {o.cell_label}",
                                    o.provenance.label, o.provenance.is_simulation, o.id))
    for a in alerts:
        events.append(TimelineEvent(a.first_seen, "alert", a.cell_key,
                                    f"{a.alert_id} [{a.severity.value}] {a.summary}",
                                    ", ".join(a.sources), a.is_simulation, a.alert_id))
    events.sort(key=lambda e: (e.timestamp, e.kind))
    return events


@dataclass
class AlertGroup:
    signature: tuple
    alerts: list[Alert] = field(default_factory=list)

    @property
    def first_seen(self) -> datetime:
        return min(a.first_seen for a in self.alerts)

    @property
    def last_seen(self) -> datetime:
        return max(a.last_seen for a in self.alerts)

    @property
    def max_priority(self) -> int:
        return max(a.priority for a in self.alerts)


def group_alerts(alerts: Iterable[Alert], by_cell: bool = False) -> list[AlertGroup]:
    """Regroupe les alertes similaires (mêmes règles, et même cellule si demandé)."""
    groups: dict[tuple, AlertGroup] = {}
    for a in alerts:
        sig = (tuple(sorted(a.rules)), a.cell_key if by_cell else None)
        groups.setdefault(sig, AlertGroup(sig)).alerts.append(a)
    return sorted(groups.values(), key=lambda g: -g.max_priority)


@dataclass
class CellChange:
    cell_key: tuple
    status: str                  # "new" | "missing" | "known"
    persistence: str             # "persistent" | "transient" | "n/a"
    first_seen: datetime | None
    last_seen: datetime | None
    observations: int
    coverage_ratio: float        # part de la période où la cellule est visible
    rssi_delta_db: float | None  # médiane observée − médiane de référence
    sources: list[str]
    is_simulation: bool


def compare_with_baseline(observations: Sequence[CellObservation], baseline: Baseline,
                          persistent_ratio: float = 0.5,
                          bucket: timedelta = timedelta(minutes=5)) -> list[CellChange]:
    """Compare la période observée à la référence, cellule par cellule.

    Une cellule visible dans au moins ``persistent_ratio`` des intervalles
    ``bucket`` de la période est jugée *persistante* ; sinon *ponctuelle*."""
    if not observations:
        return []
    obs = sorted(observations, key=lambda o: o.timestamp)
    t0 = obs[0].timestamp
    n_buckets = max(1, int((obs[-1].timestamp - t0) / bucket) + 1)
    per: dict[tuple, list[CellObservation]] = defaultdict(list)
    for o in obs:
        per[o.cell_key].append(o)
    out = []
    for key, items in per.items():
        buckets = {int((o.timestamp - t0) / bucket) for o in items}
        ratio = len(buckets) / n_buckets
        rssi = sorted(o.rssi_dbm for o in items if o.rssi_dbm is not None)
        prof = baseline.cells.get(key)
        delta = None
        if rssi and prof and prof.rssi_median is not None:
            delta = round(rssi[len(rssi) // 2] - prof.rssi_median, 1)
        out.append(CellChange(
            cell_key=key, status="known" if prof else "new",
            persistence="persistent" if ratio >= persistent_ratio else "transient",
            first_seen=items[0].timestamp, last_seen=items[-1].timestamp,
            observations=len(items), coverage_ratio=round(ratio, 3), rssi_delta_db=delta,
            sources=sorted({o.provenance.label for o in items}),
            is_simulation=any(o.provenance.is_simulation for o in items)))
    for key, prof in baseline.cells.items():
        if key not in per:
            out.append(CellChange(cell_key=key, status="missing", persistence="n/a",
                                  first_seen=prof.first_seen, last_seen=prof.last_seen,
                                  observations=0, coverage_ratio=0.0, rssi_delta_db=None,
                                  sources=[], is_simulation=False))
    order = {"new": 0, "missing": 1, "known": 2}
    return sorted(out, key=lambda c: (order[c.status], c.cell_key))


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

OBS_COLUMNS = ["id", "timestamp", "technology", "mcc", "mnc", "area_code", "cell_id", "channel",
               "frequency_mhz", "pci", "rssi_dbm", "quality_db", "latitude", "longitude",
               "position_kind", "serving", "source", "method", "is_simulation",
               "collection_parameters", "broadcast"]


def observations_to_csv(observations: Sequence[CellObservation]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(OBS_COLUMNS)
    for o in observations:
        p = o.provenance
        w.writerow([o.id, o.timestamp.isoformat(), o.technology.value, o.mcc, o.mnc, o.area_code,
                    o.cell_id, o.channel, o.frequency_mhz, o.pci, o.rssi_dbm, o.quality_db,
                    o.latitude, o.longitude, o.position_kind.value, o.serving,
                    (f"{SIMULATION_LABEL}:" if p.is_simulation and p.source != SIMULATION_LABEL
                     else "") + p.source, p.method, p.is_simulation,
                    json.dumps(p.parameters, default=str, ensure_ascii=False),
                    json.dumps(o.broadcast, default=str, ensure_ascii=False)])
    return buf.getvalue()


def export_json(path: str | Path, observations: Sequence[CellObservation] = (),
                alerts: Sequence[Alert] = (), timeline: Sequence[TimelineEvent] = (),
                metadata: dict | None = None) -> Path:
    is_sim = any(o.provenance.is_simulation for o in observations) or any(
        a.is_simulation for a in alerts)
    doc = {
        "generator": "LUNATIC IMSI LAB",
        "contains_simulation": is_sim,
        "label": SIMULATION_LABEL if is_sim else "MESURES",
        "metadata": metadata or {},
        "observations": [o.to_dict() for o in observations],
        "alerts": [a.to_dict() for a in alerts],
        "timeline": [e.to_dict() for e in timeline],
    }
    p = Path(path)
    p.write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return p


def export_csv(path: str | Path, observations: Sequence[CellObservation]) -> Path:
    p = Path(path)
    p.write_text(observations_to_csv(observations), encoding="utf-8")
    return p


def alerts_to_csv(alerts: Sequence[Alert]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["alert_id", "first_seen", "last_seen", "cell_key", "rules", "priority",
                "confidence", "confidence_score", "severity", "summary", "sources",
                "is_simulation"])
    for a in alerts:
        w.writerow([a.alert_id, a.first_seen.isoformat(), a.last_seen.isoformat(),
                    a.cell_key, "|".join(a.rules), a.priority, a.confidence.value,
                    round(a.confidence_score, 3), a.severity.value, a.summary,
                    "|".join(a.sources), a.is_simulation])
    return buf.getvalue()
