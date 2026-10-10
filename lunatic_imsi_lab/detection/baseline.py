"""Environnement de référence construit à partir d'observations historiques."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from lunatic_imsi_lab.core.models import CellObservation, PositionKind


@dataclass
class CellProfile:
    cell_key: tuple
    count: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    channels: set[int] = field(default_factory=set)
    pcis: set[int] = field(default_factory=set)
    rssi_values: list[float] = field(default_factory=list)
    positions: list[tuple[float, float]] = field(default_factory=list)
    broadcast: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    @property
    def rssi_median(self) -> float | None:
        return float(np.median(self.rssi_values)) if self.rssi_values else None

    @property
    def rssi_mad(self) -> float | None:
        if not self.rssi_values:
            return None
        v = np.asarray(self.rssi_values)
        return float(np.median(np.abs(v - np.median(v))) * 1.4826)

    @property
    def centroid(self) -> tuple[float, float] | None:
        if not self.positions:
            return None
        arr = np.asarray(self.positions)
        return float(arr[:, 0].mean()), float(arr[:, 1].mean())


@dataclass
class Baseline:
    """Profils de cellules connues + index secondaires."""

    cells: dict[tuple, CellProfile] = field(default_factory=dict)
    by_cell_id: dict[tuple, set[tuple]] = field(default_factory=lambda: defaultdict(set))
    by_radio_id: dict[tuple, set[tuple]] = field(default_factory=lambda: defaultdict(set))
    area_codes: dict[tuple, set[int]] = field(default_factory=lambda: defaultdict(set))
    observation_count: int = 0
    sources: set[str] = field(default_factory=set)
    start: datetime | None = None
    end: datetime | None = None

    @property
    def is_empty(self) -> bool:
        return not self.cells

    @classmethod
    def from_observations(cls, observations: Iterable[CellObservation]) -> "Baseline":
        b = cls()
        for o in observations:
            b.add(o)
        return b

    def add(self, o: CellObservation) -> None:
        key = o.cell_key
        prof = self.cells.get(key)
        if prof is None:
            prof = self.cells[key] = CellProfile(cell_key=key)
        prof.count += 1
        prof.first_seen = min(filter(None, [prof.first_seen, o.timestamp]))
        prof.last_seen = max(filter(None, [prof.last_seen, o.timestamp]))
        if o.channel is not None:
            prof.channels.add(o.channel)
        if o.pci is not None:
            prof.pcis.add(o.pci)
        if o.rssi_dbm is not None:
            prof.rssi_values.append(o.rssi_dbm)
        if o.has_position and o.position_kind == PositionKind.GPS:
            prof.positions.append((o.latitude, o.longitude))
        for k, v in o.broadcast.items():
            prof.broadcast[k].add(str(v))
        self.by_cell_id[(o.technology.value, o.mcc, o.mnc, o.cell_id)].add(key)
        if o.channel is not None and o.pci is not None:
            self.by_radio_id[(o.technology.value, o.channel, o.pci)].add(key)
        if o.area_code is not None:
            self.area_codes[(o.technology.value, o.mcc, o.mnc)].add(o.area_code)
        self.observation_count += 1
        self.sources.add(o.provenance.source)
        self.start = min(filter(None, [self.start, o.timestamp]))
        self.end = max(filter(None, [self.end, o.timestamp]))

    def summary(self) -> dict[str, Any]:
        return {
            "cells": len(self.cells),
            "observations": self.observation_count,
            "sources": sorted(self.sources),
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
        }

    def save(self, path: str | Path) -> None:
        """Export lisible de la référence (profils de cellules)."""
        data = [{
            "cell_key": list(p.cell_key), "count": p.count,
            "first_seen": p.first_seen.isoformat() if p.first_seen else None,
            "last_seen": p.last_seen.isoformat() if p.last_seen else None,
            "channels": sorted(p.channels), "pcis": sorted(p.pcis),
            "rssi_median": p.rssi_median, "centroid": p.centroid,
            "broadcast": {k: sorted(v) for k, v in p.broadcast.items()},
        } for p in self.cells.values()]
        Path(path).write_text(json.dumps({"summary": self.summary(), "cells": data}, indent=2,
                                         ensure_ascii=False), encoding="utf-8")
