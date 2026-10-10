"""Calculs de puissance, conversions de canaux et horodatages."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from lunatic_imsi_lab.core.models import Technology
from lunatic_imsi_lab.core.timeutils import TimestampError, check_plausible, to_utc
from lunatic_imsi_lab.core import units as u


class TestPower:
    def test_dbm_mw_roundtrip(self):
        assert u.dbm_to_mw(0) == pytest.approx(1.0)
        assert u.dbm_to_mw(30) == pytest.approx(1000.0)
        assert u.mw_to_dbm(1e-3) == pytest.approx(-30.0)
        arr = np.array([-90.0, -60.0, 10.0])
        assert np.allclose(u.mw_to_dbm(u.dbm_to_mw(arr)), arr)

    def test_watts(self):
        assert u.watts_to_dbm(1.0) == pytest.approx(30.0)

    def test_mw_to_dbm_rejects_non_positive(self):
        with pytest.raises(ValueError):
            u.mw_to_dbm(0.0)

    def test_mean_is_linear_not_db(self):
        # moyenne de -60 et -70 dBm en linéaire ≈ -62.6 dBm (et non -65)
        assert u.mean_power_dbm([-60, -70]) == pytest.approx(-62.596, abs=1e-3)
        assert u.mean_power_dbm([-80, None, -80]) == pytest.approx(-80.0)
        with pytest.raises(ValueError):
            u.mean_power_dbm([])

    def test_channel_power_sums_bins(self):
        # 10 bins à -100 dBm → -90 dBm
        assert u.channel_power_dbm(np.full(10, -100.0)) == pytest.approx(-90.0)
        mask = np.array([True] * 5 + [False] * 5)
        assert u.channel_power_dbm(np.full(10, -100.0), mask) == pytest.approx(-93.0103, 1e-3)
        with pytest.raises(ValueError):
            u.channel_power_dbm(np.full(3, -100.0), np.zeros(3, bool))

    def test_noise_floor_and_snr(self):
        p = np.r_[np.full(90, -100.0), np.full(10, -40.0)]
        assert u.noise_floor_dbm(p) == pytest.approx(-100.0)
        assert u.snr_db(-40, -100) == 60

    def test_thermal_noise(self):
        # kTB à 290 K sur 1 Hz ≈ -174 dBm ; 200 kHz ≈ -121 dBm
        assert u.thermal_noise_dbm(1.0) == pytest.approx(-173.98, abs=0.05)
        assert u.thermal_noise_dbm(200e3) == pytest.approx(-120.97, abs=0.05)
        with pytest.raises(ValueError):
            u.thermal_noise_dbm(0)


class TestChannels:
    @pytest.mark.parametrize("earfcn,mhz", [(1300, 1815.0), (6300, 806.0), (3000, 2645.0),
                                            (100, 2120.0)])
    def test_earfcn(self, earfcn, mhz):
        assert u.earfcn_to_mhz(earfcn) == pytest.approx(mhz)

    def test_earfcn_unknown(self):
        with pytest.raises(ValueError):
            u.earfcn_to_mhz(70000)

    @pytest.mark.parametrize("arfcn,mhz", [(1, 935.2), (62, 947.4), (975, 925.2),
                                           (512, 1805.2), (885, 1879.8), (128, 869.2)])
    def test_gsm(self, arfcn, mhz):
        assert u.gsm_arfcn_to_mhz(arfcn) == pytest.approx(mhz)

    def test_gsm_pcs(self):
        assert u.gsm_arfcn_to_mhz(512, pcs1900=True) == pytest.approx(1930.2)

    def test_uarfcn_and_nr(self):
        assert u.uarfcn_to_mhz(10612) == pytest.approx(2122.4)
        assert u.nrarfcn_to_mhz(636666) == pytest.approx(3549.99, abs=0.01)
        assert u.nrarfcn_to_mhz(2016667) == pytest.approx(24250.08)

    def test_generic(self):
        assert u.channel_to_mhz(Technology.LTE, 1300) == 1815.0
        assert u.channel_to_mhz(Technology.LTE, None) is None
        assert u.channel_to_mhz(Technology.LTE, 999999) is None


class TestTimestamps:
    def test_iso_with_z(self):
        dt = to_utc("2026-01-15T10:00:00Z")
        assert dt == datetime(2026, 1, 15, 10, tzinfo=timezone.utc)

    def test_offset_is_converted(self):
        assert to_utc("2026-01-15T12:00:00+02:00").hour == 10

    def test_naive_uses_declared_tz(self):
        # 15 janvier : Paris = UTC+1
        assert to_utc("2026-01-15 11:00:00", "Europe/Paris").hour == 10
        assert to_utc("2026-01-15 11:00:00").hour == 11  # UTC par défaut

    def test_epoch_seconds_and_ms(self):
        a = to_utc(1768471200)
        b = to_utc(1768471200000)
        c = to_utc("1768471200")
        assert a == b == c
        assert a.tzinfo == timezone.utc

    @pytest.mark.parametrize("bad", ["", "not a date", None, [1]])
    def test_invalid(self, bad):
        with pytest.raises(TimestampError):
            to_utc(bad)

    def test_plausibility(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert check_plausible(now, now) == []
        assert check_plausible(now + timedelta(hours=1), now)
        assert check_plausible(datetime(1999, 1, 1, tzinfo=timezone.utc), now)
