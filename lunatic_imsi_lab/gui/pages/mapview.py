from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QPushButton

from lunatic_imsi_lab.gui.pages.base import Page
from lunatic_imsi_lab.gui.widgets import PlotWidget
from lunatic_imsi_lab.mapping.maps import export_geojson, prepare_points, render_map


class MapPage(Page):
    nav_label = "Cartographie"
    title = "Cartographie des mesures"
    subtitle = ("Positions de l'équipement de mesure uniquement (● GPS mesuré, ▲ position "
                "estimée). Aucune localisation de téléphones tiers, aucun suivi de personnes. "
                "Rendu hors ligne, sans fond de carte en ligne.")

    def build(self) -> None:
        bar = QHBoxLayout()
        self.serving = QCheckBox("Cellule de service uniquement")
        self.serving.setChecked(True)
        self.serving.toggled.connect(lambda _: self.refresh())
        bar.addWidget(self.serving)
        self.info = QLabel()
        self.info.setObjectName("Muted")
        bar.addWidget(self.info, 1)
        exp = QPushButton("Exporter GeoJSON…")
        exp.clicked.connect(self.export)
        bar.addWidget(exp)
        self.layout_.addLayout(bar)
        self.plot = PlotWidget(height=5)
        self.layout_.addWidget(self.plot, 1)
        self.points = []

    def refresh(self) -> None:
        super().refresh()
        ws = self.lab.ws
        alerts = ws.result.alerts if ws.result else []
        self.points = prepare_points(ws.observations, alerts, self.serving.isChecked())
        n_gps = sum(p.kind.value == "GPS" for p in self.points)
        self.info.setText(f"{len(self.points)} point(s) · {n_gps} GPS · "
                          f"{len(self.points) - n_gps} estimé(s) · "
                          f"{sum(bool(p.alert_ids) for p in self.points)} lié(s) à une alerte")
        render_map(self.plot.ax(), self.points)
        self.plot.draw()

    def export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exporter GeoJSON", "mesures.geojson",
                                              "GeoJSON (*.geojson)")
        if path:
            export_geojson(path, self.points)
            self.lab.audit.record(self.lab.user, "export_geojson", {"points": len(self.points)})
            self.win.notify(f"GeoJSON exporté : {path}")
