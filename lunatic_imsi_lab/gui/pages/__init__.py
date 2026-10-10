from lunatic_imsi_lab.gui.pages.accounts import AccountsPage
from lunatic_imsi_lab.gui.pages.anomalies import AnomaliesPage
from lunatic_imsi_lab.gui.pages.cells import CellsPage
from lunatic_imsi_lab.gui.pages.console import ConsolePage
from lunatic_imsi_lab.gui.pages.dashboard import DashboardPage
from lunatic_imsi_lab.gui.pages.devices import DevicesPage
from lunatic_imsi_lab.gui.pages.mapview import MapPage
from lunatic_imsi_lab.gui.pages.reports import ReportsPage
from lunatic_imsi_lab.gui.pages.rules import RulesPage
from lunatic_imsi_lab.gui.pages.simulation import SimulationPage
from lunatic_imsi_lab.gui.pages.spectrum import SpectrumPage
from lunatic_imsi_lab.gui.pages.timeline import TimelinePage

ALL_PAGES = [DashboardPage, SpectrumPage, CellsPage, AnomaliesPage, TimelinePage, MapPage,
             SimulationPage, ConsolePage, ReportsPage, RulesPage, DevicesPage, AccountsPage]
