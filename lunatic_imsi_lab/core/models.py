"""Modèles de données du laboratoire.

Les modèles sont de simples dataclasses indépendantes de la base de données et
de l'interface graphique, ce qui les rend faciles à tester.

Aucun modèle ne possède de champ destiné aux identifiants d'abonnés ou
d'appareils (IMSI, IMEI, TMSI, MSISDN...). Les observations décrivent des
*cellules* (infrastructure réseau), jamais des terminaux de tiers.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import numpy as np

from lunatic_imsi_lab import SIMULATION_LABEL


class Technology(str, Enum):
    GSM = "GSM"      # 2G
    UMTS = "UMTS"    # 3G
    LTE = "LTE"      # 4G
    NR = "NR"        # 5G
    UNKNOWN = "UNKNOWN"

    @property
    def generation(self) -> int:
        return {"GSM": 2, "UMTS": 3, "LTE": 4, "NR": 5}.get(self.value, 0)

    @classmethod
    def parse(cls, value: Any) -> "Technology":
        if isinstance(value, Technology):
            return value
        text = str(value or "").strip().upper()
        aliases = {
            "2G": cls.GSM, "GSM": cls.GSM, "EDGE": cls.GSM, "GPRS": cls.GSM,
            "3G": cls.UMTS, "UMTS": cls.UMTS, "WCDMA": cls.UMTS, "HSPA": cls.UMTS,
            "4G": cls.LTE, "LTE": cls.LTE,
            "5G": cls.NR, "NR": cls.NR, "5GNR": cls.NR, "5G NR": cls.NR,
        }
        return aliases.get(text, cls.UNKNOWN)


class PositionKind(str, Enum):
    GPS = "GPS"              # position mesurée par un récepteur GNSS
    ESTIMATED = "ESTIMATED"  # position estimée (saisie manuelle, interpolation...)
    NONE = "NONE"


@dataclass(frozen=True)
class Provenance:
    """Origine d'une mesure : obligatoire pour toute donnée du laboratoire."""

    source: str                      # ex. "QualiPoc export", "RTL-SDR #1", "SIMULATION"
    method: str                      # ex. "diagnostic-modem", "sdr-psd", "import-csv"
    is_simulation: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.is_simulation and SIMULATION_LABEL not in self.source.upper():
            return f"[{SIMULATION_LABEL}] {self.source}"
        return self.source

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "method": self.method,
            "is_simulation": self.is_simulation,
            "parameters": dict(self.parameters),
        }


@dataclass
class CellObservation:
    """Observation d'une cellule fournie par un outil de diagnostic autorisé."""

    timestamp: datetime
    technology: Technology
    mcc: int | None
    mnc: int | None
    area_code: int | None            # LAC (2G/3G) ou TAC (4G/5G)
    cell_id: int | None              # CI / ECI / NCI selon la technologie
    channel: int | None              # ARFCN / UARFCN / EARFCN / NR-ARFCN
    provenance: Provenance
    frequency_mhz: float | None = None
    pci: int | None = None           # PCI / PSC / BSIC selon la technologie
    rssi_dbm: float | None = None    # puissance (RSSI / RSCP / RSRP selon techno)
    quality_db: float | None = None  # qualité (RSRQ / Ec/No / SINR)
    latitude: float | None = None
    longitude: float | None = None
    position_kind: PositionKind = PositionKind.NONE
    broadcast: dict[str, Any] = field(default_factory=dict)  # paramètres diffusés accessibles
    serving: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def cell_key(self) -> tuple:
        """Identifiant global d'une cellule tel que fourni par la source."""
        return (self.technology.value, self.mcc, self.mnc, self.area_code, self.cell_id)

    @property
    def cell_label(self) -> str:
        return (f"{self.technology.value} {self.mcc}-{self.mnc} "
                f"{'TAC' if self.technology in (Technology.LTE, Technology.NR) else 'LAC'}"
                f"={self.area_code} CI={self.cell_id}")

    @property
    def has_position(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        data["technology"] = self.technology.value
        data["position_kind"] = self.position_kind.value
        data["provenance"] = self.provenance.to_dict()
        return data


@dataclass
class SpectrumSweep:
    """Balayage spectral (densité de puissance) issu d'un récepteur."""

    timestamp: datetime
    frequencies_hz: np.ndarray
    power_dbm: np.ndarray            # puissance par bin (dBm / bin)
    provenance: Provenance
    rbw_hz: float | None = None      # résolution de bande
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self) -> None:
        self.frequencies_hz = np.asarray(self.frequencies_hz, dtype=float)
        self.power_dbm = np.asarray(self.power_dbm, dtype=float)
        if self.frequencies_hz.shape != self.power_dbm.shape:
            raise ValueError("frequencies_hz et power_dbm doivent avoir la même taille")
        if self.frequencies_hz.size < 2:
            raise ValueError("un balayage doit contenir au moins deux points")

    @property
    def start_hz(self) -> float:
        return float(self.frequencies_hz[0])

    @property
    def stop_hz(self) -> float:
        return float(self.frequencies_hz[-1])


class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ConfidenceLevel(str, Enum):
    """Niveau de confiance qualitatif. Il n'existe volontairement aucun niveau
    « confirmé » : l'outil ne peut pas, à lui seul, prouver la présence d'un
    IMSI catcher."""

    VERY_LOW = "Très faible"
    LOW = "Faible"
    MODERATE = "Modérée"
    ELEVATED = "Élevée (à confirmer)"

    @classmethod
    def from_score(cls, score: float) -> "ConfidenceLevel":
        if score < 0.2:
            return cls.VERY_LOW
        if score < 0.45:
            return cls.LOW
        if score < 0.7:
            return cls.MODERATE
        return cls.ELEVATED


@dataclass
class Indicator:
    """Résultat élémentaire d'une règle de détection."""

    rule_id: str
    rule_name: str
    timestamp: datetime
    cell_key: tuple | None
    description: str
    technical_details: str
    weight: float                     # contribution 0..1
    observation_ids: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)
    recommended_checks: list[str] = field(default_factory=list)
    is_simulation: bool = False


@dataclass
class Alert:
    """Alerte agrégée, éventuellement composée de plusieurs indicateurs."""

    alert_id: str
    created_at: datetime
    first_seen: datetime
    last_seen: datetime
    cell_key: tuple | None
    rules: list[str]
    priority: int                     # 0..100
    confidence_score: float           # 0..1
    confidence: ConfidenceLevel
    severity: Severity
    summary: str
    explanation: list[str]
    false_positives: list[str]
    recommended_checks: list[str]
    observation_ids: list[str]
    sources: list[str]
    is_simulation: bool = False
    indicators: list[Indicator] = field(default_factory=list)

    @property
    def distinct_rule_count(self) -> int:
        return len(set(self.rules))

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "created_at": self.created_at.isoformat(),
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "cell_key": list(self.cell_key) if self.cell_key else None,
            "rules": list(self.rules),
            "priority": self.priority,
            "confidence_score": round(self.confidence_score, 3),
            "confidence": self.confidence.value,
            "severity": self.severity.value,
            "summary": self.summary,
            "explanation": list(self.explanation),
            "false_positives": list(self.false_positives),
            "recommended_checks": list(self.recommended_checks),
            "observation_ids": list(self.observation_ids),
            "sources": list(self.sources),
            "is_simulation": self.is_simulation,
        }
