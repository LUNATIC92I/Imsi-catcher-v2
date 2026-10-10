"""Règles heuristiques de détection.

Chaque règle produit des *indicateurs* pondérés (0..1). Aucun indicateur ne
constitue une preuve : chaque règle documente les phénomènes légitimes qui
peuvent la déclencher (faux positifs) et les vérifications à mener.
"""

from __future__ import annotations

import abc
from collections import defaultdict
from dataclasses import dataclass, fields
from datetime import timedelta
from typing import Sequence

import numpy as np

from lunatic_imsi_lab.core.geo import MAX_CELL_RADIUS_KM, haversine_km
from lunatic_imsi_lab.core.models import CellObservation, Indicator, PositionKind
from lunatic_imsi_lab.core.timeutils import check_plausible
from lunatic_imsi_lab.detection.baseline import Baseline


@dataclass
class RuleConfig:
    """Seuils des règles. Le plafond de confiance d'un indicateur isolé et les
    pondérations ne sont volontairement *pas* configurables (garde-fou)."""

    jump_db: float = 12.0                 # saut de puissance « brutal »
    jump_max_gap_s: float = 120.0         # écart max entre deux mesures comparées
    min_jumps: int = 3                    # nombre de sauts pour « répétés »
    excess_db: float = 20.0               # excès de puissance vs référence
    min_baseline_obs_per_cell: int = 5
    short_lived_max_s: float = 600.0      # cellule « éphémère »
    short_lived_min_span_s: float = 3600.0
    strong_signal_dbm: float = -70.0
    profile: str = "urbain"

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict | None) -> "RuleConfig":
        """Construit et valide une configuration ; les clés inconnues sont ignorées."""
        cfg = cls(**{k: v for k, v in (data or {}).items() if k in RULE_PARAM_LIMITS
                     or k == "profile"})
        cfg.validate()
        return cfg

    def validate(self) -> None:
        for name, (lo, hi, _label, _unit) in RULE_PARAM_LIMITS.items():
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not lo <= value <= hi:
                raise ValueError(f"paramètre de règle « {name} » hors plage [{lo}, {hi}] : "
                                 f"{value!r}")
        for name in ("min_jumps", "min_baseline_obs_per_cell"):
            setattr(self, name, int(getattr(self, name)))
        if self.short_lived_max_s >= self.short_lived_min_span_s:
            raise ValueError("la durée « éphémère » doit être inférieure à la période minimale")

    @classmethod
    def for_profile(cls, name: str) -> "RuleConfig":
        if name not in RULE_PROFILES:
            raise ValueError(f"profil inconnu : {name}")
        return cls.from_dict({**RULE_PROFILES[name]["params"], "profile": name})


# Plages admissibles : nom -> (min, max, libellé, unité)
RULE_PARAM_LIMITS: dict[str, tuple[float, float, str, str]] = {
    "jump_db": (3.0, 40.0, "Amplitude d'un saut de puissance", "dB"),
    "jump_max_gap_s": (1.0, 3600.0, "Écart max entre mesures comparées", "s"),
    "min_jumps": (1, 50, "Nombre de sauts pour « répétés »", ""),
    "excess_db": (3.0, 60.0, "Excès de puissance vs référence", "dB"),
    "min_baseline_obs_per_cell": (1, 1000, "Mesures de référence min. par cellule", ""),
    "short_lived_max_s": (10.0, 86400.0, "Durée max d'une cellule éphémère", "s"),
    "short_lived_min_span_s": (60.0, 604800.0, "Période min. pour juger l'éphémère", "s"),
    "strong_signal_dbm": (-120.0, -20.0, "Seuil de signal fort", "dBm"),
}

# Profils d'environnement. Les valeurs s'écartent des défauts là où le
# contexte de mesure change la variabilité attendue.
RULE_PROFILES: dict[str, dict] = {
    "urbain": {"label": "Urbain, mesure piétonne (défaut)", "params": {}},
    "fixe": {"label": "Point fixe en intérieur (variabilité faible)",
             "params": {"jump_db": 8.0, "min_jumps": 3, "excess_db": 15.0,
                        "strong_signal_dbm": -75.0}},
    "vehicule": {"label": "Mesure embarquée en véhicule (forte variabilité)",
                 "params": {"jump_db": 18.0, "min_jumps": 5, "jump_max_gap_s": 30.0,
                            "excess_db": 25.0, "short_lived_max_s": 120.0}},
    "rural": {"label": "Rural (cellules éloignées, signaux faibles)",
              "params": {"strong_signal_dbm": -80.0, "excess_db": 18.0,
                         "short_lived_max_s": 900.0}},
}


