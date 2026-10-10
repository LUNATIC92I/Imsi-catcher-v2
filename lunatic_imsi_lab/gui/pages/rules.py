from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout)

from lunatic_imsi_lab.detection.engine import SINGLE_INDICATOR_CAP
from lunatic_imsi_lab.detection.rules import (DEFAULT_RULES, RULE_PARAM_LIMITS, RULE_PROFILES,
                                              RuleConfig)
from lunatic_imsi_lab.gui.pages.base import Page
from lunatic_imsi_lab.security.rbac import Permission

INT_PARAMS = {"min_jumps", "min_baseline_obs_per_cell"}


class RulesPage(Page):
    nav_label = "Règles de détection"
    title = "Règles de détection"
    subtitle = ("Seuils des règles heuristiques et profils d'environnement. Modification réservée "
                "à l'administrateur, journalisée et reprise dans les rapports.")

    def build(self) -> None:
        note = QLabel(f"Garde-fous non configurables : une alerte reposant sur un seul type "
                      f"d'indicateur reste plafonnée à {SINGLE_INDICATOR_CAP:.2f} de confiance ; "
                      f"les pondérations des règles sont fixes ; aucun niveau « confirmé » "
                      f"n'existe.")
        note.setObjectName("Notice")
        note.setWordWrap(True)
        self.layout_.addWidget(note)
        row = QHBoxLayout()

        params = QGroupBox("Seuils")
        f = QFormLayout(params)
        self.profile = QComboBox()
        for name, prof in RULE_PROFILES.items():
            self.profile.addItem(prof["label"], name)
        self.profile.activated.connect(self.load_profile)
        f.addRow("Profil d'environnement", self.profile)
        self.inputs = {}
        for key, (lo, hi, label, unit) in RULE_PARAM_LIMITS.items():
            if key in INT_PARAMS:
                w = QSpinBox()
                w.setRange(int(lo), int(hi))
            else:
                w = QDoubleSpinBox()
                w.setRange(lo, hi)
                w.setDecimals(1)
            if unit:
                w.setSuffix(f" {unit}")
            w.setToolTip(f"Plage admise : {lo} … {hi}")
            self.inputs[key] = w
            f.addRow(label, w)
        row.addWidget(params, 1)

        rules = QGroupBox("Règles actives")
        rv = QVBoxLayout(rules)
        self.checks = {}
        for cls in DEFAULT_RULES:
            cb = QCheckBox(f"{cls.rule_id} — {cls.name}")
            self.checks[cls.rule_id] = cb
            rv.addWidget(cb)
        cb = QCheckBox("R10_SPECTRUM_POWER — Variation spectrale inhabituelle")
        self.checks["R10_SPECTRUM_POWER"] = cb
        rv.addWidget(cb)
        warn = QLabel("Désactiver une règle signifie que le phénomène correspondant n'est plus "
                      "évalué ; les rapports le mentionnent dans les limites de l'analyse.")
        warn.setObjectName("Muted")
        warn.setWordWrap(True)
        rv.addWidget(warn)
        rv.addStretch(1)
        row.addWidget(rules, 1)
        self.layout_.addLayout(row, 1)

        bar = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName("Muted")
        bar.addWidget(self.status, 1)
        reset = QPushButton("Annuler les modifications")
        reset.clicked.connect(self.refresh)
        bar.addWidget(reset)
        self.apply_btn = QPushButton("Appliquer et réanalyser")
        self.apply_btn.setObjectName("Primary")
        self.apply_btn.clicked.connect(self.apply)
        bar.addWidget(self.apply_btn)
        self.layout_.addLayout(bar)

    def _show(self, cfg: RuleConfig) -> None:
        for key, w in self.inputs.items():
            w.setValue(getattr(cfg, key))

    def refresh(self) -> None:
        super().refresh()
        eng = self.lab.engine
        i = self.profile.findData(eng.config.profile)
        self.profile.setCurrentIndex(max(i, 0))
        self._show(eng.config)
        for rid, cb in self.checks.items():
            cb.setChecked(rid not in eng.disabled_rules)
        admin = self.lab.user.can(Permission.CONFIGURE_RULES)
        for w in list(self.inputs.values()) + list(self.checks.values()) + [self.profile,
                                                                           self.apply_btn]:
            w.setEnabled(admin)
        self.status.setText("" if admin else
                            "Lecture seule : la modification des règles est réservée à "
                            "l'administrateur.")

    def load_profile(self, *_):
        self._show(RuleConfig.for_profile(self.profile.currentData()))

    def apply(self) -> None:
        params = {k: w.value() for k, w in self.inputs.items()}
        params["profile"] = self.profile.currentData()
        disabled = [rid for rid, cb in self.checks.items() if not cb.isChecked()]
        if self.win.guarded(self.lab.update_rules, params, disabled) is None:
            return
        self.win.notify("Configuration des règles enregistrée.")
        if self.lab.ws.observations or self.lab.ws.sweeps:
            self.win.analyze()
        else:
            self.win.after_data()
