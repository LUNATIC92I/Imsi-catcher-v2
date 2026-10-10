from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)
from PySide6.QtCore import Qt

from lunatic_imsi_lab.gui import theme
from lunatic_imsi_lab.gui.pages.base import Page
from lunatic_imsi_lab.gui.widgets import RecordTable
from lunatic_imsi_lab.security.rbac import Permission


class _Emitter(QObject):
    line = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.emitter = _Emitter()
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                                            "%H:%M:%S"))

    def emit(self, record) -> None:
        try:
            self.emitter.line.emit(self.format(record))
        except RuntimeError:  # widget détruit
            pass


class ConsolePage(Page):
    nav_label = "Console technique"
    title = "Console technique"
    subtitle = "Journal d'exécution de l'application et journal d'audit chaîné (SHA-256)."

    def build(self) -> None:
        split = QSplitter(Qt.Vertical)
        top = QWidget()
        tv = QVBoxLayout(top)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.addWidget(QLabel("Journal d'exécution"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setStyleSheet("font-family: monospace; font-size: 9pt;")
        tv.addWidget(self.log)
        split.addWidget(top)
        bottom = QWidget()
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Journal d'audit"))
        self.integrity = QLabel()
        bar.addWidget(self.integrity, 1)
        verify = QPushButton("Vérifier l'intégrité")
        verify.clicked.connect(self.refresh)
        bar.addWidget(verify)
        bv.addLayout(bar)
        self.audit = RecordTable([
            ("#", lambda e: e.id), ("Horodatage (UTC)", lambda e: f"{e.timestamp:%Y-%m-%d %H:%M:%S}"),
            ("Utilisateur", lambda e: e.user), ("Rôle", lambda e: e.role),
            ("Action", lambda e: e.action), ("Détails", lambda e: e.details),
            ("Empreinte", lambda e: e.entry_hash[:16] + "…")])
        bv.addWidget(self.audit)
        split.addWidget(bottom)
        self.layout_.addWidget(split, 1)
        self.handler = QtLogHandler()
        self.handler.emitter.line.connect(self.log.appendPlainText)
        logging.getLogger().addHandler(self.handler)
        logging.getLogger().setLevel(logging.INFO)

    def refresh(self) -> None:
        super().refresh()
        if not self.lab.user.can(Permission.VIEW_AUDIT):
            self.integrity.setText("Consultation du journal d'audit réservée à l'administrateur.")
            self.audit.set_rows([])
            return
        ok, bad = self.lab.audit.verify()
        self.integrity.setText("✔ chaîne intègre" if ok else f"✖ altération détectée (#{bad})")
        self.integrity.setStyleSheet(f"color:{theme.GREEN if ok else theme.RED}")
        self.audit.set_rows(self.lab.audit.entries(1000))
