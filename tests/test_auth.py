"""Authentification locale : comptes, verrouillage, application dans les services,
la ligne de commande et l'IHM."""

from datetime import timedelta

import pytest

from lunatic_imsi_lab.cli import main
from lunatic_imsi_lab.security import auth
from lunatic_imsi_lab.security.auth import AuthError, UserStore, check_password_policy
from lunatic_imsi_lab.security.rbac import PermissionDenied, Role, User
from lunatic_imsi_lab.services import Lab
from lunatic_imsi_lab.storage.db import Database, UserAccountRow

PW = "Corr3ct-Horse-Battery"


@pytest.fixture(autouse=True)
def fast_hash(monkeypatch):
    monkeypatch.setattr(auth, "PBKDF2_ITERATIONS", 1000)


def store_with_admin():
    db = Database()
    s = UserStore(db)
    s.add_user(None, "chef", Role.ADMIN, PW)
    return db, s, s.authenticate("chef", PW)


class TestUserStore:
    def test_bootstrap_requires_admin(self):
        s = UserStore(Database())
        assert not s.has_users()
        with pytest.raises(ValueError, match="administrateur"):
            s.add_user(None, "x", Role.ANALYST, PW)
        s.add_user(None, "chef", Role.ADMIN, PW)
        assert s.has_users()

    def test_password_stored_as_hash_only(self):
        db, s, _ = store_with_admin()
        with db.session() as ses:
            row = ses.get(UserAccountRow, "chef")
        assert PW not in (row.password_hash + row.salt) and len(row.password_hash) == 64

    def test_authenticate(self):
        _, s, admin = store_with_admin()
        assert admin.authenticated and admin.role == Role.ADMIN
        with pytest.raises(AuthError):
            s.authenticate("chef", "mauvais-mot-de-passe")
        with pytest.raises(AuthError):
            s.authenticate("inconnu", PW)

    def test_lockout_and_expiry(self):
        db, s, _ = store_with_admin()
        for _ in range(auth.MAX_FAILED_ATTEMPTS):
            with pytest.raises(AuthError):
                s.authenticate("chef", "wrong-password-xx")
        with pytest.raises(AuthError, match="verrouillé"):
            s.authenticate("chef", PW)           # même le bon mot de passe est refusé
        with db.session() as ses, ses.begin():
            row = ses.get(UserAccountRow, "chef")
            row.locked_until = row.locked_until - timedelta(minutes=10)
        assert s.authenticate("chef", PW).authenticated

    @pytest.mark.parametrize("bad", ["court", "aaaaaaaaaaaaa", "chef-secret-12345"])
    def test_password_policy(self, bad):
        with pytest.raises(ValueError):
            check_password_policy(bad, "chef")

    def test_management_requires_authenticated_admin(self):
        _, s, admin = store_with_admin()
        with pytest.raises(AuthError):
            s.add_user(User("chef", Role.ADMIN), "bob", Role.ANALYST, PW)  # non authentifié
        s.add_user(admin, "bob", Role.ANALYST, PW)
        bob = s.authenticate("bob", PW)
        with pytest.raises(PermissionDenied):
            s.add_user(bob, "eve", Role.ADMIN, PW)
        with pytest.raises(ValueError):
            s.add_user(admin, "bob", Role.ANALYST, PW)             # doublon
        with pytest.raises(ValueError):
            s.add_user(admin, "bad name!", Role.ANALYST, PW)

    def test_disable_and_last_admin(self):
        _, s, admin = store_with_admin()
        with pytest.raises(ValueError, match="dernier administrateur"):
            s.set_disabled(admin, "chef", True)
        s.add_user(admin, "bob", Role.ANALYST, PW)
        s.set_disabled(admin, "bob", True)
        with pytest.raises(AuthError, match="désactivé"):
            s.authenticate("bob", PW)

    def test_change_password(self):
        _, s, admin = store_with_admin()
        new = "Another-Long-Secret-9"
        with pytest.raises(AuthError):
            s.change_password(admin, "chef", new)                  # ancien requis
        s.change_password(admin, "chef", new, PW)
        assert s.authenticate("chef", new)
        s.add_user(admin, "bob", Role.ANALYST, PW)
        s.change_password(admin, "bob", new)                       # admin pour autrui
        bob = s.authenticate("bob", new)
        with pytest.raises(PermissionDenied):
            s.change_password(bob, "chef", PW)


