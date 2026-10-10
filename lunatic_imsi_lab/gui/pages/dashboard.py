from __future__ import annotations

from collections import Counter

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget
from PySide6.QtCore import Qt

from lunatic_imsi_lab.correlation.analysis import serving_changes
from lunatic_imsi_lab.detection.engine import Assessment
from lunatic_imsi_lab.gui import theme
from lunatic_imsi_lab.gui.pages.base import Page
from lunatic_imsi_lab.gui.widgets import Card, PlotWidget, RecordTable
from lunatic_imsi_lab.radio.receivers import make_receiver
from lunatic_imsi_lab.reports.charts import plot_rssi_timeline


class DashboardPage(Page):
    nav_label = "Tableau de bord"
    title = "Tableau de bord"
    subtitle = ("Vue d'ensemble de l'espace de travail. Les données proviennent de mesures "
                "autorisées importées ou du mode SIMULATION explicitement signalé.")

    def build(self) -> None:
        grid = QGridLayout()
        grid.setSpacing(10)
        names = [("system", "État du système"), ("devices", "Équipements"),
                 ("tech", "Technologies observées"), ("bands", "Bandes configurées"),
                 ("power", "Puissance du signal"), ("changes", "Changements de cellule"),
                 ("alerts", "Anomalies"), ("assess", "Évaluation globale")]
        self.cards: dict[str, Card] = {}
        for i, (key, label) in enumerate(names):
            c = Card(label)
            self.cards[key] = c
            grid.addWidget(c, i // 4, i % 4)
        self.layout_.addLayout(grid)

        split = QSplitter(Qt.Horizontal)
        self.plot = PlotWidget(height=3.0, toolbar=False)
        split.addWidget(self.plot)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(QLabel("Alertes et niveau de confiance"))
        self.alerts = RecordTable([
            ("Alerte", lambda a: a.alert_id), ("Priorité", lambda a: a.priority),
            ("Confiance", lambda a: a.confidence.value), ("Sévérité", lambda a: a.severity.value),
            ("Résumé", lambda a: a.summary)])
        self.alerts.model.color_fn = lambda a: theme.SEVERITY_COLORS.get(a.severity.value)
        self.alerts.sort_by(1)
        rv.addWidget(self.alerts)
        hist = QHBoxLayout()
        col1, col2 = QVBoxLayout(), QVBoxLayout()
        col1.addWidget(QLabel("Historique des analyses"))
        self.history = RecordTable([("Date", lambda e: f"{e.timestamp:%Y-%m-%d %H:%M}"),
                                    ("Opérateur", lambda e: e.user),
                                    ("Détails", lambda e: e.details)])
        col1.addWidget(self.history)
        col2.addWidget(QLabel("Derniers rapports"))
        self.reports = RecordTable([("Date", lambda r: f"{r.created_at:%Y-%m-%d %H:%M}"),
                                    ("Titre", lambda r: r.title), ("Format", lambda r: r.fmt)])
        col2.addWidget(self.reports)
        hist.addLayout(col1)
        hist.addLayout(col2)
        rv.addLayout(hist)
        split.addWidget(right)
        split.setSizes([700, 700])
        self.layout_.addWidget(split, 1)

    def refresh(self) -> None:
        super().refresh()
        lab, ws = self.lab, self.lab.ws
        cfg = lab.config
        self.cards["system"].set("Opérationnel", f"{'Local uniquement' if cfg.local_only else 'Réseau'}"
                                 f" · audit {'intègre' if lab.audit.verify()[0] else 'ALTÉRÉ'}",
                                 theme.GREEN)
        avail = []
        for d in cfg.devices:
            if d.enabled:
                try:
                    info = make_receiver(d.driver, args=d.args).info()
                    avail.append(f"{d.name}: {'OK' if info.available else 'indisponible'}")
                except Exception as exc:
                    avail.append(f"{d.name}: {exc}")
        self.cards["devices"].set(str(sum(': OK' in a for a in avail)), " · ".join(avail))
        tech = Counter(o.technology.value for o in ws.observations)
        self.cards["tech"].set(" / ".join(sorted(tech)) or "—",
                               ", ".join(f"{t}: {n}" for t, n in tech.most_common()))
        self.cards["bands"].set(str(len(cfg.bands)), ", ".join(b.name for b in cfg.bands[:4])
                                + ("…" if len(cfg.bands) > 4 else ""))
        r = sorted(o.rssi_dbm for o in ws.observations if o.rssi_dbm is not None)
        self.cards["power"].set(f"{r[len(r)//2]:.0f} dBm" if r else "—",
                                f"min {r[0]:.0f} / max {r[-1]:.0f} dBm" if r else "aucune mesure")
        self.cards["changes"].set(str(serving_changes(ws.observations)),
                                  f"{len({o.cell_key for o in ws.observations})} cellules vues")
        res = ws.result
        if res:
            sev = Counter(a.severity.value for a in res.alerts)
            top = max((a.severity.value for a in res.alerts),
                      key=["INFO", "LOW", "MEDIUM", "HIGH"].index, default="INFO")
            self.cards["alerts"].set(str(len(res.alerts)), " · ".join(
                f"{k}: {v}" for k, v in sev.items()) or "aucune",
                theme.SEVERITY_COLORS.get(top))
            self.cards["assess"].set(Assessment.LABEL[res.assessment],
                                     "À confirmer par des vérifications indépendantes"
                                     if res.assessment == Assessment.CONVERGENT_INDICATORS
                                     else "Voir la page Anomalies")
            self.alerts.set_rows(res.alerts)
        else:
            self.cards["alerts"].set("—", "analyse non lancée")
            self.cards["assess"].set("—", "lancer l'analyse")
            self.alerts.set_rows([])
        self.history.set_rows([e for e in lab.audit.entries(200) if e.action == "analyze"][:20])
        self.reports.set_rows(lab.db.list_reports()[:20])
        ax = self.plot.ax()
        if ws.observations:
            plot_rssi_timeline(ax, ws.observations, res.alerts if res else [], max_cells=6)
        else:
            ax.text(0.5, 0.5, "Aucune donnée — importer des mesures ou lancer une simulation",
                    ha="center", va="center", transform=ax.transAxes, color=theme.MUTED)
        if ws.is_simulation:
            self.plot.figure.text(0.99, 0.98, "SIMULATION", ha="right", va="top",
                                  color=theme.RED, fontweight="bold")
        self.plot.draw()
