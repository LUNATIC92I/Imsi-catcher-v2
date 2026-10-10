"""Point d'entrée de l'interface graphique."""

from __future__ import annotations

import sys
from pathlib import Path


def install_french_translation(app) -> bool:
    """Traductions françaises fournies avec Qt (boutons standard, dialogues)."""
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    QLocale.setDefault(QLocale(QLocale.French, QLocale.France))
    translator = QTranslator(app)
    ok = translator.load("qtbase_fr", QLibraryInfo.path(QLibraryInfo.TranslationsPath))
    if ok:
        app.installTranslator(translator)
        app._lab_translator = translator  # conserver une référence
    return ok


def run(data_dir: str | None = None, argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    from lunatic_imsi_lab.config import AppConfig, default_data_dir
    from lunatic_imsi_lab.gui.main_window import MainWindow
    from lunatic_imsi_lab.services import Lab

    base = Path(data_dir) if data_dir else default_data_dir()
    cfg = AppConfig.load(base / "config.json")
    cfg.data_dir = str(base)
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("LUNATIC IMSI LAB")
    install_french_translation(app)
    from lunatic_imsi_lab.security.auth import UserStore
    from lunatic_imsi_lab.storage.db import Database
    if UserStore(Database(cfg.db_path)).has_users():
        from lunatic_imsi_lab.gui.login import LoginDialog
        dlg = LoginDialog(cfg, Lab)
        if dlg.exec() != LoginDialog.Accepted or dlg.lab is None:
            return 1
        lab = dlg.lab
    else:
        lab = Lab(cfg)
    lab.audit.record(lab.user, "gui_start", {"data_dir": cfg.data_dir})
    win = MainWindow(lab)
    win.show()
    return app.exec()
