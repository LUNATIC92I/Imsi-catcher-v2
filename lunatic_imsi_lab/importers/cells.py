"""Connecteur d'import des observations de cellules.

Formats acceptés : CSV et JSON (liste d'objets, ou objet ``{"observations": [...]}``)
exportés par des outils de diagnostic autorisés (applications de test radio,
modems en mode diagnostic, scanners de réseau opérateur...).

Filtre de confidentialité : toute colonne susceptible de contenir un
identifiant d'abonné ou d'appareil (IMSI, IMEI, TMSI, MSISDN, SUPI, SUCI...)
est **supprimée avant tout traitement** ; son nom est consigné dans le rapport
d'import, jamais ses valeurs.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from lunatic_imsi_lab.core.models import CellObservation, PositionKind, Provenance, Technology
from lunatic_imsi_lab.core.timeutils import TimestampError, check_plausible, to_utc
from lunatic_imsi_lab.core.units import channel_to_mhz

# Noms de colonnes interdits (comparaison après normalisation).
FORBIDDEN_FIELDS = {
    "imsi", "imei", "imeisv", "tmsi", "ptmsi", "p_tmsi", "msisdn", "supi", "suci", "guti",
    "5g_guti", "s_tmsi", "stmsi", "iccid", "phone", "phone_number", "subscriber", "subscriber_id",
    "msin", "ue_id", "device_id",
}

# Alias reconnus pour chaque champ canonique.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "timestamp": ("timestamp", "time", "datetime", "date", "ts", "horodatage"),
    "technology": ("technology", "tech", "rat", "network_type", "technologie"),
    "mcc": ("mcc",),
    "mnc": ("mnc",),
    "area_code": ("area_code", "lac", "tac"),
    "cell_id": ("cell_id", "cid", "ci", "eci", "nci", "cellid", "cell"),
    "channel": ("channel", "arfcn", "uarfcn", "earfcn", "nrarfcn", "nr_arfcn", "canal"),
    "frequency_mhz": ("frequency_mhz", "freq_mhz", "frequency", "frequence"),
    "pci": ("pci", "psc", "bsic"),
    "rssi_dbm": ("rssi_dbm", "rssi", "rsrp", "rscp", "signal_dbm", "power_dbm", "dbm"),
    "quality_db": ("quality_db", "rsrq", "ecno", "sinr", "snr", "quality"),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lon", "lng", "long"),
    "position_kind": ("position_kind", "position_type", "pos_kind", "gps_fix"),
    "serving": ("serving", "is_serving", "registered"),
}
BROADCAST_PREFIX = "bcast_"   # colonnes CSV « bcast_xxx » → paramètres diffusés


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.strip().lower())


def is_forbidden(name: str) -> bool:
    n = _norm(name)
    return n in FORBIDDEN_FIELDS or any(n.startswith(f + "_") or n.endswith("_" + f)
                                        for f in ("imsi", "imei", "tmsi", "msisdn", "supi", "suci"))


@dataclass
class ImportReport:
    source_name: str
    rows_total: int = 0
    rows_imported: int = 0
    rows_rejected: int = 0
    dropped_fields: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, row: int, message: str) -> None:
        self.rows_rejected += 1
        if len(self.errors) < 200:
            self.errors.append(f"ligne {row} : {message}")


def _to_int(v: Any) -> int | None:
    if v is None or (isinstance(v, str) and v.strip() in ("", "-", "NA", "null", "None")):
        return None
    if isinstance(v, str):
        v = v.strip()
        if v.lower().startswith("0x"):
            return int(v, 16)
    return int(float(v))


def _to_float(v: Any) -> float | None:
    if v is None or (isinstance(v, str) and v.strip() in ("", "-", "NA", "null", "None")):
        return None
    return float(str(v).replace(",", ".")) if isinstance(v, str) else float(v)


def _to_bool(v: Any, default: bool = True) -> bool:
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "oui", "y", "o")


def _resolve_columns(columns: Iterable[str],
                     mapping: dict[str, str] | None) -> tuple[dict[str, str], list[str]]:
    """Associe chaque champ canonique à une colonne source ; renvoie aussi les
    colonnes interdites détectées."""
    cols = list(columns)
    forbidden = [c for c in cols if is_forbidden(c)]
    allowed = {_norm(c): c for c in cols if c not in forbidden}
    resolved: dict[str, str] = {}
    if mapping:
        for canonical, src in mapping.items():
            if canonical not in FIELD_ALIASES:
                raise ValueError(f"champ de destination inconnu dans le mappage : {canonical}")
            if is_forbidden(src):
                raise ValueError(f"le mappage vers une colonne interdite ({src}) est refusé")
            # Comparaison tolérante (casse, espaces, tirets).
            if _norm(src) in allowed:
                resolved[canonical] = allowed[_norm(src)]
    for canonical, aliases in FIELD_ALIASES.items():
        if canonical in resolved:
            continue
        for alias in aliases:
            if alias in allowed:
                resolved[canonical] = allowed[alias]
                break
    return resolved, forbidden


def parse_records(records: list[dict[str, Any]], provenance: Provenance,
                  source_name: str = "records", mapping: dict[str, str] | None = None,
                  assume_tz: str | None = None, constants: dict[str, Any] | None = None
                  ) -> tuple[list[CellObservation], ImportReport]:
    """``constants`` fournit une valeur fixe pour un champ absent du fichier
    (ex. ``{"technology": "LTE"}`` pour un export mono-technologie)."""
    constants = dict(constants or {})
    bad = [k for k in constants if k not in FIELD_ALIASES]
    if bad:
        raise ValueError(f"constantes inconnues : {bad}")
    report = ImportReport(source_name=source_name)
    if not records:
        report.warnings.append("aucune ligne à importer")
        return [], report
    columns: list[str] = []
    for r in records:
        for k in r:
            if k not in columns:
                columns.append(k)
    resolved, forbidden = _resolve_columns(columns, mapping)
    report.dropped_fields = forbidden
    if forbidden:
        report.warnings.append(
            "colonnes d'identifiants personnels supprimées sans lecture : " + ", ".join(forbidden))
    missing = [f for f in ("timestamp", "technology")
               if f not in resolved and f not in constants]
    if missing:
        raise ValueError(f"colonnes obligatoires absentes : {', '.join(missing)}")
    bcast_cols = [c for c in columns if _norm(c).startswith(BROADCAST_PREFIX) and c not in forbidden]

    params = dict(provenance.parameters)
    params.setdefault("timezone_assumed_for_naive", assume_tz or "UTC")
    # Un fichier marqué comme synthétique reste une SIMULATION : le marquage ne
    # peut jamais être retiré à l'import.
    sim_flag = any(_to_bool(r.get("is_simulation"), default=False) for r in records)
    sim_flag = sim_flag or any(str(r.get("source", "")).upper().startswith("SIMULATION")
                               for r in records)
    if sim_flag and not provenance.is_simulation:
        params["simulation_flag_from_file"] = True
    prov = Provenance(provenance.source, provenance.method,
                      provenance.is_simulation or sim_flag, params)

    out: list[CellObservation] = []
    for i, raw in enumerate(records, start=1):
        report.rows_total += 1
        # Suppression immédiate des champs interdits.
        rec = {k: v for k, v in raw.items() if k not in forbidden}

        def g(name: str) -> Any:
            col = resolved.get(name)
            return rec.get(col) if col else constants.get(name)

        try:
            ts = to_utc(g("timestamp"), assume_tz)
        except TimestampError as exc:
            report.add_error(i, str(exc))
            continue
        for problem in check_plausible(ts):
            report.warnings.append(f"ligne {i} : {problem}")
        tech = Technology.parse(g("technology"))
        if tech == Technology.UNKNOWN:
            report.add_error(i, f"technologie inconnue : {g('technology')!r}")
            continue
        try:
            channel = _to_int(g("channel"))
            freq = _to_float(g("frequency_mhz"))
            if freq is None:
                freq = channel_to_mhz(tech, channel)
            rssi = _to_float(g("rssi_dbm"))
            if rssi is not None and not -160.0 <= rssi <= 0.0:
                report.add_error(i, f"puissance hors plage plausible : {rssi} dBm")
                continue
            lat, lon = _to_float(g("latitude")), _to_float(g("longitude"))
            if (lat is None) != (lon is None) or (lat is not None and not (
                    -90 <= lat <= 90 and -180 <= lon <= 180)):
                report.add_error(i, "coordonnées invalides")
                continue
            pk_raw = str(g("position_kind") or "").strip().upper()
            if lat is None:
                pos_kind = PositionKind.NONE
            elif pk_raw in ("GPS", "GNSS", "TRUE", "1"):
                pos_kind = PositionKind.GPS
            else:
                # Sans indication explicite d'un fix GNSS, la position est réputée estimée.
                pos_kind = PositionKind.ESTIMATED
            broadcast = {_norm(c)[len(BROADCAST_PREFIX):]: rec[c] for c in bcast_cols
                         if rec.get(c) not in (None, "")}
            raw_b = rec.get("broadcast")
            if isinstance(raw_b, str) and raw_b.strip().startswith("{"):
                raw_b = json.loads(raw_b)
            if isinstance(raw_b, dict):
                rec["broadcast"] = raw_b
                broadcast.update({k: v for k, v in rec["broadcast"].items() if not is_forbidden(k)})
            obs = CellObservation(
                timestamp=ts, technology=tech, mcc=_to_int(g("mcc")), mnc=_to_int(g("mnc")),
                area_code=_to_int(g("area_code")), cell_id=_to_int(g("cell_id")),
                channel=channel, frequency_mhz=freq, pci=_to_int(g("pci")), rssi_dbm=rssi,
                quality_db=_to_float(g("quality_db")), latitude=lat, longitude=lon,
                position_kind=pos_kind, broadcast=broadcast,
                serving=_to_bool(g("serving")), provenance=prov)
        except (TypeError, ValueError) as exc:
            report.add_error(i, f"valeur invalide ({exc})")
            continue
        out.append(obs)
        report.rows_imported += 1
    return out, report


def import_csv_text(text: str, provenance: Provenance, source_name: str = "csv",
                    mapping: dict[str, str] | None = None, assume_tz: str | None = None,
                    constants: dict[str, Any] | None = None
                    ) -> tuple[list[CellObservation], ImportReport]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    return parse_records(list(reader), provenance, source_name, mapping, assume_tz, constants)


def import_json_text(text: str, provenance: Provenance, source_name: str = "json",
                     mapping: dict[str, str] | None = None, assume_tz: str | None = None,
                     constants: dict[str, Any] | None = None
                     ) -> tuple[list[CellObservation], ImportReport]:
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get("observations", [])
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise ValueError("le JSON doit contenir une liste d'objets d'observation")
    return parse_records(data, provenance, source_name, mapping, assume_tz, constants)


def read_records(path: str | Path) -> list[dict[str, Any]]:
    """Lit les enregistrements bruts d'un fichier CSV/JSON (sans interprétation)."""
    p = Path(path)
    text = p.read_text(encoding="utf-8-sig")
    if p.suffix.lower() == ".json":
        data = json.loads(text)
        data = data.get("observations", []) if isinstance(data, dict) else data
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise ValueError("le JSON doit contenir une liste d'objets d'observation")
        return data
    if p.suffix.lower() == ".csv":
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return list(csv.DictReader(io.StringIO(text), dialect=dialect))
    raise ValueError(f"format non pris en charge : {p.suffix}")


def import_file(path: str | Path, provenance: Provenance, mapping: dict[str, str] | None = None,
                assume_tz: str | None = None, constants: dict[str, Any] | None = None
                ) -> tuple[list[CellObservation], ImportReport]:
    p = Path(path)
    text = p.read_text(encoding="utf-8-sig")
    if p.suffix.lower() == ".json":
        return import_json_text(text, provenance, p.name, mapping, assume_tz, constants)
    if p.suffix.lower() == ".csv":
        return import_csv_text(text, provenance, p.name, mapping, assume_tz, constants)
    raise ValueError(f"format non pris en charge : {p.suffix}")
