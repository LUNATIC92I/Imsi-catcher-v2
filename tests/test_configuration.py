"""Seuils configurables, profils d'import, suppression DC, commandes associées."""

import json

import numpy as np
import pytest

from lunatic_imsi_lab.cli import main
from lunatic_imsi_lab.core.models import Provenance, Technology
from lunatic_imsi_lab.detection.baseline import Baseline
from lunatic_imsi_lab.detection.engine import SINGLE_INDICATOR_CAP, DetectionEngine
from lunatic_imsi_lab.detection.rules import RULE_PROFILES, RuleConfig
from lunatic_imsi_lab.importers.cells import import_csv_text
from lunatic_imsi_lab.importers.profiles import (BUILTIN_PROFILES, all_profiles, preview_file,
                                                 validate_profile)
from lunatic_imsi_lab.radio.receivers import make_receiver, suppress_dc
from lunatic_imsi_lab.reports.builder import ReportInput, build_report
from lunatic_imsi_lab.reports.render import render_html
from lunatic_imsi_lab.security.rbac import PermissionDenied, Role, User
from lunatic_imsi_lab.services import Lab
from lunatic_imsi_lab.simulation.cells import Scenario


class TestRuleConfig:
    def test_defaults_and_roundtrip(self):
        cfg = RuleConfig()
        assert RuleConfig.from_dict(cfg.to_dict()) == cfg
        assert RuleConfig.from_dict({}) == cfg
        assert RuleConfig.from_dict({"unknown": 1}) == cfg

    @pytest.mark.parametrize("bad", [{"jump_db": 1}, {"strong_signal_dbm": 5},
                                     {"min_jumps": 0}, {"jump_db": "12"},
                                     {"short_lived_max_s": 5000, "short_lived_min_span_s": 3000}])
    def test_validation(self, bad):
        with pytest.raises(ValueError):
            RuleConfig.from_dict(bad)

    def test_profiles(self):
        for name in RULE_PROFILES:
            cfg = RuleConfig.for_profile(name)
            assert cfg.profile == name
        assert RuleConfig.for_profile("vehicule").jump_db > RuleConfig().jump_db
        assert RuleConfig.for_profile("fixe").jump_db < RuleConfig().jump_db
        with pytest.raises(ValueError):
            RuleConfig.for_profile("inexistant")

    def test_thresholds_change_detection(self, sim_results):
        r = sim_results[Scenario.POWER_VARIATION]
        base = Baseline.from_observations(r.baseline)
        default = DetectionEngine().run(r.observations, base)
        assert any("R04_POWER_ANOMALY" in a.rules for a in default.alerts)
        tolerant = DetectionEngine(config=RuleConfig.from_dict({"jump_db": 30.0}))
        res = tolerant.run(r.observations, base)
        assert not any("R04_POWER_ANOMALY" in a.rules for a in res.alerts)
        assert res.rule_config["jump_db"] == 30.0

    def test_disabled_rules(self, sim_results):
        r = sim_results[Scenario.SYNTHETIC_ANOMALY]
        eng = DetectionEngine(disabled_rules=["R01_UNKNOWN_CELL", "R10_SPECTRUM_POWER"])
        res = eng.run(r.observations, Baseline.from_observations(r.baseline))
        assert all("R01_UNKNOWN_CELL" not in a.rules for a in res.alerts)
        assert res.disabled_rules == ["R01_UNKNOWN_CELL", "R10_SPECTRUM_POWER"]
        assert any("désactivées" in q for q in res.data_quality)
        # Désactiver une règle n'est pas un manque de données : pas de pénalité.
        assert res.alerts[0].confidence_score > 0.5
        with pytest.raises(ValueError):
            DetectionEngine(disabled_rules=["R99_FAKE"])

    def test_cap_is_not_configurable(self):
        assert "single" not in " ".join(RuleConfig().to_dict()).lower()
        assert SINGLE_INDICATOR_CAP == 0.40

    def test_update_rules_service(self, tmp_config, sim_results):
        analyst = Lab(tmp_config)
        with pytest.raises(PermissionDenied):
            analyst.update_rules({"jump_db": 15})
        admin = Lab(tmp_config, User("root", Role.ADMIN))
        with pytest.raises(ValueError):
            admin.update_rules({"jump_db": 999})
        assert admin.engine.config.jump_db == 12.0  # rien n'a changé
        admin.update_rules({**RuleConfig.for_profile("fixe").to_dict()}, ["R07_SPATIAL"])
        assert admin.engine.config.profile == "fixe"
        reloaded = Lab(type(tmp_config).load(tmp_config.data_dir + "/config.json"))
        assert reloaded.engine.config.jump_db == 8.0
        assert reloaded.engine.disabled_rules == ["R07_SPATIAL"]
        entry = admin.audit.entries(1)[0]
        assert entry.action == "update_rules" and '"before"' in entry.details

    def test_report_mentions_thresholds(self, sim_results):
        r = sim_results[Scenario.NORMAL]
        res = DetectionEngine(config=RuleConfig.for_profile("rural"),
                              disabled_rules=["R08_BROADCAST"]).run(
            r.observations, Baseline.from_observations(r.baseline))
        text = render_html(build_report(ReportInput("t", "", "", "", r.observations, res,
                                                    include_charts=False)))
        assert "Rural" in text and "Seuil de signal fort : -80.0 dBm" in text
        assert "R08_BROADCAST" in text and "pas été évalués" in text


CSV_NR = ("Time;NCI;NR-ARFCN;SS-RSRP;SS-RSRQ;TAC;PCI;MCC;MNC;IMSI\n"
          "2026-01-15T10:00:00Z;68719476737;636666;-90;-11;100;5;208;10;001010000000001\n")


