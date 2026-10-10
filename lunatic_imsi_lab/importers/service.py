"""Service d'import complet : permission → protection du fichier → analyse →
stockage → journalisation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from lunatic_imsi_lab.core.models import Provenance
from lunatic_imsi_lab.importers.cells import ImportReport, import_file
from lunatic_imsi_lab.security.audit import AuditLog
from lunatic_imsi_lab.security.files import protect_import
from lunatic_imsi_lab.security.rbac import Permission, User
from lunatic_imsi_lab.storage.db import Database, ImportedFileRow


def import_observations_file(db: Database, audit: AuditLog, user: User, path: str | Path,
                             vault_dir: str | Path, source: str, method: str = "import-file",
                             dataset: str = "default", authorization_ref: str = "",
                             mapping: dict[str, str] | None = None,
                             assume_tz: str | None = None,
                             constants: dict | None = None,
                             profile_name: str = "") -> ImportReport:
    user.require(Permission.IMPORT)
    protected = protect_import(path, vault_dir)
    prov = Provenance(source=source, method=method, is_simulation=False,
                      parameters={"file": protected.original_name, "sha256": protected.sha256,
                                  "authorization_ref": authorization_ref,
                                  "import_profile": profile_name or "auto"})
    observations, report = import_file(protected.stored_path, prov, mapping, assume_tz,
                                       constants)
    db.ensure_dataset(dataset, authorization_ref=authorization_ref)
    db.add_observations(observations, dataset)
    with db.session() as s, s.begin():
        s.add(ImportedFileRow(imported_at=datetime.now(timezone.utc),
                              original_name=protected.original_name,
                              stored_path=str(protected.stored_path), sha256=protected.sha256,
                              size_bytes=protected.size_bytes, rows_imported=report.rows_imported,
                              rows_rejected=report.rows_rejected, dataset=dataset))
    audit.record(user, "import_observations", {
        "file": protected.original_name, "sha256": protected.sha256, "dataset": dataset,
        "imported": report.rows_imported, "rejected": report.rows_rejected,
        "dropped_fields": report.dropped_fields, "profile": profile_name or "auto"})
    return report
