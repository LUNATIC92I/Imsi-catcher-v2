"""Suppression contrôlée des données : permission, motif obligatoire,
confirmation explicite et journalisation."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from lunatic_imsi_lab.security.audit import AuditLog
from lunatic_imsi_lab.security.files import secure_delete_file
from lunatic_imsi_lab.security.rbac import Permission, User
from lunatic_imsi_lab.storage.db import Database, ImportedFileRow


class DeletionRefused(ValueError):
    pass


def delete_dataset(db: Database, audit: AuditLog, user: User, dataset: str, reason: str,
                   confirm: str, wipe_files: bool = True) -> dict[str, int]:
    """Supprime un jeu de données. ``confirm`` doit être égal au nom du jeu."""
    user.require(Permission.DELETE_DATA)
    if not reason or len(reason.strip()) < 5:
        raise DeletionRefused("un motif de suppression explicite (≥ 5 caractères) est requis")
    if confirm != dataset:
        raise DeletionRefused("la confirmation doit reprendre exactement le nom du jeu de données")

    with db.session() as s:
        files = [r.stored_path for r in s.scalars(
            select(ImportedFileRow).where(ImportedFileRow.dataset == dataset))]
    counts = db.delete_dataset_rows(dataset)
    wiped = 0
    if wipe_files:
        for f in files:
            if Path(f).exists():
                secure_delete_file(f)
                wiped += 1
    counts["files_wiped"] = wiped
    audit.record(user, "delete_dataset", {"dataset": dataset, "reason": reason.strip(), **counts})
    return counts
