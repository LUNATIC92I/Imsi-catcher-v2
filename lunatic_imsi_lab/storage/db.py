"""Persistance locale SQLite via SQLAlchemy.

La base est locale par défaut (aucune connexion réseau). Les tables stockent
des observations de cellules, des balayages spectraux, des alertes, des
rapports et le journal d'audit. Aucune table ne prévoit de colonne pour des
identifiants d'abonnés ou d'appareils.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String,
                        Text, create_engine, delete, func, select)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import TypeDecorator

from lunatic_imsi_lab.core.models import (Alert, CellObservation, ConfidenceLevel, PositionKind,
                                          Provenance, Severity, SpectrumSweep, Technology)


class UTCDateTime(TypeDecorator):
    """SQLite ne conserve pas le fuseau : on stocke en UTC et on le restaure."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("horodatage naïf refusé par la base (utiliser timeutils.to_utc)")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class ObservationRow(Base):
    __tablename__ = "observations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    technology: Mapped[str] = mapped_column(String(8))
    mcc: Mapped[int | None] = mapped_column(Integer)
    mnc: Mapped[int | None] = mapped_column(Integer)
    area_code: Mapped[int | None] = mapped_column(Integer)
    cell_id: Mapped[int | None] = mapped_column(Integer)
    channel: Mapped[int | None] = mapped_column(Integer)
    frequency_mhz: Mapped[float | None] = mapped_column(Float)
    pci: Mapped[int | None] = mapped_column(Integer)
    rssi_dbm: Mapped[float | None] = mapped_column(Float)
    quality_db: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    position_kind: Mapped[str] = mapped_column(String(12), default="NONE")
    broadcast_json: Mapped[str] = mapped_column(Text, default="{}")
    serving: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(200))
    method: Mapped[str] = mapped_column(String(100))
    is_simulation: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    parameters_json: Mapped[str] = mapped_column(Text, default="{}")
    dataset: Mapped[str] = mapped_column(String(100), default="default", index=True)


class SweepRow(Base):
    __tablename__ = "sweeps"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    start_hz: Mapped[float] = mapped_column(Float)
    stop_hz: Mapped[float] = mapped_column(Float)
    rbw_hz: Mapped[float | None] = mapped_column(Float)
    frequencies: Mapped[bytes] = mapped_column(LargeBinary)
    power: Mapped[bytes] = mapped_column(LargeBinary)
    source: Mapped[str] = mapped_column(String(200))
    method: Mapped[str] = mapped_column(String(100))
    is_simulation: Mapped[bool] = mapped_column(Boolean, default=False)
    parameters_json: Mapped[str] = mapped_column(Text, default="{}")
    dataset: Mapped[str] = mapped_column(String(100), default="default", index=True)


class AlertRow(Base):
    __tablename__ = "alerts"
    alert_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    first_seen: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime)
    priority: Mapped[int] = mapped_column(Integer)
    confidence_score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))
    summary: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text)
    is_simulation: Mapped[bool] = mapped_column(Boolean, default=False)
    dataset: Mapped[str] = mapped_column(String(100), default="default", index=True)


class ReportRow(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    title: Mapped[str] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(String(500))
    fmt: Mapped[str] = mapped_column(String(8))
    sha256: Mapped[str] = mapped_column(String(64))


class AuditRow(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime)
    user: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[str] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64))


class ImportedFileRow(Base):
    __tablename__ = "imported_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime)
    original_name: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    rows_imported: Mapped[int] = mapped_column(Integer)
    rows_rejected: Mapped[int] = mapped_column(Integer)
    dataset: Mapped[str] = mapped_column(String(100), ForeignKey("datasets.name"))


class UserAccountRow(Base):
    """Comptes locaux. Seule une empreinte PBKDF2 du mot de passe est stockée."""

    __tablename__ = "user_accounts"
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    role: Mapped[str] = mapped_column(String(20))
    salt: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(128))
    iterations: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class DatasetRow(Base):
    __tablename__ = "datasets"
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    is_simulation: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    authorization_ref: Mapped[str] = mapped_column(String(200), default="")


# ---------------------------------------------------------------------------
# Conversions modèle <-> ligne
# ---------------------------------------------------------------------------

