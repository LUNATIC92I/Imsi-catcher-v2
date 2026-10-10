"""Configuration de l'application (fichier JSON local)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Band:
    name: str
    technology: str
    start_mhz: float
    stop_mhz: float

    def contains(self, freq_mhz: float) -> bool:
        return self.start_mhz <= freq_mhz <= self.stop_mhz


# Bandes descendantes (DL) usuelles en Europe/Afrique/Moyen-Orient (région 1 UIT).
DEFAULT_BANDS = [
    Band("LTE B20 (800)", "LTE", 791.0, 821.0),
    Band("GSM/UMTS/LTE 900 DL", "GSM", 925.0, 960.0),
    Band("DCS/LTE 1800 DL (B3)", "LTE", 1805.0, 1880.0),
    Band("UMTS/LTE 2100 DL (B1)", "UMTS", 2110.0, 2170.0),
    Band("LTE 2600 DL (B7)", "LTE", 2620.0, 2690.0),
    Band("NR n78 (3.5 GHz)", "NR", 3300.0, 3800.0),
]


def default_data_dir() -> Path:
    return Path(os.environ.get("LUNATIC_DATA_DIR", Path.home() / ".lunatic_imsi_lab"))


@dataclass
class DeviceConfig:
    name: str
    driver: str                 # "simulated" | "soapy"
    args: str = ""              # ex. "driver=rtlsdr"
    sample_rate: float = 2.4e6
    gain_db: float = 30.0
    enabled: bool = True


@dataclass
class AppConfig:
    data_dir: str = field(default_factory=lambda: str(default_data_dir()))
    local_only: bool = True     # aucune ressource réseau (tuiles de carte, etc.)
    bands: list[Band] = field(default_factory=lambda: list(DEFAULT_BANDS))
    devices: list[DeviceConfig] = field(default_factory=lambda: [
        DeviceConfig(name="Récepteur simulé", driver="simulated")])
    store_raw_iq: bool = False  # par défaut, seuls les spectres agrégés sont conservés
    operator_name: str = "analyste"
    operator_role: str = "analyst"
    authorization_ref: str = ""

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / "lab.sqlite"

    @property
    def vault_dir(self) -> Path:
        return Path(self.data_dir) / "vault"

    @property
    def reports_dir(self) -> Path:
        return Path(self.data_dir) / "reports"

    def band_for(self, freq_mhz: float) -> Band | None:
        return next((b for b in self.bands if b.contains(freq_mhz)), None)

    def save(self, path: str | Path | None = None) -> Path:
        p = Path(path) if path else Path(self.data_dir) / "config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: str | Path | None = None) -> "AppConfig":
        p = Path(path) if path else default_data_dir() / "config.json"
        if not p.exists():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        data["bands"] = [Band(**b) for b in data.get("bands", [])] or list(DEFAULT_BANDS)
        data["devices"] = [DeviceConfig(**d) for d in data.get("devices", [])]
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)