class TestLabEnforcement:
    def test_lab_requires_login_once_accounts_exist(self, tmp_config):
        lab = Lab(tmp_config)
        assert not lab.auth_enabled
        lab.add_user("chef", Role.ADMIN, PW)
        assert lab.user.role == Role.VIEWER          # session non authentifiée rétrogradée
        with pytest.raises(AuthError):
            Lab(tmp_config)
        with pytest.raises(AuthError):
            Lab(tmp_config, User("chef", Role.ADMIN))     # rôle déclaré ≠ authentifié
        with pytest.raises(AuthError):
            Lab.login(tmp_config, "chef", "mauvais-mot-de-passe")
        ok = Lab.login(tmp_config, "chef", PW)
        assert ok.user.authenticated and ok.user.role == Role.ADMIN
        actions = [e.action for e in ok.audit.entries(5)]
        assert actions[0] == "login" and "login_failed" in actions


class TestCli:
    def test_cli_accounts_flow(self, tmp_path, capsys, monkeypatch):
        d = str(tmp_path / "data")
        monkeypatch.setenv("LUNATIC_NEW_PASSWORD", PW)
        assert main(["--data-dir", d, "users", "add", "chef", "--new-role", "admin"]) == 0
        # Désormais : --user obligatoire, --role ignoré
        assert main(["--data-dir", d, "--role", "admin", "datasets"]) == 3
        monkeypatch.setenv("LUNATIC_PASSWORD", "mauvais-mot-de-passe")
        assert main(["--data-dir", d, "--user", "chef", "datasets"]) == 3
        monkeypatch.setenv("LUNATIC_PASSWORD", PW)
        assert main(["--data-dir", d, "--user", "chef", "users", "add", "bob"]) == 0
        assert main(["--data-dir", d, "--user", "chef", "users", "list"]) == 0
        out = capsys.readouterr().out
        assert "bob" in out and "analyst" in out and PW not in out
        assert main(["--data-dir", d, "--user", "bob", "--role", "admin", "rules",
                     "--profile", "fixe"]) == 3            # bob reste analyste
        assert main(["--data-dir", d, "--user", "chef", "users", "disable", "bob"]) == 0
        assert main(["--data-dir", d, "--user", "bob", "datasets"]) == 3


def test_gui_accounts_page_and_login(tmp_config, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    for name in ("warning", "information"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, **k: 0)
    from lunatic_imsi_lab.gui.login import LoginDialog
    from lunatic_imsi_lab.gui.main_window import MainWindow

    lab = Lab(tmp_config)
    win = MainWindow(lab)
    page = next(p for p in win.pages if type(p).__name__ == "AccountsPage")
    assert "sans authentification" in page.mode.text()
    page.new_name.setText("chef")
    page.new_pw.setText(PW)
    page.new_pw2.setText(PW)
    page.add_user()
    app.processEvents()
    assert lab.auth_enabled and lab.user.role == Role.VIEWER
    assert page.table.model.rowCount() == 1
    win.close()

    dlg = LoginDialog(tmp_config, Lab)
    dlg.name.setText("chef")
    dlg.password.setText("mauvais-mot-de-passe")
    dlg.try_login()
    assert dlg.lab is None and "restant" in dlg.error.text()
    dlg.password.setText(PW)
    dlg.try_login()
    assert dlg.lab is not None and dlg.lab.user.authenticated
