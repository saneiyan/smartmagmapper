"""SmartMagMapper: the main window and the application launcher.

Run `python GUI.py` from the src folder, optionally followed by a survey or project file to open. The main window builds the window
and its tabs; tab and action logic comes from the mixin modules in ui/, and data processing lives in processing/.
"""
import sys, os
import traceback
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (QApplication, QMessageBox, QLabel, QMainWindow, QStatusBar, QWidget, QProgressBar,
                            QVBoxLayout, QHBoxLayout, QComboBox, QTabWidget, QSplashScreen)
from ui.survey_actions import SurveyActionsMixin
from ui.analysis_tab import AnalysisTabMixin
from ui.location_tab import LocationTabMixin
from ui.exports import ExportsMixin


frozen = 'not'
if getattr(sys, 'frozen', False):
        # we are running in a bundle
        frozen = 'ever so'
        bundle_dir = sys._MEIPASS
else:
        # we are running in a normal Python environment
        bundle_dir = os.path.dirname(os.path.abspath(__file__))

class MainWindow(SurveyActionsMixin, AnalysisTabMixin, LocationTabMixin, ExportsMixin, QMainWindow):
    """Main window: builds the window and its tabs; the tab and action logic comes from the mixins.

    Parameters
    ----------
    parent : QWidget, optional
        Parent widget.
    """
    def __init__(self, parent=None):
        """Build the window, then the per-survey state and the menus (ProjectTools).

        Parameters
        ----------
        parent : QWidget, optional
            Parent widget.
        """
        super(MainWindow, self).__init__(parent)
        self.initUI()
        self.sessions = []
        self.active_dataset_index = None
        #filters applied to the current field, in order, for plot titles
        self.active_filters = []
        self.project_tools=ProjectTools(self)

    def closeEvent(self,event):
        """Ask before closing: Save / Discard / Cancel with unsaved work, otherwise a plain exit confirmation.

        Parameters
        ----------
        event : QCloseEvent
            Accepted to close the window, ignored to keep it open.
        """
        tools=getattr(self,'project_tools',None)
        if tools is not None and not tools.loading:
            # With unsaved work, Save / Discard / Cancel doubles as the exit confirmation (no second pop-up).
            if tools.dirty:
                if not tools.confirm_replace('exiting'):
                    event.ignore();return
            elif not confirm(self,'Exit SmartMagMapper','Are you sure you would like to exit SmartMagMapper?',yes_text='Exit',no_text='Cancel'):
                event.ignore();return
        event.accept()

    def initUI(self):
        #sets the window title
        """Build the active-survey header and the four tabs (Data & Cleaning, Filter Lab, Automated Anomaly
        Analysis, Location Estimate) with their plain-language tooltips.
        """
        self.setWindowTitle('SmartMagMapper | Project workspace')
        #set tabs
        self.tabs = QTabWidget()
        #creating a status bar
        self.setStatusBar(QStatusBar(self))
        self.analysis_selected_dataset_index = None
        self.analysis_clean_df = None
        self.analysis_annotated_df = None
        self.analysis_modes = None
        self.analysis_mode_metrics = None
        self.analysis_selected_modes = []
        self.analysis_clusters = None
        self.analysis_audit = {}
        self.analysis_summary_data = {}
        self.analysis_update_timer = QTimer(self)
        self.analysis_update_timer.setSingleShot(True)
        self.analysis_update_timer.timeout.connect(self.run_anomaly_analysis)

        self.select_file = QComboBox()
        self.select_file.setPlaceholderText('Import a survey to begin')
        self.select_file.currentIndexChanged.connect(self.select_display_file)

        #active-survey header above the tabs
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.shared_survey_widget = QWidget()
        shared_layout = QHBoxLayout(self.shared_survey_widget)
        shared_layout.setContentsMargins(8, 4, 8, 4)
        shared_layout.addWidget(QLabel('Active survey:'))
        shared_layout.addWidget(self.select_file, 1)
        self.shared_field_label = QLabel('Map field: no survey')
        self.shared_field_label.setWordWrap(True)
        self.shared_field_label.setMaximumWidth(620)
        shared_layout.addWidget(self.shared_field_label)
        main_layout.addWidget(self.shared_survey_widget)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.data_workspace = DataWorkspace(self)
        data_index = self.tabs.addTab(self.data_workspace, 'Data && Cleaning')
        self.tabs.setTabToolTip(data_index,
            'Check and clean your survey before analysing it.\n\n'
            'Cleaning matches each magnetic reading to a GPS position, removes unsteady readings at the start\n'
            '(for example while the GPS settles or the sensor warms up) and drops positions caused by GPS jumps.\n'
            'The cleaning settings are suggested from your own survey; change them and click Update Cleaning Settings.\n\n'
            '\u2022 Cleaning Maps: map the survey before or after cleaning (scatter, contour or satellite web map);\n'
            '   removed readings are marked with a red \u2715.\n'
            '\u2022 Data Tables: the raw magnetometer and GPS files, the matched (synchronized) data and the cleaned data.\n'
            '\u2022 Signal Plots: any data column plotted against time.')
        self.filters_workspace = FilterWorkspace(self.active_session, self.commit_filter_result, self.reset_map, self)
        filter_index = self.tabs.addTab(self.filters_workspace, 'Filter Lab')
        self.tabs.setTabToolTip(filter_index,
            'Try filters on the magnetic data and compare them before choosing one.\n\n'
            '\u2022 Filters along the survey path smooth the signal or separate slow and fast changes\n'
            '   (low-, high- and band-pass, moving average, Savitzky\u2013Golay, linear detrend, VMD).\n'
            '\u2022 Map filters treat the survey as a grid (upward / downward continuation, reduction to pole).\n\n'
            'Apply Filter shows the effect (Before / After / Difference, Spectrum) and uses the result for anomaly analysis.\n'
            'Store several results to compare them side by side in Compare Filters.\n'
            'Reset (Clear Filter) returns to the cleaned data.')
        self.analysis_widget = self.create_analysis_tab()
        analysis_index = self.tabs.addTab(self.analysis_widget, 'Automated Anomaly Analysis')
        # Plain-language reference summary of the methods used in the four main tab groups.
        self.tabs.setTabToolTip(analysis_index,
            'Finds unusual magnetic signals (anomalies) automatically from your survey data, with no training data needed.\n\n'
            '1. VMD (variational mode decomposition) splits the magnetic signal into bands, from slow background changes\n'
            '    to fast noise, and keeps the bands that look like anomalies.\n'
            '2. Each short section of the survey path is scored by how strongly it stands out from the rest of the survey\n'
            '    (robust statistics: median and MAD).\n'
            '3. Sections that score above a threshold are grouped by location (DBSCAN clustering) to find candidate sources.\n'
            '4. GeoXAI explains why the top candidate was chosen.\n\n'
            'The settings panel on this tab lets you adjust the window length, threshold and clustering.')
        location_index = self.tabs.addTab(self.create_location_tab(), 'Location Estimate')
        self.tabs.setTabToolTip(location_index,
            'See where the most likely source of the anomaly is.\n\n'
            'Shows the candidate location found by Automated Anomaly Analysis, with its uncertainty radius,\n'
            'the other groups of high-scoring readings and your reference location (if you entered one),\n'
            'as a scatter, contour or satellite web map. The panel on the right lists the numbers behind the estimate,\n'
            'and Export location results saves them.\n\n'
            'A candidate is a place to check in the field, not a confirmed find.')
        main_layout.addWidget(self.tabs)
        self.setCentralWidget(central_widget)
        self.setMinimumSize(1200, 760)
        self.resize(1500, 940)
        # self.apply_scientific_style() # commenting for now until we figure out the dark theme

    def apply_scientific_style(self): # Sina: We need to find the right dark mode
        """Apply the application-wide light colour theme (Qt style sheet)."""
        self.setStyleSheet("""
            QMainWindow, QWidget { font-family: 'Segoe UI'; font-size: 10pt; color: #172b4d; background: #f4f7fb; }
            QToolBar { background: #15324f; padding: 8px; spacing: 14px; border: 0; }
            QToolButton { color: white; background: #15324f; padding: 7px 12px; }
            QToolButton:hover { background: #245273; }
            QMenuBar { background: #e7edf4; }
            QMenu { background: white; }
            QMenu::item { padding: 8px 48px 8px 16px; }
            QMenu::item:selected { background: #d3e3ef; }
            QMenu::item:disabled { color: #718096; }
            QTabWidget::pane { border: 1px solid #d7e0ea; background: white; }
            QTabBar::tab { background: #e7edf4; color: #334b63; padding: 11px 17px; border: 0; margin-right: 3px; }
            QTabBar::tab:selected { background: #cbddeb; font-weight: 600; color: #006d77; border-bottom: 3px solid #008d91; }
            QGroupBox { background: white; border: 1px solid #d7e0ea; border-radius: 6px; margin-top: 14px; padding: 12px 8px 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #15324f; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit { background: white; color: #172b4d; border: 1px solid #c8d5e2; border-radius: 4px; padding: 5px; }
            QLineEdit:disabled, QComboBox:disabled, QTextEdit:disabled { color: #8793a3; background: #eef1f5; border: 1px solid #dde4ec; }
            QComboBox QAbstractItemView { background: white; color: #172b4d; selection-background-color: #d4efed; }
            QPushButton { background: #e8f1f6; border: 1px solid #bfd1df; border-radius: 4px; padding: 9px; color: #15324f; }
            QPushButton:pressed, QPushButton:checked { background:#b5ccdf; border:1px solid #54799a; color:#102b46; }
            QPushButton#primaryButton:pressed { background:#005d63; }
            QPushButton:checked:hover { background:#a4bfd6; border:1px solid #54799a; }
            QPushButton:hover { background: #d7e9ed; }
            QPushButton:disabled { background: #edf0f4; color: #8896a5; }
            QPushButton#primaryButton { background: #007f86; color: white; }
            QPushButton#primaryButton:disabled { background: #edf0f4; color: #8896a5; border: 1px solid #d3dce6; }
            QLabel#sectionTitle { font-size: 18pt; font-weight: 700; color: #15324f; padding: 4px; }
            QTableView, QTableWidget { background: white; alternate-background-color: #f1f6fa; gridline-color: #dce4ec; }
            QHeaderView::section { background: #e7edf4; padding: 7px; border: 0; color: #15324f; }
            QStatusBar { background: #e7edf4; }
            QScrollArea { border: 0; }
            QAbstractSpinBox { padding-right: 22px; }
            QAbstractSpinBox:disabled { color: #8793a3; background: #eef1f5; }
            QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { width: 19px; }
        """)

    def active_session(self):
        """Survey shown in the window.

        Returns
        -------
        processing.survey_session.SurveySession or None
            The active survey, or None when no survey is loaded.
        """
        index = getattr(self, 'active_dataset_index', None)
        if index is None or not 0 <= index < len(getattr(self, 'sessions', [])):
            return None
        return self.sessions[index]


