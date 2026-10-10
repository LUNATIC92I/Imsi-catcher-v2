"""Thème « laboratoire de cybersécurité » : graphite, argent, bleu électrique."""

GRAPHITE = "#121418"
PANEL = "#1a1d23"
PANEL_2 = "#22262e"
BORDER = "#2e343e"
SILVER = "#c0c7d1"
MUTED = "#8a93a3"
BLUE = "#2f8bff"
BLUE_DARK = "#1f5fbf"
RED = "#ff4d6d"
AMBER = "#ffb703"
GREEN = "#06d6a0"

SEVERITY_COLORS = {"INFO": MUTED, "LOW": "#7ad7f0", "MEDIUM": AMBER, "HIGH": RED}

QSS = f"""
* {{ font-family: "Segoe UI", "Inter", "DejaVu Sans", sans-serif; font-size: 10pt; }}
QMainWindow, QWidget {{ background: {GRAPHITE}; color: {SILVER}; }}
QFrame#Sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
QListWidget#Nav {{ background: transparent; border: none; outline: 0; }}
QListWidget#Nav::item {{ padding: 9px 14px; border-left: 3px solid transparent; color: {SILVER}; }}
QListWidget#Nav::item:hover {{ background: {PANEL_2}; }}
QListWidget#Nav::item:selected {{ background: {PANEL_2}; border-left: 3px solid {BLUE};
                                  color: white; }}
QLabel#AppTitle {{ color: white; font-size: 13pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#AppSub {{ color: {BLUE}; font-size: 8pt; letter-spacing: 2px; }}
QLabel#PageTitle {{ color: white; font-size: 15pt; font-weight: 600; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#SimBanner {{ background: {RED}; color: white; font-weight: 700; padding: 4px 10px;
                    letter-spacing: 2px; border-radius: 3px; }}
QLabel#Notice {{ background: {PANEL_2}; border-left: 3px solid {BLUE}; padding: 6px 10px; }}
QFrame#Card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; }}
QFrame#Card QLabel {{ background: transparent; }}
QLabel#CardTitle {{ color: {MUTED}; font-size: 8pt; letter-spacing: 1px; }}
QLabel#CardValue {{ color: white; font-size: 17pt; font-weight: 600; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; padding: 6px 14px;
               border-radius: 4px; color: {SILVER}; }}
QPushButton:hover {{ border-color: {BLUE}; color: white; }}
QPushButton:disabled {{ color: #555c68; }}
QPushButton#Primary {{ background: {BLUE}; border-color: {BLUE}; color: white; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {BLUE_DARK}; }}
QPushButton#Danger {{ border-color: {RED}; color: {RED}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextBrowser, QTextEdit,
QDateTimeEdit {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 4px;
                padding: 4px; color: {SILVER}; selection-background-color: {BLUE}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {BLUE}; }}
QComboBox QAbstractItemView {{ background: {PANEL}; color: {SILVER};
                               selection-background-color: {BLUE}; }}
QTableView {{ background: {PANEL}; alternate-background-color: {PANEL_2};
              gridline-color: {BORDER}; border: 1px solid {BORDER};
              selection-background-color: {BLUE_DARK}; selection-color: white; }}
QHeaderView::section {{ background: {PANEL_2}; color: {SILVER}; border: none;
                        border-right: 1px solid {BORDER}; padding: 5px; font-weight: 600; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; }}
QTabBar::tab {{ background: {PANEL}; padding: 6px 14px; border: 1px solid {BORDER};
                color: {MUTED}; }}
QTabBar::tab:selected {{ color: white; border-bottom: 2px solid {BLUE}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 6px; margin-top: 14px; padding-top: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; color: {BLUE}; }}
QProgressBar {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 3px;
                text-align: center; color: white; max-height: 14px; }}
QProgressBar::chunk {{ background: {BLUE}; }}
QStatusBar {{ background: {PANEL}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QSplitter::handle {{ background: {BORDER}; }}
QScrollBar:vertical {{ background: {GRAPHITE}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 20px; }}
QCheckBox::indicator:checked {{ background: {BLUE}; border: 1px solid {BLUE}; }}
QCheckBox::indicator {{ border: 1px solid {BORDER}; width: 12px; height: 12px; }}
QToolTip {{ background: {PANEL_2}; color: white; border: 1px solid {BLUE}; }}
"""


def apply_mpl_style(fig) -> None:
    """Applique le thème sombre à une figure Matplotlib existante."""
    fig.set_facecolor(GRAPHITE)
    for ax in fig.axes:
        ax.set_facecolor(PANEL)
        for spine in ax.spines.values():
            spine.set_color(BORDER)
        ax.tick_params(colors=MUTED, labelsize=8)
        ax.xaxis.label.set_color(SILVER)
        ax.yaxis.label.set_color(SILVER)
        ax.title.set_color("white")
        leg = ax.get_legend()
        if leg:
            leg.get_frame().set_facecolor(PANEL_2)
            leg.get_frame().set_edgecolor(BORDER)
            for t in leg.get_texts():
                t.set_color(SILVER)
