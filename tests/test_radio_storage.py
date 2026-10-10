"""Analyse spectrale, récepteurs (sans émission) et persistance."""

import inspect
from datetime import datetime, timezone

import numpy as np
import pytest

from lunatic_imsi_lab.config import DEFAULT_BANDS
from lunatic_imsi_lab.core.models import Provenance, SpectrumSweep
from lunatic_imsi_lab.radio import receivers
from lunatic_imsi_lab.radio.receivers import (Receiver, SimulatedReceiver, SoapyReceiver,
                                              iq_to_psd_dbfs, make_receiver)
from lunatic_imsi_lab.radio.spectrum import (band_power_series, compare_sweeps, detect_emissions,
                                             detect_power_variations, robust_zscores, waterfall)
from lunatic_imsi_lab.simulation.spectrum import SimEmitter, SpectrumScenario
from lunatic_imsi_lab.storage.db import Database

T0 = datetime(2026, 1, 15, tzinfo=timezone.utc)


class TestSpectrum:
    def test_detects_all_default_carriers(self):
        sweep = SpectrumScenario.default().sweep(0)
        ems = detect_emissions(sweep, bands=DEFAULT_BANDS)
        centers = sorted(round(e.center_mhz, 1) for e in ems)
        assert centers == [1815.0, 1840.0, 1862.5, 1870.2, 1872.4]
        wide = next(e for e in ems if round(e.center_mhz) == 1840)
        assert 19e6 <= wide.bandwidth_hz <= 23e6
        gsm = next(e for e in ems if round(e.center_mhz, 1) == 1870.2)
        assert 150e3 <= gsm.bandwidth_hz <= 300e3
        assert all(e.band == "DCS/LTE 1800 DL (B3)" for e in ems)
        assert all(e.snr_db > 25 for e in ems)

    def test_noise_only_has_no_emission(self):
        sweep = SpectrumScenario([], seed=1).sweep(0)
        assert detect_emissions(sweep) == []

    def test_compare_detects_new_and_lost(self):
        sc = SpectrumScenario.with_anomaly()
        cmp = compare_sweeps(sc.sweep(0), sc.sweep(25))
        assert [round(e.center_mhz, 1) for e in cmp.new_emissions] == [1876.8]
        cmp2 = compare_sweeps(sc.sweep(25), sc.sweep(45))
        assert [round(e.center_mhz, 1) for e in cmp2.lost_emissions] == [1876.8]
        assert cmp.max_increase_db > 30

    def test_compare_regrids_and_rejects_disjoint(self):
        sc = SpectrumScenario.default()
        a = sc.sweep(0)
        b = sc.sweep(1, bin_hz=50e3)
        assert compare_sweeps(a, b).mean_abs_delta_db < 3
        c = sc.sweep(0, start_hz=900e6, stop_hz=910e6)
        with pytest.raises(ValueError):
            compare_sweeps(a, c)

    def test_power_variations(self):
        sweeps = SpectrumScenario.with_anomaly().series(60)
        var = detect_power_variations(sweeps)
        freqs = {round(v.center_hz / 1e6, 1) for v in var}
        assert 1870.2 in freqs  # sauts répétés de la porteuse GSM
        assert not detect_power_variations(SpectrumScenario.default().series(60))

    def test_power_variations_need_enough_sweeps(self):
        assert detect_power_variations(SpectrumScenario.with_anomaly().series(4)) == []

    def test_waterfall_and_series(self):
        sweeps = SpectrumScenario.default().series(5)
        f, m, t = waterfall(sweeps)
        assert m.shape == (5, f.size) and len(t) == 5
        s = band_power_series(sweeps, 1810e6, 1820e6)
        assert np.all(np.abs(s - s[0]) < 2)

    def test_robust_z(self):
        assert np.all(robust_zscores(np.ones(10)) == 0)
        z = robust_zscores(np.r_[np.random.default_rng(0).normal(0, 1, 50), 30])
        assert z[-1] > 10

    def test_sweep_validation(self):
        with pytest.raises(ValueError):
            SpectrumSweep(T0, [1, 2, 3], [1, 2], Provenance("x", "y"))
        with pytest.raises(ValueError):
            SpectrumSweep(T0, [1], [1], Provenance("x", "y"))

    def test_emitter_schedule(self):
        e = SimEmitter(1e9, 1e6, -60, start_step=2, stop_step=4, jump_db=10, jump_every=2)
        assert [e.active(i) for i in range(5)] == [False, False, True, True, False]
        assert e.level(2) == -50 and e.level(3) == -60


