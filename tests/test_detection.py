"""Moteur de détection : règles, faux positifs, données insuffisantes, prudence."""

from datetime import datetime, timedelta, timezone

import pytest

from lunatic_imsi_lab.core.models import (CellObservation, ConfidenceLevel, PositionKind,
                                          Provenance, Severity, Technology)
from lunatic_imsi_lab.detection import rules as R
from lunatic_imsi_lab.detection.baseline import Baseline
from lunatic_imsi_lab.detection.engine import (SINGLE_INDICATOR_CAP, Assessment, DetectionEngine,
                                               spectrum_indicators)
from lunatic_imsi_lab.radio.spectrum import detect_power_variations
from lunatic_imsi_lab.simulation.cells import Scenario, SimulationParams, simulate
from lunatic_imsi_lab.simulation.spectrum import SpectrumScenario

T0 = datetime(2026, 1, 15, 8, tzinfo=timezone.utc)
P = Provenance("test", "unit")


def ob(t=0, tech=Technology.LTE, area=100, cid=1, ch=1300, pci=10, rssi=-80.0, serving=True,
       lat=None, lon=None, kind=PositionKind.NONE, mnc=10, **bc):
    return CellObservation(timestamp=T0 + timedelta(seconds=t), technology=tech, mcc=208,
                           mnc=mnc, area_code=area, cell_id=cid, channel=ch, pci=pci,
                           rssi_dbm=rssi, serving=serving, latitude=lat, longitude=lon,
                           position_kind=kind if lat is not None else PositionKind.NONE,
                           broadcast=dict(bc), provenance=P)


def baseline_of(*cells, n=10):
    return Baseline.from_observations([ob(t=i * 30, **c) for c in cells for i in range(n)])


def run(obs, base):
    return DetectionEngine().run(obs, base)


# ----------------------------------------------------------------------------
# Règles individuelles
# ----------------------------------------------------------------------------

class TestRules:
    def test_unknown_cell(self):
        base = baseline_of(dict(cid=1))
        inds = R.UnknownCellRule().evaluate([ob(cid=2, rssi=-60)], base)
        assert len(inds) == 1 and inds[0].weight == 0.45  # signal fort
        inds = R.UnknownCellRule().evaluate([ob(cid=2, rssi=-100)], base)
        assert inds[0].weight == 0.3
        assert R.UnknownCellRule().evaluate([ob(cid=1)], base) == []

    def test_unknown_cell_needs_baseline(self):
        assert R.UnknownCellRule().evaluate([ob(cid=2)], Baseline()) == []

    def test_parameter_change(self):
        base = baseline_of(dict(cid=1, area=100))
        inds = R.ParameterChangeRule().evaluate([ob(cid=1, area=101)], base)
        assert inds and "LAC/TAC 101" in inds[0].technical_details
        inds = R.ParameterChangeRule().evaluate([ob(cid=1, ch=1650, pci=11)], base)
        assert inds and inds[0].weight == pytest.approx(0.35)

    def test_reidentified_cell_not_double_counted(self):
        base = baseline_of(dict(cid=1, area=100))
        moved = [ob(cid=1, area=101)]
        assert R.UnknownCellRule().evaluate(moved, base) == []
        assert R.RadioIdentityRule().evaluate(moved, base) == []
        assert R.IsolatedAreaCodeRule().evaluate(moved, base)[0].weight == 0.15

    def test_isolated_area(self):
        base = baseline_of(dict(cid=1, area=100), dict(cid=2, area=100))
        assert R.IsolatedAreaCodeRule().evaluate([ob(cid=9, area=555)], base)[0].weight == 0.3
        assert R.IsolatedAreaCodeRule().evaluate([ob(cid=9, area=100)], base) == []

    def test_power_jumps_repeated(self):
        series = [ob(t=i * 30, rssi=-80 if i % 2 else -60) for i in range(8)]
        inds = R.PowerAnomalyRule().evaluate(series, Baseline())
        assert inds and "sauts" in inds[0].technical_details

    def test_power_jumps_need_repetition_and_short_gap(self):
        two = [ob(t=0, rssi=-80), ob(t=30, rssi=-60), ob(t=60, rssi=-80), ob(t=90, rssi=-81)]
        assert R.PowerAnomalyRule().evaluate(two, Baseline()) == []  # 2 sauts < 3
        sparse = [ob(t=i * 3600, rssi=-80 if i % 2 else -60) for i in range(8)]
        assert R.PowerAnomalyRule().evaluate(sparse, Baseline()) == []  # trous > 120 s

    def test_power_excess_vs_baseline(self):
        base = baseline_of(dict(cid=1, rssi=-95))
        inds = R.PowerAnomalyRule().evaluate([ob(t=i, rssi=-60) for i in range(5)], base)
        assert inds and "+35.0 dB" in inds[0].technical_details

    def test_downgrade(self):
        base = baseline_of(dict(cid=1), dict(cid=5, tech=Technology.GSM, area=7))
        seq = [ob(t=0, cid=1), ob(t=30, cid=99, tech=Technology.GSM, area=7)]
        inds = R.TechnologyDowngradeRule().evaluate(seq, base)
        assert inds and inds[0].weight == 0.35  # cellule 2G inconnue
        seq = [ob(t=0, cid=1), ob(t=30, cid=5, tech=Technology.GSM, area=7)]
        assert R.TechnologyDowngradeRule().evaluate(seq, base)[0].weight == 0.15
        # 4G → 3G n'est pas une transition vers la 2G
        seq = [ob(t=0, cid=1), ob(t=30, cid=6, tech=Technology.UMTS)]
        assert R.TechnologyDowngradeRule().evaluate(seq, base) == []

    def test_temporal_short_lived_and_quality(self):
        base = baseline_of(dict(cid=1))
        obs = [ob(t=i * 60, cid=1) for i in range(90)] + [ob(t=1000, cid=50, rssi=-55),
                                                          ob(t=1100, cid=50, rssi=-55)]
        inds = R.TemporalAnomalyRule().evaluate(obs, base)
        assert any(i.cell_key and i.cell_key[4] == 50 for i in inds)
        obs.append(ob(t=0, cid=1))  # doublon
        q = [i for i in R.TemporalAnomalyRule().evaluate(obs, base) if i.cell_key is None]
        assert q and "doublon" in q[0].technical_details

    def test_spatial(self):
        far = [ob(t=0, lat=48.85, lon=2.35, kind=PositionKind.GPS),
               ob(t=60, lat=45.75, lon=4.85, kind=PositionKind.GPS)]  # Paris → Lyon
        inds = R.SpatialAnomalyRule().evaluate(far, Baseline())
        assert inds and inds[0].weight == 0.3
        far[1].position_kind = PositionKind.ESTIMATED
        assert R.SpatialAnomalyRule().evaluate(far, Baseline())[0].weight == 0.15
        near = [ob(t=0, lat=48.85, lon=2.35, kind=PositionKind.GPS),
                ob(t=60, lat=48.86, lon=2.36, kind=PositionKind.GPS)]
        assert R.SpatialAnomalyRule().evaluate(near, Baseline()) == []

    def test_broadcast(self):
        base = baseline_of(dict(cid=1, t3212=30))
        inds = R.BroadcastChangeRule().evaluate([ob(cid=1, t3212=1)], base)
        assert inds and "t3212=1" in inds[0].technical_details
        inds = R.BroadcastChangeRule().evaluate([ob(cid=3, neighbor_count=0)], base)
        assert inds and "voisines vide" in inds[0].technical_details

    def test_radio_identity(self):
        base = baseline_of(dict(cid=1, ch=62, pci=5, tech=Technology.GSM))
        clone = [ob(cid=77, area=900, ch=62, pci=5, tech=Technology.GSM)]
        assert R.RadioIdentityRule().evaluate(clone, base)
        other_op = [ob(cid=77, area=900, ch=62, pci=5, tech=Technology.GSM, mnc=20)]
        assert R.RadioIdentityRule().evaluate(other_op, base) == []


