"""SmartMagMapper: the main window and the application launcher.

Run `python GUI.py`, optionally followed by a survey or project file to open. The main window builds the window
and its tabs; tab and action logic comes from the mixin modules in ui/, and data processing lives in processing/.
"""
import sys
import threading
import traceback
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QMessageBox, QLabel, QMainWindow, QStatusBar, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QComboBox, QTabWidget
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from ui.project_tools import ProjectTools
from ui.filter_workspace import FilterWorkspace
from ui.data_workspace import DataWorkspace
from ui.confirm import confirm
from ui.map_field import MAP_VIEWS, TOTAL_FIELD, RESIDUAL_TREND, RESIDUAL_IGRF, FIELD_CHOICES
from ui.survey_actions import SurveyActionsMixin
from ui.analysis_tab import AnalysisTabMixin
from ui.location_tab import LocationTabMixin
from ui.map_field import MapFieldMixin
from ui.exports import ExportsMixin


class MainWindow(SurveyActionsMixin, AnalysisTabMixin, LocationTabMixin, MapFieldMixin, ExportsMixin, QMainWindow):
    """Main window: builds the window and its tabs; the tab and action logic comes from the mixins."""
    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)
        self.initUI()
        self.sessions = []
        #Caches imported datasets into a list
        self.df_list = list()
        #Cache for processed dataframes
        self.processed_dfs = {}
        #Cache for dialog config per file index
        self.dialog_configs = {}
        #Cache for magdf/gpsdf per file index
        self.mag_gps_dfs = {}
        self.active_dataset_index = None
        self.current_df = None
        #min and max magnetic field measurements within the dataset
        self.vmin = self.vmax = None
        self.df = None
        #df_list index of the dataset shown on the map
        self._analysis_mode_key = None
        #filters applied to the mapped data, in order, for plot titles
        self.active_filters = []
        #color scale for the spatial maps
        self.map_vmin = None
        self.map_vmax = None
        #year, month, day used for the IGRF residual
        self.residual_date = None
        #source df, settings, residual df so redraws don't recompute each time
        self.residual_cache = None
        self.project_tools=ProjectTools(self)

    def closeEvent(self,event):
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
        self.setWindowTitle('SmartMagMapper | Project workspace')
        #set function to 'bold' labels
        bold = QFont()
        bold.setBold(True)
        #set tabs
        self.tabs = QTabWidget()
        #creates a figure and axes
        self.figure = Figure()
        self.axes = self.figure.add_subplot()
        #creates a canvas to display figure
        self.canvas = FigureCanvas(self.figure)
        #creating a status bar
        self.setStatusBar(QStatusBar(self))
        self.analysis_file_path = None
        self.analysis_selected_dataset = None
        self.analysis_selected_dataset_index = None
        self.analysis_clean_df = None
        self.analysis_annotated_df = None
        self.analysis_modes = None
        self.analysis_mode_metrics = None
        self.analysis_selected_modes = []
        self.analysis_score_points = None
        self.analysis_clusters = None
        self.analysis_audit = {}
        self.analysis_summary_data = {}
        self.analysis_update_timer = QTimer(self)
        self.analysis_update_timer.setSingleShot(True)
        self.analysis_update_timer.timeout.connect(self.run_anomaly_analysis)
        self.analysis_reload_timer = QTimer(self)
        self.analysis_reload_timer.setSingleShot(True)
        self.analysis_reload_timer.timeout.connect(self.reload_active_survey)
        #add text boxes for changing the vmin and vmax
        self.change_label = QLabel('Edit Map Scale')
        self.change_label.setFont(bold)
        self.vmax_label = QLabel('Maximum BT (µT):')
        #self.vmax_label.setFont(bold)
        self.set_vmax = QLineEdit()
        self.set_vmax.setPlaceholderText('Max BT (µT) (e.g. "50")')
        self.set_vmax.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.vmin_label = QLabel('Minimum BT (µT):')
        #self.vmin_label.setFont(bold)
        self.set_vmin = QLineEdit()
        self.set_vmin.setPlaceholderText('Min BT (µT) (e.g. "35")')
        self.set_vmin.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.date = QLabel('Survey Date')
        self.date.setFont(bold)
        self.year_label = QLabel('Year:')
        self.year = QLineEdit()
        self.year.setPlaceholderText('Year')
        self.year.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.month_label = QLabel('Month:')
        self.month = QLineEdit()
        self.month.setPlaceholderText('Month')
        self.month.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.day_label = QLabel('Day:')
        self.day = QLineEdit()
        self.day.setPlaceholderText('Day')
        self.day.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.continuation_label = QLabel('Continuation Height (UC/DC Filters):')
        self.continuation_label.setFont(bold)
        self.set_continuation_height = QLineEdit()
        self.set_continuation_height.setPlaceholderText('Height (meters) (e.g. "5")')
        self.set_continuation_height.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.select_file = QComboBox()
        self.select_file.setPlaceholderText('Import a survey to begin')
        self.select_file.currentIndexChanged.connect(self.select_display_file)

        #one dropdown for how the map is shown
        self.map_view_label = QLabel('Map View:')
        self.map_view_type = QComboBox()
        self.map_view_type.addItems(MAP_VIEWS)
        self.map_view_type.currentIndexChanged.connect(self.map_view_changed)

        #total field or residual (Earth's background field removed), shown in any map view
        self.field_label = QLabel('Field:')
        self.residual_method = QComboBox()
        self.residual_method.addItems(FIELD_CHOICES)
        self.residual_method.setItemData(FIELD_CHOICES.index(TOTAL_FIELD), 'Measured total field',
                                         Qt.ItemDataRole.ToolTipRole)
        self.residual_method.setItemData(FIELD_CHOICES.index(RESIDUAL_TREND),
                                         'Subtract a plane fitted to the survey itself (no date needed)',
                                         Qt.ItemDataRole.ToolTipRole)
        self.residual_method.setItemData(FIELD_CHOICES.index(RESIDUAL_IGRF),
                                         'Subtract the IGRF model field for the survey date (uses the Survey Date boxes)',
                                         Qt.ItemDataRole.ToolTipRole)
        self.residual_method.currentIndexChanged.connect(self.residual_changed)
        for date_field in (self.year, self.month, self.day):
            date_field.editingFinished.connect(self.residual_date_changed)

        self.plot = Figure()
        self.plot_axes = self.plot.add_subplot()
        self.chart = FigureCanvas(self.plot)

        #creating the map layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.global_controls_widget = QWidget()
        global_controls_layout = QVBoxLayout()
        global_controls_layout.setContentsMargins(0, 0, 0, 0)
        global_controls_layout.setSpacing(4)
        self.map_layout = QVBoxLayout()
        button_layout = QHBoxLayout()
        button_layout_2 = QHBoxLayout()
        #assigning a widget to the layout
        button_layout.addWidget(self.change_label)
        button_layout.addWidget(self.vmin_label)
        button_layout.addWidget(self.set_vmin)
        button_layout.addWidget(self.vmax_label)
        button_layout.addWidget(self.set_vmax)
        button_layout.addWidget(self.continuation_label)
        button_layout.addWidget(self.set_continuation_height)
        global_controls_layout.addLayout(button_layout)
        button_layout_2.addWidget(self.date)
        button_layout_2.addWidget(self.year_label)
        button_layout_2.addWidget(self.year)
        button_layout_2.addWidget(self.month_label)
        button_layout_2.addWidget(self.month)
        button_layout_2.addWidget(self.day_label)
        button_layout_2.addWidget(self.day)
        button_layout_2.addWidget(self.map_view_label)
        button_layout_2.addWidget(self.map_view_type)
        button_layout_2.addWidget(self.field_label)
        button_layout_2.addWidget(self.residual_method)
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
        global_controls_layout.addLayout(button_layout_2)
        self.global_controls_widget.setLayout(global_controls_layout)
        main_layout.addWidget(self.global_controls_widget)
        self.map_layout.addWidget(self.canvas)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        # Table is hosted in the data workspace
        map_widget = QWidget()
        #Keep the export canvas alive outside the main tabs
        self.original_map_widget = map_widget
        map_widget.setLayout(self.map_layout)
        # Original map retained for exports and legacy plot actions
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
            'Preview Filter shows the effect (Before / After / Difference, Spectrum); your data only changes when you click\n'
            'Store filter result for anomaly analysis. Store several previews to compare them side by side in Compare Filters.\n'
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
        self.tabs.currentChanged.connect(self.update_global_controls_visibility)
        main_layout.addWidget(self.tabs)
        self.setCentralWidget(central_widget)
        self.setMinimumSize(1200, 760)
        self.resize(1500, 940)
        # self.apply_scientific_style() # commenting for now until we figure out the dark theme
        self.global_controls_widget.hide()

    def update_global_controls_visibility(self,index):
        #Each workspace owns its controls. The active-survey header is always visible
        self.global_controls_widget.hide()
        self.shared_survey_widget.show()

    def apply_scientific_style(self): # Sina: We need to find the right dark mode 
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
        # Replace the earlier dark per-page rules with the application-wide scientific theme.
        self.analysis_widget.setStyleSheet('')

    def active_session(self):
        index = getattr(self, 'active_dataset_index', None)
        if index is None or not 0 <= index < len(getattr(self, 'sessions', [])):
            return None
        return self.sessions[index]

    #def sampling frequency
    #   add ability to set sampling frequency and adjust the filters class so it's not static at d=1

    #def rewind action
    #   allows users to go back one step


