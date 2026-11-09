from PyQt6.QtCore import QSize, Qt, QTimer, QSortFilterProxyModel, QUrl
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QFont
from PyQt6.QtWidgets import (QApplication, QCheckBox, QLabel, QMainWindow,
                             QStatusBar, QToolBar, QWidget, QPushButton,
                             QVBoxLayout, QHBoxLayout, QFileDialog, QTableWidget,
                             QTableWidgetItem, QLineEdit, QMessageBox,
                             QRadioButton, QComboBox, QTabWidget, QTableView,
                             QHeaderView, QStackedLayout, QGroupBox,
                             QFormLayout, QDoubleSpinBox, QSpinBox, QTextEdit,
                             QSplitter, QScrollArea, QStyleFactory)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT
from matplotlib.figure import Figure
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import folium
import branca.colormap as cm
from pathlib import Path
from SurveySession import SurveySession
from ProjectTools import ProjectTools
from PlotTheme import compact_toolbar
from FilterWorkspace import FilterWorkspace
from DataWorkspace import DataWorkspace
from VMDPanel import VMDPanel
import MapFilter as mf
import MapMaker as mm
import DialogWindow as dw
import WebMap as wm
import TableModel
import OrphanWellPipeline as ow
import GeoXAIInterpreter as gx
from Busy import busy
import sys, os, tempfile, json

#choices in the Map View dropdown
POINT_MAP = 'Point Map'
CONTOUR_MAP = 'Contour Map'
WEB_MAP = 'Web Map'
MAP_VIEWS = [POINT_MAP, CONTOUR_MAP, WEB_MAP]

#choices in the Field dropdown, which works with any map view
TOTAL_FIELD = 'Total BT'
RESIDUAL_TREND = 'Residual BT (fitted trend - average)'
RESIDUAL_IGRF = 'Residual BT (IGRF model - absolute)'
FIELD_CHOICES = [TOTAL_FIELD, RESIDUAL_TREND, RESIDUAL_IGRF]

#labels added to plot titles and the web map legend when the Residual Map is on
RESIDUAL_LABELS = {'trend': 'Residual BT (fitted trend - average)', 'igrf': 'Residual BT (IGRF - absolute)'}
#filters whose output is already centered on zero, so the IGRF field must not be subtracted again
IGRF_INCOMPATIBLE_FILTERS = ('Reduction to Pole', 'VMD')
IGRF_SKIPPED_MESSAGE = 'IGRF residual not applied: RTP and VMD results already have the background removed. Use Fitted trend instead.'

#%% General crash ERROR
import threading
import traceback

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

#%% Main app

