"""Couche de services partagée par l'interface graphique et la ligne de commande.

Chaque opération vérifie la permission de l'utilisateur et est journalisée.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from lunatic_imsi_lab.config import AppConfig
from lunatic_imsi_lab.core.models import CellObservation, SpectrumSweep
from lunatic_imsi_lab.core.timeutils import utcnow
from lunatic_imsi_lab.correlation import analysis as corr
from lunatic_imsi_lab.detection.baseline import Baseline
from lunatic_imsi_lab.detection.engine import AnalysisResult, DetectionEngine, spectrum_indicators
from lunatic_imsi_lab.detection.rules import RuleConfig
from lunatic_imsi_lab.importers.cells import ImportReport
from lunatic_imsi_lab.importers.profiles import BUILTIN_PROFILES, all_profiles, validate_profile
from lunatic_imsi_lab.importers.service import import_observations_file
from lunatic_imsi_lab.radio.spectrum import detect_power_variations
from lunatic_imsi_lab.reports.builder import ReportInput, build_report
from lunatic_imsi_lab.reports.render import write_html, write_pdf
from lunatic_imsi_lab.security.audit import AuditLog
from lunatic_imsi_lab.security.auth import AuthError, UserStore
from lunatic_imsi_lab.security.deletion import delete_dataset
from lunatic_imsi_lab.security.rbac import Permission, Role, User
from lunatic_imsi_lab.simulation.cells import SimulationParams, SimulationResult, simulate
from lunatic_imsi_lab.simulation.spectrum import SpectrumScenario
from lunatic_imsi_lab.storage.db import Database

log = logging.getLogger("lunatic")


@dataclass
class Workspace:
    """État courant d'analyse (observations, référence, résultat)."""

    dataset: str = ""
    baseline_dataset: str = ""
    observations: list[CellObservation] = field(default_factory=list)
    baseline_obs: list[CellObservation] = field(default_factory=list)
    sweeps: list[SpectrumSweep] = field(default_factory=list)
    result: AnalysisResult | None = None

    @property
    def is_simulation(self) -> bool:
        return any(o.provenance.is_simulation for o in self.observations) or any(
            s.provenance.is_simulation for s in self.sweeps)


