from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton,
                               QSplitter, QTabWidget)

from lunatic_imsi_lab.gui import theme
from lunatic_imsi_lab.gui.pages.base import Page
from lunatic_imsi_lab.gui.widgets import PlotWidget, RecordTable
from lunatic_imsi_lab.radio.receivers import make_receiver
from lunatic_imsi_lab.radio.spectrum import (compare_sweeps, detect_emissions,
                                             detect_power_variations, waterfall)
from lunatic_imsi_lab.reports.charts import plot_spectrum, plot_waterfall
from lunatic_imsi_lab.security.rbac import Permission


def _spin(lo, hi, val, step=1.0, dec=3, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(val)
    s.setSuffix(suffix)
    return s


class SpectrumPage(Page):
    nav_label = "Analyseur de spectre"
    title = "Analyseur de spectre"
    subtitle = ("Mesure passive de densité de puissance. Aucun décodage de contenu, aucune "
                "donnée d'abonné. Les IQ bruts ne sont pas conservés par défaut.")

    def build(self) -> None:
        self.index = -1
        bar = QHBoxLayout()
        self.device = QComboBox()
        bar.addWidget(QLabel("Récepteur"))
        bar.addWidget(self.device)
        self.start = _spin(1, 7000, 1805.0, 1, 3, " MHz")
        self.stop = _spin(1, 7000, 1880.0, 1, 3, " MHz")
        self.bin = _spin(1, 1000, 25.0, 5, 1, " kHz")
        self.threshold = _spin(3, 40, 10.0, 1, 1, " dB")
        for lab, w in (("Début", self.start), ("Fin", self.stop), ("Bin", self.bin),
                       ("Seuil", self.threshold)):
            bar.addWidget(QLabel(lab))
            bar.addWidget(w)
        self.btn_acq = QPushButton("Acquérir un balayage")
        self.btn_acq.setObjectName("Primary")
        self.btn_acq.clicked.connect(self.acquire)
        self.btn_live = QPushButton("Acquisition continue")
        self.btn_live.setCheckable(True)
        self.btn_live.toggled.connect(self.toggle_live)
        bar.addWidget(self.btn_acq)
        bar.addWidget(self.btn_live)
        bar.addStretch(1)
        self.layout_.addLayout(bar)

        nav = QHBoxLayout()
        self.prev = QPushButton("◀")
        self.next = QPushButton("▶")
        self.prev.clicked.connect(lambda: self.show_index(self.index - 1))
        self.next.clicked.connect(lambda: self.show_index(self.index + 1))
        self.pos = QLabel("—")
        self.cmp = QLabel("")
        self.cmp.setObjectName("Notice")
        self.cmp.setWordWrap(True)
        nav.addWidget(self.prev)
        nav.addWidget(self.pos)
        nav.addWidget(self.next)
        nav.addWidget(self.cmp, 1)
        btn_var = QPushButton("Analyser les variations temporelles")
        btn_var.clicked.connect(self.variations)
        nav.addWidget(btn_var)
        self.layout_.addLayout(nav)

        split = QSplitter(Qt.Vertical)
        tabs = QTabWidget()
        self.plot = PlotWidget(height=3.2)
        self.wf = PlotWidget(height=3.2)
        tabs.addTab(self.plot, "Spectre")
        tabs.addTab(self.wf, "Cascade / variations")
        split.addWidget(tabs)
        self.emissions = RecordTable([
            ("Fréq. centrale (MHz)", lambda e: round(e.center_mhz, 4)),
            ("Largeur (kHz)", lambda e: round(e.bandwidth_hz / 1e3, 1)),
            ("Crête (dB/bin)", lambda e: round(e.peak_dbm, 1)),
            ("Puissance canal", lambda e: round(e.channel_power_dbm, 1)),
            ("SNR (dB)", lambda e: round(e.snr_db, 1)),
            ("Bande configurée", lambda e: e.band or "hors bandes configurées")])
        self.emissions.model.color_fn = lambda e: None if e.band else theme.AMBER
        split.addWidget(self.emissions)
        split.setSizes([520, 220])
        self.layout_.addWidget(split, 1)
        self.timer = QTimer(self, interval=1500, timeout=self.acquire)
        self._receivers: dict[str, object] = {}

    def refresh(self) -> None:
        super().refresh()
        cur = self.device.currentText()
        self.device.blockSignals(True)
        self.device.clear()
        for d in self.lab.config.devices:
            if d.enabled:
                self.device.addItem(f"{d.name} ({d.driver})", d)
        i = self.device.findText(cur)
        self.device.setCurrentIndex(max(i, 0))
        self.device.blockSignals(False)
        self.show_index(len(self.lab.ws.sweeps) - 1)

    def _receiver(self):
        d = self.device.currentData()
        if d is None:
            raise RuntimeError("aucun récepteur configuré")
        key = f"{d.driver}|{d.args}|{d.sample_rate}|{d.gain_db}|{d.calibration_offset_db}"
        if key not in self._receivers:
            self._receivers[key] = make_receiver(
                d.driver, args=d.args, sample_rate=d.sample_rate, gain_db=d.gain_db,
                calibration_offset_db=d.calibration_offset_db)
        return self._receivers[key]

    def acquire(self) -> None:
        if self.win._busy:          # acquisition continue : un balayage est encore en cours
            return
        if not self.lab.user.can(Permission.CAPTURE):
            self.btn_live.setChecked(False)
            self.win.guarded(self.lab.user.require, Permission.CAPTURE)  # affiche le refus
            return
        try:
            rx = self._receiver()
        except Exception as exc:
            self.win.notify(str(exc), "error")
            return
        info = rx.info()
        if not info.available:
            self.win.notify(f"{info.name} indisponible : {info.details}", "error")
            self.btn_live.setChecked(False)
            return
        start, stop = self.start.value() * 1e6, self.stop.value() * 1e6
        if stop <= start:
            self.win.notify("La fréquence de fin doit être supérieure au début.", "warn")
            return
        bin_hz = self.bin.value() * 1e3
        lab = self.lab

        def job():
            # Exécuté hors du thread graphique : lecture SDR et écriture en base.
            sweep = rx.sweep(start, stop, bin_hz)
            lab.db.add_sweep(sweep, lab.ws.dataset or (
                "SIMULATION-spectre" if sweep.provenance.is_simulation else "spectre"))
            lab.audit.record(lab.user, "capture_sweep", {
                "source": sweep.provenance.source, "start_hz": start, "stop_hz": stop})
            return sweep

        def done(sweep):
            lab.ws.sweeps.append(sweep)
            self.show_index(len(lab.ws.sweeps) - 1)

        self.win.run_task(job, done, "Acquisition…", on_error=lambda: self.btn_live.setChecked(
            False))

    def toggle_live(self, on: bool) -> None:
        self.timer.start() if on else self.timer.stop()

    def show_index(self, i: int) -> None:
        sweeps = self.lab.ws.sweeps
        ax = self.plot.ax()
        if not sweeps:
            self.index = -1
            self.pos.setText("aucun balayage")
            self.cmp.setText("Acquérir un balayage ou lancer une simulation.")
            self.emissions.set_rows([])
            ax.text(0.5, 0.5, "Aucun balayage", ha="center", va="center",
                    transform=ax.transAxes, color=theme.MUTED)
            self.plot.draw()
            self.wf.ax()
            self.wf.draw()
            return
        self.index = max(0, min(i, len(sweeps) - 1))
        s = sweeps[self.index]
        ems = detect_emissions(s, self.threshold.value(), bands=self.lab.config.bands)
        plot_spectrum(ax, s, ems)
        if s.provenance.is_simulation:
            self.plot.figure.text(0.99, 0.98, "SIMULATION", ha="right", va="top",
                                  color=theme.RED, fontweight="bold")
        self.plot.draw()
        self.emissions.set_rows(ems)
        self.pos.setText(f"{self.index + 1}/{len(sweeps)} · {s.provenance.label}")
        if self.index > 0:
            try:
                c = compare_sweeps(sweeps[self.index - 1], s, self.threshold.value())
                self.cmp.setText(
                    f"Vs balayage précédent : Δmax +{c.max_increase_db:.1f} / "
                    f"{c.max_decrease_db:.1f} dB, |Δ| moyen {c.mean_abs_delta_db:.2f} dB · "
                    f"nouvelles émissions : {[round(e.center_mhz, 2) for e in c.new_emissions]}"
                    f" · disparues : {[round(e.center_mhz, 2) for e in c.lost_emissions]}")
            except ValueError as exc:
                self.cmp.setText(f"Comparaison impossible : {exc}")
        else:
            self.cmp.setText("Premier balayage de la série.")
        f, m, t = waterfall(sweeps[: self.index + 1][-120:])
        im = plot_waterfall(self.wf.ax(), f, m, t)
        self.wf.figure.colorbar(im, ax=self.wf.figure.axes[0], label="dB/bin")
        self.wf.draw()

    def variations(self) -> None:
        sweeps = self.lab.ws.sweeps
        var = detect_power_variations(sweeps, self.threshold.value())
        if len(sweeps) < 5:
            self.win.notify("Au moins 5 balayages sont nécessaires (données insuffisantes).",
                            "warn")
            return
        ax = self.wf.ax()
        f, m, t = waterfall(sweeps)
        plot_waterfall(ax, f, m, t)
        for v in var:
            ax.plot(v.center_hz / 1e6, sweeps.index(next(s for s in sweeps
                                                           if s.timestamp == v.timestamp)),
                    "o", ms=5, mfc="none", mec=theme.RED)
        ax.set_title(f"Variations inhabituelles : {len(var)} (cercles rouges)")
        self.wf.draw()
        self.win.notify(f"{len(var)} variation(s) inhabituelle(s) détectée(s).",
                        "warn" if var else "info")