class TestReceivers:
    def test_receive_only_interface(self):
        """Aucune méthode d'émission n'existe dans la couche radio."""
        forbidden = ("transmit", "tx", "send", "emit", "jam", "write_stream", "writestream")
        for cls in (Receiver, SimulatedReceiver, SoapyReceiver):
            names = [n.lower() for n, _ in inspect.getmembers(cls, inspect.isfunction)]
            assert not any(n.startswith(f) or n == f for n in names for f in forbidden), names
        src = inspect.getsource(receivers)
        assert "SOAPY_SDR_TX" not in src and "writeStream" not in src

    def test_simulated_receiver(self):
        r = make_receiver("simulated", seed=3)
        info = r.info()
        assert info.available and info.is_simulation
        s1, s2 = r.sweep(1805e6, 1880e6), r.sweep(1805e6, 1880e6)
        assert s1.provenance.is_simulation and s2.timestamp > s1.timestamp

    def test_soapy_unavailable_is_reported(self):
        r = make_receiver("soapy", args="driver=rtlsdr")
        info = r.info()
        if not SoapyReceiver.module_available():
            assert not info.available and "non installé" in info.details

    def test_unknown_driver(self):
        with pytest.raises(ValueError):
            make_receiver("txonly")

    def test_iq_psd_finds_tone(self):
        fs = 1e6
        t = np.arange(8192) / fs
        iq = np.exp(2j * np.pi * 100e3 * t).astype(np.complex64)
        iq += (np.random.default_rng(0).normal(0, 0.01, t.size) * (1 + 1j)).astype(np.complex64)
        f, p = iq_to_psd_dbfs(iq, fs, 1024)
        assert abs(f[np.argmax(p)] - 100e3) < fs / 1024 * 1.5
        assert np.all(np.diff(f) > 0)


class TestDatabase:
    def test_roundtrip(self, tmp_path, sim_results):
        from lunatic_imsi_lab.simulation.cells import Scenario
        res = sim_results[Scenario.SYNTHETIC_ANOMALY]
        db = Database(tmp_path / "x.sqlite")
        n = db.add_observations(res.observations[:200], "ds")
        assert n == 200 and db.count_observations("ds") == 200
        back = db.get_observations("ds")
        o = res.observations[0]
        b = next(x for x in back if x.id == o.id)
        assert b.timestamp == o.timestamp and b.timestamp.tzinfo is not None
        assert b.cell_key == o.cell_key and b.broadcast == o.broadcast
        assert b.provenance.is_simulation
        assert db.get_observations("ds", include_simulation=False) == []
        assert db.list_datasets()[0].is_simulation

    def test_sweeps_roundtrip(self):
        db = Database()
        s = SpectrumScenario.default().sweep(0)
        db.add_sweep(s, "sp")
        back = db.get_sweeps("sp")[0]
        assert np.array_equal(back.power_dbm, s.power_dbm)
        assert back.provenance.parameters["seed"] == 7

    def test_naive_datetime_refused(self):
        from datetime import datetime as dt
        from lunatic_imsi_lab.core.models import CellObservation, Technology
        db = Database()
        o = CellObservation(dt(2026, 1, 1), Technology.GSM, 1, 1, 1, 1, 1, Provenance("a", "b"))
        with pytest.raises(Exception):
            db.add_observations([o])