def errorMessage(etype, value, tb):
    """Show an uncaught exception in a dialog (installed as sys.excepthook) instead of closing the app.

    Parameters
    ----------
    etype : type
        Exception class.
    value : BaseException
        The exception.
    tb : traceback
        Its traceback, shown under Show Details.
    """
    print('ERROR begin:')
    traceback.print_exception(etype, value, tb)
    print('ERROR end.')
    finalError = ''.join(traceback.format_exception(etype, value, tb, limit=None, chain=True))
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Icon.Critical)
    msg.setText("<b>Critical error:</b>")
    msg.setInformativeText('Please see the detailed error below:')
    msg.setWindowTitle("Error!")
    msg.setDetailedText(finalError)
    msg.setStandardButtons(QMessageBox.StandardButton.Retry)
    msg.exec()


def catchErrors():
    """Install errorMessage as the handler for uncaught exceptions."""
    sys.excepthook = errorMessage


if __name__ == '__main__':
    catchErrors() # prevent crash of the app
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setWindowIcon(QIcon(os.path.join(bundle_dir, 'imgs/logo_s.png')))

    splash_pix = QPixmap(os.path.join(bundle_dir, 'imgs/logo_s.png'))
    splash = QSplashScreen(splash_pix, Qt.WindowType.WindowStaysOnTopHint)
    splash.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    splash.setEnabled(False)

    # adding progress bar
    progressBar = QProgressBar(splash)
    progressBar.setMaximum(10)
    progressBar.setGeometry(100, splash_pix.height() - 50, splash_pix.width() - 200, 20)
    splash.show()
    splash.showMessage("Loading libraries", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
    app.processEvents()
    progressBar.setValue(1)
    app.processEvents()
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas  # noqa: F401  (preloaded while the splash shows)
    progressBar.setValue(2)
    app.processEvents()
    from matplotlib.figure import Figure  # noqa: F401  (preloaded while the splash shows)
    progressBar.setValue(3)
    app.processEvents()
    from ui.project_tools import ProjectTools
    progressBar.setValue(4)
    app.processEvents()
    from ui.filter_workspace import FilterWorkspace
    from ui.data_workspace import DataWorkspace
    progressBar.setValue(5)
    app.processEvents()
    from ui.confirm import confirm
    progressBar.setValue(6)
    app.processEvents()
    progressBar.setValue(7)
    app.processEvents()
    from ui.theme import apply_matplotlib_theme
    apply_matplotlib_theme()
    from processing.data_analysis_pipeline import SmartMagMapper_version
    progressBar.setValue(8)
    app.processEvents()
    app.setApplicationName('SmartMagMapper')
    app.setApplicationVersion(SmartMagMapper_version)
    app.setApplicationDisplayName('SmartMagMapper') 
    progressBar.setValue(9)
    app.processEvents()

    window = MainWindow()
    window.setWindowTitle(f"{app.applicationName()} v{app.applicationVersion()}")
    window.show()
    if len(sys.argv) > 1:
        startup_file = sys.argv[1]
        if Path(startup_file).suffix.lower() in ('.smmproj','.bak1','.bak2','.bak3'):
            QTimer.singleShot(250, lambda: window.project_tools.open_project(path=Path(startup_file)))
        else:QTimer.singleShot(250, lambda: window.load_survey_file(startup_file))

    splash.showMessage("SmartMagMapper is ready!", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
    progressBar.setValue(10)
    app.processEvents()
    splash.hide() # hiding the splash screen when finished
    sys.exit(app.exec())
