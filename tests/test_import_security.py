"""Import, filtre de confidentialité, protection des fichiers, base, audit, RBAC,
suppression contrôlée."""

import json
import os
import stat

import pytest

from lunatic_imsi_lab.core.models import PositionKind, Provenance, Technology
from lunatic_imsi_lab.importers.cells import import_csv_text, import_json_text, is_forbidden
from lunatic_imsi_lab.importers.service import import_observations_file
from lunatic_imsi_lab.security.audit import AuditLog
from lunatic_imsi_lab.security.deletion import DeletionRefused, delete_dataset
from lunatic_imsi_lab.security.files import (ImportRejected, protect_import, secure_delete_file,
                                             verify_integrity)
from lunatic_imsi_lab.security.rbac import Permission, PermissionDenied
from lunatic_imsi_lab.storage.db import AuditRow, Database

PROV = Provenance("Outil de test", "import-csv")

CSV = """timestamp;rat;mcc;mnc;tac;eci;earfcn;pci;rsrp;rsrq;lat;lon;gps_fix;IMSI;imei;bcast_neighbor_count
2026-01-15T10:00:00Z;LTE;208;10;31010;123456;1300;101;-85;-11;48.85;2.35;GPS;001010000000001;000000000000001;8
2026-01-15T10:00:30Z;4G;208;10;31010;123456;1300;101;-86,5;-11;48.85;2.35;;001010000000002;000000000000002;8
2026-01-15T10:01:00Z;LTE;208;10;31010;123456;1300;101;-300;-11;;;;001010000000003;000000000000003;8
pas-une-date;LTE;208;10;31010;123456;1300;101;-80;-11;;;;x;y;8
2026-01-15T10:02:00Z;Wifi;208;10;31010;123456;1300;101;-80;-11;;;;x;y;8
"""


class TestImporter:
    def test_parsing_and_aliases(self):
        obs, rep = import_csv_text(CSV, PROV, "t.csv")
        assert rep.rows_total == 5 and rep.rows_imported == 2 and rep.rows_rejected == 3
        o = obs[0]
        assert o.technology == Technology.LTE and o.area_code == 31010 and o.cell_id == 123456
        assert o.frequency_mhz == pytest.approx(1815.0)  # calculée depuis l'EARFCN
        assert o.rssi_dbm == -85 and obs[1].rssi_dbm == -86.5  # virgule décimale acceptée
        assert o.position_kind == PositionKind.GPS
        assert obs[1].position_kind == PositionKind.ESTIMATED  # pas de fix GNSS déclaré
        assert o.broadcast == {"neighbor_count": "8"}
        assert o.provenance.parameters["timezone_assumed_for_naive"] == "UTC"

    def test_privacy_filter_drops_identifiers(self):
        obs, rep = import_csv_text(CSV, PROV, "t.csv")
        assert set(rep.dropped_fields) == {"IMSI", "imei"}
        blob = json.dumps([o.to_dict() for o in obs])
        assert "001010000000001" not in blob and "000000000000001" not in blob
        assert any("supprimées" in w for w in rep.warnings)

    @pytest.mark.parametrize("name", ["IMSI", "imei", "IMEISV", "tmsi", "msisdn", "SUCI",
                                      "ue_imsi", "imsi_hash", "Phone Number"])
    def test_forbidden_names(self, name):
        assert is_forbidden(name)

    @pytest.mark.parametrize("name", ["cell_id", "rssi", "lac", "timestamp"])
    def test_allowed_names(self, name):
        assert not is_forbidden(name)

    def test_mapping_to_forbidden_column_refused(self):
        with pytest.raises(ValueError):
            import_csv_text(CSV, PROV, mapping={"cell_id": "IMSI"})

    def test_rejection_reasons(self):
        _, rep = import_csv_text(CSV, PROV)
        joined = " ".join(rep.errors)
        assert "puissance hors plage" in joined
        assert "horodatage illisible" in joined
        assert "technologie inconnue" in joined

    def test_missing_mandatory_columns(self):
        with pytest.raises(ValueError, match="obligatoires"):
            import_csv_text("mcc,mnc\n208,10\n", PROV)

    def test_json_import_and_broadcast_object(self):
        data = {"observations": [{"time": 1768471200, "technology": "GSM", "mcc": 208,
                                  "mnc": 1, "lac": 100, "cid": 7, "arfcn": 62, "rssi": -70,
                                  "imsi": "001010000000009",
                                  "broadcast": {"neighbor_count": 0, "imsi": "x"}}]}
        obs, rep = import_json_text(json.dumps(data), PROV)
        assert rep.rows_imported == 1 and "imsi" in rep.dropped_fields
        assert obs[0].frequency_mhz == pytest.approx(947.4)
        assert obs[0].broadcast == {"neighbor_count": 0}

    def test_json_invalid_structure(self):
        with pytest.raises(ValueError):
            import_json_text('{"observations": 3}', PROV)

    def test_simulation_flag_cannot_be_removed(self):
        csv_text = ("timestamp,technology,mcc,mnc,lac,cid,is_simulation\n"
                    "2026-01-15T10:00:00Z,GSM,1,1,1,1,true\n")
        obs, _ = import_csv_text(csv_text, PROV)
        assert obs[0].provenance.is_simulation

    def test_timezone_assumption(self):
        csv_text = "timestamp,technology\n2026-01-15 11:00:00,GSM\n"
        obs, _ = import_csv_text(csv_text, PROV, assume_tz="Europe/Paris")
        assert obs[0].timestamp.hour == 10
        assert obs[0].provenance.parameters["timezone_assumed_for_naive"] == "Europe/Paris"

    def test_empty(self):
        obs, rep = import_csv_text("timestamp,technology\n", PROV)
        assert obs == [] and rep.warnings


