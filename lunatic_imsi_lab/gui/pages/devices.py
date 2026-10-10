from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout)

from lunatic_imsi_lab.config import Band, DeviceConfig
from lunatic_imsi_lab.gui.pages.base import Page
from lunatic_imsi_lab.gui.widgets import RecordTable
from lunatic_imsi_lab.radio.receivers import SoapyReceiver, make_receiver
from lunatic_imsi_lab.security.rbac import Permission


class DevicesPage(Page):
    nav_label = "Équipements & configuration"
    title = "Équipements et configuration"
    subtitle = ("Récepteurs en réception seule (SoapySDR) ou récepteur simulé. Consulter "
                "docs/equipment_guide.md et docs/legal_compliance.md avant toute mesure réelle.")

    def build(self) -> None:
        row = QHBoxLayout()
        left = QVBoxLayout()
        self.devices = RecordTable([
            ("Nom", lambda d: d.name), ("Pilote", lambda d: d.driver), ("Arguments", lambda d: d.args),
            ("Échant. (MS/s)", lambda d: d.sample_rate / 1e6), ("Gain (dB)", lambda d: d.gain_db),
            ("Actif", lambda d: "oui" if d.enabled else "non")])
        left.addWidget(QLabel("Récepteurs configurés"))
        left.addWidget(self.devices, 1)
        box = QGroupBox("Ajouter / modifier un récepteur")
        f = QFormLayout(box)
        self.d_name = QLineEdit()
        self.d_driver = QComboBox()
        self.d_driver.addItems(["simulated", "soapy"])
        self.d_args = QLineEdit()
        self.d_args.setPlaceholderText("ex. driver=rtlsdr ; driver=hackrf ; driver=airspy")
        self.d_rate = QDoubleSpinBox()
        self.d_rate.setRange(0.25, 61.44)
        self.d_rate.setValue(2.4)
        self.d_rate.setSuffix(" MS/s")
        self.d_gain = QDoubleSpinBox()
        self.d_gain.setRange(0, 80)
        self.d_gain.setValue(30)
        self.d_gain.setSuffix(" dB")
        self.d_cal = QDoubleSpinBox()
        self.d_cal.setRange(-200, 200)
        self.d_cal.setSuffix(" dB")
        self.d_cal.setToolTip("Offset d'étalonnage : dBm = dBFS + offset (0 = non étalonné)")
        self.d_enabled = QCheckBox("Actif")
        self.d_enabled.setChecked(True)
        for lab, w in (("Nom", self.d_name), ("Pilote", self.d_driver), ("Arguments", self.d_args),
                       ("Échantillonnage", self.d_rate), ("Gain", self.d_gain),
                       ("Étalonnage", self.d_cal), ("", self.d_enabled)):
            f.addRow(lab, w)
        btns = QHBoxLayout()
        for text, slot in (("Enregistrer", self.save_device), ("Supprimer", self.remove_device),
                           ("Tester", self.test_device)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        f.addRow(btns)
        self.soapy_info = QLabel()
        self.soapy_info.setObjectName("Notice")
        self.soapy_info.setWordWrap(True)
        f.addRow(self.soapy_info)
        left.addWidget(box)
        self.devices.view.selectionModel().selectionChanged.connect(self.load_device)
        row.addLayout(left, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel("Bandes de fréquences surveillées (DL)"))
        self.bands = RecordTable([("Nom", lambda b: b.name), ("Techno", lambda b: b.technology),
                                  ("Début (MHz)", lambda b: b.start_mhz),
                                  ("Fin (MHz)", lambda b: b.stop_mhz)])
        right.addWidget(self.bands, 1)
        bb = QHBoxLayout()
        add_b = QPushButton("Ajouter une bande…")
        add_b.clicked.connect(self.add_band)
        del_b = QPushButton("Retirer")
        del_b.clicked.connect(self.remove_band)
        bb.addWidget(add_b)
        bb.addWidget(del_b)
        right.addLayout(bb)
        gen = QGroupBox("Général")
        g = QFormLayout(gen)
        self.auth = QLineEdit()
        self.local = QCheckBox("Fonctionnement local uniquement (recommandé)")
        self.iq = QCheckBox("Conserver les IQ bruts (désactivé : non implémenté par conception)")
        self.iq.setEnabled(False)
        g.addRow("Référence d'autorisation", self.auth)
        g.addRow(self.local)
        g.addRow(self.iq)
        save = QPushButton("Enregistrer la configuration")
        save.setObjectName("Primary")
        save.clicked.connect(self.save_config)
        g.addRow(save)
        right.addWidget(gen)
        data = QGroupBox("Gestion des données (administrateur)")
        dl = QHBoxLayout(data)
        self.ds = QComboBox()
        dl.addWidget(self.ds, 1)
        rm = QPushButton("Suppression contrôlée…")
        rm.setObjectName("Danger")
        rm.clicked.connect(self.delete_dataset)
        dl.addWidget(rm)
        right.addWidget(data)
        row.addLayout(right, 1)
        self.layout_.addLayout(row, 1)

    def refresh(self) -> None:
        super().refresh()
        cfg = self.lab.config
        self.devices.set_rows(cfg.devices)
        self.bands.set_rows(cfg.bands)
        self.auth.setText(cfg.authorization_ref)
        self.local.setChecked(cfg.local_only)
        avail = SoapyReceiver.module_available()
        self.soapy_info.setText(
            "SoapySDR : " + (f"disponible — {len(SoapyReceiver.enumerate_devices())} "
                             "périphérique(s) détecté(s)" if avail else
                             "bindings Python non installés (voir guide d'installation). "
                             "Le récepteur simulé reste utilisable."))
        self.ds.clear()
        for d in self.lab.db.list_datasets():
            self.ds.addItem(d.name)

    def _can_configure(self) -> bool:
        if not self.lab.user.can(Permission.CONFIGURE_DEVICES):
            self.win.guarded(self.lab.user.require, Permission.CONFIGURE_DEVICES)
            return False
        return True

    def load_device(self, *_):
        d = self.devices.selected()
        if d:
            self.d_name.setText(d.name)
            self.d_driver.setCurrentText(d.driver)
            self.d_args.setText(d.args)
            self.d_rate.setValue(d.sample_rate / 1e6)
            self.d_gain.setValue(d.gain_db)
            self.d_cal.setValue(d.calibration_offset_db)
            self.d_enabled.setChecked(d.enabled)

    def save_device(self) -> None:
        if not self._can_configure():
            return
        name = self.d_name.text().strip()
        if not name:
            self.win.notify("Nom du récepteur requis.", "warn")
            return
        dev = DeviceConfig(name=name, driver=self.d_driver.currentText(),
                           args=self.d_args.text().strip(), sample_rate=self.d_rate.value() * 1e6,
                           gain_db=self.d_gain.value(), enabled=self.d_enabled.isChecked(),
                           calibration_offset_db=self.d_cal.value())
        devs = [d for d in self.lab.config.devices if d.name != name] + [dev]
        self.lab.config.devices = devs
        self.save_config(quiet=True)
        self.win.after_data(f"Récepteur « {name} » enregistré.")

    def remove_device(self) -> None:
        d = self.devices.selected()
        if d and self._can_configure():
            self.lab.config.devices = [x for x in self.lab.config.devices if x is not d]
            self.save_config(quiet=True)
            self.win.after_data(f"Récepteur « {d.name} » retiré.")

    def test_device(self) -> None:
        try:
            rx = make_receiver(self.d_driver.currentText(), args=self.d_args.text().strip())
            info = rx.info()
            QMessageBox.information(self, "Test du récepteur",
                                    f"{info.name}\nDisponible : {'oui' if info.available else 'non'}"
                                    f"\n{info.details}")
        except Exception as exc:
            QMessageBox.warning(self, "Test du récepteur", str(exc))

    def add_band(self) -> None:
        if not self._can_configure():
            return
        text, ok = QInputDialog.getText(self, "Nouvelle bande",
                                        "Nom;Techno;Début MHz;Fin MHz (ex. B28 DL;LTE;758;803)")
        if not ok or not text:
            return
        try:
            name, tech, a, b = [x.strip() for x in text.split(";")]
            band = Band(name, tech, float(a), float(b))
            if band.stop_mhz <= band.start_mhz:
                raise ValueError("fin ≤ début")
        except ValueError as exc:
            self.win.notify(f"Format invalide : {exc}", "error")
            return
        self.lab.config.bands.append(band)
        self.save_config(quiet=True)
        self.refresh()

    def remove_band(self) -> None:
        b = self.bands.selected()
        if b and self._can_configure():
            self.lab.config.bands = [x for x in self.lab.config.bands if x is not b]
            self.save_config(quiet=True)
            self.refresh()

    def save_config(self, quiet: bool = False) -> None:
        if not self._can_configure():
            return
        cfg = self.lab.config
        cfg.authorization_ref = self.auth.text().strip()
        cfg.local_only = self.local.isChecked()
        path = cfg.save()
        self.lab.audit.record(self.lab.user, "save_config", {"path": str(path)})
        if not quiet:
            self.win.notify(f"Configuration enregistrée : {path}")

    def delete_dataset(self) -> None:
        name = self.ds.currentText()
        if not name:
            return
        if not self.lab.user.can(Permission.DELETE_DATA):
            self.win.guarded(self.lab.user.require, Permission.DELETE_DATA)
            return
        reason, ok = QInputDialog.getText(self, "Suppression contrôlée",
                                          f"Motif de la suppression de « {name} » :")
        if not ok:
            return
        confirm, ok = QInputDialog.getText(
            self, "Confirmation", f"Saisir exactement « {name} » pour confirmer. Les fichiers "
                                  "importés associés seront écrasés puis supprimés.")
        if not ok:
            return
        counts = self.win.guarded(self.lab.delete_dataset, name, reason, confirm)
        if counts is not None:
            self.win.after_data(f"Jeu « {name} » supprimé : {counts}")
            self.win.notify(f"Jeu « {name} » supprimé.", "warn")