def _by_cell(observations: Sequence[CellObservation]) -> dict[tuple, list[CellObservation]]:
    groups: dict[tuple, list[CellObservation]] = defaultdict(list)
    for o in observations:
        groups[o.cell_key].append(o)
    for v in groups.values():
        v.sort(key=lambda o: o.timestamp)
    return groups


def _reidentified(o: CellObservation, baseline: Baseline) -> bool:
    """Vrai si l'identifiant de cellule est connu sous un autre LAC/TAC : le
    fait est alors traité une seule fois, par la règle R02."""
    known = baseline.by_cell_id.get((o.technology.value, o.mcc, o.mnc, o.cell_id))
    return bool(known) and o.cell_key not in baseline.cells


def _is_sim(obs: Sequence[CellObservation]) -> bool:
    return any(o.provenance.is_simulation for o in obs)


class Rule(abc.ABC):
    rule_id: str = ""
    name: str = ""
    false_positives: list[str] = []
    recommended_checks: list[str] = []

    def __init__(self, config: RuleConfig | None = None) -> None:
        self.config = config or RuleConfig()

    def indicator(self, obs: Sequence[CellObservation], description: str, details: str,
                  weight: float, cell_key: tuple | None = None) -> Indicator:
        return Indicator(
            rule_id=self.rule_id, rule_name=self.name,
            timestamp=min(o.timestamp for o in obs),
            cell_key=cell_key if cell_key is not None else obs[0].cell_key,
            description=description, technical_details=details,
            weight=float(np.clip(weight, 0.0, 1.0)),
            observation_ids=[o.id for o in obs][:200],
            false_positives=list(self.false_positives),
            recommended_checks=list(self.recommended_checks),
            is_simulation=_is_sim(obs))

    @abc.abstractmethod
    def evaluate(self, observations: Sequence[CellObservation],
                 baseline: Baseline) -> list[Indicator]: ...


class UnknownCellRule(Rule):
    rule_id = "R01_UNKNOWN_CELL"
    name = "Cellule absente de l'environnement de référence"
    false_positives = [
        "Mise en service d'une nouvelle cellule ou d'un nouveau secteur par l'opérateur",
        "Référence incomplète (période ou zone de collecte trop restreinte)",
        "Déplacement de l'équipement de mesure hors de la zone de référence",
        "Small cell / femtocell légitime installée dans un bâtiment",
    ]
    recommended_checks = [
        "Vérifier la cellule auprès des bases publiques ou de l'opérateur (avec autorisation)",
        "Prolonger la collecte de référence sur plusieurs jours",
        "Comparer avec un second équipement de mesure indépendant",
    ]

    def evaluate(self, observations, baseline):
        if baseline.is_empty:
            return []
        out = []
        for key, obs in _by_cell(observations).items():
            if key in baseline.cells or _reidentified(obs[0], baseline):
                continue
            rssi = [o.rssi_dbm for o in obs if o.rssi_dbm is not None]
            peak = max(rssi) if rssi else None
            strong = peak is not None and peak >= self.config.strong_signal_dbm
            weight = 0.45 if strong else 0.3
            out.append(self.indicator(
                obs, f"Cellule inconnue de la référence : {obs[0].cell_label}",
                f"{len(obs)} observation(s) ; puissance max "
                f"{peak if peak is not None else 'n/d'} dBm ; référence de "
                f"{len(baseline.cells)} cellules / {baseline.observation_count} mesures.",
                weight))
        return out