def _obs_to_row(obs: CellObservation, dataset: str) -> ObservationRow:
    p = obs.provenance
    return ObservationRow(
        id=obs.id, timestamp=obs.timestamp, technology=obs.technology.value, mcc=obs.mcc,
        mnc=obs.mnc, area_code=obs.area_code, cell_id=obs.cell_id, channel=obs.channel,
        frequency_mhz=obs.frequency_mhz, pci=obs.pci, rssi_dbm=obs.rssi_dbm,
        quality_db=obs.quality_db, latitude=obs.latitude, longitude=obs.longitude,
        position_kind=obs.position_kind.value, broadcast_json=json.dumps(obs.broadcast, default=str),
        serving=obs.serving, source=p.source, method=p.method, is_simulation=p.is_simulation,
        parameters_json=json.dumps(p.parameters, default=str), dataset=dataset)


def _row_to_obs(row: ObservationRow) -> CellObservation:
    prov = Provenance(row.source, row.method, row.is_simulation, json.loads(row.parameters_json))
    return CellObservation(
        id=row.id, timestamp=row.timestamp, technology=Technology(row.technology), mcc=row.mcc,
        mnc=row.mnc, area_code=row.area_code, cell_id=row.cell_id, channel=row.channel,
        frequency_mhz=row.frequency_mhz, pci=row.pci, rssi_dbm=row.rssi_dbm,
        quality_db=row.quality_db, latitude=row.latitude, longitude=row.longitude,
        position_kind=PositionKind(row.position_kind), broadcast=json.loads(row.broadcast_json),
        serving=row.serving, provenance=prov)


