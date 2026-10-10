from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QSplitter)

from lunatic_imsi_lab.correlation.analysis import summarize_cells
from lunatic_imsi_lab.detection.baseline import Baseline
from lunatic_imsi_lab.gui import theme
from lunatic_imsi_lab.gui.pages.base import Page
from lunatic_imsi_lab.gui.widgets import PlotWidget, RecordTable


class ImportDialog(QDialog):
    def __init__(self, parent, path: str, profiles: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Importer des observations")
        form = QFormLayout(self)
        form.addRow(QLabel(f"Fichier : {path}"))
        self.source = QLineEdit()
        self.source.setPlaceholderText("ex. Outil de diagnostic X, terminal de test n°2")
        self.dataset = QLineEdit("default")
        self.auth = QLineEdit()
        self.auth.setPlaceholderText("référence de l'autorisation de mesure")
        self.tz = QComboBox()
        self.tz.setEditable(True)
        self.tz.addItems(["UTC", "Europe/Paris", "Africa/Abidjan", "Africa/Casablanca",
                          "Africa/Douala", "America/Montreal"])
        form.addRow("Source / méthode", self.source)
        form.addRow("Jeu de données", self.dataset)
        form.addRow("Autorisation", self.auth)
        form.addRow("Fuseau des dates sans fuseau", self.tz)
        self.path = path
        self.profiles = profiles or {}
        self.profile = QComboBox()
        for name, prof in self.profiles.items():
            self.profile.addItem(f"{name} — {prof['label']}", name)
        self.profile.currentIndexChanged.connect(self.update_preview)
        form.addRow("Profil de mappage", self.profile)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setObjectName("Muted")
        form.addRow("Aperçu des colonnes", self.preview)
        note = QLabel("Les colonnes d'identifiants personnels (IMSI, IMEI, TMSI, MSISDN…) "
                      "sont supprimées automatiquement sans être lues.")
        note.setObjectName("Notice")
        note.setWordWrap(True)
        form.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.ok_button = bb.button(QDialogButtonBox.Ok)
        self.update_preview()

    def update_preview(self, *_):
        from lunatic_imsi_lab.importers.profiles import preview_file
        if not self.profiles:
            return
        try:
            pv = preview_file(self.path, self.profiles[self.profile.currentData()])
        except Exception as exc:  # fichier illisible, profil invalide…
            self.preview.setText(f"Lecture impossible : {exc}")
            self.ok_button.setEnabled(False)
            return
        lines = [f"{pv.rows} ligne(s)"]
        lines += [f"{c} ← {col}" for c, col in pv.resolved.items()]
        lines += [f"{c} = {v} (constante)" for c, v in pv.constants.items()]
        if pv.dropped:
            lines.append("Supprimées (identifiants personnels) : " + ", ".join(pv.dropped))
        if pv.unused:
            lines.append("Ignorées : " + ", ".join(pv.unused))
        lines += pv.warnings
        if not pv.ok:
            lines.append("CHAMPS OBLIGATOIRES MANQUANTS : " + ", ".join(pv.missing_required))
        self.preview.setText("\n".join(lines))
        self.ok_button.setEnabled(pv.ok)


class CellsPage(Page):
    nav_label = "Explorateur de cellules"
    title = "Explorateur de cellules"
    subtitle = ("Observations d'infrastructure issues d'outils de diagnostic autorisés. "
                "Aucun identifiant d'abonné ou d'appareil n'est collecté ni affiché.")

    def build(self) -> None:
        bar = QHBoxLayout()
        self.tech = QComboBox()
        self.tech.addItems(["Toutes", "GSM", "UMTS", "LTE", "NR"])
        self.tech.currentTextChanged.connect(lambda _: self.refresh())
        self.status = QComboBox()
        self.status.addItems(["Toutes", "Connues (référence)", "Absentes de la référence"])
        self.status.currentTextChanged.connect(lambda _: self.refresh())
        bar.addWidget(QLabel("Technologie"))
        bar.addWidget(self.tech)
        bar.addWidget(QLabel("Statut"))
        bar.addWidget(self.status)
        bar.addStretch(1)
        imp = QPushButton("Importer CSV / JSON…")
        imp.setObjectName("Primary")
        imp.clicked.connect(self.import_file)
        bar.addWidget(imp)
        self.layout_.addLayout(bar)

        split = QSplitter(Qt.Vertical)
        self.table = RecordTable([
            ("Techno", lambda c: c.technology), ("MCC", lambda c: c.mcc),
            ("MNC", lambda c: c.mnc), ("LAC/TAC", lambda c: c.area_code),
            ("Cell ID", lambda c: c.cell_id), ("Canal", lambda c: c.channel),
            ("Fréq. (MHz)", lambda c: c.frequency_mhz), ("PCI/PSC/BSIC", lambda c: c.pci),
            ("Obs.", lambda c: c.count), ("P. méd. (dBm)", lambda c: c.rssi_median),
            ("P. min", lambda c: c.rssi_min), ("P. max", lambda c: c.rssi_max),
            ("Qualité (dB)", lambda c: c.quality_median),
            ("Service", lambda c: c.serving_count),
            ("Première obs. (UTC)", lambda c: f"{c.first_seen:%Y-%m-%d %H:%M:%S}"),
            ("Dernière obs. (UTC)", lambda c: f"{c.last_seen:%Y-%m-%d %H:%M:%S}"),
            ("Référence", lambda c: {None: "—", True: "connue", False: "ABSENTE"}[c.in_baseline]),
            ("Source", lambda c: c.sources), ("Méthode", lambda c: c.methods)],
            filter_placeholder="Filtrer (MCC, LAC, cell ID, source…)")
        self.table.model.color_fn = lambda c: theme.AMBER if c.in_baseline is False else None
        self.table.view.selectionModel().selectionChanged.connect(self.plot_selected)
        split.addWidget(self.table)
        self.plot = PlotWidget(height=2.4)
        split.addWidget(self.plot)
        split.setSizes([480, 260])
        self.layout_.addWidget(split, 1)

    def refresh(self) -> None:
        super().refresh()
        ws = self.lab.ws
        base = Baseline.from_observations(ws.baseline_obs) if ws.baseline_obs else None
        rows = summarize_cells(ws.observations, base)
        t = self.tech.currentText()
        if t != "Toutes":
            rows = [r for r in rows if r.technology == t]
        st = self.status.currentIndex()
        if st == 1:
            rows = [r for r in rows if r.in_baseline]
        elif st == 2:
            rows = [r for r in rows if r.in_baseline is False]
        self.table.set_rows(rows)
        self.plot_selected()

    def plot_selected(self, *_):
        c = self.table.selected()
        ax = self.plot.ax()
        if c is None:
            ax.text(0.5, 0.5, "Sélectionner une cellule pour afficher sa puissance",
                    ha="center", va="center", transform=ax.transAxes, color=theme.MUTED)
        else:
            obs = sorted((o for o in self.lab.ws.observations if o.cell_key == c.cell_key
                          and o.rssi_dbm is not None), key=lambda o: o.timestamp)
            ax.plot([o.timestamp for o in obs], [o.rssi_dbm for o in obs], color=theme.BLUE,
                    lw=1)
            ref = [o for o in self.lab.ws.baseline_obs if o.cell_key == c.cell_key
                   and o.rssi_dbm is not None]
            if ref:
                med = sorted(o.rssi_dbm for o in ref)[len(ref) // 2]
                ax.axhline(med, color=theme.SILVER, ls="--", lw=0.8,
                           label=f"médiane de référence {med:.1f} dBm")
                ax.legend(fontsize=7)
            ax.set_title(f"{c.technology} {c.mcc}-{c.mnc} LAC/TAC={c.area_code} CI={c.cell_id}")
            ax.set_ylabel("dBm")
            ax.grid(True, alpha=0.2)
        self.plot.draw()

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importer des observations", "",
                                              "Observations (*.csv *.json)")
        if not path:
            return
        dlg = ImportDialog(self, path, self.lab.import_profiles())
        if dlg.exec() != QDialog.Accepted:
            return
        if not dlg.source.text().strip():
            QMessageBox.warning(self, "Source requise",
                                "La source et la méthode de collecte doivent être renseignées.")
            return
        ds = dlg.dataset.text().strip() or "default"
        rep = self.win.guarded(self.lab.import_file, path, dlg.source.text().strip(), ds,
                               dlg.auth.text().strip(), dlg.tz.currentText(),
                               dlg.profile.currentData())
        if rep is None:
            return
        msg = (f"{rep.rows_imported} ligne(s) importée(s), {rep.rows_rejected} rejetée(s)."
               + (f"\nColonnes supprimées : {', '.join(rep.dropped_fields)}"
                  if rep.dropped_fields else "")
               + ("\n\n" + "\n".join(rep.errors[:10]) if rep.errors else ""))
        QMessageBox.information(self, "Import terminé", msg)
        self.lab.load(ds, self.lab.ws.baseline_dataset)
        self.win.after_data(f"Import dans « {ds} » terminé.")
