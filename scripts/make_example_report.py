"""Régénère l'exemple de rapport (examples/) à partir du scénario synthétique."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lunatic_imsi_lab.detection.baseline import Baseline  # noqa: E402
from lunatic_imsi_lab.detection.engine import DetectionEngine, spectrum_indicators  # noqa: E402
from lunatic_imsi_lab.radio.spectrum import detect_power_variations  # noqa: E402
from lunatic_imsi_lab.reports.builder import ReportInput, build_report  # noqa: E402
from lunatic_imsi_lab.reports.render import write_html, write_pdf  # noqa: E402
from lunatic_imsi_lab.simulation.cells import Scenario, SimulationParams, simulate  # noqa: E402
from lunatic_imsi_lab.simulation.spectrum import SpectrumScenario  # noqa: E402


def main() -> None:
    params = SimulationParams(scenario=Scenario.SYNTHETIC_ANOMALY, seed=42)
    sim = simulate(params)
    sc = SpectrumScenario.with_anomaly(params.seed)
    sc.start = sim.observations[0].timestamp
    sc.step_s = params.duration_minutes * 60 / 60
    sweeps = sc.series(60)
    extra = spectrum_indicators(detect_power_variations(sweeps), is_simulation=True)
    result = DetectionEngine().run(sim.observations, Baseline.from_observations(sim.baseline),
                                   extra)
    content = build_report(ReportInput(
        title="Exemple de rapport — scénario synthétique multi-indicateurs",
        scope=("Démonstration du format de rapport sur données de SIMULATION (aucune mesure "
               "réelle). Environnement urbain virtuel de 6 cellules, référence de 6 h, "
               "observation de 2 h."),
        operator="laboratoire (exemple)", authorization_ref="N/A — données synthétiques",
        observations=sim.observations, analysis=result, sweeps=sweeps,
        equipment=["Récepteur simulé (aucune émission)"],
        measurement_parameters=params.to_dict()))
    out = ROOT / "examples"
    for writer, name in ((write_pdf, "exemple_rapport.pdf"), (write_html, "exemple_rapport.html")):
        path, digest = writer(content, out / name)
        print(path, digest)


if __name__ == "__main__":
    main()