class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)
        self.initUI()
        self.sessions = []
        self.df_list = list()
        self.processed_dfs = {}  # Cache for processed dataframes
        self.dialog_configs = {}  # Cache for dialog config per file index
        self.mag_gps_dfs = {}  # Cache for magdf/gpsdf per file index
        self.active_dataset_index = None
        self.current_df = None
        self.vmin = self.vmax = None
        self.df = None
        self._analysis_mode_key = None  # df_list index of the dataset shown on the map
        self.active_filters = []  # filters applied to the mapped data, in order, for plot titles
        self.map_vmin = None  # color scale on the regular map, shared with the web map
        self.map_vmax = None
        self.residual_date = None  # (year, month, day) used for the IGRF residual
        self.residual_cache = None  # (source df, settings, residual df) so redraws don't recompute
        self.project_tools=ProjectTools(self)

    def closeEvent(self,event):
        if hasattr(self,'project_tools') and not self.project_tools.loading and not self.project_tools.confirm_replace():
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
        #self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        #creates a figure and axes
        #self.figure, self.ax = plt.subplots()
        self.figure = Figure()
        self.axes = self.figure.add_subplot()
        #creates a canvas to display figure
        self.canvas = FigureCanvas(self.figure)
        #the menu bar is built by ProjectTools.build_menus
        #creating a status bar
        self.setStatusBar(QStatusBar(self))
        self.ow_file_path = None
        self.ow_selected_dataset = None
        self.ow_selected_dataset_index = None
        self.ow_clean_df = None
        self.ow_annotated_df = None
        self.ow_modes = None
        self.ow_mode_metrics = None
        self.ow_selected_modes = []
        self.ow_score_points = None
        self.ow_clusters = None
        self.ow_audit = {}
        self.ow_summary_data = {}
        self.ow_update_timer = QTimer(self)
        self.ow_update_timer.setSingleShot(True)
        self.ow_update_timer.timeout.connect(self.run_orphan_analysis)
        self.ow_reload_timer = QTimer(self)
        self.ow_reload_timer.setSingleShot(True)
        self.ow_reload_timer.timeout.connect(self.reload_orphan_well_file)
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
        #self.select_file.setAlignment(Qt.AlignmentFlag.AlignRight)

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

        self.data = QTableView()
        # self.proxyModel = QSortFilterProxyModel()
        # self.proxyModel.setSourceModel(self.data.model())
        # self.data.setSortingEnabled(True)
        # self.data.setModel(self.proxyModel)

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

        # #creating the plot layout
         # self.plot_layout = QVBoxLayout()
         # self.plot_layout.addWidget(self.chart)

        #creating the data table layour
        #table_layout = QVBoxLayout()
        #table_layout.addWidget(self.data)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        # Table is hosted in the data workspace.
        map_widget = QWidget()
        self.original_map_widget = map_widget  # Keep the export canvas alive outside the main tabs.
        map_widget.setLayout(self.map_layout)
        # Original map retained for exports and legacy plot actions.
        #table_widget = QWidget()
        #table_widget.setLayout(table_layout)
        self.plot_tabs = QTabWidget()
        self.plot_tabs.setTabsClosable(True)
        self.plot_tabs.tabCloseRequested.connect(self.close_signal_plot)
        self.plot_widget = QWidget()
        #creating the plot layout
        self.plot_layout = QVBoxLayout()
        self.plot_layout.addWidget(self.plot_tabs)
        #plot_layout.addWidget(self.chart)
        self.plot_widget.setLayout(self.plot_layout)
        self.data_workspace = DataWorkspace(self)
        self.tabs.addTab(self.data_workspace, 'Data && Cleaning')
        self.filters_workspace = FilterWorkspace(self.active_session, self.commit_filter_result, self.reset_map, self)
        self.tabs.addTab(self.filters_workspace, 'Filter Lab')
        self.orphan_well_widget = self.create_orphan_well_tab()
        self.tabs.addTab(self.orphan_well_widget, 'Anomaly Analysis')
        self.tabs.addTab(self.create_location_tab(), 'Location Estimate')
        self.data_workspace.bind_controls()
        self.tabs.currentChanged.connect(self.update_global_controls_visibility)
        main_layout.addWidget(self.tabs)
        self.setCentralWidget(central_widget)
        #self.setCentralWidget(central_widget)
        self.setMinimumSize(1200, 760)
        self.resize(1500, 940)
        self.apply_scientific_style()
        self.global_controls_widget.hide()

    def update_global_controls_visibility(self,index):
        # Each workspace owns its controls. The active-survey header is always visible.
        self.global_controls_widget.hide()
        self.shared_survey_widget.show()


    def create_orphan_well_tab(self):
        widget = QWidget()
        widget.setObjectName('orphanWellPage')
        root_layout = QVBoxLayout(widget)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)
        widget.setStyleSheet("""
            QWidget#orphanWellPage {
                background: #111827;
                color: #E5E7EB;
            }
            QWidget#orphanWellPage QGroupBox {
                border: 1px solid #374151;
                border-radius: 6px;
                margin-top: 14px;
                padding: 10px;
                font-weight: 600;
            }
            QWidget#orphanWellPage QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QWidget#orphanWellPage QPushButton {
                min-height: 30px;
                border: 1px solid #4B5563;
                border-radius: 5px;
                background: #1F2937;
                color: #F9FAFB;
            }
            QWidget#orphanWellPage QPushButton:hover {
                background: #263244;
                border-color: #64748B;
            }
            QWidget#orphanWellPage QComboBox {
                background: #1F2937;
                color: #F9FAFB;
                border: 1px solid #4B5563;
                border-radius: 5px;
                min-height: 28px;
                padding: 4px;
            }
            QWidget#orphanWellPage QComboBox::drop-down {
                border: none;
            }
            QWidget#orphanWellPage QComboBox QAbstractItemView {
                background: #1F2937;
                color: #F9FAFB;
                selection-background-color: #4B5563;
            }
            QWidget#orphanWellPage QDoubleSpinBox,
            QWidget#orphanWellPage QSpinBox,
            QWidget#orphanWellPage QTextEdit {
                background: #1F2937;
                color: #F9FAFB;
                border: 1px solid #4B5563;
                border-radius: 5px;
                min-height: 28px;
            }
            QWidget#orphanWellPage QTabWidget::pane {
                border: 1px solid #374151;
                border-radius: 6px;
                background: #0F172A;
            }
            QWidget#orphanWellPage QTabBar::tab {
                background: #1F2937;
                color: #D1D5DB;
                padding: 8px 14px;
                border: 1px solid #374151;
                border-bottom: none;
                min-width: 96px;
            }
            QWidget#orphanWellPage QTabBar::tab:selected {
                background: #F9FAFB;
                color: #111827;
            }
            QWidget#orphanWellPage QScrollArea {
                border: none;
                background: #111827;
            }
        """)

        controls = QGroupBox('Workflow and parameters')
        controls_layout = QVBoxLayout()

        self.ow_dataset_label = QLabel('Active survey: none')
        self.ow_dataset_label.setWordWrap(True)
        controls_layout.addWidget(self.ow_dataset_label)
        self.ow_input = QComboBox()
        self.ow_input.addItems(['Cleaned total field', 'Current filter result'])
        self.ow_input.setToolTip('Use the shared cleaned baseline, or explicitly analyze the field currently shown on the map.')
        self.ow_input.currentIndexChanged.connect(self.process_orphan_well_dataset)
        controls_layout.addWidget(QLabel('Analyze:'))
        controls_layout.addWidget(self.ow_input)
        self.ow_input_label = QLabel('Analysis input: no survey')
        self.ow_input_label.setWordWrap(True)
        controls_layout.addWidget(self.ow_input_label)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.ow_startup_samples = QSpinBox()
        self.ow_startup_samples.setRange(0, 500)
        self.ow_startup_samples.setValue(10)

        self.ow_spatial_mad = QDoubleSpinBox()
        self.ow_spatial_mad.setRange(0.5, 25.0)
        self.ow_spatial_mad.setDecimals(1)
        self.ow_spatial_mad.setSingleStep(0.5)
        self.ow_spatial_mad.setValue(6.0)

        self.ow_window_length = QDoubleSpinBox()
        self.ow_window_length.setRange(1.0, 50.0)
        self.ow_window_length.setDecimals(1)
        self.ow_window_length.setSingleStep(1.0)
        self.ow_window_length.setValue(5.0)

        self.ow_step_ratio = QDoubleSpinBox()
        self.ow_step_ratio.setRange(0.05, 1.0)
        self.ow_step_ratio.setDecimals(2)
        self.ow_step_ratio.setSingleStep(0.05)
        self.ow_step_ratio.setValue(0.25)

        self.ow_gamma = QDoubleSpinBox()
        self.ow_gamma.setRange(0.5, 10.0)
        self.ow_gamma.setDecimals(1)
        self.ow_gamma.setSingleStep(0.5)
        self.ow_gamma.setValue(2.0)

        self.ow_dbscan_eps = QDoubleSpinBox()
        self.ow_dbscan_eps.setRange(0.5, 30.0)
        self.ow_dbscan_eps.setDecimals(1)
        self.ow_dbscan_eps.setSingleStep(0.5)
        self.ow_dbscan_eps.setValue(4.0)

        self.ow_min_samples = QSpinBox()
        self.ow_min_samples.setRange(1, 100)
        self.ow_min_samples.setValue(5)

        #optional known well location, left blank when the well location is unknown
        self.ow_well_lat = QLineEdit()
        self.ow_well_lat.setPlaceholderText('Optional latitude in degrees')
        self.ow_well_lon = QLineEdit()
        self.ow_well_lon.setPlaceholderText('Optional longitude in degrees')
        for well_field in (self.ow_well_lat, self.ow_well_lon):
            well_field.setAlignment(Qt.AlignmentFlag.AlignRight)
            well_field.setClearButtonEnabled(True)

        form.addRow('Known well latitude', self.ow_well_lat)
        form.addRow('Known well longitude', self.ow_well_lon)
        # Cleaning controls live in Data & cleaning.
        self.ow_fallback_percentile = QDoubleSpinBox()
        self.ow_fallback_percentile.setRange(50,100)
        self.ow_fallback_percentile.setValue(95)
        self.ow_fallback_percentile.setSuffix(' %')
        self.ow_fallback_percentile.valueChanged.connect(self.cleaning_settings_edited)
        form.addRow('Score window length (m)', self.ow_window_length)
        form.addRow('Window step ratio', self.ow_step_ratio)
        form.addRow('Threshold gamma', self.ow_gamma)
        form.addRow('DBSCAN eps (m)', self.ow_dbscan_eps)
        form.addRow('DBSCAN min samples', self.ow_min_samples)

        button_column = QVBoxLayout()
        self.ow_apply_button = QPushButton('Update Results')
        self.ow_apply_button.clicked.connect(self.run_orphan_analysis)
        self.ow_export_button = QPushButton('Export Results')
        self.ow_export_button.clicked.connect(self.export_orphan_results)
        self.ow_export_button.setEnabled(False)
        for button in [
            self.ow_apply_button,
            self.ow_export_button,
        ]:
            button_column.addWidget(button)

        controls_layout.addLayout(form)
        controls_layout.addSpacing(8)
        controls_layout.addLayout(button_column)
        controls.setLayout(controls_layout)

        self.ow_summary = QTextEdit()
        self.ow_summary.setReadOnly(True)
        self.ow_summary.setMinimumHeight(180)
        self.ow_summary.setMaximumHeight(340)
        self.ow_summary.setText('Import a survey using File > Import Data. Inspect the result map, then follow the numbered stages for supporting evidence.')

        controls_panel = QWidget()
        controls_panel_layout = QVBoxLayout(controls_panel)
        controls_panel_layout.setContentsMargins(0, 0, 0, 0)
        controls_panel_layout.setSpacing(10)
        controls_panel_layout.addWidget(controls)
        # Detailed location summary lives in the final workspace.
        controls_panel_layout.addWidget(self.ow_summary)
        controls_panel_layout.addStretch()

        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setWidget(controls_panel)
        controls_scroll.setMinimumWidth(310)
        controls_scroll.setMaximumWidth(380)

        self.ow_visual_tabs = QTabWidget()
        self.ow_visual_tabs.setDocumentMode(True)

        self.ow_web_map = QWebEngineView()
        self.ow_web_map.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self.ow_web_map.setHtml(
            "<html><body style='margin:0;background:#0f172a;color:#e5e7eb;"
            "font-family:Segoe UI,Arial,sans-serif;display:flex;align-items:center;"
            "justify-content:center;height:100vh;'>Import a survey to draw the cluster map.</body></html>"
        )

        self.ow_cluster_figure = Figure(figsize=(8.5, 6.2), constrained_layout=True)
        self.ow_cluster_canvas = FigureCanvas(self.ow_cluster_figure)
        self.ow_cluster_canvas.setMinimumHeight(300)

        self.ow_score_figure = Figure(figsize=(8.5, 4.8), constrained_layout=True)
        self.ow_score_canvas = FigureCanvas(self.ow_score_figure)
        self.ow_score_canvas.setMinimumHeight(280)

        self.ow_field_figure = Figure(figsize=(8.5, 4.8), constrained_layout=True)
        self.ow_field_canvas = FigureCanvas(self.ow_field_figure)
        self.ow_field_canvas.setMinimumHeight(280)

        self.ow_vmd_panel = VMDPanel(editable=False)
        self.ow_modes_figure = Figure(figsize=(8.5, 4.8), constrained_layout=True)
        self.ow_modes_canvas = FigureCanvas(self.ow_modes_figure)
        self.ow_modes_canvas.setMinimumHeight(280)

        self.ow_geoxai_text = QTextEdit()
        self.ow_geoxai_text.setReadOnly(True)
        self.ow_geoxai_text.setMinimumHeight(230)
        self.ow_geoxai_text.setText('Import a survey to generate a GeoXAI candidate explanation.')
        self.ow_geoxai_figure = Figure(figsize=(8.5, 4.8), constrained_layout=True)
        self.ow_geoxai_canvas = FigureCanvas(self.ow_geoxai_figure)
        self.ow_geoxai_canvas.setMinimumHeight(280)

        self.ow_figure = self.ow_cluster_figure
        self.ow_canvas = self.ow_cluster_canvas

        def plot_page(canvas):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.addWidget(canvas)
            return page

        geoxai_page = QWidget()
        geoxai_layout = QVBoxLayout(geoxai_page)
        geoxai_layout.setContentsMargins(12, 12, 12, 12)
        geoxai_layout.setSpacing(10)
        geoxai_layout.addWidget(self.ow_geoxai_text)
        geoxai_layout.addWidget(self.ow_geoxai_canvas)

        self.ow_visual_tabs.addTab(self.ow_web_map, 'Web Map')
        self.ow_visual_tabs.addTab(plot_page(self.ow_cluster_canvas), 'Location Map')
        self.ow_visual_tabs.addTab(plot_page(self.ow_field_canvas), 'Magnetic Field')
        self.ow_visual_tabs.addTab(self.ow_vmd_panel, 'VMD Modes')
        self.ow_visual_tabs.addTab(plot_page(self.ow_score_canvas), 'Anomaly Scores')
        self.ow_visual_tabs.addTab(geoxai_page, 'Explainable AI (XAI)')
        for source,target in [(2,0),(3,1),(4,2),(4,3),(5,4)]:
            self.ow_visual_tabs.tabBar().moveTab(source,target)
        self.ow_visual_tabs.setCurrentIndex(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(controls_scroll)
        splitter.addWidget(self.ow_visual_tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([390, 1040])
        self.result_headline = QLabel('Import data to begin anomaly exploration.')
        self.result_headline.setObjectName('analysisMetrics')
        self.result_headline.setWordWrap(True)
        controls_layout.addWidget(self.result_headline)
        navigation = QHBoxLayout()
        self.previous_stage = QPushButton('Previous view')
        self.next_stage = QPushButton('Next stage')
        self.stage_label = QLabel();self.stage_label.hide()
        settings_toggle=QPushButton('Analysis settings');settings_toggle.setCheckable(True);settings_toggle.setChecked(True);settings_toggle.toggled.connect(controls_scroll.setVisible)
        navigation.addWidget(settings_toggle)
        navigation.addWidget(self.previous_stage); navigation.addWidget(self.stage_label,1); navigation.addWidget(self.next_stage)
        root_layout.addLayout(navigation)
        self.stage_order = list(range(6))
        self.previous_stage.clicked.connect(lambda: self.move_analysis_stage(-1))
        self.next_stage.clicked.connect(lambda: self.move_analysis_stage(1))
        self.ow_visual_tabs.currentChanged.connect(self.update_stage_navigation)
        self.update_stage_navigation()
        root_layout.addWidget(splitter)

        clean_widgets = [self.ow_startup_samples, self.ow_spatial_mad]
        analysis_widgets = [
            self.ow_window_length,
            self.ow_step_ratio,
            self.ow_gamma,
            self.ow_dbscan_eps,
            self.ow_min_samples,
        ]
        # Cleaning re-runs only when "Update Cleaning Settings" is clicked.
        for spinbox in clean_widgets:
            spinbox.valueChanged.connect(self.cleaning_settings_edited)
        for spinbox in analysis_widgets:
            spinbox.valueChanged.connect(self.schedule_orphan_analysis)
        #rerun once a coordinate is finished being typed, not on every keystroke
        for well_field in (self.ow_well_lat, self.ow_well_lon):
            well_field.editingFinished.connect(self.well_coordinates_changed)
            #the clear button empties the field without finishing an edit
            well_field.textChanged.connect(lambda text: None if text else self.well_coordinates_changed())

        # Initialize the dataset selector with any existing datasets
        if hasattr(self, 'df_list') and self.df_list:
            self._populate_ow_dataset_selector()

        return widget


    def create_location_tab(self):
        page=QWidget();layout=QVBoxLayout(page)
        # The selected workspace tab supplies its heading.
        self.location_headline=QLabel('Inspect the anomaly evidence first. Location estimates appear here after analysis.')
        self.location_headline.setWordWrap(True);self.location_headline.hide()
        self.location_views=QTabWidget()
        # Move candidate-location views to the final workspace; preserve canvas objects.
        for name in ['Location Map','Web Map']:
            index=next(i for i in range(self.ow_visual_tabs.count()) if self.ow_visual_tabs.tabText(i)==name)
            widget=self.ow_visual_tabs.widget(index);self.ow_visual_tabs.removeTab(index)
            self.location_views.addTab(widget,name)
        splitter=QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.location_views)
        self.ow_summary.setParent(None);self.ow_summary.setMaximumHeight(16777215)
        self.ow_summary.setMinimumWidth(260);splitter.addWidget(self.ow_summary)
        splitter.setSizes([1000,320]);layout.addWidget(splitter,1)
        footer=QHBoxLayout();back=QPushButton('Review anomaly evidence');back.clicked.connect(lambda:self.tabs.setCurrentWidget(self.orphan_well_widget))
        export=QPushButton('Export location results');export.clicked.connect(self.export_orphan_results)
        footer.addWidget(back);footer.addStretch();footer.addWidget(export);layout.addLayout(footer)
        self.stage_order=list(range(self.ow_visual_tabs.count()))
        self.ow_visual_tabs.setCurrentIndex(0);self.update_stage_navigation()
        return page

    def move_analysis_stage(self, delta):
        position=self.ow_visual_tabs.currentIndex()+delta
        if position>=self.ow_visual_tabs.count():
            self.tabs.setCurrentIndex(self.tabs.count()-1)
        else:self.ow_visual_tabs.setCurrentIndex(max(0,position))

    def update_stage_navigation(self, *_):
        position=self.ow_visual_tabs.currentIndex()
        self.stage_label.clear();self.stage_label.hide()
        self.previous_stage.setEnabled(position>0)
        self.next_stage.setEnabled(True)
        self.next_stage.setText('View location estimate' if position==self.ow_visual_tabs.count()-1 else 'Next view')

    def commit_filter_result(self,frame,settings):
        if settings['field'] != 'Current result':
            self.active_filters = []
        filters=self.active_filters + [settings['method']]
        self.filtered_scale_changed(frame,filters=filters,parameters=settings,replace_history=settings['field']!='Current result',
            status_message='Filter result stored. Original map preserved; Anomaly Explorer analysis input is explicit.')

    def apply_scientific_style(self):
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
        self.orphan_well_widget.setStyleSheet('')
        self.data.setAlternatingRowColors(True)

    def active_session(self):
        index = getattr(self, 'active_dataset_index', None)
        if index is None or not 0 <= index < len(getattr(self, 'sessions', [])):
            return None
        return self.sessions[index]

    def register_survey(self, path, mag, gps):
        candidate = SurveySession(path, mag, gps)
        candidate.ensure_cleaned(self.orphan_params())
        index = next((i for i, item in enumerate(self.sessions)
                      if os.path.normcase(item.path) == os.path.normcase(candidate.path)), None)
        self.select_file.blockSignals(True)
        try:
            if index is None:
                index = len(self.sessions)
                self.sessions.append(candidate)
                self.df_list.append(None)
                label = Path(candidate.path).name
                if self.select_file.findText(label) >= 0:
                    label += f' ({Path(candidate.path).parent.name})'
                self.select_file.addItem(label, candidate.path)
            else:
                self.sessions[index] = candidate
            self.select_file.setCurrentIndex(index)
        finally:
            self.select_file.blockSignals(False)
        self.activate_survey(index)
        if hasattr(self,'project_tools'):self.project_tools.changed()
        return index

    def activate_survey(self, index):
        if index is None or not 0 <= index < len(self.sessions):
            return
        self.ow_update_timer.stop()
        self.ow_reload_timer.stop()
        self.clear_orphan_results('Loading shared survey...')
        session = self.sessions[index]
        if hasattr(self,'project_tools') and self.active_dataset_index!=index:self.project_tools.select_survey_cleaning(session)
        session.ensure_cleaned(self.orphan_params())
        self.active_dataset_index = index
        self.ow_selected_dataset_index = index
        self.ow_selected_dataset = session.cleaned
        self.ow_file_path = session.path
        self.file_paths = [session.path]
        self.short_name = Path(session.path).name
        self.active_filters = list(session.filters)
        self.processed_dfs[index] = session.cleaned.copy(deep=True)
        self.mag_gps_dfs[index] = (session.magnetometer, session.location)
        self.residual_cache = None
        self.map_vmin = self.map_vmax = self.vmin = self.vmax = None
        self.set_vmin.clear()
        self.set_vmax.clear()
        self.display_processed_df(session.working)
        self.update_field_labels()
        self.filters_workspace.session_changed()
        self.data_workspace.refresh()
        # Displayed data now match the cleaning controls.
        self.data_workspace.set_cleaning_pending(False)
        self.run_orphan_analysis()

    def current_map_field_name(self):
        session=self.active_session()
        if session is None or not session.filter_history:
            return 'Cleaned total field'
        history=session.filter_history
        signal=history[0]['parameters'].get('field','Total magnitude')
        parts=[signal]
        for step in history:
            settings=step['parameters'];name=step['filter']
            if name=='VMD' and settings.get('selected_modes'):
                name+=' (modes '+', '.join(map(str,settings['selected_modes']))+')'
            elif 'continuation' in name.lower() and 'height' in settings:
                name+=f" ({settings['height']:g} m)"
            parts.append(name)
        mode=self.residual_mode()
        if mode: parts.append(RESIDUAL_LABELS[mode])
        return ' ? '.join(parts)

    def update_field_labels(self):
        session = self.active_session()
        if session:
            self.ow_dataset_label.setText(f'Active survey: {Path(session.path).name} | {len(session.cleaned)} shared samples')
            self.shared_field_label.setText(f'Current filter result: {self.current_map_field_name()}')

    def clear_orphan_results(self, message):
        self.ow_clean_df = self.ow_annotated_df = None
        if hasattr(self,'result_headline'): self.result_headline.setText(message)
        if hasattr(self,'location_headline'): self.location_headline.setText(message)
        self.ow_score_points = self.ow_clusters = None
        self.ow_summary_data = {}
        self.ow_modes = self.ow_mode_metrics = None
        self.ow_selected_modes = []
        self.ow_export_button.setEnabled(False)
        self.ow_summary.setPlainText(message)
        self.ow_input_label.setText('Analysis input: pending')
        if hasattr(self, 'ow_vmd_panel'): self.ow_vmd_panel.clear(message)
        for name in ('ow_field', 'ow_score', 'ow_cluster', 'ow_modes', 'ow_geoxai'):
            figure = getattr(self, name + '_figure', None)
            canvas = getattr(self, name + '_canvas', None)
            if figure is not None:
                figure.clear()
            if canvas is not None:
                canvas.draw_idle()
        self.ow_geoxai_report=None
        self.ow_geoxai_text.setPlainText(message)
        self.ow_web_map.setHtml('<html><body>' + 'Candidate results pending' + '</body></html>')

    def import_data_action(self):
        self.file_editor_window()

    def file_editor_window(self):
        #creates the dialog window after button is clicked
        #self and parent connection ensures that the dialog opens above the
        #main window
        self.dlg = dw.CustomDialog(self)
        self.dlg.FileDialog.clicked.connect(self.dlg.select_file_button_clicked)
        # Remove the default accepted handlers so validation can run first
        try:
            self.dlg.FinishBtn.accepted.disconnect(self.dlg.accept)
        except Exception:
            pass
        # connect FinishBtn to custom validator that shows a message box if variables missing
        self.dlg.FinishBtn.accepted.connect(self._dialog_finish_handler)
        self.dlg.exec()

#    def dialog_accepted(self):
#        self.read_from_dialog()

    def read_from_dialog(self):
        dlg = self.dlg
        mag, gps = dlg.build_streams()
        return self.register_survey(dlg.file_paths[0], mag, gps)

    def store_dataset(self, file_path, raw_file):
        raise RuntimeError('Use register_survey so both workspaces share validated survey streams.')

    def _populate_ow_dataset_selector(self, select_index=None):
        # Compatibility hook: the only dataset selector is now the global one.
        if select_index is not None:
            self.select_file.setCurrentIndex(select_index)

    def _update_ow_dataset(self, index):
        self.select_file.setCurrentIndex(index)

    def _dialog_finish_handler(self):
        try:
            self.read_from_dialog()
        except Exception as exc:
            QMessageBox.warning(self.dlg, 'Survey import', str(exc))
            return
        self.dlg.accept()

    def read_file(self, file_index):
        self.select_file.setCurrentIndex(file_index)
        self.activate_survey(file_index)
    #make excel reader optional? for people who don't want their data cleaned or already did it

    def reference_well_coordinates(self, report=False):
        """(lat, lon) of the known well the user entered, or None if left blank or invalid.
        With report=True, problems are shown in the status bar."""
        lat_text = self.ow_well_lat.text().strip()
        lon_text = self.ow_well_lon.text().strip()
        if not lat_text and not lon_text:
            return None
        if not lat_text or not lon_text:
            if report:
                self.statusBar().showMessage('Enter both latitude and longitude for the known well.')
            return None
        try:
            lat, lon = float(lat_text), float(lon_text)
        except ValueError:
            if report:
                self.statusBar().showMessage('Known well coordinates must be numbers in decimal degrees.')
            return None
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            if report:
                self.statusBar().showMessage('Known well latitude must be -90 to 90 and longitude -180 to 180.')
            return None
        return lat, lon

    def reference_well_known(self):
        return self.reference_well_coordinates() is not None

    def well_coordinates_changed(self):
        #editingFinished also fires when the field just loses focus, so only rerun on a real change
        coordinates = self.reference_well_coordinates(report=True)
        if coordinates == getattr(self, 'ow_last_well_coordinates', None):
            return
        self.ow_last_well_coordinates = coordinates
        if coordinates is not None:
            self.statusBar().showMessage(f'Known well set to {coordinates[0]:.6f}, {coordinates[1]:.6f}')
        self.schedule_orphan_analysis()

    def orphan_params(self):
        well = self.reference_well_coordinates()
        return ow.OrphanWellParams(
            well_lat=well[0] if well else None,
            well_lon=well[1] if well else None,
            startup_samples=int(self.ow_startup_samples.value()),
            spatial_mad_multiplier=float(self.ow_spatial_mad.value()),
            spatial_fallback_percentile=float(self.ow_fallback_percentile.value()),
            window_length_m=float(self.ow_window_length.value()),
            step_ratio=float(self.ow_step_ratio.value()),
            gamma=float(self.ow_gamma.value()),
            dbscan_eps_m=float(self.ow_dbscan_eps.value()),
            dbscan_min_samples=int(self.ow_min_samples.value()),
        )

    def cleaning_settings_edited(self, *_):
        if self.active_session() is None:
            return
        self.data_workspace.set_cleaning_pending(True)
        self.statusBar().showMessage('Cleaning settings changed. Click "Update Cleaning Settings" to apply them.')

    def apply_cleaning_settings(self):
        if self.active_session() is None:
            return
        workspace = self.data_workspace
        workspace.update_cleaning.setEnabled(False)
        with busy(self, 'Updating cleaning settings... re-cleaning survey and rerunning analysis.'):
            ok = self.reload_orphan_well_file()
        if ok:
            workspace.set_cleaning_pending(False)
            session = self.active_session()
            self.statusBar().showMessage(f'Cleaning settings updated: {len(session.cleaned):,} samples retained.', 8000)
        else:
            workspace.update_cleaning.setEnabled(True)

    def schedule_orphan_analysis(self):
        if self.active_session() is not None:
            self.ow_update_timer.start(350)

    def schedule_orphan_reload(self):
        if self.active_session() is not None:
            self.ow_reload_timer.start(650)

    def import_orphan_well_survey(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            'Select Orphan Well Survey',
            '',
            'Survey files (*.xls *.xlsx *.xlsm *.csv);;All files (*.*)',
        )
        if file_path:
            self.load_orphan_well_file(file_path)

    def load_butkowsky_test_survey(self):
        self.import_orphan_well_survey()

    def reload_orphan_well_file(self):
        if self.active_session() is not None:
            try:
                self.activate_survey(self.active_dataset_index)
                return True
            except Exception as exc:
                self.data_workspace.status.show()
                self.data_workspace.status.setText(f'Cleaning settings could not be applied: {exc}. Displayed data retain the last successful settings.')
                self.filters_workspace.invalidate()
                self.clear_orphan_results(f'Cleaning settings could not be applied: {exc}')
                self.statusBar().showMessage('Adjust cleaning settings to retain enough valid samples.')
        return False

    def process_orphan_well_dataset(self, *_args):
        self._analysis_mode_key = None
        self.run_orphan_analysis()

    def load_orphan_well_file(self, file_path):
        # Startup paths and file-dialog imports enter the same registration path.
        try:
            mag, gps = ow.read_survey_file(file_path)
            self.register_survey(file_path, mag, gps)
        except Exception as exc:
            QMessageBox.warning(self, 'Survey import', str(exc))
            return False
        return True

    def run_orphan_analysis(self):
        session = self.active_session()
        if session is None:
            return
        self.ow_update_timer.stop()
        self.clear_orphan_results('Updating candidate analysis...')
        params = self.orphan_params()
        try:
            if self.ow_input.currentIndex() == 1:
                source = self.map_view(session.working)
                input_name = self.current_map_field_name()
            else:
                source = session.cleaned
                input_name = 'Cleaned total field'
            frame = source.copy(deep=True)
            frame['Analysis_Field_uT'] = frame['BT'].to_numpy(dtype=float)
            frame['Analysis_Input'] = input_name
            frame['Source_Survey'] = Path(session.path).name
            history = session.filter_history if self.ow_input.currentIndex() == 1 else []
            frame['Analysis_Processing_History'] = json.dumps(history, sort_keys=True)
            frame['Analysis_Startup_Samples'] = session.cleaning_key[0]
            frame['Analysis_Spatial_MAD'] = session.cleaning_key[1]
            frame['Analysis_Spatial_Fallback_Percentile'] = session.cleaning_key[2]
            modes, metrics, selected = session.modes_for(frame, params)
            self.ow_clean_df, self.ow_audit = frame, session.audit
            self.ow_modes, self.ow_mode_metrics, self.ow_selected_modes = modes, metrics, selected
            points, clusters, summary = ow.analyze_with_cached_modes(frame, modes, selected, params)
            summary.update(source_survey=Path(session.path).name, analysis_input=input_name,
                           processing_history=history, dataset_revision=session.revision)
            annotated = ow.annotate_clean_points(ow.add_well_distance(frame, params), points, clusters)
            self.ow_score_points, self.ow_clusters = points, clusters
            self.ow_summary_data, self.ow_annotated_df = summary, annotated
            self.ow_input_label.setText(f'Analysis input: {input_name}')
            self.plot_orphan_results(annotated, points, clusters, summary)
            self.ow_summary.setText(self.format_orphan_summary(summary))
            radius=summary.get('candidate_radius_m')
            spread=f'{radius:.2f} m cluster spread' if radius is not None else 'No selected candidate'
            self.result_headline.setText(f"{summary.get('n_clusters',0)} candidate clusters\n{summary.get('n_hits',0)} hit windows")
            self.location_headline.setText(f"{spread}. This is an orphan-well / ferrous-target candidate, requiring field verification. Cluster spread is not a confidence interval.")
            self.ow_export_button.setEnabled(True)
            self.statusBar().showMessage(f"{Path(session.path).name}: {len(frame)} shared samples | {summary['n_clusters']} candidate clusters")
        except Exception as exc:
            self.clear_orphan_results(f'Analysis unavailable: {exc}')
            self.statusBar().showMessage(f'Candidate analysis unavailable: {exc}')

    def format_orphan_summary(self, summary):
        if not summary:
            return 'No orphan-well analysis has been run.'
        lines = [f"Survey: {summary.get('source_survey', '')}", f"Analysis input: {summary.get('analysis_input', '')}", f"Dataset revision: {summary.get('dataset_revision', '')}", f"Field processing: {json.dumps(summary.get('processing_history', []), sort_keys=True)}", '']
        lines.append('Candidate Estimate')
        lines.append('------------------')
        if 'candidate_latitude' in summary:
            lines.extend([
                f"Latitude:  {summary['candidate_latitude']:.6f}",
                f"Longitude: {summary['candidate_longitude']:.6f}",
                f"UTM zone: {summary.get('utm_zone', '?')}",
                f"UTM Easting:  {summary['candidate_easting_m']:.2f} m",
                f"UTM Northing: {summary['candidate_northing_m']:.2f} m",
                f"Cluster spread radius: {summary['candidate_radius_m']:.2f} m",
                'Spread definition: weighted RMS distance of supporting windows from the cluster center.',
                f"Supporting windows: {summary['candidate_points']}",
            ])
            if 'candidate_distance_to_well_m' in summary:
                lines.append(f"Offset to known well: {summary['candidate_distance_to_well_m']:.2f} m")
            else:
                lines.append("Mode: unknown-location estimate")
        else:
            lines.append('No selected candidate cluster.')

        audit = self.ow_audit or {}
        lines.extend([
            '',
            'Processing Summary',
            '------------------',
            f"Cleaned samples: {summary.get('n_samples', 0)}",
            f"Startup samples removed: {audit.get('startup_removed', 0)}",
            f"Spatial outliers removed: {audit.get('spatial_removed', 0)}",
            f"Selected VMD modes: {summary.get('selected_modes', '')}",
            '',
            'Scoring Parameters',
            '------------------',
            f"Window length: {summary.get('window_length_m', 0):.1f} m",
            f"Window samples: {summary.get('window_samples', 0)}",
            f"Step samples: {summary.get('step_samples', 0)}",
            f"Threshold gamma: {summary.get('gamma', 0):.1f}",
            f"Score threshold: {summary.get('threshold', 0):.3f}",
            '',
            'Cluster Results',
            '---------------',
            f"DBSCAN eps: {summary.get('dbscan_eps_m', 0):.1f} m",
            f"DBSCAN min samples: {summary.get('dbscan_min_samples', 0)}",
            f"Hit windows: {summary.get('n_hits', 0)}",
            f"Clusters: {summary.get('n_clusters', 0)}",
        ])
        return '\n'.join(lines)

    def plot_orphan_results(self, clean_df, score_points, clusters, summary):
        self.plot_orphan_total_field(clean_df)
        self.plot_orphan_score_trace(score_points)
        self.plot_orphan_engineering_map(clean_df, score_points, clusters)
        self.plot_orphan_mode_metrics()
        self.refresh_orphan_geoxai(clean_df, score_points, clusters, summary)
        self.refresh_orphan_web_map(clean_df, score_points, clusters, summary)

    def style_orphan_axis(self, ax):
        ax.set_facecolor('#FFFFFF')
        ax.grid(color='#E5E7EB', linewidth=0.8, alpha=0.9)
        for spine in ax.spines.values():
            spine.set_color('#CBD5E1')
        ax.tick_params(colors='#111827')
        ax.title.set_color('#111827')
        ax.xaxis.label.set_color('#111827')
        ax.yaxis.label.set_color('#111827')

    def plot_orphan_total_field(self, clean_df):
        self.ow_field_figure.clear()
        ax_field = self.ow_field_figure.add_subplot(111)
        ordered = clean_df.sort_values('Time (s)').reset_index(drop=True)
        ax_field.plot(ordered['Time (s)'], ordered['BT'], color='#111827', linewidth=0.9)
        ax_field.set_title('Analysis field: ' + self.ow_summary_data.get('analysis_input', 'Cleaned total field'), pad=12)
        ax_field.set_xlabel('Time (s)')
        ax_field.set_ylabel('BT (uT)')
        ax_field.margins(x=0.01)
        self.style_orphan_axis(ax_field)
        self.ow_field_canvas.draw_idle()

    def plot_orphan_score_trace(self, score_points):
        self.ow_score_figure.clear()
        ax_score = self.ow_score_figure.add_subplot(111)
        if score_points is not None and not score_points.empty:
            ax_score.plot(score_points['t_center_s'], score_points['score'], color='#0F766E', linewidth=1.1)
            threshold = float(score_points['threshold'].iloc[0])
            ax_score.axhline(threshold, color='#B91C1C', linestyle='--', linewidth=1.1, label='threshold')
            hits = score_points[score_points['is_hit']]
            if not hits.empty:
                ax_score.scatter(
                    hits['t_center_s'],
                    hits['score'],
                    s=18,
                    color='#F59E0B',
                    edgecolor='#111827',
                    linewidth=0.25,
                    label='hit window',
                    zorder=3,
                )
            ax_score.fill_between(
                score_points['t_center_s'],
                threshold,
                score_points['score'],
                where=score_points['score'] >= threshold,
                color='#F59E0B',
                alpha=0.16,
                interpolate=True,
            )
        else:
            ax_score.text(0.5, 0.5, 'No score windows', ha='center', va='center', transform=ax_score.transAxes)
        ax_score.set_title('Anomaly score and threshold', pad=12)
        ax_score.set_xlabel('Time (s)')
        ax_score.set_ylabel('Score')
        ax_score.margins(x=0.01)
        if score_points is not None and not score_points.empty:
            ax_score.legend(loc='upper left', frameon=True, fontsize=9)
        self.style_orphan_axis(ax_score)
        self.ow_score_canvas.draw_idle()

    def plot_orphan_engineering_map(self, clean_df, score_points, clusters):
        self.ow_cluster_figure.clear()
        ax_map = self.ow_cluster_figure.add_subplot(111)
        ax_map.plot(
            clean_df['Easting (m)'],
            clean_df['Northing (m)'],
            color='#94A3B8',
            linewidth=1.0,
            alpha=0.9,
            label='survey track',
            zorder=1,
        )
        if score_points is not None and not score_points.empty:
            scatter = ax_map.scatter(
                score_points['e_m'],
                score_points['n_m'],
                c=score_points['score'],
                s=16,
                cmap='magma',
                alpha=0.82,
                edgecolors='none',
                zorder=2,
            )
            self.ow_cluster_figure.colorbar(scatter, ax=ax_map, fraction=0.038, pad=0.02, label='Anomaly score',panchor=False)
            hits = score_points[score_points['is_hit']]
            if not hits.empty:
                ax_map.scatter(
                    hits['e_m'],
                    hits['n_m'],
                    facecolors='none',
                    edgecolors='#F59E0B',
                    s=44,
                    linewidths=0.8,
                    label='hit windows',
                    zorder=3,
                )
        epsg = ow.survey_epsg(clean_df)
        well = ow.well_utm(self.orphan_params(), epsg)
        if well is not None:
            ax_map.scatter(
                [well[0]],
                [well[1]],
                marker='*',
                s=220,
                c='#B91C1C',
                edgecolors='black',
                linewidths=0.5,
                label='known well',
                zorder=5,
            )
        if clusters is not None and not clusters.empty:
            for _, row in clusters.iterrows():
                selected = bool(row.get('selected_by_support_compactness', False))
                marker = 'D' if selected else 'd'
                color = '#111827' if selected else '#F97316'
                ax_map.scatter(
                    row['centroid_e_m'],
                    row['centroid_n_m'],
                    marker=marker,
                    c=color,
                    s=90 if selected else 60,
                    edgecolors='white',
                    linewidths=0.7,
                    label='estimated location' if selected else None,
                    zorder=6 if selected else 4,
                )
                ax_map.annotate(
                    f"C{int(row['cluster_label'])}",
                    (row['centroid_e_m'], row['centroid_n_m']),
                    xytext=(4, 4),
                    textcoords='offset points',
                    fontsize=8,
                )
        title = 'Estimated location and magnetic anomalies'
        ax_map.set_title(title, pad=12)
        zone = ow.utm_zone_label(epsg)
        ax_map.set_xlabel(f'UTM {zone} Easting (m)')
        ax_map.set_ylabel(f'UTM {zone} Northing (m)')
        ax_map.set_aspect('equal', adjustable='box')
        ax_map.set_anchor('C')
        ax_map.legend(loc='upper left', fontsize=8, frameon=True)
        self.style_orphan_axis(ax_map)
        self.ow_cluster_canvas.draw_idle()

    def plot_orphan_mode_metrics(self):
        if self.ow_modes is None or self.ow_clean_df is None:
            self.ow_vmd_panel.clear();return
        frame=self.ow_clean_df.sort_values('Time (s)').reset_index(drop=True)
        self.ow_vmd_panel.set_data(frame['Time (s)'].to_numpy(),frame['Analysis_Field_uT'].to_numpy(),
            self.ow_modes,self.ow_mode_metrics,self.ow_selected_modes,'Time (s)')

    def refresh_orphan_geoxai(self, clean_df, score_points, clusters, summary):
        if not hasattr(self, 'ow_geoxai_text'):
            return
        report = gx.explain_candidate(
            clean_df,
            score_points,
            clusters,
            summary,
            reference_known='candidate_distance_to_well_m' in summary,
        )
        self.ow_geoxai_report=report
        self.ow_geoxai_text.setPlainText(report.narrative)

        self.ow_geoxai_figure.clear()
        if report.contributions.empty and report.cluster_scores.empty:
            ax = self.ow_geoxai_figure.add_subplot(111)
            ax.text(0.5, 0.5, 'No GeoXAI evidence to plot', ha='center', va='center', transform=ax.transAxes)
            ax.set_axis_off()
            self.ow_geoxai_canvas.draw_idle()
            return

        ax_factors, ax_clusters = self.ow_geoxai_figure.subplots(1, 2)
        if not report.contributions.empty:
            contrib = report.contributions.sort_values('weighted_score', ascending=True)
            ax_factors.barh(contrib['factor'], contrib['weighted_score'], color='#0F766E')
            ax_factors.set_xlim(0, max(0.35, float(contrib['weighted_score'].max()) * 1.15))
            ax_factors.set_title('Selected-candidate evidence', pad=12)
            ax_factors.set_xlabel('Weighted GeoXAI contribution')
            for index, value in enumerate(contrib['weighted_score']):
                ax_factors.text(value + 0.005, index, f'{value:.2f}', va='center', fontsize=8)
        else:
            ax_factors.text(0.5, 0.5, 'No selected candidate', ha='center', va='center', transform=ax_factors.transAxes)
        self.style_orphan_axis(ax_factors)

        if not report.cluster_scores.empty:
            scored = report.cluster_scores.sort_values('geo_xai_confidence', ascending=True)
            labels = [f"C{int(v)}" for v in scored['cluster_label']]
            colors = [
                '#111827' if bool(v) else '#94A3B8'
                for v in scored['selected_by_support_compactness'].astype(bool)
            ]
            ax_clusters.barh(labels, 100*scored['geo_xai_confidence'], color=colors)
            ax_clusters.set_xlim(0, 100)
            ax_clusters.set_title('Cluster Evidence Scores', pad=12)
            ax_clusters.set_xlabel('XAI Evidence Score (0–100)')
            for index, value in enumerate(scored['geo_xai_confidence']):
                ax_clusters.text(100.0*float(value) + 1.5, index, f'{100.0 * float(value):.0f}', va='center', fontsize=8)
        else:
            ax_clusters.text(0.5, 0.5, 'No clusters', ha='center', va='center', transform=ax_clusters.transAxes)
        self.style_orphan_axis(ax_clusters)
        self.ow_geoxai_canvas.draw_idle()

    def refresh_orphan_web_map(self, clean_df, score_points, clusters, summary):
        if not hasattr(self, 'ow_web_map') or clean_df is None or clean_df.empty:
            return
        try:
            if 'candidate_latitude' in summary:
                center_lat = float(summary['candidate_latitude'])
                center_lon = float(summary['candidate_longitude'])
            elif score_points is not None and not score_points.empty:
                center_lat = float(score_points['latitude'].mean())
                center_lon = float(score_points['longitude'].mean())
            else:
                center_lat = float(clean_df['Latitude (°)'].mean())
                center_lon = float(clean_df['Longitude (°)'].mean())

            m = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=19,
                control_scale=True,
                prefer_canvas=True,
                tiles=None,
            )
            folium.TileLayer('OpenStreetMap', name='Street map', show=False).add_to(m)
            folium.TileLayer(
                tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                attr='Esri World Imagery',
                name='Satellite imagery',
                max_zoom=23,
                show=True,
            ).add_to(m)

            route = clean_df[['Latitude (°)', 'Longitude (°)']].dropna()
            if len(route) > 900:
                route = route.iloc[::max(1, int(np.ceil(len(route) / 900)))]
            route_points = route.values.tolist()
            if route_points:
                folium.PolyLine(
                    route_points,
                    color='#38BDF8',
                    weight=3,
                    opacity=0.75,
                    tooltip='survey track',
                ).add_to(m)

            if score_points is not None and not score_points.empty:
                score_values = score_points['score'].to_numpy(dtype=float)
                vmin = float(np.nanpercentile(score_values, 5))
                vmax = float(np.nanpercentile(score_values, 98))
                if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin == vmax:
                    vmin, vmax = float(np.nanmin(score_values)), float(np.nanmax(score_values) + 1.0)
                colormap = cm.LinearColormap(
                    colors=['#2C7BB6', '#00A676', '#F6D743', '#D7191C'],
                    vmin=vmin,
                    vmax=vmax,
                    caption='Anomaly score',
                )
                point_layer = folium.FeatureGroup(name='score windows', show=True)
                display_points = score_points.copy()
                if len(display_points) > 1200:
                    display_points = display_points.iloc[::max(1, int(np.ceil(len(display_points) / 1200)))]
                for _, row in display_points.iterrows():
                    is_hit = bool(row.get('is_hit', False))
                    folium.CircleMarker(
                        location=[float(row['latitude']), float(row['longitude'])],
                        radius=4 if is_hit else 2,
                        color='#111827' if is_hit else '#475569',
                        weight=1.0 if is_hit else 0.4,
                        fill=True,
                        fill_color=colormap(float(row['score'])),
                        fill_opacity=0.88 if is_hit else 0.48,
                        tooltip=f"Score {float(row['score']):.2f}",
                    ).add_to(point_layer)
                point_layer.add_to(m)
                colormap.add_to(m)

            known_well = self.reference_well_coordinates()
            if known_well is not None:
                folium.Marker(
                    list(known_well),
                    tooltip='Known well',
                    popup=f'Known well<br>{known_well[0]:.6f}, {known_well[1]:.6f}',
                    icon=folium.Icon(color='red', icon='flag'),
                ).add_to(m)

            if clusters is not None and not clusters.empty:
                cluster_layer = folium.FeatureGroup(name='clusters and candidate', show=True)
                for _, row in clusters.iterrows():
                    selected = bool(row.get('selected_by_support_compactness', False))
                    color = '#111827' if selected else '#F97316'
                    label = f"C{int(row['cluster_label'])}"
                    popup = (
                        f"<b>{'Selected candidate' if selected else 'Cluster'} {label}</b><br>"
                        f"Support: {int(row['n_points'])} windows<br>"
                        f"Peak score: {float(row['peak_score']):.2f}<br>"
                        f"Radius: {float(row['uncertainty_radius_m']):.2f} m"
                    )
                    if known_well is not None:
                        popup += f"<br>Offset to known well: {float(row['dist_to_well_m']):.2f} m"
                    folium.CircleMarker(
                        [float(row['centroid_latitude']), float(row['centroid_longitude'])],
                        radius=9 if selected else 6,
                        color='white',
                        weight=2,
                        fill=True,
                        fill_color=color,
                        fill_opacity=0.96,
                        tooltip=label,
                        popup=folium.Popup(popup, max_width=280),
                    ).add_to(cluster_layer)
                    folium.Marker(
                        [float(row['centroid_latitude']), float(row['centroid_longitude'])],
                        icon=folium.DivIcon(
                            html=(
                                "<div style='font-size:12px;font-weight:700;color:white;"
                                "text-shadow:0 1px 3px #000;'>"
                                f"{label}</div>"
                            )
                        ),
                    ).add_to(cluster_layer)
                    if selected:
                        folium.Circle(
                            [float(row['centroid_latitude']), float(row['centroid_longitude'])],
                            radius=float(row['uncertainty_radius_m']),
                            color='#111827',
                            weight=2,
                            fill=True,
                            fill_color='#111827',
                            fill_opacity=0.12,
                            tooltip='candidate uncertainty radius',
                        ).add_to(cluster_layer)
                cluster_layer.add_to(m)

            bounds = []
            if route_points:
                bounds.extend(route_points)
            if score_points is not None and not score_points.empty:
                bounds.extend(score_points[['latitude', 'longitude']].dropna().values.tolist())
            if known_well is not None:
                bounds.append(list(known_well))
            if len(bounds) > 1:
                m.fit_bounds(bounds, padding=(28, 28))
            folium.LayerControl(collapsed=False).add_to(m)

            map_path = Path(tempfile.gettempdir()) / 'magpy_orphan_well_cluster_map.html'
            m.save(str(map_path))
            self.ow_web_map.load(QUrl.fromLocalFile(str(map_path)))
        except Exception as exc:
            self.ow_web_map.setHtml(
                "<html><body style='margin:0;background:#0f172a;color:#e5e7eb;"
                "font-family:Segoe UI,Arial,sans-serif;padding:24px;'>"
                f"<h3>Map could not be rendered</h3><p>{str(exc)}</p></body></html>"
            )

    def assign_optional_v_values(self):
        self.vmin = None
        self.vmax = None
        vmin_entry = self.set_vmin.text().strip()
        vmax_entry = self.set_vmax.text().strip()
        try:
            if vmin_entry:
                self.vmin = float(vmin_entry)
            if vmax_entry:
                self.vmax = float(vmax_entry)
            return True
        except ValueError:
            self.statusBar().showMessage('Invalid field scale value entered. Try again.')
            return False

    #def change continuation height
    def assign_continuation_height(self):
        H_entry = self.set_continuation_height.text()
        if H_entry.strip() == '':
            self.H = 0
            self.statusBar().showMessage('Continuation Height Not Entered (fill continuation height field). Try again.')
            return False
        try:
            self.H = float(H_entry)
            self.statusBar().showMessage(f'Continuation Height={self.H}m')
            return True
        except ValueError:
            self.statusBar().showMessage('Invalid continuation height entered (must be a number). Try again.')
            return False

    def extract_survey_date(self):
        self.date_year = self.year.text()
        self.date_month = self.month.text()
        self.date_day = self.day.text()
        if self.date_year.strip() == '' or self.date_month.strip() == '' or self.date_day.strip() == '':
            self.statusBar().showMessage('Survey date not entered (fill year, month, day fields). Try again.')
            return False
        try:
            self.date_year = int(self.date_year)
            self.date_month = int(self.date_month)
            self.date_day = int(self.date_day)
            return True
        except ValueError:
            self.statusBar().showMessage('Invalid survey date entered. Try again.')
            return False

    def select_display_file(self, index):
        if not hasattr(self, 'sessions') or index < 0 or index >= len(self.sessions):
            return
        try:
            self.activate_survey(index)
        except Exception as exc:
            self.select_file.blockSignals(True)
            self.select_file.setCurrentIndex(self.active_dataset_index)
            self.select_file.blockSignals(False)
            self.clear_orphan_results(f'Survey unavailable: {exc}')
            self.statusBar().showMessage(str(exc))

    def excel_reader(self, df=None, cache_index=None):
        # Legacy callers now use the common preprocessing cache.
        index = self.active_dataset_index if cache_index is None else cache_index
        self.activate_survey(index)

    def add_menu(self, columns):
        session=self.active_session()
        if session is not None:self.data_workspace.update_signal_columns(session.cleaned)

    def display_processed_df(self,df):
        self.df=df.copy(deep=True);self.current_df=self.df
        session=self.active_session()
        original=session.cleaned if session else self.df
        signals_blocked=self.plot_tabs.blockSignals(True)
        try:
            self.plot_tabs.clear()
            # Original Map and Data Table remain the reproducible cleaned baseline.
            self.figure.clear();self.axes=self.figure.add_subplot()
            mapper=mm.MapMaker(original)
            mapper.showMap(original,ax=self.axes,cbar_label='Original cleaned total field [uT]')
            self.axes.set_title('Original survey — cleaned total magnitude')
            self.canvas.draw_idle()
            self.plot_table(original)
            self.new_plot(df=original,name='Total magnitude',column=original['BT'])
            self.add_menu(original.columns)
        finally:
            self.plot_tabs.blockSignals(signals_blocked)


    def plot_data(self, df, vmin=None, vmax=None, contour=None):
        #clears any previous figures from the canvas widget
        self.figure.clear()
        #replots the blank matplotlib figure and axes
        self.axes = self.figure.add_subplot()
        #calls mapmaker class to plot the data
        mapper = mm.MapMaker(df)
        #runs data through showMap function, as a residual if Residual Map is on
        mapper.showMap(self.map_view(df), ax=self.axes, contour=contour, vmin=vmin, vmax=vmax,
                        cbar_label=self.colorbar_label())
        #refreshes the canvas
        self.canvas.draw()
        self.current_df = df
        self.map_vmin, self.map_vmax = vmin, vmax
        self.refresh_web_map()

    def refresh_web_map(self):
        """Rebuild the web map, if it's open, so it matches the regular map."""
        if self.map_view_type.currentText() == WEB_MAP:
            self.web_map()