# ----------------------------------------------------------------------------
# Moteur : agrégation, prudence, données insuffisantes
# ----------------------------------------------------------------------------

class TestEngine:
    def test_single_indicator_is_capped(self):
        base = baseline_of(dict(cid=1), n=40)
        obs = [ob(t=i * 30, cid=1) for i in range(20)] + [ob(t=600, cid=2, pci=20, rssi=-100)]
        res = run(obs, base)
        alert = next(a for a in res.alerts if a.cell_key[4] == 2)
        assert alert.distinct_rule_count == 1
        assert alert.confidence_score <= SINGLE_INDICATOR_CAP
        assert alert.confidence in (ConfidenceLevel.VERY_LOW, ConfidenceLevel.LOW)
        assert res.assessment == Assessment.ISOLATED_INDICATORS
        assert any("isolé" in c for c in alert.recommended_checks)

    def test_no_confirmed_level_exists(self):
        names = " ".join(c.name + c.value for c in ConfidenceLevel).lower()
        assert "confirm" not in names.replace("à confirmer", "")

    def test_insufficient_without_baseline(self):
        obs = [ob(t=i * 30, cid=1) for i in range(20)]
        res = run(obs, Baseline())
        assert res.assessment == Assessment.INSUFFICIENT_DATA
        assert any("référence" in q for q in res.data_quality)

    def test_insufficient_with_few_observations(self):
        res = run([ob(t=0, cid=2, pci=20, rssi=-50)], baseline_of(dict(cid=1), n=40))
        assert res.assessment == Assessment.INSUFFICIENT_DATA
        assert all(a.confidence_score <= SINGLE_INDICATOR_CAP * 0.5 + 1e-9 for a in res.alerts)

    def test_short_baseline_reduces_confidence(self):
        obs = [ob(t=i * 30, cid=1) for i in range(20)] + [ob(t=600, cid=2, pci=20, rssi=-55)]
        short = run(obs, baseline_of(dict(cid=1), n=5))
        long = run(obs, baseline_of(dict(cid=1), n=40))
        s = next(a for a in short.alerts if a.cell_key[4] == 2).confidence_score
        lg = next(a for a in long.alerts if a.cell_key[4] == 2).confidence_score
        assert s == pytest.approx(lg * 0.5)

    def test_empty_input(self):
        res = run([], Baseline())
        assert res.alerts == [] and res.assessment == Assessment.INSUFFICIENT_DATA

    def test_alert_fields_complete(self, sim_results):
        r = sim_results[Scenario.SYNTHETIC_ANOMALY]
        res = run(r.observations, Baseline.from_observations(r.baseline))
        a = res.alerts[0]
        assert a.alert_id.startswith("ALR-") and a.first_seen <= a.last_seen
        assert a.observation_ids and a.rules and 0 <= a.priority <= 100
        assert a.explanation and a.false_positives and a.recommended_checks
        assert a.sources == ["SIMULATION"] and a.is_simulation

    def test_alert_ids_are_reproducible(self, sim_results):
        r = sim_results[Scenario.SYNTHETIC_ANOMALY]
        b = Baseline.from_observations(r.baseline)
        ids1 = [a.alert_id for a in run(r.observations, b).alerts]
        ids2 = [a.alert_id for a in run(r.observations, b).alerts]
        assert ids1 == ids2

    def test_spectrum_indicators(self):
        var = detect_power_variations(SpectrumScenario.with_anomaly().series(60))
        inds = spectrum_indicators(var, is_simulation=True)
        assert inds and all(i.rule_id == "R10_SPECTRUM_POWER" for i in inds)
        res = DetectionEngine().run([], Baseline(), inds)
        assert all(a.confidence_score <= SINGLE_INDICATOR_CAP for a in res.alerts)