class ParameterChangeRule(Rule):
    rule_id = "R02_PARAM_CHANGE"
    name = "Incohérence d'identité ou de paramètres d'une cellule connue"
    false_positives = [
        "Réorganisation des zones de localisation (LAC/TAC) par l'opérateur",
        "Re-planification des fréquences ou des PCI (refarming)",
        "Erreur ou arrondi dans l'outil de diagnostic source",
    ]
    recommended_checks = [
        "Vérifier si le changement est persistant sur plusieurs jours",
        "Contrôler si d'autres cellules du même site ont changé simultanément",
        "Confronter avec les annonces de maintenance de l'opérateur",
    ]

    def evaluate(self, observations, baseline):
        if baseline.is_empty:
            return []
        out = []
        for key, obs in _by_cell(observations).items():
            o0 = obs[0]
            known_keys = baseline.by_cell_id.get((o0.technology.value, o0.mcc, o0.mnc, o0.cell_id))
            reasons = []
            if key not in baseline.cells and known_keys:
                old = sorted({k[3] for k in known_keys if k[3] is not None})
                reasons.append(f"même identifiant de cellule mais LAC/TAC {o0.area_code} "
                               f"au lieu de {old}")
            prof = baseline.cells.get(key)
            if prof is not None and prof.count >= self.config.min_baseline_obs_per_cell:
                chans = {o.channel for o in obs if o.channel is not None}
                pcis = {o.pci for o in obs if o.pci is not None}
                if prof.channels and chans - prof.channels:
                    reasons.append(f"canal {sorted(chans - prof.channels)} inhabituel "
                                   f"(référence {sorted(prof.channels)})")
                if prof.pcis and pcis - prof.pcis:
                    reasons.append(f"PCI/PSC/BSIC {sorted(pcis - prof.pcis)} inhabituel "
                                   f"(référence {sorted(prof.pcis)})")
            if reasons:
                out.append(self.indicator(obs, f"Paramètres modifiés : {o0.cell_label}",
                                          " ; ".join(reasons), 0.3 + 0.05 * (len(reasons) - 1)))
        return out


class IsolatedAreaCodeRule(Rule):
    rule_id = "R03_ISOLATED_AREA"
    name = "Code de zone (LAC/TAC) inédit pour l'opérateur"
    false_positives = [
        "Nouvelle zone de localisation créée par l'opérateur",
        "Mesures effectuées en bordure de zone non couverte par la référence",
    ]
    recommended_checks = [
        "Vérifier si d'autres cellules légitimes partagent ce LAC/TAC",
        "Observer si les terminaux effectuent des mises à jour de localisation répétées",
    ]

    def evaluate(self, observations, baseline):
        if baseline.is_empty:
            return []
        out = []
        for key, obs in _by_cell(observations).items():
            o0 = obs[0]
            known = baseline.area_codes.get((o0.technology.value, o0.mcc, o0.mnc))
            if known and o0.area_code is not None and o0.area_code not in known:
                # Cellule connue changeant de zone : indice plus faible (réorganisation).
                weight = 0.15 if _reidentified(o0, baseline) else 0.3
                out.append(self.indicator(
                    obs, f"LAC/TAC {o0.area_code} jamais observé pour {o0.mcc}-{o0.mnc} "
                         f"({o0.technology.value})",
                    f"Codes connus : {sorted(known)[:20]}", weight))
        return out


class PowerAnomalyRule(Rule):
    rule_id = "R04_POWER_ANOMALY"
    name = "Variations de puissance brutales et répétées / niveau anormal"
    false_positives = [
        "Évanouissements (fading) liés à la mobilité ou aux obstacles",
        "Changement d'antenne, d'orientation ou de position de l'équipement",
        "Régulation de puissance ou mise en veille énergétique de la cellule",
        "Saturation ou réglage de gain du récepteur",
    ]
    recommended_checks = [
        "Répéter la mesure en position fixe avec un équipement étalonné",
        "Comparer avec les cellules voisines au même instant",
        "Vérifier la journalisation du gain et de l'antenne",
    ]

    def evaluate(self, observations, baseline):
        out = []
        c = self.config
        for key, obs in _by_cell(observations).items():
            series = [o for o in obs if o.rssi_dbm is not None]
            if len(series) < 3:
                continue
            jumps = 0
            for a, b in zip(series, series[1:]):
                gap = (b.timestamp - a.timestamp).total_seconds()
                if 0 < gap <= c.jump_max_gap_s and abs(b.rssi_dbm - a.rssi_dbm) >= c.jump_db:
                    jumps += 1
            reasons, weight = [], 0.0
            if jumps >= c.min_jumps:
                reasons.append(f"{jumps} sauts ≥ {c.jump_db} dB entre mesures consécutives")
                weight = max(weight, 0.2 + 0.02 * min(jumps - c.min_jumps, 5))
            prof = baseline.cells.get(key)
            if prof is not None and prof.count >= c.min_baseline_obs_per_cell:
                med = prof.rssi_median
                obs_med = float(np.median([o.rssi_dbm for o in series]))
                if med is not None and obs_med - med >= c.excess_db:
                    reasons.append(f"puissance médiane {obs_med:.1f} dBm vs référence "
                                   f"{med:.1f} dBm (+{obs_med - med:.1f} dB)")
                    weight = max(weight, 0.25)
            if reasons:
                out.append(self.indicator(series, f"Anomalie de puissance : {obs[0].cell_label}",
                                          " ; ".join(reasons), weight))
        return out