#
    def plot_table(self, df):
        #df = pd.to_numeric(df, errors='coerce')
        labels=self.data_workspace.record_labels(df) if hasattr(self,'data_workspace') else None
        self.model = TableModel.TableModel(df,row_labels=labels)
        self.data.setModel(self.model)
        self.proxyModel = QSortFilterProxyModel()
        self.proxyModel.setSourceModel(self.data.model())
        self.proxyModel.setSortRole(Qt.ItemDataRole.EditRole)
        self.data.setSortingEnabled(True)
        self.data.setModel(self.proxyModel)
        #self.data.resizeColumnsToContents()
        header = self.data.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    def plot_changed(self,val=None,ymin=None,ymax=None):
        session=self.active_session()
        if session is not None and val in session.cleaned:
            frame=session.cleaned
            self.new_plot(name=val,df=frame,column=frame[val])
            self.tabs.setCurrentWidget(self.data_workspace)
            self.data_workspace.tabs.setCurrentWidget(self.plot_widget)

    def filter_suffix(self, column):
        """Label for plots of filtered BT, e.g. ' - Upward Continuation'. Other columns
        are left unlabeled because the filters don't change them."""
        labels = list(self.active_filters)
        mode = self.residual_mode()
        if mode is not None:
            labels.append(RESIDUAL_LABELS[mode])
        if labels and getattr(column, 'name', None) == 'BT':
            return ' - ' + ' + '.join(labels)
        return ''

    def close_signal_plot(self, index):
        """Close only this display; the survey column remains available to reopen."""
        page = self.plot_tabs.widget(index)
        if page is None:
            return
        self.plot_tabs.removeTab(index)
        page.deleteLater()

    def new_plot(self,df,name,ymin=None,ymax=None,column=None,ax=None):
        if column is None:return
        for index in range(self.plot_tabs.count()):
            existing=self.plot_tabs.widget(index)
            if getattr(existing,'signal_column',None)==getattr(column,'name',None):
                self.plot_tabs.setCurrentIndex(index);return
        fig=Figure(constrained_layout=True);axes=fig.add_subplot()
        axes.set_title(name+' versus time');axes.set_xlabel('Time (s)');axes.set_ylabel(str(getattr(column,'name',name)))
        canvas=FigureCanvas(fig);page=QWidget();layout=QVBoxLayout(page);layout.addWidget(canvas,1)
        toolbar=NavigationToolbar2QT(canvas,page);compact_toolbar(toolbar);layout.addWidget(toolbar)
        page.column=column;page.df=df;page.signal_column=getattr(column,'name',None);page.title=name+' versus time'
        def draw_signal(frame,style):
            key=page.signal_column
            if key not in frame:return
            axes.clear();x=frame['Time (s)'];y=frame[key]
            if style=='Line':axes.plot(x,y,lw=.8,color='#0f766e')
            if style=='Scatter':axes.scatter(x,y,s=36,marker='o',color='#0f766e',edgecolors='black',linewidths=1.0)
            axes.set_title(page.title);axes.set_xlabel('Time (s)');axes.set_ylabel(str(key));axes.grid(alpha=.2)
            # Each column uses its Data & Cleaning scale, shared with its cleaning map.
            scale_source=getattr(self,'data_workspace',None)
            # Before-cleaning data: mark the samples cleaning removed, as on the cleaning map.
            removed=scale_source.excluded_rows(frame) if scale_source is not None else None
            if removed is not None and len(removed):
                axes.scatter(removed['Time (s)'],removed[key],marker='x',c='#b91c1c',s=28,linewidths=1,zorder=3,label='Excluded')
                axes.legend(loc='best',fontsize=9)
            if scale_source is not None:
                user_lo,user_hi=scale_source.field_scale(key)
                bottom,top=axes.get_ylim()
                bottom=bottom if user_lo is None else user_lo;top=top if user_hi is None else user_hi
                if bottom<top:axes.set_ylim(bottom,top)
            page.df=frame;page.column=frame[key];toolbar.update();canvas.draw_idle()
        page.draw_signal=draw_signal
        workspace=getattr(self,'data_workspace',None)
        source=df
        if workspace is not None and workspace.signal_source.currentIndex()==1 and workspace.raw is not None:source=workspace.raw
        draw_signal(source,workspace.signal_style.currentText() if workspace is not None else 'Line')
        self.plot_tabs.addTab(page,'Total Magnitude' if name=='Total magnitude' else name);self.plot_tabs.setCurrentWidget(page);canvas.draw_idle()


    def web_map(self):
        if self.map_view_type.currentText() == WEB_MAP:
            self.canvas.hide()

            # Remove existing web map if it exists
            if hasattr(self, 'web_map_widget') and self.web_map_widget:
                self.map_layout.removeWidget(self.web_map_widget)
                self.web_map_widget.deleteLater()

            if getattr(self, 'current_df', None) is None:
                self.statusBar().showMessage('No data loaded for the web map. Import a dataset first.')
                self.web_map_widget = None
                self.canvas.show()
                return

            # Create new web map with the same color scale as the regular map
            caption = 'BT (µT)' + self.filter_suffix(self.current_df['BT'])
            self.web_map_widget = wm.MapWidget(self.map_view(self.current_df), caption=caption,
                                               vmin=self.map_vmin, vmax=self.map_vmax)
            self.map_layout.addWidget(self.web_map_widget)
            self.web_map_widget.show()
        else:
            if hasattr(self, 'web_map_widget') and self.web_map_widget:
                self.web_map_widget.hide()
                self.map_layout.removeWidget(self.web_map_widget)
                self.web_map_widget.deleteLater()
                self.web_map_widget = None
            self.canvas.show()

    def filtered_scale_changed(self, df, contour=None, status_message=None, filters=None, parameters=None, replace_history=False):
        session = self.active_session()
        if session is None:
            return
        try:
            session.set_working(df, self.active_filters if filters is None else filters, parameters=parameters,replace_history=replace_history)
            if hasattr(self,'project_tools'):self.project_tools.changed()
        except ValueError as exc:
            QMessageBox.warning(self, 'Map filter', str(exc))
            return
        self.active_filters = list(session.filters)
        self.residual_cache = None
        self.assign_optional_v_values()
        self.display_processed_df(session.working)
        self.update_field_labels()
        if self.ow_input.currentIndex() == 1:
            self.run_orphan_analysis()
        self.statusBar().showMessage(status_message or 'Map field updated; analysis input is shown in Anomaly Explorer.')

    def map_view_changed(self):
        """Map View dropdown changed: switch between point, contour and web maps."""
        if self.map_view_type.currentText() in (POINT_MAP, CONTOUR_MAP):
            self.map_type_changed()
        #shows the web map if it's selected, otherwise hides it and shows the regular map
        self.web_map()

    def map_type_changed(self):
        if getattr(self, 'current_df', None) is None:
            return
        #keep the scale the map is currently drawn with
        contour = True if self.map_view_type.currentText() == CONTOUR_MAP else None
        self.plot_data(self.current_df, vmin=self.map_vmin, vmax=self.map_vmax, contour=contour)

    def residual_selected(self):
        return self.residual_method.currentText() != TOTAL_FIELD

    def colorbar_label(self):
        mode = self.residual_mode()
        return f'{RESIDUAL_LABELS[mode]} Magnetic Field [uT]' if mode else 'Total Magnetic Field [uT]'

    def residual_mode(self):
        """'trend' or 'igrf' when a residual is selected and applies to the mapped data, otherwise None."""
        if not self.residual_selected():
            return None
        if self.residual_method.currentText() == RESIDUAL_IGRF:
            #RTP and VMD results are already centered on zero, so subtracting the Earth's field would be wrong
            if any(name in self.active_filters for name in IGRF_INCOMPATIBLE_FILTERS):
                return None
            if self.residual_date is None:
                return None
            return 'igrf'
        return 'trend'

    def map_view(self, df):
        """The data as it should be displayed: df itself, or its residual when a residual Field is selected."""
        mode = self.residual_mode()
        if mode is None or df is None or 'Residual_BT' in df.columns:
            return df
        settings = (mode, self.residual_date if mode == 'igrf' else None)
        if self.residual_cache is not None and self.residual_cache[0] is df and self.residual_cache[1] == settings:
            return self.residual_cache[2]
        filters = mf.MapFilter(df)
        try:
            if mode == 'igrf':
                residual = filters.residual_igrf(*self.residual_date)
            else:
                residual = filters.residual_trend()
        except Exception as exc:
            self.statusBar().showMessage(f'Residual could not be calculated: {exc}')
            return df
        self.residual_cache = (df, settings, residual)
        return residual

    def residual_changed(self):
        """Field dropdown changed: check inputs, then redraw every view."""
        #total and residual values are on very different scales, so any typed scale no longer fits
        self.set_vmin.clear()
        self.set_vmax.clear()
        self.vmin = None
        self.vmax = None
        self.map_vmin = None
        self.map_vmax = None
        if self.residual_method.currentText() == RESIDUAL_IGRF:
            if not self.extract_survey_date():
                #go back to Total BT and redraw so the map doesn't keep showing an earlier residual
                self.residual_method.blockSignals(True)
                self.residual_method.setCurrentText(TOTAL_FIELD)
                self.residual_method.blockSignals(False)
                self.residual_date = None
                self.redraw_map_views()
                self.statusBar().showMessage('The IGRF residual needs a valid Survey Date (year, month, day). Fill those in and try again.')
                return
            self.residual_date = (self.date_year, self.date_month, self.date_day)
        self.redraw_map_views()

    def residual_date_changed(self):
        """Recompute the IGRF residual when the survey date is edited while it is shown."""
        if self.residual_method.currentText() != RESIDUAL_IGRF:
            return
        if not self.extract_survey_date():
            return
        new_date = (self.date_year, self.date_month, self.date_day)
        if new_date != self.residual_date:
            self.residual_date = new_date
            self.redraw_map_views()

    def redraw_map_views(self):
        if self.active_session() is None:
            return
        self.residual_cache = None
        self.display_processed_df(self.active_session().working)
        self.update_field_labels()
        if self.ow_input.currentIndex() == 1:
            self.run_orphan_analysis()


    def clear_data(self, df):
        #clear previous plots
        self.axes.clear()
        self.figure.clear()
        self.canvas.draw()

    def upward_continuation(self, df=None):
        if self.active_session() is None or not self.assign_continuation_height():
            return
        result = mf.MapFilter(self.current_df).upward_continuation(H=self.H)
        self.filtered_scale_changed(result, filters=self.active_filters + ['Upward Continuation'], parameters={'height_m': self.H})


    def downward_continuation(self, df=None):
        if self.active_session() is None or not self.assign_continuation_height():
            return
        result = mf.MapFilter(self.current_df).downward_continuation(H=self.H)
        self.filtered_scale_changed(result, filters=self.active_filters + ['Downward Continuation'], parameters={'height_m': self.H})
            #self.plot_data(df)
           # self.plot_data(df)

    def reduction_to_pole(self, df):
        #calls the magnetic filtering class
        filters = mf.MapFilter(self.current_df)
        #extract survey date from the user input
        if not self.extract_survey_date():
            return
        #runs data through reduction to pole filter, sampled back at the survey points
        try:
            df = filters.reduction_to_pole_points(year=self.date_year, month=self.date_month, day=self.date_day)
        except Exception as exc:
            QMessageBox.warning(self, 'RTP Filter', f'RTP filter could not be applied:\n{exc}')
            self.statusBar().showMessage('RTP filter failed.')
            return
        self.filtered_scale_changed(
            df,
            status_message=f'RTP filter applied for {self.date_year}-{self.date_month:02d}-{self.date_day:02d}',
            #RTP runs on the data already on the map, so it adds to any earlier filters
            filters=self.active_filters + ['Reduction to Pole'],
            parameters={'survey_date': [self.date_year, self.date_month, self.date_day]}
        )

    def variational_mode_decomposition(self, df=None):
        source_df = getattr(self, 'current_df', None)
        if source_df is None or getattr(source_df, 'empty', True):
            source_df = getattr(self, 'df', None)
        if source_df is None or getattr(source_df, 'empty', True):
            self.statusBar().showMessage('No data loaded for VMD filtering.')
            return

        try:
            filters = mf.MapFilter(source_df)
            filtered_df, selected_modes, _metrics = filters.variational_mode_decomposition()
        except Exception as exc:
            QMessageBox.warning(self, 'VMD Filter', f'VMD filter could not be applied:\n{exc}')
            self.statusBar().showMessage('VMD filter failed.')
            return

        modes_text = ';'.join(str(mode) for mode in selected_modes)
        self.filtered_scale_changed(
            filtered_df,
            status_message=f'VMD filter applied using selected modes {modes_text}',
            #VMD runs on the data already on the map, so it adds to any earlier filters
            filters=self.active_filters + ['VMD'],
            parameters={'k_modes': 10, 'alpha': 2000.0, 'selected_modes': selected_modes}
        )

    def reset_map(self):
        session = self.active_session()
        if session is None:
            return
        session.reset_field()
        self.active_filters = []
        self.residual_cache = None
        self.set_vmin.clear()
        self.set_vmax.clear()
        self.vmin = self.vmax = self.map_vmin = self.map_vmax = None
        self.residual_method.blockSignals(True)
        self.residual_method.setCurrentText(TOTAL_FIELD)
        self.residual_method.blockSignals(False)
        self.display_processed_df(session.working)
        self.update_field_labels()
        self.filters_workspace.session_changed()
        self.data_workspace.refresh()
        self.run_orphan_analysis()
        self.filters_workspace.session_changed()
        self.statusBar().showMessage('Restored the shared cleaned survey field.')
        if hasattr(self,'project_tools'):self.project_tools.changed()

    def is_imported_file(self, path):
        """True if path is one of the imported source files, so exports never overwrite raw data."""
        target = Path(path).resolve()
        for index in range(self.select_file.count()):
            source = self.select_file.itemData(index, Qt.ItemDataRole.UserRole)
            if source and Path(source).resolve() == target:
                return True
        return False

    def export_dialog(self):
        if getattr(self, 'current_df', None) is None:
            self.statusBar().showMessage('No data to export. Import a dataset first.')
            return
        # suggest a name next to the source file
        default_path = ''
        index = self.select_file.currentIndex()
        if index == -1:
            index = self.active_dataset_index
        if index is not None and 0 <= index < self.select_file.count():
            source_path = Path(self.select_file.itemData(index, Qt.ItemDataRole.UserRole))
            default_path = str(source_path.with_name(f'{source_path.stem}_export.csv'))
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            'Export Data',
            default_path,
            'CSV files (*.csv)',
        )
        if file_path:
            self.export_data(file_path)

    def export_data(self, file_path):
        """Save the mapped data as CSV, plus the map and the current time-series plot as PNGs."""
        base_path = Path(file_path).with_suffix('')
        csv_path = base_path.with_suffix('.csv')
        map_path = base_path.with_name(f'{base_path.name}_map.png')
        plot_path = base_path.with_name(f'{base_path.name}_timeseries.png')
        if any(self.is_imported_file(path) for path in (csv_path, map_path, plot_path)):
            QMessageBox.warning(self, 'Export Data', 'That name would overwrite an imported data file. Choose a different name.')
            return

        written = []
        try:
            self.active_session().cleaned.to_csv(csv_path, index=False)
            written.append(csv_path)
            self.canvas.print_figure(str(map_path))
            written.append(map_path)
            current_plot = self.plot_tabs.currentWidget()
            if current_plot is not None:
                plot_canvas = current_plot.layout().itemAt(0).widget()
                plot_canvas.figure.savefig(plot_path)
                written.append(plot_path)
        except Exception as exc:
            QMessageBox.warning(self, 'Export Data', f'Export failed:\n{exc}')
            self.statusBar().showMessage('Export failed.')
            return
        self.statusBar().showMessage(f'Dataset Successfully Exported to {base_path.parent} ({len(written)} files)')
    def export_orphan_results(self):
        """Save the Anomaly Explorer results: scored points, candidate clusters, summary and engineering map."""
        if self.ow_annotated_df is None:
            self.statusBar().showMessage('No orphan-well results to export. Import a dataset first.')
            return

        # suggest a name next to the source file
        default_path = ''
        index = self.ow_selected_dataset_index
        if index is not None and 0 <= index < self.select_file.count():
            source_path = Path(self.select_file.itemData(index, Qt.ItemDataRole.UserRole))
            default_path = str(source_path.with_name(f'{source_path.stem}_anomalies.csv'))
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            'Export Anomaly Explorer Results',
            default_path,
            'CSV files (*.csv)',
        )
        if not file_path:
            return

        base_path = Path(file_path).with_suffix('')
        points_path = base_path.with_suffix('.csv')
        output_paths = [points_path] + [
            base_path.with_name(f'{base_path.name}{suffix}')
            for suffix in ('_clusters.csv', '_summary.txt', '_engineering_map.png', '_xai_explanation.txt', '_xai_contributions.csv', '_xai_clusters.csv', '_xai.png')
        ]
        if any(self.is_imported_file(path) for path in output_paths):
            QMessageBox.warning(self, 'Anomaly Explorer Export', 'That name would overwrite an imported data file. Choose a different name.')
            return
        written = [points_path]
        try:
            self.ow_annotated_df.to_csv(points_path, index=False)
            if self.ow_clusters is not None and not self.ow_clusters.empty:
                clusters_path = base_path.with_name(f'{base_path.name}_clusters.csv')
                self.ow_clusters.to_csv(clusters_path, index=False)
                written.append(clusters_path)
            summary_path = base_path.with_name(f'{base_path.name}_summary.txt')
            summary_path.write_text(self.ow_summary.toPlainText(), encoding='utf-8')
            written.append(summary_path)
            map_path = base_path.with_name(f'{base_path.name}_engineering_map.png')
            report=getattr(self,'ow_geoxai_report',None)
            if report is not None:
                for suffix,content in [('_xai_explanation.txt',report.narrative),('_xai_contributions.csv',report.contributions),('_xai_clusters.csv',report.cluster_scores)]:
                    path=base_path.with_name(base_path.name+suffix)
                    if isinstance(content,str):path.write_text(content,encoding='utf-8')
                    else:content.to_csv(path,index=False)
                    written.append(path)
                xai_path=base_path.with_name(base_path.name+'_xai.png');self.ow_geoxai_figure.savefig(xai_path,dpi=200,bbox_inches='tight');written.append(xai_path)
            self.ow_cluster_figure.savefig(map_path, dpi=200, bbox_inches='tight')
            written.append(map_path)
        except Exception as exc:
            QMessageBox.warning(self, 'Anomaly Explorer Export', f'Export failed:\n{exc}')
            self.statusBar().showMessage('Anomaly Explorer export failed.')
            return

        self.statusBar().showMessage(f'Anomaly Explorer results exported to {base_path.parent} ({len(written)} files)')

    #def sampling frequency
    #   add ability to set sampling frequency and adjust the filters class so it's not static at d=1

    #def rewind action
    #   allows users to go back one step
#%% Executing app
if __name__ == '__main__':
    catchErrors() # prevent crash of the app
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        startup_file = sys.argv[1]
        if Path(startup_file).suffix.lower() in ('.smmproj','.bak1','.bak2','.bak3'):
            QTimer.singleShot(250, lambda: window.project_tools.open_project(path=Path(startup_file)))
        else:QTimer.singleShot(250, lambda: window.load_orphan_well_file(startup_file))
    sys.exit(app.exec())