class Lab:
    def __init__(self, config: AppConfig | None = None, user: User | None = None,
                 db: Database | None = None) -> None:
        self.config = config or AppConfig()
        Path(self.config.data_dir).mkdir(parents=True, exist_ok=True)
        self.db = db or Database(self.config.db_path)
        self.audit = AuditLog(self.db)
        self.users = UserStore(self.db)
        self.user = user or User(self.config.operator_name, Role(self.config.operator_role))
        if self.users.has_users() and not self.user.authenticated:
            raise AuthError("des comptes existent : une authentification est requise")
        self.engine = self._make_engine()
        self.ws = Workspace()

    @property
    def auth_enabled(self) -> bool:
        return self.users.has_users()

    @classmethod
    def login(cls, config: AppConfig, name: str, password: str) -> "Lab":
        """Authentifie l'utilisateur et journalise la tentative (réussie ou non)."""
        db = Database(config.db_path)
        store, audit = UserStore(db), AuditLog(db)
        try:
            user = store.authenticate(name, password)
        except AuthError as exc:
            audit.record(User(name[:80] or "?", Role.VIEWER), "login_failed", str(exc))
            raise
        audit.record(user, "login", {"role": user.role.value})
        return cls(config, user, db)

    def add_user(self, name: str, role: Role, password: str) -> None:
        bootstrap = not self.users.has_users()
        self.users.add_user(self.user, name, Role(role), password)
        self.audit.record(self.user, "add_user", {"name": name, "role": Role(role).value,
                                                  "bootstrap": bootstrap})
        if bootstrap:
            # L'authentification est désormais obligatoire : la session non
            # authentifiée en cours perd ses droits jusqu'à reconnexion.
            self.user = User(self.user.name, Role.VIEWER)

    def set_user_disabled(self, name: str, disabled: bool) -> None:
        self.users.set_disabled(self.user, name, disabled)
        self.audit.record(self.user, "disable_user" if disabled else "enable_user",
                          {"name": name})

    def change_password(self, name: str, new_password: str,
                        old_password: str | None = None) -> None:
        self.users.change_password(self.user, name, new_password, old_password)
        self.audit.record(self.user, "change_password", {"name": name})

    def _make_engine(self) -> DetectionEngine:
        return DetectionEngine(config=RuleConfig.from_dict(self.config.rule_config),
                               disabled_rules=self.config.disabled_rules)

    def update_rules(self, params: dict, disabled_rules: Sequence[str] = ()) -> RuleConfig:
        """Modifie les seuils de détection (administrateur, journalisé, persistant)."""
        self.user.require(Permission.CONFIGURE_RULES)
        new = RuleConfig.from_dict(params)          # valide avant toute modification
        engine = DetectionEngine(config=new, disabled_rules=disabled_rules)
        before = {"rules": self.engine.config.to_dict(), "disabled": self.engine.disabled_rules}
        self.engine = engine
        self.config.rule_config = new.to_dict()
        self.config.disabled_rules = list(engine.disabled_rules)
        self.config.save()
        self.audit.record(self.user, "update_rules", {
            "before": before, "after": {"rules": new.to_dict(),
                                        "disabled": engine.disabled_rules}})
        return new

    # -- simulation ---------------------------------------------------------
    def run_simulation(self, params: SimulationParams, with_spectrum: bool = True,
                       n_sweeps: int = 60) -> SimulationResult:
        self.user.require(Permission.SIMULATE)
        res = simulate(params)
        tag = f"SIMULATION-{params.scenario.value}-{params.seed}"
        # Une nouvelle exécution remplace la précédente (jamais de mélange de deux runs).
        # Seuls des jeux marqués SIMULATION peuvent être remplacés ainsi.
        existing = {d.name: d for d in self.db.list_datasets()}
        for name in (tag, tag + "-ref"):
            if name in existing:
                if not existing[name].is_simulation:
                    raise ValueError(f"le jeu « {name} » contient des mesures réelles")
                self.db.delete_dataset_rows(name)
        self.db.ensure_dataset(tag + "-ref", is_simulation=True,
                               description="Référence synthétique")
        self.db.ensure_dataset(tag, is_simulation=True, description="Observations synthétiques")
        self.db.add_observations(res.baseline, tag + "-ref")
        self.db.add_observations(res.observations, tag)
        sweeps: list[SpectrumSweep] = []
        if with_spectrum:
            sc = (SpectrumScenario.with_anomaly(params.seed) if params.scenario.value ==
                  "synthetic_anomaly" else SpectrumScenario.default(params.seed))
            # Balayages répartis sur la même période que les observations de cellules.
            if res.observations:
                sc.start = res.observations[0].timestamp
                sc.step_s = params.duration_minutes * 60 / max(n_sweeps, 1)
            sweeps = sc.series(n_sweeps)
            for s in sweeps:
                self.db.add_sweep(s, tag)
        self.ws = Workspace(dataset=tag, baseline_dataset=tag + "-ref",
                            observations=res.observations, baseline_obs=res.baseline,
                            sweeps=sweeps)
        self.audit.record(self.user, "simulation", {"dataset": tag, **params.to_dict()})
        return res

    # -- import ---------------------------------------------------------------
    def import_profiles(self) -> dict[str, dict]:
        return all_profiles(self.config.import_profiles)

    def import_file(self, path: str | Path, source: str, dataset: str,
                    authorization_ref: str = "", assume_tz: str | None = None,
                    profile: str | dict | None = None) -> ImportReport:
        """``profile`` : nom d'un profil (intégré ou personnalisé) ou profil explicite."""
        if isinstance(profile, str) and profile:
            profiles = self.import_profiles()
            if profile not in profiles:
                raise ValueError(f"profil d'import inconnu : {profile}")
            name, prof = profile, profiles[profile]
        elif isinstance(profile, dict):
            name, prof = "fichier", validate_profile(profile)
        else:
            name, prof = "auto", BUILTIN_PROFILES["auto"]
        return import_observations_file(
            self.db, self.audit, self.user, path, self.config.vault_dir, source=source,
            dataset=dataset, authorization_ref=authorization_ref or self.config.authorization_ref,
            assume_tz=assume_tz, mapping=prof["columns"], constants=prof["constants"],
            profile_name=name)

    def save_import_profile(self, name: str, profile: dict) -> None:
        self.user.require(Permission.CONFIGURE_DEVICES)
        if not name or name in BUILTIN_PROFILES:
            raise ValueError("nom de profil invalide ou réservé")
        self.config.import_profiles[name] = validate_profile(profile)
        self.config.save()
        self.audit.record(self.user, "save_import_profile", {"name": name, **profile})

    def delete_import_profile(self, name: str) -> None:
        self.user.require(Permission.CONFIGURE_DEVICES)
        if name not in self.config.import_profiles:
            raise ValueError(f"profil personnalisé inconnu : {name}")
        del self.config.import_profiles[name]
        self.config.save()
        self.audit.record(self.user, "delete_import_profile", {"name": name})

    def load(self, dataset: str, baseline_dataset: str = "") -> Workspace:
        self.user.require(Permission.VIEW)
        self.ws = Workspace(dataset=dataset, baseline_dataset=baseline_dataset,
                            observations=self.db.get_observations(dataset),
                            baseline_obs=self.db.get_observations(baseline_dataset)
                            if baseline_dataset else [],
                            sweeps=self.db.get_sweeps(dataset))
        return self.ws

    # -- analyse ---------------------------------------------------------------
    def analyze(self) -> AnalysisResult:
        self.user.require(Permission.ANALYZE)
        ws = self.ws
        baseline = Baseline.from_observations(ws.baseline_obs)
        extra = spectrum_indicators(detect_power_variations(ws.sweeps),
                                    is_simulation=any(s.provenance.is_simulation
                                                      for s in ws.sweeps)) if ws.sweeps else []
        ws.result = self.engine.run(ws.observations, baseline, extra)
        if ws.dataset:
            self.db.save_alerts(ws.result.alerts, ws.dataset)
        self.audit.record(self.user, "analyze", {
            "dataset": ws.dataset, "baseline": ws.baseline_dataset,
            "alerts": len(ws.result.alerts), "assessment": ws.result.assessment})
        return ws.result

    # -- export / rapports -------------------------------------------------------
    def export(self, directory: str | Path, stem: str | None = None) -> list[Path]:
        self.user.require(Permission.EXPORT)
        ws = self.ws
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        stem = stem or (ws.dataset or "export")
        alerts = ws.result.alerts if ws.result else []
        timeline = corr.build_timeline(ws.observations, alerts)
        paths = [corr.export_csv(d / f"{stem}_observations.csv", ws.observations),
                 corr.export_json(d / f"{stem}.json", ws.observations, alerts, timeline,
                                  {"dataset": ws.dataset, "baseline": ws.baseline_dataset,
                                   "exported_at": utcnow().isoformat(),
                                   "exported_by": self.user.name})]
        (d / f"{stem}_alerts.csv").write_text(corr.alerts_to_csv(alerts), encoding="utf-8")
        paths.append(d / f"{stem}_alerts.csv")
        self.audit.record(self.user, "export", {"dataset": ws.dataset,
                                                "files": [p.name for p in paths]})
        return paths

    def generate_report(self, title: str, scope: str, directory: str | Path | None = None,
                        formats: Sequence[str] = ("pdf", "html")) -> list[Path]:
        self.user.require(Permission.REPORT)
        ws = self.ws
        if ws.result is None:
            self.analyze()
        content = build_report(ReportInput(
            title=title, scope=scope, operator=self.user.name,
            authorization_ref=self.config.authorization_ref, observations=ws.observations,
            analysis=ws.result, sweeps=ws.sweeps,
            equipment=[f"{d.name} ({d.driver})" for d in self.config.devices if d.enabled]))
        out_dir = Path(directory or self.config.reports_dir)
        stamp = utcnow().strftime("%Y%m%d-%H%M%S")
        base = out_dir / f"rapport_{ws.dataset or 'analyse'}_{stamp}"
        paths = []
        for fmt in formats:
            writer = {"pdf": write_pdf, "html": write_html}[fmt]
            p, digest = writer(content, base.with_suffix("." + fmt))
            self.db.register_report(title, str(p), fmt, digest)
            paths.append(p)
        self.audit.record(self.user, "report", {"dataset": ws.dataset,
                                                "files": [p.name for p in paths]})
        return paths

    # -- suppression --------------------------------------------------------------
    def delete_dataset(self, dataset: str, reason: str, confirm: str) -> dict[str, int]:
        counts = delete_dataset(self.db, self.audit, self.user, dataset, reason, confirm)
        if self.ws.dataset == dataset:
            self.ws = Workspace()
        return counts
