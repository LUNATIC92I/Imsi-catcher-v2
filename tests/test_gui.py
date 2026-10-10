"""Tests de fumée de l'IHM (plateforme Qt « offscreen »)."""

import time

import pytest

pytest.importorskip("PySide6")
try:  # bibliothèques système Qt absentes (libEGL...) → tests ignorés
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError as exc:  # pragma: no cover
    pytest.skip(f"Qt indisponible : {exc}", allow_module_level=True)

from lunatic_imsi_lab.gui.main_window import MainWindow  # noqa: E402
from lunatic_imsi_lab.security.rbac import Role, User  # noqa: E402
from lunatic_imsi_lab.services import Lab  # noqa: E402
from lunatic_imsi_lab.simulation.cells import Scenario  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def boxes(monkeypatch):
    shown = []
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name,
                            lambda *a, _n=name, **k: shown.append((_n, a[1:3])) or 0)
    return shown


def wait_idle(qapp, win, timeout=60):
    end = time.time() + timeout
    while win._busy and time.time() < end:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()
    assert not win._busy, "tâche de fond non terminée"


def page(win, cls_name):
    return next(p for p in win.pages if type(p).__name__ == cls_name)


def test_window_builds_with_all_pages(qapp, tmp_config, boxes):
    win = MainWindow(Lab(tmp_config))
    labels = [win.nav.item(i).text() for i in range(win.nav.count())]
    for needle in ("Tableau de bord", "spectre", "cellules", "Anomalies", "Chronologie",
                   "Cartographie", "simulation", "Console", "Rapports", "Équipements"):
        assert any(needle in lab for lab in labels), needle
    for i in range(win.nav.count()):
        win.nav.setCurrentRow(i)
        qapp.processEvents()
    win.close()


def test_simulation_workflow_through_gui(qapp, tmp_config, boxes):
    lab = Lab(tmp_config)
    win = MainWindow(lab)
    sim = page(win, "SimulationPage")
    sim.scenario.setCurrentIndex(sim.scenario.findData(Scenario.SYNTHETIC_ANOMALY))
    sim.base_h.setValue(1.0)
    sim.duration.setValue(60)
    sim.interval.setValue(60)
    sim.run()
    wait_idle(qapp, win)
    assert lab.ws.result is not None and lab.ws.is_simulation
    assert "SIMULATION" in sim.out.toPlainText()
    assert "oui" in sim.out.toPlainText()  # cohérent avec la vérité terrain
    for p in win.pages:
        assert p.sim_banner.isVisible() or not p.isVisible()
        assert p.sim_banner.text().startswith("SIMULATION")
    anomalies = page(win, "AnomaliesPage")
    assert anomalies.table.model.rowCount() == len(lab.ws.result.alerts)
    anomalies.table.view.selectRow(0)
    assert "Faux positifs possibles" in anomalies.detail.toPlainText()
    cells = page(win, "CellsPage")
    assert cells.table.model.rowCount() >= 6
    assert win.ds_combo.count() >= 3  # « choisir » + jeu + référence

    # Acquisition simulée dans l'analyseur de spectre
    spec = page(win, "SpectrumPage")
    n = len(lab.ws.sweeps)
    spec.acquire()
    wait_idle(qapp, win)
    assert len(lab.ws.sweeps) == n + 1 and spec.emissions.model.rowCount() >= 3

    # Rapport via la page Rapports
    rep = page(win, "ReportsPage")
    rep.generate()
    wait_idle(qapp, win)
    assert rep.table.model.rowCount() == 2
    win.close()


def test_viewer_restrictions(qapp, tmp_config, boxes):
    lab = Lab(tmp_config, User("lecteur", Role.VIEWER))
    win = MainWindow(lab)
    page(win, "SpectrumPage").acquire()
    assert boxes and boxes[-1][0] == "warning"
    assert lab.ws.sweeps == []
    page(win, "SimulationPage").run()
    wait_idle(qapp, win)
    assert lab.ws.result is None
    console = page(win, "ConsolePage")
    assert "réservée" in console.integrity.text()
    win.close()


def test_rules_page(qapp, tmp_config, boxes):
    analyst_win = MainWindow(Lab(tmp_config))
    rules = page(analyst_win, "RulesPage")
    assert not rules.apply_btn.isEnabled() and "réservée" in rules.status.text()
    analyst_win.close()

    lab = Lab(tmp_config, User("root", Role.ADMIN))
    win = MainWindow(lab)
    rules = page(win, "RulesPage")
    assert rules.apply_btn.isEnabled()
    rules.profile.setCurrentIndex(rules.profile.findData("vehicule"))
    rules.load_profile()
    assert rules.inputs["jump_db"].value() == 18.0
    rules.checks["R07_SPATIAL"].setChecked(False)
    rules.apply()
    wait_idle(qapp, win)
    assert lab.engine.config.profile == "vehicule"
    assert lab.engine.disabled_rules == ["R07_SPATIAL"]
    win.close()


def test_import_dialog_preview(qapp, tmp_config, tmp_path, boxes):
    from lunatic_imsi_lab.gui.pages.cells import ImportDialog
    p = tmp_path / "nr.csv"
    p.write_text("Time;NCI;NR-ARFCN;SS-RSRP;IMSI\n2026-01-15T10:00:00Z;1;636666;-90;0010100\n")
    lab = Lab(tmp_config)
    dlg = ImportDialog(None, str(p), lab.import_profiles())
    assert not dlg.ok_button.isEnabled() and "MANQUANTS" in dlg.preview.text()
    dlg.profile.setCurrentIndex(dlg.profile.findData("nr-3gpp"))
    assert dlg.ok_button.isEnabled()
    assert "IMSI" in dlg.preview.text() and "0010100" not in dlg.preview.text()


def test_profile_editor(qapp, tmp_config, boxes):
    from lunatic_imsi_lab.gui.profile_editor import ProfileEditor
    lab = Lab(tmp_config, User("root", Role.ADMIN))
    win = MainWindow(lab)
    ed = ProfileEditor(win)
    ed.choice.setCurrentIndex(ed.choice.findData("builtin:nr-3gpp"))   # partir d'un modèle
    assert ed.cols["rssi_dbm"].text() == "SS-RSRP" and ed.name.text() == ""
    ed.name.setText("mon-outil")
    ed.cols["rssi_dbm"].setText("RSRP_5G")
    ed.save()
    assert lab.config.import_profiles["mon-outil"]["columns"]["rssi_dbm"] == "RSRP_5G"
    assert lab.config.import_profiles["mon-outil"]["constants"] == {"technology": "NR"}
    ed.cols["cell_id"].setText("IMSI")                     # refusé
    ed.save()
    assert lab.config.import_profiles["mon-outil"]["columns"]["cell_id"] == "NCI"  # inchangé
    ed.choice.setCurrentIndex(ed.choice.findData("mon-outil"))
    ed.delete()
    assert "mon-outil" not in lab.config.import_profiles
    win.close()
