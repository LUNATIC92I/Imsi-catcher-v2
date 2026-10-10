"""Authentification locale.

* Mots de passe stockés sous forme d'empreinte PBKDF2-HMAC-SHA256 salée
  (bibliothèque standard, 600 000 itérations par défaut).
* Verrouillage temporaire après plusieurs échecs consécutifs.
* Le premier compte créé doit être administrateur ; tant qu'aucun compte
  n'existe, l'application fonctionne en mode « sans authentification »
  (rôle issu de la configuration) et le signale.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy import func, select

from lunatic_imsi_lab.core.timeutils import utcnow
from lunatic_imsi_lab.security.rbac import Permission, Role, User
from lunatic_imsi_lab.storage.db import Database, UserAccountRow

PBKDF2_ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 10
MAX_FAILED_ATTEMPTS = 5
LOCKOUT = timedelta(minutes=5)


class AuthError(PermissionError):
    pass


def _hash(password: str, salt: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt),
                               iterations).hex()


def check_password_policy(password: str, name: str = "") -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"mot de passe trop court (minimum {MIN_PASSWORD_LENGTH} caractères)")
    if name and name.lower() in password.lower():
        raise ValueError("le mot de passe ne doit pas contenir le nom d'utilisateur")
    if len(set(password)) < 5:
        raise ValueError("mot de passe trop peu varié")


class UserStore:
    def __init__(self, db: Database, iterations: int | None = None) -> None:
        self.db = db
        self.iterations = iterations or PBKDF2_ITERATIONS

    def has_users(self) -> bool:
        with self.db.session() as s:
            return bool(s.scalar(select(func.count()).select_from(UserAccountRow)))

    def list_users(self) -> list[UserAccountRow]:
        with self.db.session() as s:
            return list(s.scalars(select(UserAccountRow).order_by(UserAccountRow.name)))

    def _admins(self, s) -> int:
        return int(s.scalar(select(func.count()).select_from(UserAccountRow).where(
            UserAccountRow.role == Role.ADMIN.value, UserAccountRow.disabled.is_(False))) or 0)

    def add_user(self, actor: User | None, name: str, role: Role, password: str) -> None:
        name = name.strip()
        if not name or len(name) > 80 or not name.replace("-", "").replace("_", "").replace(
                ".", "").isalnum():
            raise ValueError("nom d'utilisateur invalide (lettres, chiffres, . _ -)")
        bootstrap = not self.has_users()
        if bootstrap:
            if role != Role.ADMIN:
                raise ValueError("le premier compte créé doit être administrateur")
        else:
            if actor is None or not actor.authenticated:
                raise AuthError("authentification requise pour gérer les comptes")
            actor.require(Permission.MANAGE_USERS)
        check_password_policy(password, name)
        salt = secrets.token_hex(16)
        with self.db.session() as s, s.begin():
            if s.get(UserAccountRow, name) is not None:
                raise ValueError(f"le compte « {name} » existe déjà")
            s.add(UserAccountRow(name=name, role=Role(role).value, salt=salt,
                                 password_hash=_hash(password, salt, self.iterations),
                                 iterations=self.iterations, created_at=utcnow()))

    def authenticate(self, name: str, password: str) -> User:
        now = utcnow()
        error: str | None = None
        with self.db.session() as s, s.begin():
            row = s.get(UserAccountRow, name)
            if row is None:
                # Calcul factice : même durée qu'un compte existant.
                _hash(password, "00" * 16, self.iterations)
                error = "identifiants invalides"
            elif row.disabled:
                error = "compte désactivé"
            elif row.locked_until and row.locked_until > now:
                error = "compte temporairement verrouillé après plusieurs échecs"
            elif not hmac.compare_digest(_hash(password, row.salt, row.iterations),
                                         row.password_hash):
                # L'échec est enregistré (transaction validée) avant de lever l'erreur.
                row.failed_attempts += 1
                if row.failed_attempts >= MAX_FAILED_ATTEMPTS:
                    row.locked_until = now + LOCKOUT
                    row.failed_attempts = 0
                error = "identifiants invalides"
            else:
                row.failed_attempts = 0
                row.locked_until = None
                user = User(row.name, Role(row.role), authenticated=True)
        if error:
            raise AuthError(error)
        return user

    def change_password(self, actor: User, name: str, new_password: str,
                        old_password: str | None = None) -> None:
        if not actor.authenticated:
            raise AuthError("authentification requise")
        if actor.name == name:
            if old_password is None:
                raise AuthError("l'ancien mot de passe est requis")
            self.authenticate(name, old_password)
        else:
            actor.require(Permission.MANAGE_USERS)
        check_password_policy(new_password, name)
        salt = secrets.token_hex(16)
        with self.db.session() as s, s.begin():
            row = s.get(UserAccountRow, name)
            if row is None:
                raise ValueError(f"compte inconnu : {name}")
            row.salt, row.iterations = salt, self.iterations
            row.password_hash = _hash(new_password, salt, self.iterations)

    def set_disabled(self, actor: User, name: str, disabled: bool) -> None:
        if not actor.authenticated:
            raise AuthError("authentification requise")
        actor.require(Permission.MANAGE_USERS)
        with self.db.session() as s, s.begin():
            row = s.get(UserAccountRow, name)
            if row is None:
                raise ValueError(f"compte inconnu : {name}")
            if disabled and row.role == Role.ADMIN.value and not row.disabled \
                    and self._admins(s) <= 1:
                raise ValueError("impossible de désactiver le dernier administrateur actif")
            row.disabled = disabled
