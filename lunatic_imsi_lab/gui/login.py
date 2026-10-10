"""Fenêtre de connexion (affichée uniquement lorsque des comptes existent)."""

from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
                               QVBoxLayout)

from lunatic_imsi_lab import APP_NAME
from lunatic_imsi_lab.gui import theme
from lunatic_imsi_lab.security.auth import AuthError

MAX_TRIES = 3


class LoginDialog(QDialog):
    def __init__(self, config, lab_cls) -> None:
        super().__init__()
        self.config, self.lab_cls = config, lab_cls
        self.lab = None
        self.tries = 0
        self.setWindowTitle(f"{APP_NAME} — connexion")
        self.setStyleSheet(theme.QSS)
        lay = QVBoxLayout(self)
        title = QLabel("LUNATIC IMSI LAB")
        title.setObjectName("AppTitle")
        lay.addWidget(title)
        form = QFormLayout()
        self.name = QLineEdit(config.operator_name)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("Utilisateur", self.name)
        form.addRow("Mot de passe", self.password)
        lay.addLayout(form)
        self.error = QLabel()
        self.error.setStyleSheet(f"color:{theme.RED}")
        lay.addWidget(self.error)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Se connecter")
        bb.button(QDialogButtonBox.Cancel).setText("Annuler")
        bb.accepted.connect(self.try_login)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.password.setFocus()

    def try_login(self) -> None:
        try:
            self.lab = self.lab_cls.login(self.config, self.name.text().strip(),
                                          self.password.text())
        except AuthError as exc:
            self.tries += 1
            self.password.clear()
            if self.tries >= MAX_TRIES:
                self.reject()
                return
            self.error.setText(f"{exc} ({MAX_TRIES - self.tries} essai(s) restant(s))")
            return
        self.accept()
