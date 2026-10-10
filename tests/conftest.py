import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lunatic_imsi_lab.config import AppConfig  # noqa: E402
from lunatic_imsi_lab.security.rbac import Role, User  # noqa: E402
from lunatic_imsi_lab.simulation.cells import Scenario, SimulationParams, simulate  # noqa: E402


@pytest.fixture
def tmp_config(tmp_path):
    return AppConfig(data_dir=str(tmp_path / "lab"))


@pytest.fixture
def analyst():
    return User("alice", Role.ANALYST)


@pytest.fixture
def admin():
    return User("root", Role.ADMIN)


@pytest.fixture
def viewer():
    return User("bob", Role.VIEWER)


@pytest.fixture(scope="session")
def sim_results():
    """Un résultat par scénario (paramètres allégés, reproductibles)."""
    return {sc: simulate(SimulationParams(scenario=sc, seed=42, baseline_hours=2.0,
                                          interval_s=60.0))
            for sc in Scenario}
