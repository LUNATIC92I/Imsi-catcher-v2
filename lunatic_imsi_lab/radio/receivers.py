"""Récepteurs radio — **réception uniquement**.

Cette couche ne définit volontairement aucune méthode d'émission : l'interface
``Receiver`` n'expose que la lecture de densité de puissance. Le pilote
SoapySDR ouvre exclusivement des flux ``SOAPY_SDR_RX``.

Par défaut, les échantillons IQ bruts ne sont pas conservés : seul le spectre
de puissance moyenné est calculé puis renvoyé.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass

import numpy as np
from scipy import signal

from lunatic_imsi_lab.core.models import Provenance, SpectrumSweep
from lunatic_imsi_lab.core.timeutils import utcnow


@dataclass
class ReceiverInfo:
    name: str
    driver: str
    available: bool
    details: str = ""
    is_simulation: bool = False


class Receiver(abc.ABC):
    """Interface de récepteur passif."""

    name: str = "receiver"

    @abc.abstractmethod
    def info(self) -> ReceiverInfo: ...

    @abc.abstractmethod
    def sweep(self, start_hz: float, stop_hz: float, bin_hz: float = 25e3) -> SpectrumSweep: ...

    def close(self) -> None:  # pragma: no cover - rien à libérer par défaut
        pass


def iq_to_psd_dbfs(iq: np.ndarray, sample_rate: float, nfft: int = 1024) -> tuple[np.ndarray,
                                                                                  np.ndarray]:
    """Densité de puissance (dBFS/bin) d'un bloc IQ, centrée sur 0 Hz (Welch)."""
    freqs, pxx = signal.welch(iq, fs=sample_rate, nperseg=min(nfft, len(iq)),
                              return_onesided=False, scaling="spectrum", detrend=False)
    order = np.argsort(freqs)
    pxx = np.maximum(pxx[order], 1e-20)
    return freqs[order], 10.0 * np.log10(pxx)


class SimulatedReceiver(Receiver):
    """Récepteur virtuel : génère des spectres synthétiques, n'émet rien."""

    def __init__(self, scenario=None, seed: int = 7) -> None:
        from lunatic_imsi_lab.simulation.spectrum import SpectrumScenario
        self.scenario = scenario or SpectrumScenario.default(seed=seed)
        self.name = "Récepteur simulé"
        self._t = 0

    def info(self) -> ReceiverInfo:
        return ReceiverInfo(self.name, "simulated", True, "Données synthétiques — SIMULATION",
                            is_simulation=True)

    def sweep(self, start_hz: float, stop_hz: float, bin_hz: float = 25e3) -> SpectrumSweep:
        s = self.scenario.sweep(self._t, start_hz, stop_hz, bin_hz)
        self._t += 1
        return s


class SoapyReceiver(Receiver):
    """Récepteur SoapySDR (RTL-SDR, HackRF en RX, Airspy, USRP en RX...).

    Les valeurs sont exprimées en dBFS + ``calibration_offset_db`` : elles ne
    deviennent des dBm que si l'offset a été déterminé avec un générateur
    étalonné (voir docs/equipment_guide.md)."""

    def __init__(self, args: str = "", sample_rate: float = 2.4e6, gain_db: float = 30.0,
                 calibration_offset_db: float = 0.0, nfft: int = 1024,
                 averages: int = 16) -> None:
        self.args = args
        self.sample_rate = sample_rate
        self.gain_db = gain_db
        self.calibration_offset_db = calibration_offset_db
        self.nfft = nfft
        self.averages = averages
        self.name = f"SoapySDR({args or 'auto'})"
        self._dev = None
        self._soapy = None

    @staticmethod
    def module_available() -> bool:
        try:
            import SoapySDR  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def enumerate_devices() -> list[dict]:
        try:
            import SoapySDR
            return [dict(d) for d in SoapySDR.Device.enumerate()]
        except Exception:
            return []

    def info(self) -> ReceiverInfo:
        if not self.module_available():
            return ReceiverInfo(self.name, "soapy", False,
                                "Module SoapySDR (bindings Python) non installé")
        devices = self.enumerate_devices()
        return ReceiverInfo(self.name, "soapy", bool(devices),
                            f"{len(devices)} périphérique(s) détecté(s)")

    def _open(self):
        if self._dev is None:
            import SoapySDR
            self._soapy = SoapySDR
            self._dev = SoapySDR.Device(self.args)
            self._dev.setSampleRate(SoapySDR.SOAPY_SDR_RX, 0, self.sample_rate)
            self._dev.setGain(SoapySDR.SOAPY_SDR_RX, 0, self.gain_db)
        return self._dev

    def _capture_psd(self, center_hz: float) -> tuple[np.ndarray, np.ndarray]:
        S = self._soapy
        dev = self._open()
        dev.setFrequency(S.SOAPY_SDR_RX, 0, center_hz)
        stream = dev.setupStream(S.SOAPY_SDR_RX, S.SOAPY_SDR_CF32)
        dev.activateStream(stream)
        try:
            n = self.nfft * self.averages
            buf = np.zeros(n, dtype=np.complex64)
            got = 0
            while got < n:
                sr = dev.readStream(stream, [buf[got:]], n - got, timeoutUs=1_000_000)
                if sr.ret <= 0:
                    raise IOError(f"lecture SoapySDR en échec (code {sr.ret})")
                got += sr.ret
        finally:
            dev.deactivateStream(stream)
            dev.closeStream(stream)
        f, p = iq_to_psd_dbfs(buf, self.sample_rate, self.nfft)
        del buf  # aucun IQ conservé
        return f + center_hz, p + self.calibration_offset_db

    def sweep(self, start_hz: float, stop_hz: float, bin_hz: float = 25e3) -> SpectrumSweep:
        usable = self.sample_rate * 0.8           # on écarte les bords du filtre anti-repliement
        centers = np.arange(start_hz + usable / 2, stop_hz + usable / 2, usable)
        fs, ps = [], []
        for c in centers:
            f, p = self._capture_psd(float(c))
            keep = np.abs(f - c) <= usable / 2
            fs.append(f[keep])
            ps.append(p[keep])
        f_all, p_all = np.concatenate(fs), np.concatenate(ps)
        grid = np.arange(start_hz, stop_hz, bin_hz)
        p_grid = np.interp(grid, f_all, p_all)
        prov = Provenance(source=self.name, method="sdr-psd-welch", is_simulation=False,
                          parameters={"sample_rate": self.sample_rate, "gain_db": self.gain_db,
                                      "nfft": self.nfft, "averages": self.averages,
                                      "calibration_offset_db": self.calibration_offset_db,
                                      "unit": "dBm" if self.calibration_offset_db else "dBFS",
                                      "raw_iq_stored": False})
        return SpectrumSweep(timestamp=utcnow(), frequencies_hz=grid, power_dbm=p_grid,
                             provenance=prov, rbw_hz=self.sample_rate / self.nfft)

    def close(self) -> None:
        self._dev = None


def make_receiver(driver: str, **kwargs) -> Receiver:
    if driver == "simulated":
        return SimulatedReceiver(**{k: v for k, v in kwargs.items() if k in ("scenario", "seed")})
    if driver == "soapy":
        return SoapyReceiver(**{k: v for k, v in kwargs.items()
                                if k in ("args", "sample_rate", "gain_db",
                                         "calibration_offset_db", "nfft", "averages")})
    raise ValueError(f"pilote inconnu : {driver}")
