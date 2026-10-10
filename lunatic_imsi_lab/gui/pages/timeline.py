from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton,
                               QSplitter, QTabWidget)

from lunatic_imsi_lab.correlation import analysis as corr
from lunatic_imsi_lab.detection.baseline import Baseline
from lunatic_imsi_lab.gui import theme
from lunatic_imsi_lab.gui.pages.base import Page
from lunatic_imsi_lab.gui.widgets import PlotWidget, RecordTable

KIND_LABELS = {"first_seen": "Apparition", "last_seen": "Disparition", "alert": "Alerte",
               "serving_change": "Changement de service"}


class TimelinePage(Page):
    nav_label = "Chronologie / corrélation"
    title = "Chronologie et corrélation"
    subtitle = ("Chronologie des événements, regroupement des anomalies similaires, comparaison "
                "à la référence et distinction changements persistants / ponctuels.")

    def build(self) -> None:
        bar = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems(["Tous les événements"] + list(KIND_LABELS.values()))
        self.kind.currentTextChanged.connect(lambda _: self.refresh())
        bar.addWidget(QLabel("Type"))
        bar.addWidget(self.kind)
        bar.addStretch(1)
        exp = QPushButton("Exporter CSV + JSON…")
        exp.setObjectName("Primary")
        exp.clicked.connect(self.export)
        bar.addWidget(exp)
        self.layout_.addLayout(bar)

        split = QSplitter(Qt.Vertical)
        self.plot = PlotWidget(height=2.2)
        split.addWidget(self.plot)
        tabs = QTabWidget()
        self.events = RecordTable([
            ("Horodatage (UTC)", lambda e: f"{e.timestamp:%Y-%m-%d %H:%M:%S}"),
            ("Type", lambda e: KIND_LABELS.get(e.kind, e.kind)),
            ("Description", lambda e: e.description), ("Source", lambda e: e.source),
            ("Réf.", lambda e: e.ref)])
        self.events.model.color_fn = lambda e: theme.RED if e.kind == "alert" else None
        tabs.addTab(self.events, "Chronologie")
        self.groups = RecordTable([
            ("Règles", lambda g: ", ".join(g.signature[0])),
            ("Alertes", lambda g: len(g.alerts)),
            ("Priorité max", lambda g: g.max_priority),
            ("Première", lambda g: f"{g.first_seen:%Y-%m-%d %H:%M}"),
            ("Dernière", lambda g: f"{g.last_seen:%Y-%m-%d %H:%M}")])
        tabs.addTab(self.groups, "Anomalies regroupées")
        self.changes = RecordTable([
            ("Cellule", lambda c: f"{c.cell_key[0]} {c.cell_key[1]}-{c.cell_key[2]} "
                                  f"{c.cell_key[3]}/{c.cell_key[4]}"),
            ("Statut", lambda c: {"new": "NOUVELLE", "missing": "absente",
                                  "known": "connue"}[c.status]),
            ("Nature", lambda c: {"persistent": "persistante", "transient": "ponctuelle",
                                  "n/a": "—"}[c.persistence]),
            ("Couverture", lambda c: f"{c.coverage_ratio:.0%}"),
            ("ΔP vs réf. (dB)", lambda c: c.rssi_delta_db),
            ("Obs.", lambda c: c.observations),
            ("Source", lambda c: ", ".join(c.sources))])
        self.changes.model.color_fn = lambda c: (theme.AMBER if c.status == "new" else
                                                 theme.MUTED if c.status == "missing" else None)
        tabs.addTab(self.changes, "Comparaison à la référence")
        split.addWidget(tabs)
        split.setSizes([260, 480])
        self.layout_.addWidget(split, 1)

    def refresh(self) -> None:
        super().refresh()
        ws = self.lab.ws
        alerts = ws.result.alerts if ws.result else []
        events = corr.build_timeline(ws.observations, alerts)
        if self.kind.currentIndex() > 0:
            wanted = list(KIND_LABELS)[self.kind.currentIndex() - 1]
            events = [e for e in events if e.kind == wanted]
        self.events.set_rows(events)
        self.groups.set_rows(corr.group_alerts(alerts))
        self.changes.set_rows(corr.compare_with_baseline(
            ws.observations, Baseline.from_observations(ws.baseline_obs)))
        ax = self.plot.ax()
        lanes = list(KIND_LABELS)
        colors = {"first_seen": theme.GREEN, "last_seen": theme.MUTED, "alert": theme.RED,
                  "serving_change": theme.BLUE}
        for k in lanes:
            ev = [e for e in events if e.kind == k]
            ax.scatter([e.timestamp for e in ev], [lanes.index(k)] * len(ev), s=14,
                       color=colors[k])
        ax.set_yticks(range(len(lanes)), [KIND_LABELS[k] for k in lanes])
        ax.set_title("Chronologie des événements")
        ax.grid(True, axis="x", alpha=0.2)
        self.plot.draw()

    def export(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Répertoire d'export")
        if not d:
            return
        paths = self.win.guarded(self.lab.export, d)
        if paths:
            self.win.notify(f"Export : {', '.join(p.name for p in paths)}")
