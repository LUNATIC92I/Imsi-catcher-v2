"""Laboratoire virtuel : génération reproductible d'observations de cellules.

Toutes les données produites portent ``Provenance(source="SIMULATION",
is_simulation=True)``. Le générateur ne produit que des *tableaux de
nombres* : il n'émet aucun signal et n'émule aucune station de base.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

import numpy as np

from lunatic_imsi_lab.core.geo import haversine_km, offset_latlon
from lunatic_imsi_lab.core.models import CellObservation, PositionKind, Provenance, Technology
from lunatic_imsi_lab.core.units import channel_to_mhz


class Scenario(str, Enum):
    NORMAL = "normal"
    COVERAGE_CHANGE = "coverage_change"
    POWER_VARIATION = "power_variation"
    PARAMETER_CHANGE = "parameter_change"
    INCONSISTENT = "inconsistent"
    SYNTHETIC_ANOMALY = "synthetic_anomaly"

    @property
    def label(self) -> str:
        return {
            "normal": "Cellules normales",
            "coverage_change": "Changement de couverture",
            "power_variation": "Variations de puissance",
            "parameter_change": "Changement de paramètres",
            "inconsistent": "Observations incohérentes",
            "synthetic_anomaly": "Anomalie synthétique multi-indicateurs",
        }[self.value]


@dataclass
class SimulationParams:
    seed: int = 42
    scenario: Scenario = Scenario.NORMAL
    start: datetime = field(default_factory=lambda: datetime(2026, 1, 15, 8, 0,
                                                             tzinfo=timezone.utc))
    baseline_hours: float = 6.0
    duration_minutes: float = 120.0
    interval_s: float = 30.0
    n_cells: int = 6
    mcc: int = 208
    mnc: int = 10
    center_lat: float = 48.8566
    center_lon: float = 2.3522
    shadowing_db: float = 4.0
    anomaly_start_fraction: float = 0.4
    anomaly_duration_fraction: float = 0.25
    anomaly_power_dbm: float = -50.0
    power_jump_db: float = 18.0

    def __post_init__(self) -> None:
        self.scenario = Scenario(self.scenario)  # accepte aussi la valeur texte

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scenario"] = self.scenario.value
        d["start"] = self.start.isoformat()
        return d


@dataclass
class GroundTruth:
    """Ce que le scénario a réellement injecté (pour évaluer le moteur)."""

    scenario: Scenario
    events: list[str]
    anomalous_cell_keys: list[tuple]
    expected_legitimate: bool


@dataclass
class SimulationResult:
    params: SimulationParams
    baseline: list[CellObservation]
    observations: list[CellObservation]
    truth: GroundTruth


@dataclass
class _Site:
    tech: Technology
    area_code: int
    cell_id: int
    channel: int
    pci: int
    lat: float
    lon: float
    eirp_dbm: float
    broadcast: dict


_CHANNELS = {Technology.GSM: [62, 75, 88, 112], Technology.UMTS: [10612, 10637, 10662],
             Technology.LTE: [1300, 1650, 6300, 3000], Technology.NR: [636666, 643334]}


def _environment(p: SimulationParams, rng: np.random.Generator) -> list[_Site]:
    techs = [Technology.LTE, Technology.LTE, Technology.GSM, Technology.UMTS, Technology.NR,
             Technology.LTE, Technology.GSM, Technology.LTE]
    sites = []
    for i in range(p.n_cells):
        tech = techs[i % len(techs)]
        ang = 2 * math.pi * i / p.n_cells
        dist = 0.4 + 1.2 * rng.random()
        lat, lon = offset_latlon(p.center_lat, p.center_lon, dist * math.cos(ang),
                                 dist * math.sin(ang))
        area = (31010 if tech in (Technology.LTE, Technology.NR) else 1010) + (i % 2)
        sites.append(_Site(
            tech=tech, area_code=area, cell_id=10000 + 17 * i + int(rng.integers(0, 10)),
            channel=int(rng.choice(_CHANNELS[tech])), pci=int(rng.integers(0, 500)),
            lat=lat, lon=lon, eirp_dbm=float(rng.uniform(55, 62)),
            broadcast={"neighbor_count": int(rng.integers(5, 16)),
                       "reselection_offset_db": 0, "t3212": 30}))
    return sites


def _rx_power(site: _Site, lat: float, lon: float, shadow: float, rng) -> float:
    d_km = max(haversine_km(site.lat, site.lon, lat, lon), 0.1)
    f = channel_to_mhz(site.tech, site.channel) or 1800.0
    # Modèle simplifié (espace libre + exposant urbain) — à des fins de simulation.
    # +20 dB : surplus urbain ; +12 dB : pénétration bâtiment (mesure en intérieur).
    pl = 32.45 + 20 * math.log10(f) + 35 * math.log10(d_km) + 20 + 12
    return float(np.clip(site.eirp_dbm - pl + shadow + rng.normal(0, 1.0), -140, -25))


def _obs(site: _Site, ts: datetime, rssi: float, lat: float, lon: float, prov: Provenance,
         mcc: int, mnc: int, serving: bool, **over) -> CellObservation:
    data = dict(timestamp=ts, technology=site.tech, mcc=mcc, mnc=mnc, area_code=site.area_code,
                cell_id=site.cell_id, channel=site.channel,
                frequency_mhz=channel_to_mhz(site.tech, site.channel), pci=site.pci,
                rssi_dbm=round(rssi, 1), quality_db=round(-8 + (rssi + 90) / 10, 1),
                latitude=round(lat, 6), longitude=round(lon, 6), position_kind=PositionKind.GPS,
                broadcast=dict(site.broadcast), serving=serving, provenance=prov)
    data.update(over)
    return CellObservation(**data)


def _walk(p: SimulationParams, t: float) -> tuple[float, float]:
    """Trajet lent et déterministe autour du centre (≈ 300 m)."""
    return offset_latlon(p.center_lat, p.center_lon, 0.3 * math.sin(t / 900),
                         0.3 * math.cos(t / 1300))


def _collect(p: SimulationParams, sites: list[_Site], start: datetime, minutes: float,
             rng, prov: Provenance, mutate=None) -> list[CellObservation]:
    out = []
    steps = int(minutes * 60 / p.interval_s)
    # Masquage corrélé dans le temps (AR(1)) : évite des sauts irréalistes.
    rho = 0.9
    shadows = {s.cell_id: float(rng.normal(0, p.shadowing_db)) for s in sites}
    for k in range(steps):
        t = k * p.interval_s
        ts = start + timedelta(seconds=t)
        lat, lon = _walk(p, t)
        frac = k / max(steps - 1, 1)
        for s in sites:
            shadows[s.cell_id] = (rho * shadows[s.cell_id]
                                  + math.sqrt(1 - rho ** 2) * float(rng.normal(0, p.shadowing_db)))
        powers = [(_rx_power(s, lat, lon, shadows[s.cell_id], rng), s) for s in sites]
        powers.sort(key=lambda x: -x[0])
        # Comme un terminal réel : préférence pour la génération la plus récente
        # disponible au-dessus du seuil de sélection, puis pour la plus forte.
        usable = [x for x in powers if x[0] >= -105] or powers
        serving_site = max(usable, key=lambda x: (x[1].tech.generation, x[0]))[1]
        tick = []
        for pw, s in powers:
            tick.append(_obs(s, ts, pw, lat, lon, prov, p.mcc, p.mnc,
                             serving=(s is serving_site)))
        if mutate:
            tick = mutate(k, frac, ts, lat, lon, tick)
        out.extend(tick)
    return out


def simulate(params: SimulationParams | None = None) -> SimulationResult:
    p = params or SimulationParams()
    rng = np.random.default_rng(p.seed)
    sites = _environment(p, rng)
    compact = {"generator": "lunatic-sim-cells/1", "scenario": p.scenario.value,
               "seed": p.seed, "interval_s": p.interval_s, "shadowing_db": p.shadowing_db}
    base_prov = Provenance("SIMULATION", "synthetic-generator", True,
                           {**compact, "phase": "baseline"})
    prov = Provenance("SIMULATION", "synthetic-generator", True,
                      {**compact, "phase": "observation"})
    baseline = _collect(p, sites, p.start, p.baseline_hours * 60, rng, base_prov)
    obs_start = p.start + timedelta(hours=p.baseline_hours, minutes=30)

    events: list[str] = []
    anomalous: list[tuple] = []
    a0, a1 = p.anomaly_start_fraction, p.anomaly_start_fraction + p.anomaly_duration_fraction
    mutate = None

    if p.scenario == Scenario.COVERAGE_CHANGE:
        target = sites[1]
        events.append(f"Affaiblissement progressif de la cellule {target.cell_id} (−25 dB) "
                      f"puis disparition : phénomène légitime de couverture.")

        def mutate(k, frac, ts, lat, lon, tick):
            out = []
            for o in tick:
                if o.cell_id == target.cell_id:
                    if frac > a1:
                        continue
                    if frac > a0:
                        o.rssi_dbm = round(o.rssi_dbm - 25 * (frac - a0) / (a1 - a0), 1)
                out.append(o)
            return out

    elif p.scenario == Scenario.POWER_VARIATION:
        target = sites[0]
        events.append(f"Sauts de puissance répétés (±{p.power_jump_db} dB) sur la cellule "
                      f"{target.cell_id}.")
        anomalous.append((target.tech.value, p.mcc, p.mnc, target.area_code, target.cell_id))

        def mutate(k, frac, ts, lat, lon, tick):
            if a0 <= frac <= a1:
                for o in tick:
                    if o.cell_id == target.cell_id and k % 2 == 0:
                        o.rssi_dbm = round(min(o.rssi_dbm + p.power_jump_db, -25), 1)
            return tick

    elif p.scenario == Scenario.PARAMETER_CHANGE:
        target = sites[0]
        new_area = target.area_code + 7
        events.append(f"La cellule {target.cell_id} change de LAC/TAC "
                      f"({target.area_code} → {new_area}) : réorganisation opérateur simulée.")
        anomalous.append((target.tech.value, p.mcc, p.mnc, new_area, target.cell_id))

        def mutate(k, frac, ts, lat, lon, tick):
            if frac >= a0:
                for o in tick:
                    if o.cell_id == target.cell_id:
                        o.area_code = new_area
            return tick

    elif p.scenario == Scenario.INCONSISTENT:
        events.append("Horodatages dupliqués, une mesure datée de 1999 et une position "
                      "estimée à 200 km : défauts de qualité de données.")

        def mutate(k, frac, ts, lat, lon, tick):
            if k == 10:
                dup = tick[0]
                tick.append(CellObservation(**{**dup.__dict__, "id": dup.id + "d"}))
            if k == 20:
                tick[0].timestamp = datetime(1999, 1, 1, tzinfo=timezone.utc)
            if k == 30:
                tick[1].latitude, tick[1].longitude = offset_latlon(lat, lon, 200, 0)
                tick[1].position_kind = PositionKind.ESTIMATED
            return tick

    elif p.scenario == Scenario.SYNTHETIC_ANOMALY:
        donor = next((s for s in sites if s.tech == Technology.GSM), sites[0])
        rogue = _Site(tech=Technology.GSM, area_code=4242, cell_id=99001,
                      channel=donor.channel, pci=donor.pci, lat=p.center_lat, lon=p.center_lon,
                      eirp_dbm=0, broadcast={"neighbor_count": 0, "reselection_offset_db": 40,
                                             "t3212": 1})
        key = (rogue.tech.value, p.mcc, p.mnc, rogue.area_code, rogue.cell_id)
        anomalous.append(key)
        events.append("Cellule 2G inconnue à signal très fort, LAC inédit, canal/BSIC d'une "
                      "cellule connue, liste de voisines vide, passage forcé 4G→2G : "
                      "scénario synthétique multi-indicateurs.")

        def mutate(k, frac, ts, lat, lon, tick):
            if a0 <= frac <= a1:
                for o in tick:
                    o.serving = False
                pw = float(p.anomaly_power_dbm + rng.normal(0, 1.5))
                tick.append(_obs(rogue, ts, pw, lat, lon, prov, p.mcc, p.mnc, serving=True))
            return tick

    observations = _collect(p, sites, obs_start, p.duration_minutes, rng, prov, mutate)
    # Identifiants déterministes : mêmes paramètres → mêmes fichiers, octet pour octet.
    digest = hashlib.sha1(json.dumps(p.to_dict(), sort_keys=True).encode()).hexdigest()[:8]
    for prefix, items in (("b", baseline), ("o", observations)):
        for i, o in enumerate(items):
            o.id = f"sim{digest}{prefix}{i:06d}"
    if p.scenario == Scenario.NORMAL:
        events.append("Environnement stable : aucune anomalie injectée.")
    return SimulationResult(
        params=p, baseline=baseline, observations=observations,
        truth=GroundTruth(scenario=p.scenario, events=events, anomalous_cell_keys=anomalous,
                          expected_legitimate=p.scenario in (Scenario.NORMAL,
                                                             Scenario.COVERAGE_CHANGE)))