class TestFileProtection:
    def test_protect_copies_readonly_with_hash(self, tmp_path):
        src = tmp_path / "evil name.csv"
        src.write_text(CSV)
        pf = protect_import(src, tmp_path / "vault")
        assert pf.stored_path.parent == tmp_path / "vault"
        assert pf.stored_path.name == pf.sha256 + ".csv"
        assert not (os.stat(pf.stored_path).st_mode & stat.S_IWUSR)
        assert verify_integrity(pf)

    @pytest.mark.parametrize("name,content", [("x.exe", "a"), ("x.csv", "")])
    def test_rejections(self, tmp_path, name, content):
        p = tmp_path / name
        p.write_text(content)
        with pytest.raises(ImportRejected):
            protect_import(p, tmp_path / "vault")

    def test_too_big_and_missing_and_symlink(self, tmp_path):
        p = tmp_path / "big.csv"
        p.write_text("x" * 100)
        with pytest.raises(ImportRejected):
            protect_import(p, tmp_path / "v", max_bytes=10)
        with pytest.raises(ImportRejected):
            protect_import(tmp_path / "absent.csv", tmp_path / "v")
        link = tmp_path / "link.csv"
        link.symlink_to(p)
        with pytest.raises(ImportRejected):
            protect_import(link, tmp_path / "v")

    def test_secure_delete(self, tmp_path):
        p = tmp_path / "f.csv"
        p.write_text("secret")
        os.chmod(p, stat.S_IRUSR)
        secure_delete_file(p)
        assert not p.exists()
        secure_delete_file(p)  # idempotent


class TestRbacAuditDeletion:
    def test_roles(self, viewer, analyst, admin):
        assert viewer.can(Permission.VIEW) and not viewer.can(Permission.IMPORT)
        assert analyst.can(Permission.IMPORT) and not analyst.can(Permission.DELETE_DATA)
        assert all(admin.can(p) for p in Permission)
        with pytest.raises(PermissionDenied):
            viewer.require(Permission.ANALYZE)

    def test_audit_chain_detects_tampering(self, analyst):
        db = Database()
        audit = AuditLog(db)
        for i in range(3):
            audit.record(analyst, "action", {"i": i})
        assert audit.verify() == (True, None)
        with db.session() as s, s.begin():
            row = s.get(AuditRow, 2)
            row.details = '{"i": 99}'
        ok, bad = audit.verify()
        assert not ok and bad == 2

    def test_import_service_and_controlled_deletion(self, tmp_path, analyst, admin, viewer):
        db = Database(tmp_path / "lab.sqlite")
        audit = AuditLog(db)
        src = tmp_path / "m.csv"
        src.write_text(CSV)
        with pytest.raises(PermissionDenied):
            import_observations_file(db, audit, viewer, src, tmp_path / "vault", "x")
        rep = import_observations_file(db, audit, analyst, src, tmp_path / "vault", "Outil",
                                       dataset="site", authorization_ref="AUT-1")
        assert rep.rows_imported == 2 and db.count_observations("site") == 2
        stored = list((tmp_path / "vault").iterdir())
        assert len(stored) == 1

        with pytest.raises(PermissionDenied):
            delete_dataset(db, audit, analyst, "site", "fin de mission", "site")
        with pytest.raises(DeletionRefused):
            delete_dataset(db, audit, admin, "site", "", "site")
        with pytest.raises(DeletionRefused):
            delete_dataset(db, audit, admin, "site", "fin de mission", "autre")
        counts = delete_dataset(db, audit, admin, "site", "fin de mission", "site")
        assert counts["observations"] == 2 and counts["files_wiped"] == 1
        assert db.count_observations("site") == 0
        assert not any((tmp_path / "vault").iterdir())
        actions = [e.action for e in audit.entries()]
        assert actions[0] == "delete_dataset" and "import_observations" in actions
        assert audit.verify()[0]


def test_config_roundtrip(tmp_path):
    from lunatic_imsi_lab.config import AppConfig, Band, DeviceConfig
    cfg = AppConfig(data_dir=str(tmp_path))
    cfg.devices.append(DeviceConfig("RTL", "soapy", "driver=rtlsdr", calibration_offset_db=-12.5))
    cfg.bands.append(Band("B28", "LTE", 758, 803))
    cfg.authorization_ref = "AUT-9"
    back = AppConfig.load(cfg.save())
    assert back.devices[-1].calibration_offset_db == -12.5
    assert back.band_for(780).name == "B28" and back.authorization_ref == "AUT-9"
    assert back.local_only and not back.store_raw_iq
    assert AppConfig.load(tmp_path / "absent.json").bands
