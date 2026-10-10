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