class Database:
    """Façade d'accès à la base locale."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        url = "sqlite://" if str(path) == ":memory:" else f"sqlite:///{Path(path)}"
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Les opérations longues de l'IHM s'exécutent dans un thread de travail
        # (une seule à la fois) : la connexion SQLite doit pouvoir changer de thread.
        self.engine = create_engine(url, future=True,
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self._session = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> Session:
        return self._session()

    # -- jeux de données ---------------------------------------------------
    def ensure_dataset(self, name: str, is_simulation: bool = False, description: str = "",
                       authorization_ref: str = "") -> None:
        with self.session() as s, s.begin():
            if s.get(DatasetRow, name) is None:
                s.add(DatasetRow(name=name, created_at=datetime.now(timezone.utc),
                                 is_simulation=is_simulation, description=description,
                                 authorization_ref=authorization_ref))

    def list_datasets(self) -> list[DatasetRow]:
        with self.session() as s:
            return list(s.scalars(select(DatasetRow).order_by(DatasetRow.created_at)))

    # -- observations ------------------------------------------------------
    def add_observations(self, observations: Iterable[CellObservation],
                         dataset: str = "default") -> int:
        obs_list = list(observations)
        is_sim = bool(obs_list) and all(o.provenance.is_simulation for o in obs_list)
        self.ensure_dataset(dataset, is_simulation=is_sim)
        with self.session() as s, s.begin():
            for obs in obs_list:
                s.merge(_obs_to_row(obs, dataset))
        return len(obs_list)

    def get_observations(self, dataset: str | None = None, start: datetime | None = None,
                         end: datetime | None = None,
                         include_simulation: bool = True) -> list[CellObservation]:
        stmt = select(ObservationRow).order_by(ObservationRow.timestamp)
        if dataset:
            stmt = stmt.where(ObservationRow.dataset == dataset)
        if start:
            stmt = stmt.where(ObservationRow.timestamp >= start)
        if end:
            stmt = stmt.where(ObservationRow.timestamp <= end)
        if not include_simulation:
            stmt = stmt.where(ObservationRow.is_simulation.is_(False))
        with self.session() as s:
            return [_row_to_obs(r) for r in s.scalars(stmt)]

    def count_observations(self, dataset: str | None = None) -> int:
        stmt = select(func.count()).select_from(ObservationRow)
        if dataset:
            stmt = stmt.where(ObservationRow.dataset == dataset)
        with self.session() as s:
            return int(s.scalar(stmt) or 0)

    # -- balayages ---------------------------------------------------------
    def add_sweep(self, sweep: SpectrumSweep, dataset: str = "default") -> None:
        self.ensure_dataset(dataset, is_simulation=sweep.provenance.is_simulation)
        p = sweep.provenance
        with self.session() as s, s.begin():
            s.merge(SweepRow(
                id=sweep.id, timestamp=sweep.timestamp, start_hz=sweep.start_hz,
                stop_hz=sweep.stop_hz, rbw_hz=sweep.rbw_hz,
                frequencies=sweep.frequencies_hz.astype("<f8").tobytes(),
                power=sweep.power_dbm.astype("<f8").tobytes(), source=p.source, method=p.method,
                is_simulation=p.is_simulation, parameters_json=json.dumps(p.parameters, default=str),
                dataset=dataset))

    def get_sweeps(self, dataset: str | None = None) -> list[SpectrumSweep]:
        stmt = select(SweepRow).order_by(SweepRow.timestamp)
        if dataset:
            stmt = stmt.where(SweepRow.dataset == dataset)
        with self.session() as s:
            return [SpectrumSweep(
                id=r.id, timestamp=r.timestamp,
                frequencies_hz=np.frombuffer(r.frequencies, dtype="<f8").copy(),
                power_dbm=np.frombuffer(r.power, dtype="<f8").copy(), rbw_hz=r.rbw_hz,
                provenance=Provenance(r.source, r.method, r.is_simulation,
                                      json.loads(r.parameters_json)))
                for r in s.scalars(stmt)]

    # -- alertes -----------------------------------------------------------
    def save_alerts(self, alerts: Iterable[Alert], dataset: str = "default") -> int:
        alerts = list(alerts)
        self.ensure_dataset(dataset)
        with self.session() as s, s.begin():
            for a in alerts:
                s.merge(AlertRow(
                    alert_id=a.alert_id, created_at=a.created_at, first_seen=a.first_seen,
                    last_seen=a.last_seen, priority=a.priority,
                    confidence_score=a.confidence_score, confidence=a.confidence.value,
                    severity=a.severity.value, summary=a.summary,
                    payload_json=json.dumps(a.to_dict(), default=str),
                    is_simulation=a.is_simulation, dataset=dataset))
        return len(alerts)

    def get_alerts(self, dataset: str | None = None) -> list[Alert]:
        stmt = select(AlertRow).order_by(AlertRow.first_seen)
        if dataset:
            stmt = stmt.where(AlertRow.dataset == dataset)
        out = []
        with self.session() as s:
            for r in s.scalars(stmt):
                d = json.loads(r.payload_json)
                out.append(Alert(
                    alert_id=r.alert_id, created_at=r.created_at, first_seen=r.first_seen,
                    last_seen=r.last_seen,
                    cell_key=tuple(d["cell_key"]) if d.get("cell_key") else None,
                    rules=d["rules"], priority=r.priority, confidence_score=r.confidence_score,
                    confidence=ConfidenceLevel(r.confidence), severity=Severity(r.severity),
                    summary=r.summary, explanation=d["explanation"],
                    false_positives=d["false_positives"],
                    recommended_checks=d["recommended_checks"],
                    observation_ids=d["observation_ids"], sources=d["sources"],
                    is_simulation=r.is_simulation))
        return out

    # -- rapports ----------------------------------------------------------
    def register_report(self, title: str, path: str, fmt: str, sha256: str) -> None:
        with self.session() as s, s.begin():
            s.add(ReportRow(created_at=datetime.now(timezone.utc), title=title, path=path,
                            fmt=fmt, sha256=sha256))

    def list_reports(self) -> list[ReportRow]:
        with self.session() as s:
            return list(s.scalars(select(ReportRow).order_by(ReportRow.created_at.desc())))

    # -- suppression -------------------------------------------------------
    def delete_dataset_rows(self, dataset: str) -> dict[str, int]:
        """Suppression brute ; à n'appeler qu'au travers de ``security.deletion``."""
        counts = {}
        with self.session() as s, s.begin():
            for model in (ObservationRow, SweepRow, AlertRow):
                res = s.execute(delete(model).where(model.dataset == dataset))
                counts[model.__tablename__] = res.rowcount or 0
            s.execute(delete(ImportedFileRow).where(ImportedFileRow.dataset == dataset))
            s.execute(delete(DatasetRow).where(DatasetRow.name == dataset))
        return counts
