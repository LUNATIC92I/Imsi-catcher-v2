"""Corrélation, export, cartographie, rapports, services et CLI."""

import csv
import html
import io
import json
import re

import pytest

from lunatic_imsi_lab.cli import main
from lunatic_imsi_lab.core.models import PositionKind
from lunatic_imsi_lab.correlation import analysis as corr
from lunatic_imsi_lab.detection.baseline import Baseline
from lunatic_imsi_lab.detection.engine import Assessment, DetectionEngine
from lunatic_imsi_lab.importers.cells import import_csv_text
from lunatic_imsi_lab.core.models import Provenance
from lunatic_imsi_lab.mapping.maps import export_geojson, prepare_points, to_local_km
from lunatic_imsi_lab.reports.builder import ReportInput, build_report
from lunatic_imsi_lab.reports.render import render_html, render_pdf
from lunatic_imsi_lab.security.rbac import PermissionDenied, Role, User
from lunatic_imsi_lab.services import Lab
from lunatic_imsi_lab.simulation.cells import Scenario, SimulationParams
from lunatic_imsi_lab.simulation.spectrum import SpectrumScenario

# Formulations affirmatives interdites dans un rapport.
OVERCLAIM = re.compile(r"(imsi[- ]catcher\s+(a\s+été\s+)?(détecté|identifié|confirmé|localisé)"
                       r"|présence\s+(certaine|confirmée)\s+d'un\s+imsi)", re.I)


@pytest.fixture(scope="module")
def anomaly(sim_results):
    r = sim_results[Scenario.SYNTHETIC_ANOMALY]
    res = DetectionEngine().run(r.observations, Baseline.from_observations(r.baseline))
    return r, res


class TestCorrelation:
    def test_timeline(self, anomaly):
        r, res = anomaly
        tl = corr.build_timeline(r.observations, res.alerts)
        kinds = {e.kind for e in tl}
        assert {"first_seen", "last_seen", "alert", "serving_change"} <= kinds
        assert [e.timestamp for e in tl] == sorted(e.timestamp for e in tl)
        assert all(e.is_simulation for e in tl)

    def test_group_alerts(self, anomaly):
        _, res = anomaly
        dup = res.alerts + res.alerts
        groups = corr.group_alerts(dup)
        assert sum(len(g.alerts) for g in groups) == len(dup)
        assert all(len(g.alerts) % 2 == 0 for g in groups)
        assert groups[0].max_priority == max(a.priority for a in res.alerts)

    def test_persistent_vs_transient(self, anomaly):
        r, _ = anomaly
        changes = corr.compare_with_baseline(r.observations, Baseline.from_observations(
            r.baseline))
        rogue = next(c for c in changes if c.cell_key == r.truth.anomalous_cell_keys[0])
        assert rogue.status == "new" and rogue.persistence == "transient"
        known = [c for c in changes if c.status == "known"]
        assert known and all(c.persistence == "persistent" for c in known)
        assert all(c.rssi_delta_db is not None for c in known)

    def test_missing_cell(self, sim_results):
        r = sim_results[Scenario.COVERAGE_CHANGE]
        changes = corr.compare_with_baseline(r.observations, Baseline.from_observations(
            r.baseline))
        assert "new" not in {c.status for c in changes}
        # La cellule affaiblie disparaît aux 2/3 de la période : couverture réduite.
        ratios = sorted(c.coverage_ratio for c in changes)
        assert 0.5 <= ratios[0] < 0.75 and ratios[1] > 0.95

    def test_compare_empty(self):
        assert corr.compare_with_baseline([], Baseline()) == []

    def test_csv_export_roundtrip_keeps_provenance(self, anomaly, tmp_path):
        r, _ = anomaly
        text = corr.observations_to_csv(r.observations[:50])
        rows = list(csv.DictReader(io.StringIO(text)))
        assert len(rows) == 50
        assert all(row["is_simulation"] == "True" and row["source"] for row in rows)
        assert json.loads(rows[0]["collection_parameters"])["seed"] == 42
        back, rep = import_csv_text(text, Provenance("ré-import", "csv"))
        assert rep.rows_imported == 50
        assert all(o.provenance.is_simulation for o in back)
        assert back[0].broadcast == r.observations[0].broadcast

    def test_json_export(self, anomaly, tmp_path):
        r, res = anomaly
        p = corr.export_json(tmp_path / "e.json", r.observations[:10], res.alerts,
                             corr.build_timeline(r.observations[:10]), {"k": "v"})
        doc = json.loads(p.read_text())
        assert doc["contains_simulation"] and doc["label"] == "SIMULATION"
        assert doc["observations"][0]["provenance"]["source"] == "SIMULATION"
        assert doc["alerts"][0]["alert_id"].startswith("ALR-")

    def test_alerts_csv(self, anomaly):
        _, res = anomaly
        rows = list(csv.DictReader(io.StringIO(corr.alerts_to_csv(res.alerts))))
        assert len(rows) == len(res.alerts)