#%% General crash ERROR

def errorMessage(etype, value, tb):
    print('ERROR begin:')
    traceback.print_exception(etype, value, tb)
    print('ERROR end.')
    errorMsg = traceback.format_exception(etype, value, tb,limit=None, chain=True)
    finalError =''
    for errs in errorMsg:
        finalError += errs
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Icon.Critical)
    msg.setText("<b>Critical error:</b>")
    msg.setInformativeText('''Please see the detailed error below:''')
    msg.setWindowTitle("Error!")
    msg.setDetailedText('%s' % (finalError))
    msg.setStandardButtons(QMessageBox.StandardButton.Retry)
    msg.exec()

def catchErrors():
    sys.excepthook = errorMessage
    threading.Thread.__init__

#%% Executing app
if __name__ == '__main__':
    catchErrors() # prevent crash of the app
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    from ui.theme import apply_matplotlib_theme
    apply_matplotlib_theme()
    from processing.data_analysis_pipeline import SmartMagMapper_version
    app.setApplicationName('SmartMagMapper')
    app.setApplicationVersion(SmartMagMapper_version)
    app.setApplicationDisplayName('SmartMagMapper') 
    window = MainWindow()
    window.setWindowTitle(f"{app.applicationName()} v{app.applicationVersion()}")
    window.show()
    if len(sys.argv) > 1:
        startup_file = sys.argv[1]
        if Path(startup_file).suffix.lower() in ('.smmproj','.bak1','.bak2','.bak3'):
            QTimer.singleShot(250, lambda: window.project_tools.open_project(path=Path(startup_file)))
        else:QTimer.singleShot(250, lambda: window.load_survey_file(startup_file))
    sys.exit(app.exec())
