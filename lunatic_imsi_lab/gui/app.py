"""Point d'entrée de l'interface graphique."""

from __future__ import annotations

import sys
from pathlib import Path


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
    lab = Lab(cfg)
    lab.audit.record(lab.user, "gui_start", {"data_dir": cfg.data_dir})
    win = MainWindow(lab)
    win.show()
    return app.exec()
