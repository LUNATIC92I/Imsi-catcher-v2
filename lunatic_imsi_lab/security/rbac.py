"""Permissions par rôle (RBAC) minimales et explicites."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    VIEWER = "viewer"      # consultation seule
    ANALYST = "analyst"    # import, analyse, simulation, rapports
    ADMIN = "admin"        # + configuration équipements, suppression de données


class Permission(str, Enum):
    VIEW = "view"
    IMPORT = "import"
    ANALYZE = "analyze"
    SIMULATE = "simulate"
    EXPORT = "export"
    REPORT = "report"
    CONFIGURE_DEVICES = "configure_devices"
    CAPTURE = "capture"              # réception SDR réelle
    DELETE_DATA = "delete_data"
    VIEW_AUDIT = "view_audit"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset({Permission.VIEW}),
    Role.ANALYST: frozenset({Permission.VIEW, Permission.IMPORT, Permission.ANALYZE,
                             Permission.SIMULATE, Permission.EXPORT, Permission.REPORT,
                             Permission.CAPTURE}),
    Role.ADMIN: frozenset(Permission),
}


class PermissionDenied(PermissionError):
    pass


@dataclass(frozen=True)
class User:
    name: str
    role: Role

    def can(self, permission: Permission) -> bool:
        return permission in ROLE_PERMISSIONS[self.role]

    def require(self, permission: Permission) -> None:
        if not self.can(permission):
            raise PermissionDenied(
                f"L'utilisateur « {self.name} » (rôle {self.role.value}) ne dispose pas "
                f"de la permission « {permission.value} ».")
