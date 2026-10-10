"""Fenêtre principale : navigation latérale, sélection du jeu de données,
tâches de fond avec indicateur de progression et notifications."""

from __future__ import annotations

import logging

from PySide6.QtCore import QThreadPool, QTimer, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from lunatic_imsi_lab import APP_NAME, __version__
from lunatic_imsi_lab.gui import theme
from lunatic_imsi_lab.gui.widgets import Worker
from lunatic_imsi_lab.security.rbac import PermissionDenied
from lunatic_imsi_lab.services import Lab

log = logging.getLogger("lunatic.gui")


class MainWindow(QMainWindow):
    data_changed = Signal()

    def __init__(self, lab: Lab) -> None:
        super().__init__()
        self.lab = lab
        self.pool = QThreadPool.globalInstance()
        self._busy = False
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(1440, 900)
        self.setStyleSheet(theme.QSS)

        from lunatic_imsi_lab.gui.pages import ALL_PAGES
        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(230)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 16, 0, 10)
        title = QLabel("LUNATIC IMSI LAB")
        title.setObjectName("AppTitle")
        sub = QLabel("ANALYSE DÉFENSIVE\nRÉCEPTION SEULE")
        sub.setObjectName("AppSub")
        for w in (title, sub):
            w.setContentsMargins(16, 0, 10, 0)
            sv.addWidget(w)
        sv.addSpacing(12)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        sv.addWidget(self.nav, 1)
        self.user_label = QLabel()
        self.user_label.setObjectName("Muted")
        self.user_label.setContentsMargins(16, 0, 10, 0)
        self.user_label.setWordWrap(True)
        sv.addWidget(self.user_label)
        h.addWidget(side)

        main = QWidget()
        mv = QVBoxLayout(main)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(0)
        mv.addWidget(self._dataset_bar())
        self.stack = QStackedWidget()
        mv.addWidget(self.stack, 1)
        h.addWidget(main, 1)
        self.setCentralWidget(root)

        self.pages = []
        for cls in ALL_PAGES:
            page = cls(self)
            self.pages.append(page)
            self.stack.addWidget(page)
            QListWidgetItem(page.nav_label, self.nav)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        sb = self.statusBar()
        self.progress = QProgressBar()
        self.progress.setFixedWidth(180)
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.toast = QLabel()
        sb.addPermanentWidget(self.toast)
        sb.addPermanentWidget(self.progress)
        local = "local uniquement" if lab.config.local_only else "réseau autorisé"
        sb.showMessage(f"Base : {lab.config.db_path} · {local}")
        self._toast_timer = QTimer(self, singleShot=True, timeout=lambda: self.toast.setText(""))

        self.data_changed.connect(self.refresh_all)
        self.refresh_datasets()
        self.refresh_all()

    # -- barre de sélection des données ------------------------------------
    def _dataset_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Card")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.addWidget(QLabel("Jeu de données"))
        self.ds_combo = QComboBox()
        self.ds_combo.setMinimumWidth(260)
        lay.addWidget(self.ds_combo)
        lay.addWidget(QLabel("Référence"))
        self.ref_combo = QComboBox()
        self.ref_combo.setMinimumWidth(260)
        lay.addWidget(self.ref_combo)
        load = QPushButton("Charger")
        load.clicked.connect(self.load_selected)
        lay.addWidget(load)
        analyze = QPushButton("Analyser")
        analyze.setObjectName("Primary")
        analyze.clicked.connect(self.analyze)
        lay.addWidget(analyze)
        lay.addStretch(1)
        self.ws_label = QLabel()
        self.ws_label.setObjectName("Muted")
        lay.addWidget(self.ws_label)
        return bar

    def refresh_datasets(self) -> None:
        names = [d.name + ("  [SIMULATION]" if d.is_simulation else "")
                 for d in self.lab.db.list_datasets()]
        for combo, empty in ((self.ds_combo, "— choisir —"), (self.ref_combo, "— aucune —")):
            cur = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(empty, "")
            for n in names:
                combo.addItem(n, n.split("  [")[0])
            i = combo.findData(cur)
            combo.setCurrentIndex(max(i, 0))
            combo.blockSignals(False)
        for combo, val in ((self.ds_combo, self.lab.ws.dataset),
                           (self.ref_combo, self.lab.ws.baseline_dataset)):
            i = combo.findData(val)
            if i >= 0:
                combo.setCurrentIndex(i)

    def load_selected(self) -> None:
        ds, ref = self.ds_combo.currentData(), self.ref_combo.currentData()
        if not ds:
            self.notify("Sélectionner un jeu de données.", "warn")
            return
        self.run_task(lambda: self.lab.load(ds, ref), lambda _: self.after_data(
            f"Jeu « {ds} » chargé."), "Chargement…")

    def analyze(self) -> None:
        if not self.lab.ws.observations and not self.lab.ws.sweeps:
            self.notify("Aucune donnée chargée : charger un jeu ou lancer une simulation.",
                        "warn")
            return
        self.run_task(self.lab.analyze, lambda r: self.after_data(
            f"Analyse terminée : {len(r.alerts)} alerte(s) — {r.assessment}"), "Analyse…")

    # -- infrastructure ------------------------------------------------------
    def after_data(self, message: str = "") -> None:
        self.refresh_datasets()
        self.data_changed.emit()
        if message:
            self.notify(message)

    def refresh_all(self) -> None:
        ws = self.lab.ws
        u = self.lab.user
        self.user_label.setText(f"Opérateur : {u.name}\nRôle : {u.role.value}")
        sim = " · SIMULATION" if ws.is_simulation else ""
        self.ws_label.setText(f"{len(ws.observations)} obs. · {len(ws.sweeps)} balayages · "
                              f"{len(ws.result.alerts) if ws.result else 0} alertes{sim}")
        for p in self.pages:
            try:
                p.refresh()
            except Exception:  # une page défaillante ne doit pas bloquer les autres
                log.exception("rafraîchissement de %s", type(p).__name__)

    def notify(self, message: str, level: str = "info") -> None:
        color = {"info": theme.GREEN, "warn": theme.AMBER, "error": theme.RED}[level]
        self.toast.setText(message)
        self.toast.setStyleSheet(f"color:{color}; padding-right:10px;")
        self._toast_timer.start(8000)
        getattr(log, "warning" if level != "info" else "info")(message)

    def run_task(self, fn, on_done=None, label: str = "Traitement…", on_error=None) -> None:
        if self._busy:
            self.notify("Une tâche est déjà en cours.", "warn")
            return
        self._busy = True
        self.progress.setVisible(True)
        self.progress.setFormat(label)
        self.statusBar().showMessage(label)
        worker = Worker(fn)

        def done(result):
            self._end_task()
            if on_done:
                on_done(result)

        def failed(msg: str):
            self._end_task()
            if on_error:
                on_error()
            first = msg.splitlines()[0]
            log.error(msg)
            if "PermissionDenied" in first:
                QMessageBox.warning(self, "Permission refusée", first.split(": ", 1)[-1])
            else:
                self.notify(first, "error")

        worker.signals.finished.connect(done, Qt.QueuedConnection)
        worker.signals.failed.connect(failed, Qt.QueuedConnection)
        # Référence conservée : sans elle, le ramasse-miettes Python détruit
        # l'objet de signaux avant l'émission du résultat.
        worker.setAutoDelete(False)
        self._worker = worker
        self.pool.start(worker)

    def _end_task(self) -> None:
        self._busy = False
        self.progress.setVisible(False)
        self.statusBar().showMessage(f"Base : {self.lab.config.db_path}")

    def guarded(self, fn, *args, **kwargs):
        """Exécute une action courte en affichant les refus de permission."""
        try:
            return fn(*args, **kwargs)
        except PermissionDenied as exc:
            QMessageBox.warning(self, "Permission refusée", str(exc))
        except Exception as exc:  # erreur utilisateur (fichier invalide...)
            log.exception("action")
            self.notify(f"{type(exc).__name__}: {exc}", "error")
        return None