class TestMapping:
    def test_points_and_kinds(self, anomaly):
        r, res = anomaly
        pts = prepare_points(r.observations, res.alerts)
        assert pts and all(p.kind == PositionKind.GPS for p in pts)
        assert any(p.alert_ids for p in pts)
        xs, ys, lat0, lon0 = to_local_km(pts)
        assert max(map(abs, xs)) < 2 and max(map(abs, ys)) < 2

    def test_estimated_positions_distinguished(self, sim_results, tmp_path):
        r = sim_results[Scenario.INCONSISTENT]
        pts = prepare_points(r.observations, serving_only=False)
        assert {p.kind for p in pts} == {PositionKind.GPS, PositionKind.ESTIMATED}
        gj = json.loads(export_geojson(tmp_path / "m.geojson", pts).read_text())
        kinds = {f["properties"]["position_kind"] for f in gj["features"]}
        assert kinds == {"GPS", "ESTIMATED"}

    def test_no_position(self):
        assert to_local_km([]) == ([], [], 0.0, 0.0)


class TestReports:
    def test_report_structure_and_caution(self, anomaly):
        r, res = anomaly
        content = build_report(ReportInput(
            "Rapport", "Périmètre de test", "alice", "AUT-1", r.observations, res,
            SpectrumScenario.with_anomaly().series(10), ["Récepteur simulé"]))
        titles = [s.title for s in content.sections]
        for needle in ("Périmètre", "Équipements", "Période", "Paramètres", "Observations radio",
                       "Anomalies", "Règles", "Limites", "Hypothèses", "Recommandations"):
            assert any(needle in t for t in titles), needle
        assert content.is_simulation and "SIMULATION" in content.banner
        assert any(s.images for s in content.sections)
        html_text = html.unescape(render_html(content))
        assert not OVERCLAIM.search(html_text)
        assert "faits observés" in html_text and "HYPOTHÈSES" in html_text
        assert "n'est pas démontrée" in html_text
        assert html_text.count("SIMULATION") >= 3

    def test_pdf_is_valid(self, anomaly):
        r, res = anomaly
        content = build_report(ReportInput("R", "S", "a", "", r.observations, res,
                                           include_charts=False))
        pdf = render_pdf(content)
        assert pdf.startswith(b"%PDF") and len(pdf) > 3000

    def test_report_with_insufficient_data(self):
        res = DetectionEngine().run([], Baseline())
        content = build_report(ReportInput("Vide", "", "", "", [], res))
        text = render_html(content)
        assert res.assessment == Assessment.INSUFFICIENT_DATA
        assert "Données insuffisantes" in text and "NON RENSEIGNÉE" in text
        assert render_pdf(content).startswith(b"%PDF")


class TestServicesAndCli:
    def test_lab_workflow(self, tmp_config, tmp_path):
        lab = Lab(tmp_config)
        lab.run_simulation(SimulationParams(scenario=Scenario.POWER_VARIATION, baseline_hours=1,
                                            duration_minutes=60, interval_s=60), n_sweeps=10)
        res = lab.analyze()
        assert res.alerts and lab.db.get_alerts(lab.ws.dataset)
        files = lab.export(tmp_path / "exp")
        assert all(p.exists() for p in files)
        reports = lab.generate_report("t", "s", tmp_path / "rep")
        assert {p.suffix for p in reports} == {".pdf", ".html"}
        assert len(lab.db.list_reports()) == 2
        lab.load(lab.ws.dataset, lab.ws.baseline_dataset)
        assert lab.ws.observations and lab.ws.baseline_obs and len(lab.ws.sweeps) == 10
        actions = [e.action for e in lab.audit.entries()]
        assert {"simulation", "analyze", "export", "report"} <= set(actions)

    def test_viewer_cannot_simulate(self, tmp_config):
        lab = Lab(tmp_config, User("v", Role.VIEWER))
        with pytest.raises(PermissionDenied):
            lab.run_simulation(SimulationParams())

    def test_cli(self, tmp_path, capsys):
        d = str(tmp_path / "data")
        assert main(["--data-dir", d, "simulate", "--scenario", "normal", "--duration", "20",
                     "--report", "--out", str(tmp_path / "r")]) == 0
        out = capsys.readouterr().out
        assert "[SIMULATION]" in out and "Rapport" in out
        assert main(["--data-dir", d, "datasets"]) == 0
        assert "SIMULATION-normal-42" in capsys.readouterr().out
        assert main(["--data-dir", d, "analyze", "--dataset", "SIMULATION-normal-42",
                     "--baseline", "SIMULATION-normal-42-ref"]) == 0
        assert main(["--data-dir", d, "audit", "--verify"]) == 0
        assert main(["--data-dir", d, "--role", "viewer", "simulate"]) == 3
        assert main(["--data-dir", d, "delete", "SIMULATION-normal-42", "--reason", "nettoyage",
                     "--confirm", "SIMULATION-normal-42"]) == 3  # analyste ≠ admin
        assert main(["--data-dir", d, "--role", "admin", "delete", "SIMULATION-normal-42",
                     "--reason", "nettoyage", "--confirm", "SIMULATION-normal-42"]) == 0
        assert main(["--data-dir", d, "analyze", "--dataset", "absent"]) == 1

    def test_cli_import_privacy_file(self, tmp_path, capsys):
        from lunatic_imsi_lab.simulation.dataset import write_lab_datasets
        files = write_lab_datasets(tmp_path / "syn")
        priv = next(p for p in files if p.name == "privacy_filter_test.csv")
        d = str(tmp_path / "data")
        assert main(["--data-dir", d, "import", str(priv), "--source", "test",
                     "--dataset", "priv"]) == 0
        out = capsys.readouterr().out
        assert "imsi" in out and "imei" in out and "001010000000001" not in out
        manifest = json.loads((tmp_path / "syn" / "MANIFEST.json").read_text())
        assert manifest["label"] == "SIMULATION" and len(manifest["datasets"]) == 6
