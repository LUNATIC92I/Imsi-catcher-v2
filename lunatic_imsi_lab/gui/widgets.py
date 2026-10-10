"""Composants réutilisables de l'IHM."""

from __future__ import annotations

import traceback
from typing import Any, Callable, Sequence

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QObject, QRunnable,
                            QSortFilterProxyModel, Qt, Signal)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QTableView, QVBoxLayout, QWidget)

from lunatic_imsi_lab.gui import theme


class PlotWidget(QWidget):
    """Canevas Matplotlib interactif (zoom, déplacement, export) au thème sombre."""

    def __init__(self, parent=None, height: float = 3.0, toolbar: bool = True) -> None:
        super().__init__(parent)
        self.figure = Figure(figsize=(6, height), dpi=100, tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        if toolbar:
            self.toolbar = NavigationToolbar2QT(self.canvas, self)
            self.toolbar.setStyleSheet(f"background:{theme.PANEL}; border:none;")
            lay.addWidget(self.toolbar)
        lay.addWidget(self.canvas)

    def ax(self, rows: int = 1, cols: int = 1, index: int = 1, clear: bool = True):
        if clear and index == 1:
            self.figure.clear()
        return self.figure.add_subplot(rows, cols, index)

    def draw(self) -> None:
        theme.apply_mpl_style(self.figure)
        self.canvas.draw_idle()


class Card(QFrame):
    def __init__(self, title: str, value: str = "—", sub: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        self.title = QLabel(title.upper())
        self.title.setObjectName("CardTitle")
        self.value = QLabel(value)
        self.value.setObjectName("CardValue")
        self.sub = QLabel(sub)
        self.sub.setObjectName("Muted")
        self.sub.setWordWrap(True)
        for w in (self.title, self.value, self.sub):
            lay.addWidget(w)

    def set(self, value: str, sub: str = "", color: str | None = None) -> None:
        self.value.setText(value)
        self.sub.setText(sub)
        self.value.setStyleSheet(f"color:{color};" if color else "")


class RecordModel(QAbstractTableModel):
    """Modèle tabulaire générique : liste d'objets + définitions de colonnes."""

    def __init__(self, columns: Sequence[tuple[str, Callable[[Any], Any]]], parent=None) -> None:
        super().__init__(parent)
        self.columns = list(columns)
        self.rows: list[Any] = []
        self.color_fn: Callable[[Any], str | None] | None = None

    def set_rows(self, rows: Sequence[Any]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.columns[section][0]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        value = self.columns[index.column()][1](row)
        if role == Qt.DisplayRole:
            if isinstance(value, float):
                return f"{value:.2f}"
            return "" if value is None else str(value)
        if role == Qt.UserRole:  # valeur brute pour le tri
            return value if isinstance(value, (int, float)) else ("" if value is None
                                                                  else str(value))
        if role == Qt.ForegroundRole and self.color_fn:
            c = self.color_fn(row)
            return QColor(c) if c else None
        return None


class RecordTable(QWidget):
    """Tableau triable avec filtre textuel."""

    def __init__(self, columns, parent=None, filter_placeholder: str = "Filtrer…") -> None:
        super().__init__(parent)
        self.model = RecordModel(columns, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.UserRole)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.verticalHeader().setVisible(False)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(filter_placeholder)
        self.filter.textChanged.connect(self.proxy.setFilterFixedString)
        self.count = QLabel("0 ligne")
        self.count.setObjectName("Muted")
        top = QHBoxLayout()
        top.addWidget(self.filter, 1)
        top.addWidget(self.count)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(top)
        lay.addWidget(self.view)

    def set_rows(self, rows) -> None:
        self.model.set_rows(rows)
        self.count.setText(f"{len(rows)} ligne{'s' if len(rows) > 1 else ''}")
        self.view.resizeColumnsToContents()

    def sort_by(self, column: int, descending: bool = True) -> None:
        self.view.sortByColumn(column, Qt.DescendingOrder if descending else Qt.AscendingOrder)

    def selected(self):
        idx = self.view.selectionModel().selectedRows()
        if not idx:
            return None
        return self.model.rows[self.proxy.mapToSource(idx[0]).row()]


def page_header(title: str, subtitle: str = "") -> tuple[QWidget, QLabel]:
    """En-tête de page + bandeau SIMULATION (masqué par défaut)."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 6)
    col = QVBoxLayout()
    t = QLabel(title)
    t.setObjectName("PageTitle")
    col.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("Muted")
        s.setWordWrap(True)
        col.addWidget(s)
    lay.addLayout(col, 1)
    banner = QLabel("SIMULATION")
    banner.setObjectName("SimBanner")
    banner.setVisible(False)
    lay.addWidget(banner, 0, Qt.AlignTop)
    return w, banner


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class Worker(QRunnable):
    """Exécute une fonction hors du thread graphique."""

    def __init__(self, fn: Callable, *args, **kwargs) -> None:
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # remonté à l'IHM
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        else:
            self.signals.finished.emit(result)
