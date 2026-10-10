"""Éditeur des profils de mappage d'import personnalisés (administrateur)."""

from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from lunatic_imsi_lab.gui import theme
from lunatic_imsi_lab.importers.cells import FIELD_ALIASES
from lunatic_imsi_lab.importers.profiles import BUILTIN_PROFILES

FIELD_LABELS = {
    "timestamp": "Horodatage", "technology": "Technologie", "mcc": "MCC", "mnc": "MNC",
    "area_code": "LAC / TAC", "cell_id": "Identifiant de cellule", "channel": "Canal",
    "frequency_mhz": "Fréquence (MHz)", "pci": "PCI / PSC / BSIC", "rssi_dbm": "Puissance (dBm)",
    "quality_db": "Qualité (dB)", "latitude": "Latitude", "longitude": "Longitude",
    "position_kind": "Type de position", "serving": "Cellule de service",
}


class ProfileEditor(QDialog):
    def __init__(self, win) -> None:
        super().__init__(win)
        self.win, self.lab = win, win.lab
        self.setWindowTitle("Profils de mappage d'import")
        self.setStyleSheet(theme.QSS)
        self.resize(620, 680)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.choice = QComboBox()
        self.choice.currentIndexChanged.connect(self.load)
        top.addWidget(QLabel("Profil"))
        top.addWidget(self.choice, 1)
        self.delete_btn = QPushButton("Supprimer")
        self.delete_btn.setObjectName("Danger")
        self.delete_btn.clicked.connect(self.delete)
        top.addWidget(self.delete_btn)
        lay.addLayout(top)
        note = QLabel("Saisir pour chaque champ le nom exact de la colonne dans l'export (casse, "
                      "espaces et tirets ignorés). Laisser vide pour la détection automatique. "
                      "Les colonnes d'identifiants personnels sont refusées.")
        note.setObjectName("Notice")
        note.setWordWrap(True)
        lay.addWidget(note)
        form_host = QWidget()
        form = QFormLayout(form_host)
        self.name = QLineEdit()
        self.label = QLineEdit()
        form.addRow("Nom (identifiant)", self.name)
        form.addRow("Description", self.label)
        self.tech_const = QComboBox()
        for text, val in (("— (colonne du fichier)", ""), ("GSM", "GSM"), ("UMTS", "UMTS"),
                          ("LTE", "LTE"), ("NR", "NR")):
            self.tech_const.addItem(text, val)
        form.addRow("Technologie fixe", self.tech_const)
        self.cols: dict[str, QLineEdit] = {}
        for field in FIELD_ALIASES:
            e = QLineEdit()
            e.setPlaceholderText("auto : " + ", ".join(FIELD_ALIASES[field][:3]))
            self.cols[field] = e
            form.addRow(FIELD_LABELS.get(field, field), e)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_host)
        lay.addWidget(scroll, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Save).setText("Enregistrer")
        bb.button(QDialogButtonBox.Close).setText("Fermer")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.reload_choices()

    def reload_choices(self, select: str = "") -> None:
        self.choice.blockSignals(True)
        self.choice.clear()
        self.choice.addItem("— nouveau profil —", "")
        for name in self.lab.config.import_profiles:
            self.choice.addItem(name, name)
        for name in BUILTIN_PROFILES:
            self.choice.addItem(f"{name} (intégré, modèle)", "builtin:" + name)
        i = self.choice.findData(select)
        self.choice.setCurrentIndex(max(i, 0))
        self.choice.blockSignals(False)
        self.load()

    def load(self, *_):
        key = self.choice.currentData() or ""
        builtin = key.startswith("builtin:")
        prof = (BUILTIN_PROFILES[key[8:]] if builtin else
                self.lab.config.import_profiles.get(key, {"label": "", "columns": {},
                                                          "constants": {}}))
        self.name.setText("" if builtin else key)
        self.label.setText(prof.get("label", ""))
        tech = prof.get("constants", {}).get("technology", "")
        self.tech_const.setCurrentIndex(max(self.tech_const.findData(tech), 0))
        for field, e in self.cols.items():
            e.setText(prof.get("columns", {}).get(field, ""))
        self.delete_btn.setEnabled(bool(key) and not builtin)

    def profile(self) -> dict:
        cols = {f: e.text().strip() for f, e in self.cols.items() if e.text().strip()}
        consts = {"technology": self.tech_const.currentData()} if self.tech_const.currentData() \
            else {}
        return {"label": self.label.text().strip(), "columns": cols, "constants": consts}

    def save(self) -> None:
        name = self.name.text().strip()
        if self.win.try_action(self.lab.save_import_profile, name, self.profile()):
            self.win.notify(f"Profil d'import « {name} » enregistré.")
            self.reload_choices(name)

    def delete(self) -> None:
        key = self.choice.currentData()
        if key and self.win.try_action(self.lab.delete_import_profile, key):
            self.win.notify(f"Profil « {key} » supprimé.", "warn")
            self.reload_choices()
