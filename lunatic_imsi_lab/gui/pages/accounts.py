from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QVBoxLayout)

from lunatic_imsi_lab.gui import theme
from lunatic_imsi_lab.gui.pages.base import Page
from lunatic_imsi_lab.gui.widgets import RecordTable
from lunatic_imsi_lab.security.auth import MIN_PASSWORD_LENGTH
from lunatic_imsi_lab.security.rbac import Permission, Role


def _pw() -> QLineEdit:
    w = QLineEdit()
    w.setEchoMode(QLineEdit.Password)
    return w


class AccountsPage(Page):
    nav_label = "Comptes & sécurité"
    title = "Comptes et sécurité"
    subtitle = ("Comptes locaux (empreintes PBKDF2-SHA256, verrouillage après échecs répétés). "
                "Dès qu'un compte existe, la connexion devient obligatoire.")

    def build(self) -> None:
        self.mode = QLabel()
        self.mode.setObjectName("Notice")
        self.mode.setWordWrap(True)
        self.layout_.addWidget(self.mode)
        row = QHBoxLayout()
        left = QVBoxLayout()
        self.table = RecordTable([
            ("Compte", lambda u: u.name), ("Rôle", lambda u: u.role),
            ("État", lambda u: "désactivé" if u.disabled else "actif"),
            ("Créé le", lambda u: f"{u.created_at:%Y-%m-%d %H:%M}")])
        self.table.model.color_fn = lambda u: theme.MUTED if u.disabled else None
        left.addWidget(self.table, 1)
        btns = QHBoxLayout()
        self.btn_disable = QPushButton("Désactiver")
        self.btn_disable.clicked.connect(lambda: self.toggle(True))
        self.btn_enable = QPushButton("Réactiver")
        self.btn_enable.clicked.connect(lambda: self.toggle(False))
        btns.addWidget(self.btn_disable)
        btns.addWidget(self.btn_enable)
        btns.addStretch(1)
        left.addLayout(btns)
        row.addLayout(left, 1)

        right = QVBoxLayout()
        self.add_box = QGroupBox("Créer un compte")
        f = QFormLayout(self.add_box)
        self.new_name = QLineEdit()
        self.new_role = QComboBox()
        for r in Role:
            self.new_role.addItem(r.value, r.value)
        self.new_pw, self.new_pw2 = _pw(), _pw()
        f.addRow("Nom", self.new_name)
        f.addRow("Rôle", self.new_role)
        f.addRow(f"Mot de passe (≥ {MIN_PASSWORD_LENGTH})", self.new_pw)
        f.addRow("Confirmation", self.new_pw2)
        add = QPushButton("Créer")
        add.setObjectName("Primary")
        add.clicked.connect(self.add_user)
        f.addRow(add)
        right.addWidget(self.add_box)
        self.pw_box = QGroupBox("Changer mon mot de passe")
        g = QFormLayout(self.pw_box)
        self.old_pw, self.pw1, self.pw2 = _pw(), _pw(), _pw()
        g.addRow("Actuel", self.old_pw)
        g.addRow("Nouveau", self.pw1)
        g.addRow("Confirmation", self.pw2)
        chg = QPushButton("Modifier")
        chg.clicked.connect(self.change_own)
        g.addRow(chg)
        right.addWidget(self.pw_box)
        right.addStretch(1)
        row.addLayout(right, 1)
        self.layout_.addLayout(row, 1)

    def refresh(self) -> None:
        super().refresh()
        lab = self.lab
        if lab.auth_enabled:
            self.mode.setText("Authentification <b>active</b> : les rôles proviennent des "
                              "comptes ; toute connexion est journalisée.")
            self.add_box.setTitle("Créer un compte (administrateur)")
        else:
            self.mode.setText(
                f"<span style='color:{theme.AMBER}'><b>Mode sans authentification</b></span> : "
                "le rôle provient de la configuration locale. Créer un premier compte "
                "<b>administrateur</b> pour activer la connexion obligatoire.")
            self.add_box.setTitle("Créer le premier compte (administrateur)")
        manage = not lab.auth_enabled or (lab.user.authenticated and
                                          lab.user.can(Permission.MANAGE_USERS))
        self.add_box.setEnabled(manage)
        self.btn_disable.setEnabled(manage and lab.auth_enabled)
        self.btn_enable.setEnabled(manage and lab.auth_enabled)
        self.pw_box.setEnabled(lab.user.authenticated)
        if not lab.auth_enabled:
            self.new_role.setCurrentText(Role.ADMIN.value)
        self.table.set_rows(lab.users.list_users())

    def add_user(self) -> None:
        if self.new_pw.text() != self.new_pw2.text():
            self.win.notify("Les mots de passe ne correspondent pas.", "warn")
            return
        bootstrap = not self.lab.auth_enabled
        ok = self.win.try_action(self.lab.add_user, self.new_name.text(),
                                 Role(self.new_role.currentData()), self.new_pw.text())
        for w in (self.new_pw, self.new_pw2):
            w.clear()
        if not ok:
            return
        if bootstrap:
            QMessageBox.information(
                self, "Authentification activée",
                "Le compte administrateur a été créé. La session actuelle passe en lecture "
                "seule : relancer l'application et se connecter.")
            self.win.after_data()
        else:
            self.win.after_data(f"Compte « {self.new_name.text()} » créé.")

    def toggle(self, disabled: bool) -> None:
        u = self.table.selected()
        if u is not None:
            self.win.try_action(self.lab.set_user_disabled, u.name, disabled)
            self.refresh()

    def change_own(self) -> None:
        if self.pw1.text() != self.pw2.text():
            self.win.notify("Les mots de passe ne correspondent pas.", "warn")
            return
        ok = self.win.try_action(self.lab.change_password, self.lab.user.name, self.pw1.text(),
                                 self.old_pw.text())
        for w in (self.old_pw, self.pw1, self.pw2):
            w.clear()
        if ok:
            self.win.notify("Mot de passe modifié.")
