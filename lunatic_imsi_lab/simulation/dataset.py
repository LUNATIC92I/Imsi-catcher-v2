"""Écriture des jeux de données synthétiques reproductibles du laboratoire."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from lunatic_imsi_lab.correlation.analysis import export_json, observations_to_csv
from lunatic_imsi_lab.simulation.cells import Scenario, SimulationParams, simulate
from lunatic_imsi_lab.simulation.spectrum import SpectrumScenario


def write_lab_datasets(directory: str | Path, seed: int = 42) -> list[Path]:
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    manifest = {"label": "SIMULATION", "seed": seed, "datasets": []}
    # Paramètres allégés pour limiter la taille des fichiers versionnés.
    light = dict(seed=seed, baseline_hours=2.0, interval_s=60.0)
    for sc in Scenario:
        params = SimulationParams(scenario=sc, **light)
        res = simulate(params)
        ref = d / f"sim_{sc.value}_reference.csv"
        obs = d / f"sim_{sc.value}_observations.csv"
        ref.write_text(observations_to_csv(res.baseline), encoding="utf-8")
        obs.write_text(observations_to_csv(res.observations), encoding="utf-8")
        written += [ref, obs]
        manifest["datasets"].append({
            "scenario": sc.value, "label": sc.label, "parameters": params.to_dict(),
            "reference": ref.name,
            "observations": obs.name, "events": res.truth.events,
            "expected_legitimate": res.truth.expected_legitimate,
            "anomalous_cell_keys": res.truth.anomalous_cell_keys})
    # Variante JSON (scénario multi-indicateurs).
    res = simulate(SimulationParams(scenario=Scenario.SYNTHETIC_ANOMALY, **light))
    written.append(export_json(d / "sim_synthetic_anomaly.json", res.observations))
    # Spectres synthétiques.
    for name, sc in (("normal", SpectrumScenario.default(seed)),
                     ("anomaly", SpectrumScenario.with_anomaly(seed))):
        sweeps = sc.series(45)
        p = d / f"sim_spectrum_{name}.npz"
        np.savez_compressed(p, frequencies_hz=sweeps[0].frequencies_hz,
                            power_dbm=np.vstack([s.power_dbm for s in sweeps]).astype(np.float32),
                            timestamps=np.array([s.timestamp.isoformat() for s in sweeps]),
                            label=np.array("SIMULATION"))
        written.append(p)
    # Fichier de test du filtre de confidentialité : colonnes IMSI/IMEI avec
    # des valeurs de test (PLMN de test 001-01) qui doivent être supprimées.
    priv = d / "privacy_filter_test.csv"
    priv.write_text(
        "timestamp,technology,mcc,mnc,lac,cid,arfcn,rssi,imsi,imei,source,is_simulation\n"
        "2026-01-15T10:00:00Z,GSM,1,1,100,200,62,-70,001010000000001,000000000000001,"
        "SIMULATION,true\n"
        "2026-01-15T10:00:30Z,GSM,1,1,100,200,62,-71,001010000000002,000000000000002,"
        "SIMULATION,true\n", encoding="utf-8")
    written.append(priv)
    m = d / "MANIFEST.json"
    m.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
                 encoding="utf-8")
    written.append(m)
    return written
