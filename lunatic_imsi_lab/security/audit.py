"""Journal d'audit chaîné par hachage (détection d'altération)."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from lunatic_imsi_lab.security.rbac import User
from lunatic_imsi_lab.storage.db import AuditRow, Database

log = logging.getLogger("lunatic.audit")

GENESIS = "0" * 64


def _entry_hash(prev_hash: str, timestamp: datetime, user: str, role: str, action: str,
                details: str) -> str:
    payload = "|".join([prev_hash, timestamp.isoformat(), user, role, action, details])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(self, user: User, action: str, details: dict[str, Any] | str = "") -> AuditRow:
        details_text = details if isinstance(details, str) else json.dumps(
            details, sort_keys=True, default=str, ensure_ascii=False)
        ts = datetime.now(timezone.utc).replace(microsecond=0)
        with self.db.session() as s, s.begin():
            last = s.scalars(select(AuditRow).order_by(AuditRow.id.desc()).limit(1)).first()
            prev = last.entry_hash if last else GENESIS
            row = AuditRow(timestamp=ts, user=user.name, role=user.role.value, action=action,
                           details=details_text, prev_hash=prev,
                           entry_hash=_entry_hash(prev, ts, user.name, user.role.value, action,
                                                  details_text))
            s.add(row)
        log.info("AUDIT %s %s %s", user.name, action, details_text)
        return row

    def entries(self, limit: int | None = None) -> list[AuditRow]:
        stmt = select(AuditRow).order_by(AuditRow.id.desc())
        if limit:
            stmt = stmt.limit(limit)
        with self.db.session() as s:
            return list(s.scalars(stmt))

    def verify(self) -> tuple[bool, int | None]:
        """Vérifie la chaîne. Renvoie (ok, id de la première entrée invalide)."""
        prev = GENESIS
        with self.db.session() as s:
            for row in s.scalars(select(AuditRow).order_by(AuditRow.id)):
                expected = _entry_hash(prev, row.timestamp, row.user, row.role, row.action,
                                       row.details)
                if row.prev_hash != prev or row.entry_hash != expected:
                    return False, row.id
                prev = row.entry_hash
        return True, None