class TechnologyDowngradeRule(Rule):
    rule_id = "R05_TECH_DOWNGRADE"
    name = "Transition technologique descendante inattendue (vers 2G)"
    false_positives = [
        "Absence de couverture 4G/5G (intérieur, zone rurale)",
        "Repli CSFB lors d'un appel vocal sur un réseau sans VoLTE",
        "Préférences de réseau du terminal de mesure",
    ]
    recommended_checks = [
        "Vérifier la disponibilité de la 4G/5G au même endroit avec un autre terminal",
        "Contrôler si la cellule 2G cible figure dans la référence",
        "Corréler avec d'autres indicateurs sur la même période",
    ]

    def evaluate(self, observations, baseline):
        serving = sorted((o for o in observations if o.serving), key=lambda o: o.timestamp)
        out = []
        for a, b in zip(serving, serving[1:]):
            if a.technology.generation >= 4 and b.technology.generation == 2:
                unknown = not baseline.is_empty and b.cell_key not in baseline.cells
                weight = 0.35 if unknown else 0.15
                out.append(self.indicator(
                    [a, b], f"Passage {a.technology.value} → {b.technology.value} "
                            f"vers {b.cell_label}",
                    f"Transition à {b.timestamp.isoformat()} ; cellule 2G "
                    f"{'absente de' if unknown else 'présente dans'} la référence.",
                    weight, cell_key=b.cell_key))
        return out


class TemporalAnomalyRule(Rule):
    rule_id = "R06_TEMPORAL"
    name = "Anomalies temporelles (cellule éphémère, horodatages incohérents)"
    false_positives = [
        "Cellule en bordure de couverture vue brièvement",
        "Horloge de l'équipement non synchronisée (NTP/GNSS)",
        "Fusion de plusieurs fichiers d'export",
    ]
    recommended_checks = [
        "Vérifier la synchronisation horaire des équipements",
        "Contrôler si la cellule réapparaît à des horaires réguliers",
    ]

    def evaluate(self, observations, baseline):
        out = []
        if not observations:
            return out
        c = self.config
        times = [o.timestamp for o in observations]
        span = (max(times) - min(times)).total_seconds()
        for key, obs in _by_cell(observations).items():
            life = (obs[-1].timestamp - obs[0].timestamp).total_seconds()
            rssi = [o.rssi_dbm for o in obs if o.rssi_dbm is not None]
            if (span >= c.short_lived_min_span_s and life <= c.short_lived_max_s
                    and rssi and max(rssi) >= c.strong_signal_dbm
                    and (baseline.is_empty or key not in baseline.cells)):
                out.append(self.indicator(
                    obs, f"Cellule éphémère à signal fort : {obs[0].cell_label}",
                    f"Présente {life:.0f} s sur une période de {span:.0f} s ; "
                    f"puissance max {max(rssi):.1f} dBm.", 0.2))
        # Qualité des horodatages (ordre d'origine des données).
        problems = []
        for o in observations:
            problems += [f"{o.id}: {p}" for p in check_plausible(o.timestamp)]
        dup = len(times) - len({(o.cell_key, o.timestamp) for o in observations})
        if dup:
            problems.append(f"{dup} doublon(s) cellule/horodatage")
        if problems:
            ind = self.indicator(observations, "Qualité des horodatages à vérifier",
                                 " ; ".join(problems[:10]), 0.05, cell_key=None)
            ind.cell_key = None
            out.append(ind)
        return out


class SpatialAnomalyRule(Rule):
    rule_id = "R07_SPATIAL"
    name = "Incohérence spatiale (cellule observée à des distances improbables)"
    false_positives = [
        "Positions estimées imprécises",
        "Propagation exceptionnelle (conduits troposphériques, zones maritimes)",
        "Même identifiant réutilisé par l'opérateur dans une autre région",
    ]
    recommended_checks = [
        "Vérifier la qualité du fix GNSS (HDOP, nombre de satellites)",
        "Contrôler l'identifiant complet (MCC/MNC/LAC/CI) sur la zone concernée",
    ]

    def evaluate(self, observations, baseline):
        out = []
        for key, obs in _by_cell(observations).items():
            pts = [o for o in obs if o.has_position]
            if len(pts) < 2 and not (pts and key in baseline.cells):
                continue
            radius = MAX_CELL_RADIUS_KM.get(obs[0].technology.value, 35.0)
            max_d, estimated = 0.0, False
            for i, a in enumerate(pts):
                for b in pts[i + 1:]:
                    d = haversine_km(a.latitude, a.longitude, b.latitude, b.longitude)
                    if d > max_d:
                        max_d = d
                        estimated = PositionKind.ESTIMATED in (a.position_kind, b.position_kind)
            prof = baseline.cells.get(key)
            ref_d = 0.0
            if prof is not None and prof.centroid:
                clat, clon = prof.centroid
                for p in pts:
                    ref_d = max(ref_d, haversine_km(clat, clon, p.latitude, p.longitude))
            if max_d > 2 * radius or ref_d > 2 * radius:
                w = 0.3 * (0.5 if estimated else 1.0)
                out.append(self.indicator(
                    pts, f"Cellule observée sur une étendue improbable : {obs[0].cell_label}",
                    f"Écart max entre observations {max_d:.1f} km ; écart à la référence "
                    f"{ref_d:.1f} km ; rayon plausible {radius:.0f} km"
                    f"{' (positions estimées)' if estimated else ''}.", w))
        return out


