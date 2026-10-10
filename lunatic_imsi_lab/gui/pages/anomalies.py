from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton, QSplitter,
                               QTextBrowser)

from lunatic_imsi_lab.gui import theme
from lunatic_imsi_lab.gui.pages.base import Page
from lunatic_imsi_lab.gui.widgets import RecordTable


def _cell(k) -> str:
    if not k:
        return "global"
    if k[0] == "SPECTRUM":
        return f"spectre {k[1]} MHz"
    return f"{k[0]} {k[1]}-{k[2]} LAC/TAC={k[3]} CI={k[4]}"


class AnomaliesPage(Page):
    nav_label = "Anomalies"
    title = "Anomalies"
    subtitle = ("Indicateurs heuristiques. Aucun indicateur isolé ne permet de conclure à la "
                "présence d'un IMSI catcher ; chaque alerte liste les explications légitimes.")

    def build(self) -> None:
        self.assess = QLabel()
        self.assess.setObjectName("Notice")
        self.assess.setWordWrap(True)
        self.layout_.addWidget(self.assess)
        bar = QHBoxLayout()
        self.sev = QComboBox()
        self.sev.addItems(["Toutes sévérités", "HIGH", "MEDIUM", "LOW", "INFO"])
        self.sev.currentTextChanged.connect(lambda _: self.refresh())
        bar.addWidget(QLabel("Sévérité"))
        bar.addWidget(self.sev)
        bar.addStretch(1)
        run = QPushButton("Relancer l'analyse")
        run.setObjectName("Primary")
        run.clicked.connect(self.win.analyze)
        bar.addWidget(run)
        self.layout_.addLayout(bar)
        split = QSplitter(Qt.Horizontal)
        self.table = RecordTable([
            ("Alerte", lambda a: a.alert_id),
            ("Début (UTC)", lambda a: f"{a.first_seen:%Y-%m-%d %H:%M:%S}"),
            ("Cellule", lambda a: _cell(a.cell_key)),
            ("Règles", lambda a: ", ".join(a.rules)),
            ("Priorité", lambda a: a.priority),
            ("Confiance", lambda a: a.confidence.value),
            ("Score", lambda a: round(a.confidence_score, 2)),
            ("Sévérité", lambda a: a.severity.value),
            ("Origine", lambda a: "SIMULATION" if a.is_simulation else "mesure")])
        self.table.model.color_fn = lambda a: theme.SEVERITY_COLORS.get(a.severity.value)
        self.table.sort_by(4)
        self.table.view.selectionModel().selectionChanged.connect(self.show_detail)
        split.addWidget(self.table)
        self.detail = QTextBrowser()
        split.addWidget(self.detail)
        split.setSizes([800, 560])
        self.layout_.addWidget(split, 1)

    def refresh(self) -> None:
        super().refresh()
        res = self.lab.ws.result
        if res is None:
            self.assess.setText("Analyse non lancée.")
            self.table.set_rows([])
            self.detail.setHtml("")
            return
        dq = "".join(f"<br>⚠ {html.escape(q)}" for q in res.data_quality)
        self.assess.setText(f"<b>Évaluation globale :</b> {html.escape(res.assessment_text)}{dq}")
        rows = res.alerts
        if self.sev.currentIndex() > 0:
            rows = [a for a in rows if a.severity.value == self.sev.currentText()]
        self.table.set_rows(rows)
        self.show_detail()

    def show_detail(self, *_):
        a = self.table.selected()
        if a is None:
            self.detail.setHtml("<p style='color:#8a93a3'>Sélectionner une alerte.</p>")
            return
        e = html.escape
        sim = ("<p style='background:#ff4d6d;color:white;padding:4px'><b>SIMULATION</b></p>"
               if a.is_simulation else "")
        li = lambda xs: "<ul>" + "".join(f"<li>{e(x)}</li>" for x in xs) + "</ul>"  # noqa
        color = theme.SEVERITY_COLORS.get(a.severity.value)
        self.detail.setHtml(
            f"{sim}<h3 style='color:white'>{e(a.alert_id)}</h3>"
            f"<p><b>Cellule :</b> {e(_cell(a.cell_key))}<br>"
            f"<b>Période :</b> {a.first_seen:%Y-%m-%d %H:%M:%S} → {a.last_seen:%H:%M:%S} UTC<br>"
            f"<b>Priorité :</b> {a.priority}/100 · <b>Sévérité :</b> "
            f"<span style='color:{color}'>{a.severity.value}</span> · "
            f"<b>Confiance :</b> {e(a.confidence.value)} ({a.confidence_score:.2f})<br>"
            f"<b>Règles :</b> {e(', '.join(a.rules))}<br>"
            f"<b>Sources :</b> {e(', '.join(a.sources))} · {len(a.observation_ids)} mesure(s)</p>"
            f"<h4 style='color:{theme.BLUE}'>Explications techniques (faits et calculs)</h4>"
            f"{li(a.explanation)}"
            f"<h4 style='color:{theme.BLUE}'>Faux positifs possibles</h4>{li(a.false_positives)}"
            f"<h4 style='color:{theme.BLUE}'>Vérifications complémentaires</h4>"
            f"{li(a.recommended_checks)}"
            f"<h4 style='color:{theme.BLUE}'>Mesures sources</h4>"
            f"<p style='font-family:monospace;font-size:8pt'>"
            f"{e(', '.join(a.observation_ids[:60]))}{' …' if len(a.observation_ids) > 60 else ''}"
            f"</p>")
