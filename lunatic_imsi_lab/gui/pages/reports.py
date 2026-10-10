from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton)

from lunatic_imsi_lab.gui.pages.base import Page
from lunatic_imsi_lab.gui.widgets import RecordTable


class ReportsPage(Page):
    nav_label = "Rapports"
    title = "Gestionnaire de rapports"
    subtitle = ("Rapports PDF et HTML distinguant faits observés, résultats d'analyse et "
                "hypothèses. Aucun rapport n'affirme l'identification d'un IMSI catcher.")

    def build(self) -> None:
        box = QGroupBox("Nouveau rapport")
        f = QFormLayout(box)
        self.title_edit = QLineEdit("Rapport d'analyse radio")
        self.scope = QPlainTextEdit()
        self.scope.setPlaceholderText("Périmètre : lieu, objectif, cadre d'autorisation…")
        self.scope.setMaximumHeight(80)
        self.auth = QLineEdit()
        self.auth.setPlaceholderText("Référence d'autorisation (reprise de la configuration)")
        fmts = QHBoxLayout()
        self.pdf = QCheckBox("PDF")
        self.pdf.setChecked(True)
        self.html = QCheckBox("HTML")
        self.html.setChecked(True)
        fmts.addWidget(self.pdf)
        fmts.addWidget(self.html)
        fmts.addStretch(1)
        f.addRow("Titre", self.title_edit)
        f.addRow("Périmètre", self.scope)
        f.addRow("Autorisation", self.auth)
        f.addRow("Formats", fmts)
        gen = QPushButton("Générer le rapport")
        gen.setObjectName("Primary")
        gen.clicked.connect(self.generate)
        f.addRow(gen)
        self.layout_.addWidget(box)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Rapports générés"))
        bar.addStretch(1)
        op = QPushButton("Ouvrir")
        op.clicked.connect(self.open_selected)
        bar.addWidget(op)
        self.layout_.addLayout(bar)
        self.table = RecordTable([
            ("Date (UTC)", lambda r: f"{r.created_at:%Y-%m-%d %H:%M:%S}"),
            ("Titre", lambda r: r.title), ("Format", lambda r: r.fmt.upper()),
            ("SHA-256", lambda r: r.sha256[:20] + "…"), ("Fichier", lambda r: r.path)])
        self.table.view.doubleClicked.connect(lambda _: self.open_selected())
        self.layout_.addWidget(self.table, 1)

    def refresh(self) -> None:
        super().refresh()
        if not self.auth.text():
            self.auth.setText(self.lab.config.authorization_ref)
        self.table.set_rows(self.lab.db.list_reports())

    def generate(self) -> None:
        formats = [f for f, cb in (("pdf", self.pdf), ("html", self.html)) if cb.isChecked()]
        if not formats:
            self.win.notify("Choisir au moins un format.", "warn")
            return
        if not self.lab.ws.observations and not self.lab.ws.sweeps:
            self.win.notify("Aucune donnée chargée.", "warn")
            return
        self.lab.config.authorization_ref = self.auth.text().strip()
        title, scope = self.title_edit.text().strip(), self.scope.toPlainText().strip()
        self.win.run_task(lambda: self.lab.generate_report(title, scope, formats=formats),
                          lambda paths: self.win.after_data(
                              "Rapport généré : " + ", ".join(p.name for p in paths)),
                          "Génération du rapport…")

    def open_selected(self) -> None:
        r = self.table.selected()
        if r and Path(r.path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(r.path))
        elif r:
            self.win.notify("Fichier introuvable (supprimé ou déplacé).", "warn")
