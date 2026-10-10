"""Profils de mappage d'import et aperçu de la résolution des colonnes.

Un profil associe des champs canoniques à des noms de colonnes d'un export
donné (``columns``) et peut fixer des valeurs constantes (``constants``),
par exemple la technologie d'un export mono-technologie. Les profils intégrés
reposent sur des conventions de nommage génériques ; les formats propres à un
outil se déclarent comme profils personnalisés (configuration
``import_profiles`` ou fichier JSON).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lunatic_imsi_lab.importers.cells import (FIELD_ALIASES, _resolve_columns, is_forbidden,
                                              read_records)

BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "auto": {"label": "Détection automatique (alias usuels)", "columns": {}, "constants": {}},
    "nr-3gpp": {
        "label": "5G NR — noms de mesures 3GPP (SS-RSRP, NR-ARFCN, NCI…)",
        "columns": {"cell_id": "NCI", "channel": "NR-ARFCN", "rssi_dbm": "SS-RSRP",
                    "quality_db": "SS-RSRQ", "area_code": "TAC", "pci": "PCI"},
        "constants": {"technology": "NR"}},
    "lte-only": {
        "label": "Export LTE sans colonne de technologie",
        "columns": {"cell_id": "ECI", "channel": "EARFCN", "rssi_dbm": "RSRP",
                    "quality_db": "RSRQ", "area_code": "TAC"},
        "constants": {"technology": "LTE"}},
    "gsm-only": {
        "label": "Export GSM sans colonne de technologie",
        "columns": {"cell_id": "CI", "channel": "ARFCN", "rssi_dbm": "RxLev_dBm",
                    "area_code": "LAC", "pci": "BSIC"},
        "constants": {"technology": "GSM"}},
}


def validate_profile(profile: dict[str, Any]) -> dict[str, Any]:
    cols = dict(profile.get("columns") or {})
    consts = dict(profile.get("constants") or {})
    for canonical, src in cols.items():
        if canonical not in FIELD_ALIASES:
            raise ValueError(f"champ inconnu dans le profil : {canonical}")
        if not isinstance(src, str) or is_forbidden(src):
            raise ValueError(f"colonne source refusée dans le profil : {src!r}")
    for canonical in consts:
        if canonical not in FIELD_ALIASES:
            raise ValueError(f"constante inconnue dans le profil : {canonical}")
    return {"label": str(profile.get("label", "")), "columns": cols, "constants": consts}


def all_profiles(custom: dict[str, dict] | None = None) -> dict[str, dict[str, Any]]:
    out = dict(BUILTIN_PROFILES)
    for name, prof in (custom or {}).items():
        out[name] = validate_profile(prof)
    return out


def load_profile_file(path: str | Path) -> dict[str, Any]:
    return validate_profile(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass
class ColumnPreview:
    resolved: dict[str, str]                 # champ canonique -> colonne source
    constants: dict[str, Any]
    dropped: list[str]                       # colonnes d'identifiants personnels
    unused: list[str]                        # colonnes ignorées
    missing_required: list[str]
    rows: int
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing_required


def preview_file(path: str | Path, profile: dict[str, Any] | None = None) -> ColumnPreview:
    """Indique comment les colonnes d'un fichier seront interprétées, sans
    importer ni lire les valeurs des colonnes interdites."""
    records = read_records(path)
    profile = validate_profile(profile or {})
    columns: list[str] = []
    for r in records:
        for k in r:
            if k not in columns:
                columns.append(k)
    resolved, dropped = _resolve_columns(columns, profile["columns"])
    consts = {k: v for k, v in profile["constants"].items() if k not in resolved}
    used = set(resolved.values()) | set(dropped)
    unused = [c for c in columns if c not in used and not c.lower().startswith("bcast_")
              and c not in ("broadcast", "is_simulation", "source", "method", "id",
                            "collection_parameters")]
    missing = [f for f in ("timestamp", "technology") if f not in resolved and f not in consts]
    warnings = [f"colonne du profil absente du fichier : {src} ({canon})"
                for canon, src in profile["columns"].items() if canon not in resolved]
    return ColumnPreview(resolved=resolved, constants=consts, dropped=dropped, unused=unused,
                         missing_required=missing, rows=len(records), warnings=warnings)
