from __future__ import annotations

import html

from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QPushButton, QSpinBox, QTextBrowser, QVBoxLayout)

from lunatic_imsi_lab.detection.engine import Assessment
from lunatic_imsi_lab.gui import theme
from lunatic_imsi_lab.gui.pages.base import Page
from lunatic_imsi_lab.simulation.cells import Scenario, SimulationParams


def _dspin(lo, hi, val, step=1.0, dec=1, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(val)
    s.setSuffix(suffix)
    return s


class SimulationPage(Page):
    nav_label = "Laboratoire de simulation"
    title = "Laboratoire de simulation"
    subtitle = ("Génération de données synthétiques reproductibles pour éprouver le moteur de "
                "détection. Aucun signal n'est émis ; aucune station de base n'est émulée.")

    def build(self) -> None:
        banner = QLabel("SIMULATION — toutes les données produites ici sont synthétiques et "
                        "marquées comme telles dans la base, les exports et les rapports.")
        banner.setObjectName("SimBanner")
        banner.setWordWrap(True)
        self.layout_.addWidget(banner)
        row = QHBoxLayout()
        box = QGroupBox("Paramètres")
        f = QFormLayout(box)
        self.scenario = QComboBox()
        for sc in Scenario:
            self.scenario.addItem(sc.label, sc)
        self.scenario.setCurrentIndex(len(Scenario) - 1)
        self.seed = QSpinBox()
        self.seed.setRange(0, 10 ** 6)
        self.seed.setValue(42)
        self.cells = QSpinBox()
        self.cells.setRange(2, 12)
        self.cells.setValue(6)
        self.base_h = _dspin(0.5, 48, 6, 0.5, 1, " h")
        self.duration = _dspin(10, 1440, 120, 10, 0, " min")
        self.interval = _dspin(5, 600, 30, 5, 0, " s")
        self.shadow = _dspin(0, 15, 4, 0.5, 1, " dB")
        self.a_start = _dspin(0, 0.9, 0.4, 0.05, 2)
        self.a_dur = _dspin(0.05, 1, 0.25, 0.05, 2)
        self.a_pow = _dspin(-110, -30, -50, 1, 0, " dBm")
        self.jump = _dspin(3, 40, 18, 1, 0, " dB")
        for label, w in (("Scénario", self.scenario), ("Graine", self.seed),
                         ("Cellules", self.cells), ("Durée de référence", self.base_h),
                         ("Durée d'observation", self.duration), ("Intervalle", self.interval),
                         ("Masquage (σ)", self.shadow),
                         ("Début anomalie (fraction)", self.a_start),
                         ("Durée anomalie (fraction)", self.a_dur),
                         ("Puissance cellule synthétique", self.a_pow),
                         ("Amplitude des sauts", self.jump)):
            f.addRow(label, w)
        run = QPushButton("Lancer la simulation et l'analyse")
        run.setObjectName("Primary")
        run.clicked.connect(self.run)
        f.addRow(run)
        row.addWidget(box)
        col = QVBoxLayout()
        col.addWidget(QLabel("Vérité terrain et réaction du moteur"))
        self.out = QTextBrowser()
        col.addWidget(self.out, 1)
        row.addLayout(col, 1)
        self.layout_.addLayout(row, 1)
        self.last = None

    def params(self) -> SimulationParams:
        return SimulationParams(
            scenario=self.scenario.currentData(), seed=self.seed.value(),
            n_cells=self.cells.value(), baseline_hours=self.base_h.value(),
            duration_minutes=self.duration.value(), interval_s=self.interval.value(),
            shadowing_db=self.shadow.value(), anomaly_start_fraction=self.a_start.value(),
            anomaly_duration_fraction=self.a_dur.value(),
            anomaly_power_dbm=self.a_pow.value(), power_jump_db=self.jump.value())

    def run(self) -> None:
        p = self.params()

        def job():
            sim = self.lab.run_simulation(p)
            return sim, self.lab.analyze()

        def done(out):
            self.last = out
            self.win.after_data(f"Simulation « {p.scenario.label} » terminée.")
            self.show_result()

        self.win.run_task(job, done, "Simulation en cours…")

    def show_result(self) -> None:
        if not self.last:
            return
        sim, res = self.last
        e = html.escape
        truth = sim.truth
        top = res.alerts[0] if res.alerts else None
        hit = top is not None and top.cell_key in truth.anomalous_cell_keys
        expected = ("aucune alerte significative (scénario légitime)" if truth.expected_legitimate
                    else "indicateur(s) sur la ou les cellules modifiées")
        verdict_ok = (res.assessment in (Assessment.NO_INDICATOR,) if truth.expected_legitimate
                      else hit)
        color = theme.GREEN if verdict_ok else theme.AMBER
        rows = "".join(
            f"<tr><td>{e(a.alert_id)}</td><td>{a.priority}</td><td>{e(a.confidence.value)}</td>"
            f"<td>{e(', '.join(a.rules))}</td></tr>" for a in res.alerts[:12])
        self.out.setHtml(
            f"<p style='color:{theme.RED}'><b>SIMULATION</b> · graine {sim.params.seed} · "
            f"{len(sim.baseline)} mesures de référence · {len(sim.observations)} observations</p>"
            f"<h4 style='color:{theme.BLUE}'>Ce que le scénario a injecté</h4>"
            + "".join(f"<p>{e(x)}</p>" for x in truth.events)
            + f"<h4 style='color:{theme.BLUE}'>Réaction du moteur</h4>"
            f"<p><b>Évaluation :</b> {e(res.assessment_text)}</p>"
            f"<p><b>Attendu :</b> {e(expected)}<br><b>Cohérence avec la vérité terrain :</b> "
            f"<span style='color:{color}'>{'oui' if verdict_ok else 'à examiner'}</span></p>"
            f"<table width='100%' cellspacing='0' cellpadding='3' border='1' "
            f"style='border-color:{theme.BORDER}'><tr><th>Alerte</th><th>Prio.</th>"
            f"<th>Confiance</th><th>Règles</th></tr>{rows}</table>"
            f"<p style='color:{theme.MUTED}'>Modifier les paramètres (puissance, durée, "
            f"amplitude des sauts, masquage) pour observer la sensibilité des règles.</p>")