class TestImportProfiles:
    def test_builtin_nr_profile(self, tmp_path):
        p = tmp_path / "nr.csv"
        p.write_text(CSV_NR)
        prof = BUILTIN_PROFILES["nr-3gpp"]
        pv = preview_file(p, prof)
        assert pv.ok and pv.resolved["rssi_dbm"] == "SS-RSRP"
        assert pv.constants == {"technology": "NR"} and pv.dropped == ["IMSI"]
        obs, rep = import_csv_text(CSV_NR, Provenance("t", "t"), mapping=prof["columns"],
                                   constants=prof["constants"])
        assert rep.rows_imported == 1
        o = obs[0]
        assert o.technology == Technology.NR and o.cell_id == 68719476737
        assert o.frequency_mhz == pytest.approx(3549.99, abs=0.01) and o.rssi_dbm == -90

    def test_preview_auto_reports_missing_technology(self, tmp_path):
        p = tmp_path / "nr.csv"
        p.write_text(CSV_NR)
        pv = preview_file(p, BUILTIN_PROFILES["auto"])
        assert not pv.ok and pv.missing_required == ["technology"]
        assert "NCI" in pv.unused or "NCI" in pv.resolved.values()

    def test_profile_validation(self):
        with pytest.raises(ValueError):
            validate_profile({"columns": {"cell_id": "imsi"}})
        with pytest.raises(ValueError):
            validate_profile({"columns": {"subscriber": "x"}})
        with pytest.raises(ValueError):
            validate_profile({"constants": {"imei": "x"}})
        assert "perso" in all_profiles({"perso": {"label": "x", "columns": {"cell_id": "Z"}}})

    def test_constants_cannot_override_existing_column(self):
        csv_text = "timestamp,technology\n2026-01-15T10:00:00Z,GSM\n"
        obs, _ = import_csv_text(csv_text, Provenance("t", "t"), constants={"technology": "LTE"})
        assert obs[0].technology == Technology.GSM

    def test_lab_import_with_profile(self, tmp_config, tmp_path):
        p = tmp_path / "nr.csv"
        p.write_text(CSV_NR)
        lab = Lab(tmp_config)
        rep = lab.import_file(p, "Outil NR", "nr", profile="nr-3gpp")
        assert rep.rows_imported == 1
        o = lab.db.get_observations("nr")[0]
        assert o.provenance.parameters["import_profile"] == "nr-3gpp"
        with pytest.raises(ValueError):
            lab.import_file(p, "x", "nr", profile="inconnu")
        with pytest.raises(PermissionDenied):
            lab.save_import_profile("perso", {"columns": {}})
        admin = Lab(tmp_config, User("root", Role.ADMIN))
        admin.save_import_profile("perso", {"label": "Mon outil",
                                            "columns": {"rssi_dbm": "SS-RSRP"},
                                            "constants": {"technology": "NR"}})
        assert "perso" in Lab(type(tmp_config).load(
            tmp_config.data_dir + "/config.json")).import_profiles()
        with pytest.raises(ValueError):
            admin.save_import_profile("auto", {})


class TestDcSuppression:
    def test_spike_removed_signal_kept(self):
        f = np.linspace(-1e6, 1e6, 201)
        p = np.full(201, -100.0)
        p[100] = -40.0                     # raie DC
        p[150] = -50.0                     # vraie émission hors zone
        out = suppress_dc(f, p, 0.0, 2e4)
        assert out[100] == pytest.approx(-100.0) and out[150] == -50.0
        assert p[100] == -40.0             # l'entrée n'est pas modifiée

    def test_degenerate_cases(self):
        f = np.linspace(-1, 1, 5)
        p = np.arange(5.0)
        assert np.array_equal(suppress_dc(f, p, 10.0, 0.1), p)   # hors bloc
        assert np.array_equal(suppress_dc(f, p, 0.0, 10.0), p)   # couvre tout

    def test_receiver_parameter(self):
        rx = make_receiver("soapy", args="driver=rtlsdr", dc_bins=0)
        assert rx.dc_bins == 0


class TestCli:
    def test_rules_and_profiles_commands(self, tmp_path, capsys):
        d = str(tmp_path / "data")
        assert main(["--data-dir", d, "rules"]) == 0
        assert "jump_db" in capsys.readouterr().out
        assert main(["--data-dir", d, "rules", "--profile", "fixe"]) == 3   # analyste
        assert main(["--data-dir", d, "--role", "admin", "rules", "--profile", "vehicule",
                     "--set", "jump_db=20", "--disable", "R07_SPATIAL"]) == 0
        out = capsys.readouterr().out
        assert "vehicule" in out and "R07_SPATIAL" in out
        cfg = json.loads((tmp_path / "data" / "config.json").read_text())
        assert cfg["rule_config"]["jump_db"] == 20.0
        assert main(["--data-dir", d, "--role", "admin", "rules", "--set", "jump_db=1"]) == 1
        assert main(["--data-dir", d, "profiles"]) == 0
        assert "nr-3gpp" in capsys.readouterr().out

    def test_preview_and_import_with_profile(self, tmp_path, capsys):
        p = tmp_path / "nr.csv"
        p.write_text(CSV_NR)
        d = str(tmp_path / "data")
        assert main(["--data-dir", d, "preview", str(p)]) == 1
        assert "technology" in capsys.readouterr().out
        assert main(["--data-dir", d, "preview", str(p), "--profile", "nr-3gpp"]) == 0
        out = capsys.readouterr().out
        assert "IMSI" in out and "001010000000001" not in out
        prof = tmp_path / "p.json"
        prof.write_text(json.dumps(BUILTIN_PROFILES["nr-3gpp"]))
        assert main(["--data-dir", d, "import", str(p), "--source", "x", "--dataset", "nr",
                     "--profile-file", str(prof)]) == 0