# ----------------------------------------------------------------------------
# Scénarios de simulation : faux positifs et vrais positifs synthétiques
# ----------------------------------------------------------------------------

class TestScenarios:
    def _res(self, sim_results, sc):
        r = sim_results[sc]
        return r, run(r.observations, Baseline.from_observations(r.baseline))

    @pytest.mark.parametrize("sc", [Scenario.NORMAL, Scenario.COVERAGE_CHANGE])
    def test_legitimate_scenarios_raise_no_significant_alert(self, sim_results, sc):
        _, res = self._res(sim_results, sc)
        assert res.assessment == Assessment.NO_INDICATOR
        assert all(a.severity == Severity.INFO for a in res.alerts)

    def test_parameter_change_stays_isolated(self, sim_results):
        """Une réorganisation LAC/TAC légitime ne doit pas être présentée comme convergente."""
        r, res = self._res(sim_results, Scenario.PARAMETER_CHANGE)
        assert res.assessment == Assessment.ISOLATED_INDICATORS
        top = res.alerts[0]
        assert top.cell_key == r.truth.anomalous_cell_keys[0]
        assert top.severity in (Severity.LOW, Severity.MEDIUM)

    def test_power_variation_detected_but_isolated(self, sim_results):
        r, res = self._res(sim_results, Scenario.POWER_VARIATION)
        assert res.alerts[0].rules == ["R04_POWER_ANOMALY"]
        assert res.alerts[0].cell_key == r.truth.anomalous_cell_keys[0]
        assert res.assessment == Assessment.ISOLATED_INDICATORS

    def test_inconsistent_data_flagged_as_quality_issue(self, sim_results):
        _, res = self._res(sim_results, Scenario.INCONSISTENT)
        rules = {r for a in res.alerts for r in a.rules}
        assert {"R06_TEMPORAL", "R07_SPATIAL"} <= rules
        assert all(a.severity in (Severity.INFO, Severity.LOW) for a in res.alerts)

    def test_synthetic_anomaly_convergent(self, sim_results):
        r, res = self._res(sim_results, Scenario.SYNTHETIC_ANOMALY)
        assert res.assessment == Assessment.CONVERGENT_INDICATORS
        top = res.alerts[0]
        assert top.cell_key == r.truth.anomalous_cell_keys[0]
        assert top.distinct_rule_count >= 4
        assert {"R01_UNKNOWN_CELL", "R05_TECH_DOWNGRADE", "R08_BROADCAST"} <= set(top.rules)
        assert "PAS une identification" in res.assessment_text

    def test_seed_reproducibility(self):
        a = simulate(SimulationParams(seed=5, duration_minutes=20, baseline_hours=0.5))
        b = simulate(SimulationParams(seed=5, duration_minutes=20, baseline_hours=0.5))
        c = simulate(SimulationParams(seed=6, duration_minutes=20, baseline_hours=0.5))
        key = lambda r: [(o.cell_key, o.rssi_dbm, o.timestamp) for o in r.observations]  # noqa
        assert key(a) == key(b) and key(a) != key(c)

    def test_all_simulated_data_is_labelled(self, sim_results):
        for r in sim_results.values():
            for o in r.baseline + r.observations:
                assert o.provenance.is_simulation and o.provenance.source == "SIMULATION"