class BroadcastChangeRule(Rule):
    rule_id = "R08_BROADCAST"
    name = "Modification des paramètres diffusés accessibles"
    false_positives = [
        "Optimisation radio par l'opérateur (offsets de resélection, timers)",
        "Valeurs non fournies ou mal interprétées par l'outil source",
    ]
    recommended_checks = [
        "Comparer les paramètres diffusés des cellules voisines du même site",
        "Vérifier la persistance de la modification",
    ]

    def evaluate(self, observations, baseline):
        out = []
        for key, obs in _by_cell(observations).items():
            reasons, weight = [], 0.0
            prof = baseline.cells.get(key)
            if prof is not None:
                for o in obs:
                    for k, v in o.broadcast.items():
                        ref = prof.broadcast.get(k)
                        if ref and str(v) not in ref:
                            reasons.append(f"{k}={v} (référence {sorted(ref)})")
                            weight = max(weight, 0.2)
            nb = [o.broadcast.get("neighbor_count") for o in obs
                  if o.broadcast.get("neighbor_count") not in (None, "")]
            if nb and all(int(float(x)) == 0 for x in nb):
                reasons.append("liste de cellules voisines vide")
                weight = max(weight, 0.25)
            if reasons:
                out.append(self.indicator(obs, f"Paramètres diffusés inhabituels : "
                                               f"{obs[0].cell_label}",
                                          " ; ".join(sorted(set(reasons))[:10]), weight))
        return out


class RadioIdentityRule(Rule):
    rule_id = "R09_RADIO_IDENTITY"
    name = "Canal et identifiant physique d'une cellule connue réutilisés par une autre identité"
    false_positives = [
        "Réutilisation normale des PCI/PSC/BSIC à distance",
        "Cellule voisine légitime partageant canal et code physique",
    ]
    recommended_checks = [
        "Comparer la position de mesure aux positions de référence de la cellule connue",
        "Vérifier si les deux identités sont visibles simultanément",
    ]

    def evaluate(self, observations, baseline):
        if baseline.is_empty:
            return []
        out = []
        for key, obs in _by_cell(observations).items():
            if key in baseline.cells or _reidentified(obs[0], baseline):
                continue
            o0 = obs[0]
            if o0.channel is None or o0.pci is None:
                continue
            known = baseline.by_radio_id.get((o0.technology.value, o0.channel, o0.pci), set())
            same_op = [k for k in known if k[1] == o0.mcc and k[2] == o0.mnc and k != key]
            if same_op:
                out.append(self.indicator(
                    obs, f"Canal {o0.channel} / code physique {o0.pci} déjà associé à une "
                         f"autre cellule connue",
                    f"Identités de référence : {same_op[:5]}", 0.25))
        return out


RULE_IDS = ("R01_UNKNOWN_CELL", "R02_PARAM_CHANGE", "R03_ISOLATED_AREA", "R04_POWER_ANOMALY",
            "R05_TECH_DOWNGRADE", "R06_TEMPORAL", "R07_SPATIAL", "R08_BROADCAST",
            "R09_RADIO_IDENTITY")

DEFAULT_RULES = (UnknownCellRule, ParameterChangeRule, IsolatedAreaCodeRule, PowerAnomalyRule,
                 TechnologyDowngradeRule, TemporalAnomalyRule, SpatialAnomalyRule,
                 BroadcastChangeRule, RadioIdentityRule)

# Durée utilisée par défaut pour considérer deux indicateurs comme simultanés.
CORRELATION_WINDOW = timedelta(minutes=30)
