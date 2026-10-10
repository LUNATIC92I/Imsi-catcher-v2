"""Classe de base des pages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QVBoxLayout, QWidget

from lunatic_imsi_lab.gui.widgets import page_header

if TYPE_CHECKING:  # pragma: no cover
    from lunatic_imsi_lab.gui.main_window import MainWindow


class Page(QWidget):
    title = ""
    subtitle = ""

    def __init__(self, win: "MainWindow") -> None:
        super().__init__()
        self.win = win
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(18, 14, 18, 14)
        header, self.sim_banner = page_header(self.title, self.subtitle)
        self.layout_.addWidget(header)
        self.build()

    @property
    def lab(self):
        return self.win.lab

    def build(self) -> None:  # pragma: no cover - surchargé
        pass

    def refresh(self) -> None:
        """Appelé à chaque modification des données de l'espace de travail."""
        self.sim_banner.setVisible(self.lab.ws.is_simulation)
        self.sim_banner.setText("SIMULATION — DONNÉES SYNTHÉTIQUES")
