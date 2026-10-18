from PyQt6.QtCore import QSize, Qt, QTimer, QSortFilterProxyModel, QUrl
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QFont
from PyQt6.QtWidgets import (QApplication, QCheckBox, QLabel, QMainWindow,
                             QStatusBar, QToolBar, QWidget, QPushButton,
                             QVBoxLayout, QHBoxLayout, QFileDialog, QTableWidget,
                             QTableWidgetItem, QLineEdit, QMessageBox,
                             QRadioButton, QComboBox, QTabWidget, QTableView,
                             QHeaderView, QStackedLayout, QGroupBox,
                             QFormLayout, QDoubleSpinBox, QSpinBox, QTextEdit,
                             QSplitter, QScrollArea)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import folium
import branca.colormap as cm
from pathlib import Path
import ExcelReader as er
import MapFilter as mf
import MapMaker as mm
import DialogWindow as dw
import PlotData as plot
import WebMap as wm
import TableModel
import OrphanWellPipeline as ow
import GeoXAIInterpreter as gx
import sys, os, tempfile

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
        self.df_list = list()
        self.processed_dfs = {}  # Cache for processed dataframes
        self.dialog_configs = {}  # Cache for dialog config per file index
        self.mag_gps_dfs = {}  # Cache for magdf/gpsdf per file index
        self.active_dataset_index = None  # df_list index of the dataset shown on the map
        self.active_filters = []  # filters applied to the mapped data, in order, for plot titles
        self.map_vmin = None  # color scale on the regular map, shared with the web map
        self.map_vmax = None
        self.residual_date = None  # (year, month, day) used for the IGRF residual
        self.residual_cache = None  # (source df, settings, residual df) so redraws don't recompute

    def initUI(self):
        #sets the window title
        self.setWindowTitle('SmartMagMapper')
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
        #creates the toolbar
        self.create_toolbar()
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
        self.select_file.setPlaceholderText('Select File to Display')
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
        button_layout_2.addWidget(self.select_file)
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
        self.tabs.addTab(self.data, 'Data Table')
        map_widget = QWidget()
        map_widget.setLayout(self.map_layout)
        self.tabs.addTab(map_widget,'Map')
        #table_widget = QWidget()
        #table_widget.setLayout(table_layout)
        self.plot_tabs = QTabWidget()
        self.plot_widget = QWidget()
        #creating the plot layout
        self.plot_layout = QVBoxLayout()
        self.plot_layout.addWidget(self.plot_tabs)
        #plot_layout.addWidget(self.chart)
        self.plot_widget.setLayout(self.plot_layout)
        self.tabs.addTab(self.plot_widget, 'Time-Series Data')
        self.orphan_well_widget = self.create_orphan_well_tab()
        self.tabs.addTab(self.orphan_well_widget, 'OrphaMag')
        self.tabs.currentChanged.connect(self.update_global_controls_visibility)
        main_layout.addWidget(self.tabs)
        self.setCentralWidget(central_widget)
        #self.setCentralWidget(central_widget)
        self.setMinimumSize(1200, 760)
        self.resize(1500, 900)

    def update_global_controls_visibility(self, index):
        if hasattr(self, 'global_controls_widget'):
            self.global_controls_widget.setVisible(self.tabs.tabText(index) != 'OrphaMag')
        # Update orphan well dataset selector when switching to OrphaMag tab
        if index == 1 and self.tabs.tabText(index) == 'OrphaMag':
            self._populate_ow_dataset_selector()


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

        # Dataset selection dropdown
        dataset_layout = QHBoxLayout()
        dataset_label = QLabel('Select Dataset:')
        self.ow_dataset_selector = QComboBox()
        self.ow_dataset_selector.setPlaceholderText('Choose imported dataset...')
        self.ow_dataset_selector.currentIndexChanged.connect(self._update_ow_dataset)
        dataset_layout.addWidget(dataset_label)
        dataset_layout.addWidget(self.ow_dataset_selector)
        dataset_layout.addStretch()
        controls_layout.addLayout(dataset_layout)

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
        self.ow_well_lat.setPlaceholderText('Optional, e.g. 42.142823')
        self.ow_well_lon = QLineEdit()
        self.ow_well_lon.setPlaceholderText('Optional, e.g. -75.824952')
        for well_field in (self.ow_well_lat, self.ow_well_lon):
            well_field.setAlignment(Qt.AlignmentFlag.AlignRight)
            well_field.setClearButtonEnabled(True)

        form.addRow('Known well latitude', self.ow_well_lat)
        form.addRow('Known well longitude', self.ow_well_lon)
        form.addRow('Startup samples removed', self.ow_startup_samples)
        form.addRow('Spatial MAD filter', self.ow_spatial_mad)
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
        self.ow_summary.setMinimumHeight(280)
        self.ow_summary.setMaximumHeight(420)
        self.ow_summary.setText('Use the top Import Data button while this tab is active to run the orphan-well workflow.')

        controls_panel = QWidget()
        controls_panel_layout = QVBoxLayout(controls_panel)
        controls_panel_layout.setContentsMargins(0, 0, 0, 0)
        controls_panel_layout.setSpacing(10)
        controls_panel_layout.addWidget(controls)
        controls_panel_layout.addWidget(QLabel('Result summary'))
        controls_panel_layout.addWidget(self.ow_summary)
        controls_panel_layout.addStretch()

        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setWidget(controls_panel)
        controls_scroll.setMinimumWidth(360)
        controls_scroll.setMaximumWidth(450)

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
        self.ow_cluster_canvas.setMinimumHeight(560)

        self.ow_score_figure = Figure(figsize=(8.5, 4.8), constrained_layout=True)
        self.ow_score_canvas = FigureCanvas(self.ow_score_figure)
        self.ow_score_canvas.setMinimumHeight(500)

        self.ow_field_figure = Figure(figsize=(8.5, 4.8), constrained_layout=True)
        self.ow_field_canvas = FigureCanvas(self.ow_field_figure)
        self.ow_field_canvas.setMinimumHeight(500)

        self.ow_modes_figure = Figure(figsize=(8.5, 4.8), constrained_layout=True)
        self.ow_modes_canvas = FigureCanvas(self.ow_modes_figure)
        self.ow_modes_canvas.setMinimumHeight(500)

        self.ow_geoxai_text = QTextEdit()
        self.ow_geoxai_text.setReadOnly(True)
        self.ow_geoxai_text.setMinimumHeight(230)
        self.ow_geoxai_text.setText('Import a survey to generate a GeoXAI candidate explanation.')
        self.ow_geoxai_figure = Figure(figsize=(8.5, 4.8), constrained_layout=True)
        self.ow_geoxai_canvas = FigureCanvas(self.ow_geoxai_figure)
        self.ow_geoxai_canvas.setMinimumHeight(420)

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

        self.ow_visual_tabs.addTab(self.ow_web_map, 'Map')
        self.ow_visual_tabs.addTab(plot_page(self.ow_cluster_canvas), 'Engineering Map')
        self.ow_visual_tabs.addTab(plot_page(self.ow_field_canvas), 'Total Field')
        self.ow_visual_tabs.addTab(plot_page(self.ow_modes_canvas), 'VMD Modes')
        self.ow_visual_tabs.addTab(plot_page(self.ow_score_canvas), 'Scores')
        self.ow_visual_tabs.addTab(geoxai_page, 'GeoXAI')

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(controls_scroll)
        splitter.addWidget(self.ow_visual_tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([390, 1040])
        root_layout.addWidget(splitter)

        clean_widgets = [self.ow_startup_samples, self.ow_spatial_mad]
        analysis_widgets = [
            self.ow_window_length,
            self.ow_step_ratio,
            self.ow_gamma,
            self.ow_dbscan_eps,
            self.ow_min_samples,
        ]
        for spinbox in clean_widgets:
            spinbox.valueChanged.connect(self.schedule_orphan_reload)
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


    def create_toolbar(self):
        #creates the toolbar
        self.toolbar = QToolBar('Main Toolbar')
        #sets the toolbar to the main window
        self.addToolBar(self.toolbar)
        #creates action for opening files
        open_action = QAction('Import Data', self)
        open_action.setStatusTip('Import Excel Data')
        open_action.triggered.connect(self.import_data_action)
        self.toolbar.addAction(open_action)

        #export cleaned dataset
        export_data = QAction('Export Data', self)
        export_data.triggered.connect(self.export_dialog)
        self.toolbar.addAction(export_data)

        #filter_actions
        filter_action = QAction('Upward Continuation', self)
        #filter_action.setStatusTip('Filter Applied to Data')
        filter_action.triggered.connect(self.upward_continuation)
        #self.toolbar.addAction(filter_action)

        filter2_action = QAction('Downward Continuation', self)
        filter2_action.triggered.connect(self.downward_continuation)
        #toolbar.addAction(filter2_action)

        rtp_action = QAction('Reduction to Pole', self)
        rtp_action.triggered.connect(self.reduction_to_pole)

        vmd_action = QAction('Variational Mode Decomposition', self)
        vmd_action.triggered.connect(self.variational_mode_decomposition)

        #reset_canvas_actions
        reset_canvas_action = QAction('Clear Figure', self)
        #filter_action.setStatusTip('Filter Applied to Data')
        reset_canvas_action.triggered.connect(self.clear_data)
        #self.toolbar.addAction(reset_canvas_action)

        #reset map action
        reset_map = QAction('Reset Map', self)
        reset_map.triggered.connect(self.reset_map)
        self.toolbar.addAction(reset_map)

        #set v values action
        set_value_action = QAction('Change Map Scale', self)
        set_value_action.triggered.connect(self.scale_changed)
        self.toolbar.addAction(set_value_action)

        #change the data visualized in the plot
        plot_data = QAction('Change Plot', self)
        plot_data.triggered.connect(self.plot_changed)
        #self.toolbar.addAction(plot_data)

        self.menu = self.menuBar()
        self.file_menu = self.menu.addMenu('&File')
        self.file_menu.addAction(open_action)
        self.file_menu.addAction(reset_map)
        self.file_menu.addAction(export_data)

        self.edit_menu = self.menu.addMenu('&Plot')

        self.filters_menu = self.menu.addMenu('&Apply Filters')
        self.filters_menu.addAction(filter_action)
        self.filters_menu.addAction(filter2_action)
        self.filters_menu.addAction(rtp_action)
        self.filters_menu.addAction(vmd_action)
        self.toolbar.addAction(self.filters_menu.menuAction())

        #export_actions

    #def create_menu(self):
        #add menu with actions from toolbar

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
    #will probably have to change this when adding the ability to manually choose columns
        try:
            self.file_paths = self.dlg.file_paths
            raw_file = self.dlg.raw_file
            if raw_file is not None and self.file_paths:
                # the dialog only reads the first selected file
                file_index = self.store_dataset(self.file_paths[0], raw_file)
                for index, value in enumerate(self.df_list):
                    print(f"Index: {index}, Value: {value}")
                self.read_file(file_index)
                # Update orphan well dataset selector and switch it to the imported file
                self._populate_ow_dataset_selector(select_index=file_index)
                print('Yeahh!')
        except Exception as e:
            print(f':( {e}')
            import traceback
            traceback.print_exc()

    def store_dataset(self, file_path, raw_file):
        """Add an imported file to df_list and the file selector at the same index.
        Re-importing the same file replaces its entry instead of adding a duplicate."""
        file_path = str(file_path)
        file_index = self.select_file.findData(file_path)
        if file_index != -1:
            self.df_list[file_index] = raw_file
            # drop cached results so the file is reprocessed with the new dialog settings
            for cache in (self.processed_dfs, self.dialog_configs, self.mag_gps_dfs):
                cache.pop(file_index, None)
            return file_index

        # df_list must be updated before addItem, which can trigger select_display_file
        self.df_list.append(raw_file)
        label = os.path.basename(file_path)
        if self.select_file.findText(label) != -1:
            # different file with the same name, so show its folder too
            label = f'{label} ({os.path.basename(os.path.dirname(file_path))})'
        self.select_file.addItem(label, userData=file_path)
        return len(self.df_list) - 1

    def _populate_ow_dataset_selector(self, select_index=None):
        """Update the orphan well dataset dropdown with current imported datasets.
        Keeps the user's selection unless a dataset was imported, and only
        reruns the pipeline when the selected dataset actually changes.
        Passing select_index selects that dataset and always reruns the pipeline."""
        previous_index = self.ow_dataset_selector.currentIndex()
        previous_count = self.ow_dataset_selector.count()

        self.ow_dataset_selector.blockSignals(True)
        self.ow_dataset_selector.clear()

        for index, df in enumerate(self.df_list):
            # Use file name from select_file combobox if available, else use index
            if index < self.select_file.count():
                label = self.select_file.itemText(index)
            else:
                label = f'Dataset {index}'
            self.ow_dataset_selector.addItem(label, index)

        count = self.ow_dataset_selector.count()
        if count == 0:
            self.ow_dataset_selector.blockSignals(False)
            return
        # Jump to the requested or newest dataset after an import, otherwise keep the current selection
        if select_index is not None and 0 <= select_index < count:
            target_index = select_index
        elif count > previous_count or not 0 <= previous_index < count:
            target_index = count - 1
        else:
            target_index = previous_index
        self.ow_dataset_selector.setCurrentIndex(target_index)
        self.ow_dataset_selector.blockSignals(False)

        if select_index is not None or target_index != self.ow_selected_dataset_index:
            self._update_ow_dataset(target_index)

    def _update_ow_dataset(self, index):
        """Handle orphan well dataset selection change and automatically process."""
        if index < 0 or index >= len(self.df_list):
            return
        # Store the selected dataset for use in the pipeline
        self.ow_selected_dataset = self.df_list[index]
        self.ow_selected_dataset_index = index
        self.statusBar().showMessage(f'Selected dataset: {self.ow_dataset_selector.itemText(index)}')

        # Automatically trigger the orphan well pipeline
        self.process_orphan_well_dataset()

    def _dialog_finish_handler(self):
        """Validate dialog dropdowns before finishing. If any required field is empty,
        show the dialog's missing_variable_warning. Otherwise assign variables,
        read from dialog and accept the dialog."""
        dlg = self.dlg
        # Determine required fields based on mag type
        if dlg.VectorMag.isChecked():
            mag_widgets = [dlg.XMagField, dlg.YMagField, dlg.ZMagField]
        else:
            mag_widgets = [dlg.TotalMagField]

        # Determine required fields based on time type
        if dlg.SingleTime.isChecked():
            time_widgets = [dlg.TotalTime]
        else:
            time_widgets = [dlg.MagTime, dlg.LocTime]

        coord_widgets = [dlg.XLatitude, dlg.YLongitude]
        required_widgets = mag_widgets + time_widgets + coord_widgets

        self.missing = []
        for w in required_widgets:
            try:
                text = w.currentText()
            except Exception:
                try:
                    text = w.text()
                except Exception:
                    text = ''
            if not text:
                self.missing.append(w)

        if self.missing:
            try:
                self.dlg.missing_variable_warning()
            except Exception:
                self.statusBar().showMessage('Missing variables in dialog. Please fill all required fields.')
            return

        # all good: assign variables, process and close dialog
        try:
            dlg.assign_variables()
        except Exception:
            pass
        try:
            self.read_from_dialog()
        except Exception:
            pass
        try:
            dlg.accept()
        except Exception:
            pass

    def read_file(self, file_index):
        self.active_dataset_index = file_index
        self.short_name = self.select_file.itemText(file_index)
        self.select_file.setPlaceholderText(self.short_name)
        self.excel_reader(df=self.df_list[file_index], cache_index=file_index)
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
            window_length_m=float(self.ow_window_length.value()),
            step_ratio=float(self.ow_step_ratio.value()),
            gamma=float(self.ow_gamma.value()),
            dbscan_eps_m=float(self.ow_dbscan_eps.value()),
            dbscan_min_samples=int(self.ow_min_samples.value()),
        )

    def schedule_orphan_analysis(self):
        if self.ow_clean_df is None or self.ow_modes is None:
            return
        self.ow_update_timer.start(350)

    def schedule_orphan_reload(self):
        if self.ow_selected_dataset is None and self.ow_file_path is None:
            return
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
        test_path = (
            Path(__file__).resolve().parents[1]
            / 'Orphan Well Data'
            / 'Butkowsky 1A Surveys 10_09_25'
            / 'McKee_Seth.xls'
        )
        if not test_path.exists():
            test_path = Path(
                r'C:\Users\nimri\OneDrive\Desktop\Retreived OW\Orphan Well Data\Butkowsky 1A Surveys 10_09_25\McKee_Seth.xls'
            )
        if not test_path.exists():
            QMessageBox.warning(self, 'Missing test survey', f'Could not find test survey:\n{test_path}')
            return
        self.load_orphan_well_file(str(test_path))

    def reload_orphan_well_file(self):
        # Datasets from the main import are re-cleaned from the cached mag/gps data
        if self.ow_selected_dataset is not None:
            self.process_orphan_well_dataset()
            return
        if self.ow_file_path is None:
            self.statusBar().showMessage('No orphan-well survey loaded.')
            return
        self.load_orphan_well_file(self.ow_file_path)

    def process_orphan_well_dataset(self):
        """Process the selected dataset from the dropdown through the orphan well pipeline."""
        if not hasattr(self, 'ow_selected_dataset') or self.ow_selected_dataset is None:
            self.statusBar().showMessage('Please select a dataset from the dropdown first.')
            return

        dataset_index = self.ow_selected_dataset_index
        if dataset_index not in self.mag_gps_dfs:
            self.statusBar().showMessage('Dataset not yet processed. Please re-import the dataset.')
            return

        params = self.orphan_params()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.statusBar().showMessage('Processing selected dataset through orphan well pipeline...')

            # Use cached magdf and gpsdf from excel_reader for this dataset
            magdf, gpsdf = self.mag_gps_dfs[dataset_index]

            # Process through pipeline
            clean_df, audit = ow.clean_survey(magdf, gpsdf, params)
            modes, mode_metrics, selected_modes = ow.run_vmd_modes(clean_df, params)
            self.ow_clean_df = clean_df
            self.ow_audit = audit
            self.ow_modes = modes
            self.ow_mode_metrics = mode_metrics
            self.ow_selected_modes = selected_modes
            self.run_orphan_analysis()
            dataset_name = self.ow_dataset_selector.currentText()
            self.statusBar().showMessage(f'Orphan-well processing complete: {dataset_name}')
        except Exception as exc:
            QMessageBox.critical(self, 'Orphan-well processing failed', str(exc))
            self.statusBar().showMessage('Orphan-well processing failed.')
        finally:
            QApplication.restoreOverrideCursor()

    def load_orphan_well_file(self, file_path):
        self.ow_file_path = str(file_path)
        self.ow_selected_dataset = None
        self.ow_selected_dataset_index = None
        params = self.orphan_params()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.statusBar().showMessage(f'Processing orphan-well survey: {file_path}')
            clean_df, audit = ow.load_and_clean(file_path, params)
            modes, mode_metrics, selected_modes = ow.run_vmd_modes(clean_df, params)
            self.ow_clean_df = clean_df
            self.ow_audit = audit
            self.ow_modes = modes
            self.ow_mode_metrics = mode_metrics
            self.ow_selected_modes = selected_modes
            self.run_orphan_analysis()
            short_name = os.path.basename(str(file_path))
            self.tabs.setCurrentWidget(self.orphan_well_widget)
            self.statusBar().showMessage(f'Orphan-well processing complete: {short_name}')
        except Exception as exc:
            QMessageBox.critical(self, 'Orphan-well processing failed', str(exc))
            self.statusBar().showMessage('Orphan-well processing failed.')
        finally:
            QApplication.restoreOverrideCursor()

    def run_orphan_analysis(self):
        if self.ow_clean_df is None or self.ow_modes is None:
            return
        params = self.orphan_params()
        try:
            score_points, clusters, summary = ow.analyze_with_cached_modes(
                self.ow_clean_df,
                self.ow_modes,
                self.ow_selected_modes,
                params,
            )
            annotated = ow.annotate_clean_points(
                ow.add_well_distance(self.ow_clean_df, params),
                score_points,
                clusters,
            )
            self.ow_score_points = score_points
            self.ow_clusters = clusters
            self.ow_summary_data = summary
            self.ow_annotated_df = annotated
            #results stay on the OrphaMag tab so the main map, table and filters keep the imported data
            self.plot_orphan_results(annotated, score_points, clusters, summary)
            self.ow_summary.setText(self.format_orphan_summary(summary))
            self.statusBar().showMessage(
                f"Candidate clusters: {summary.get('n_clusters', 0)} | hits: {summary.get('n_hits', 0)}"
            )
        except Exception as exc:
            QMessageBox.critical(self, 'Orphan-well analysis failed', str(exc))
            self.statusBar().showMessage('Orphan-well analysis failed.')

    def format_orphan_summary(self, summary):
        if not summary:
            return 'No orphan-well analysis has been run.'
        lines = []
        lines.append('Candidate Estimate')
        lines.append('------------------')
        if 'candidate_latitude' in summary:
            lines.extend([
                f"Latitude:  {summary['candidate_latitude']:.6f}",
                f"Longitude: {summary['candidate_longitude']:.6f}",
                f"UTM zone: {summary.get('utm_zone', '?')}",
                f"UTM Easting:  {summary['candidate_easting_m']:.2f} m",
                f"UTM Northing: {summary['candidate_northing_m']:.2f} m",
                f"Uncertainty radius: {summary['candidate_radius_m']:.2f} m",
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
        ax_field.set_title('Cleaned total magnetic field', pad=12)
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
            self.ow_cluster_figure.colorbar(scatter, ax=ax_map, fraction=0.038, pad=0.02, label='Anomaly score')
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
                    label='selected candidate' if selected else None,
                    zorder=6 if selected else 4,
                )
                ax_map.annotate(
                    f"C{int(row['cluster_label'])}",
                    (row['centroid_e_m'], row['centroid_n_m']),
                    xytext=(4, 4),
                    textcoords='offset points',
                    fontsize=8,
                )
        title = 'Score windows, clusters, and candidate'
        if well is None:
            title += ' (unknown true location)'
        ax_map.set_title(title, pad=12)
        zone = ow.utm_zone_label(epsg)
        ax_map.set_xlabel(f'UTM {zone} Easting (m)')
        ax_map.set_ylabel(f'UTM {zone} Northing (m)')
        ax_map.set_aspect('equal', adjustable='box')
        ax_map.legend(loc='upper left', fontsize=8, frameon=True)
        self.style_orphan_axis(ax_map)
        self.ow_cluster_canvas.draw_idle()

    def plot_orphan_mode_metrics(self):
        self.ow_modes_figure.clear()
        ax_modes = self.ow_modes_figure.add_subplot(111)
        if self.ow_mode_metrics is not None and not self.ow_mode_metrics.empty:
            colors = ['#0F766E' if bool(v) else '#94A3B8' for v in self.ow_mode_metrics['selected']]
            ax_modes.bar(self.ow_mode_metrics['mode'], self.ow_mode_metrics['energy_ratio'], color=colors, width=0.72)
        else:
            ax_modes.text(0.5, 0.5, 'No mode metrics', ha='center', va='center', transform=ax_modes.transAxes)
        ax_modes.set_title('VMD mode energy selection', pad=12)
        ax_modes.set_xlabel('Mode')
        ax_modes.set_ylabel('Energy ratio')
        self.style_orphan_axis(ax_modes)
        self.ow_modes_canvas.draw_idle()

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
        self.ow_geoxai_text.setText(report.narrative)

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
            ax_clusters.barh(labels, scored['geo_xai_confidence'], color=colors)
            ax_clusters.set_xlim(0, 1)
            ax_clusters.set_title('Cluster confidence comparison', pad=12)
            ax_clusters.set_xlabel('GeoXAI confidence')
            for index, value in enumerate(scored['geo_xai_confidence']):
                ax_clusters.text(float(value) + 0.015, index, f'{100.0 * float(value):.0f}', va='center', fontsize=8)
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

    def assign_v_values(self):
        #self.vmin = self.set_vmin.text()
        #self.vmax = self.set_vmax.text()
        valid = True
        vmin_entry = self.set_vmin.text()
        if vmin_entry.strip() == '':
            self.vmin = None
            self.statusBar().showMessage('Minimum/Maximum Scale Value(s) Not Entered (fill min/max scale fields). Try again.')
            valid = False
        try:
            self.vmin = float(vmin_entry)
            #self.statusBar().showMessage('Field Scale Changed')
        except ValueError:
            #self.statusBar().showMessage('Invalid field value entered (must be a number)')
            valid = True

        vmax_entry = self.set_vmax.text()
        if vmax_entry.strip() == '':
            self.vmax = None
            self.statusBar().showMessage('Minimum/Maximum Scale Value(s) Not Entered (fill min/max scale fields). Try again.')
            valid = False
        try:
            self.vmax = float(vmax_entry)
            #self.statusBar().showMessage('Field Scale Changed')
            #self.statusBar().showMessage(f'Continuation Height={self.Hm')

        except ValueError:
            #self.statusBar().showMessage('Invalid field value entered (must be a number)')
            valid = True

        return valid

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
        file_entry = self.select_file.itemData(index, Qt.ItemDataRole.UserRole)
        current_index = self.select_file.currentIndex()
        print(f'current index: {current_index}')
        if current_index != -1:
            self.active_dataset_index = current_index
        try:
            if current_index in self.processed_dfs:
                # Already processed, just display
                self.display_processed_df(self.processed_dfs[current_index])
            else:
                # First time, process and cache
                self.excel_reader(df=self.df_list[current_index], cache_index=current_index)

        except ValueError:
            self.statusBar().showMessage('File not selected. Try again.')
            return False

    def excel_reader(self, df, cache_index=None):#, file_path):
        self.active_filters = []
        self.plot_tabs.clear()

        # Use cached dialog config if available, otherwise use current dialog values
        if cache_index is not None and cache_index in self.dialog_configs:
            config = self.dialog_configs[cache_index]
            bx, by, bz, bt, lat, lon, loc_time, mag_time, total_time, use_single_time = config
        else:
            bx = self.dlg.BX
            by = self.dlg.BY
            bz = self.dlg.BZ
            bt = self.dlg.BT
            lat = self.dlg.Lat
            lon = self.dlg.Lon
            loc_time = self.dlg.LocTime
            mag_time = self.dlg.MagTime
            total_time = self.dlg.TotalTime
            use_single_time = self.dlg.SingleTime.isChecked()

            # Cache the config for this file
            if cache_index is not None:
                self.dialog_configs[cache_index] = (bx, by, bz, bt, lat, lon, loc_time, mag_time, total_time, use_single_time)

        if not bt:
            mag_columns = [f'{bx}', f'{by}', f'{bz}']
            rename_mag_columns = {f'{bx}': 'X (µT)', f'{by}': 'Y (µT)', f'{bz}': 'Z (µT)'}
        else:
            mag_columns = [f'{bt}']
            rename_mag_columns = {f'{bt}': 'BT'}

        # Handle time columns based on selection
        if use_single_time:
            time_columns = [f'{total_time}']
            rename_time_columns = {f'{total_time}': 'Mag_Time (s)'}
            gps_time_col = f'{total_time}'
        else:
            time_columns = [f'{mag_time}', f'{loc_time}']
            rename_time_columns = {f'{mag_time}': 'Mag_Time (s)', f'{loc_time}': 'Loc_Time (s)'}
            gps_time_col = f'{loc_time}'

        mag_columns.extend(time_columns)
        rename_mag_columns.update(rename_time_columns)

        gps_columns = [f'{lat}', f'{lon}', gps_time_col]
        rename_gps_columns = {f'{lat}': 'Latitude (°)', f'{lon}': 'Longitude (°)', gps_time_col: 'Loc_Time (s)'}

        self.df = df

        self.magdf = self.df[mag_columns]
        self.magdf = self.magdf.rename(columns=rename_mag_columns)
        self.gpsdf = self.df[gps_columns]
        self.gpsdf = self.gpsdf.rename(columns=rename_gps_columns)

        # Cache magdf and gpsdf for orphan well processing
        if cache_index is not None:
            self.mag_gps_dfs[cache_index] = (self.magdf.copy(), self.gpsdf.copy())

        excelreader = er.ExcelReader(self.magdf, self.gpsdf)
        self.df = excelreader.read_mag_field()
        #self.df = excelreader.input_sheets()
        self.df = excelreader.interpolate()
        #self.df = excelreader.alignTime()
        self.df = excelreader.convertUTM()
        self.df = excelreader.distance()

        # Cache the processed result before displaying
        if cache_index is not None:
            self.processed_dfs[cache_index] = self.df.copy()

        self.statusBar().showMessage(f'Successfully Loaded {self.file_paths}')
        self.plot_data(self.df)
        self.plot_table(self.df)
        self.new_plot(df=self.df, name='BT', column=self.df['BT'])
        self.add_menu(columns=self.df.columns)

    def add_menu(self, columns):
        if hasattr(self, 'select_data') and self.select_data:
            self.edit_menu.removeAction(self.select_data.menuAction())
            self.select_data.deleteLater()
        self.select_data = self.edit_menu.addMenu('&Select data')
        for column in columns:
            add_column = QAction(column, self)
            self.select_data.addAction(add_column)
            add_column.triggered.connect(lambda _, col=column: self.plot_changed(val=col))

    def display_processed_df(self, df):
        """Display a previously processed dataframe without re-processing"""
        self.active_filters = []
        self.df = df
        self.plot_tabs.clear()
        self.statusBar().showMessage(f'Successfully Loaded {self.file_paths}')
        self.plot_data(self.df)
        self.plot_table(self.df)

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
        self.model = TableModel.TableModel(df)
        self.data.setModel(self.model)
        self.proxyModel = QSortFilterProxyModel()
        self.proxyModel.setSourceModel(self.data.model())
        self.proxyModel.setSortRole(Qt.ItemDataRole.EditRole)
        self.data.setSortingEnabled(True)
        self.data.setModel(self.proxyModel)
        #self.data.resizeColumnsToContents()
        header = self.data.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    def update_current_plot(self, ymin=None, ymax=None):
        idx = self.plot_tabs.currentIndex()
        current_plot = self.plot_tabs.widget(idx)
        if current_plot is not None:
            canvas = current_plot.layout().itemAt(0).widget()
            fig = canvas.figure
            ax = fig.axes[0]
            ax.clear()
            column = getattr(current_plot, 'column', None)
            df = getattr(current_plot, 'df', None)
            if column is not None and df is not None:
                self.plotter = plot.PlotData(df)
                self.plotter.plot(val=column, ax=ax, ymin=ymin, ymax=ymax, title=getattr(current_plot, 'title', None))
            if ymin is not None and ymax is not None:
                ax.set_ylim(ymin, ymax)
            canvas.draw()

    def plot_changed(self, val=None, ymin=None, ymax=None):
        print(f'success! y axis: {val}')
        self.new_plot(name=val, df=self.current_df, column=self.current_df[val])

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

    def new_plot(self, df, name, ymin=None, ymax=None, column=None, ax=None):
        #BT plots follow the Residual Map setting, like the map
        if getattr(column, 'name', None) == 'BT' and df is not None:
            view = self.map_view(df)
            if view is not df:
                df, column = view, view['BT']
        suffix = self.filter_suffix(column)
        name = f'{name}{suffix}'
        title = f'Total Magnetic Field v Time{suffix}'
        fig = Figure()
        #plot_layout = QStackedLayout()
        plot_axes = fig.add_subplot()
        self.plotter = plot.PlotData(df)
        self.plotter.plot(val=column, ax=plot_axes, ymin=ymin, ymax=ymax, color=None, title=title)
        plot_canvas = FigureCanvas(fig)
        plot_tabs = QWidget()
        plot_layout = QVBoxLayout()
        plot_layout.addWidget(plot_canvas)
        plot_tabs.setLayout(plot_layout)
        plot_tabs.column = column
        plot_tabs.df = df
        plot_tabs.title = title
        self.plot_tabs.addTab(plot_tabs, f'{name}')
        plot_canvas.draw()


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

    def scale_changed(self, df, contour=None):
        #checks if v values were assigned
        if not self.assign_v_values():
            return
        if self.map_view_type.currentText() == CONTOUR_MAP:
            contour=True
        #refreshs the graph after clearing
        self.figure.clear()
        #replot the figure widget
        self.axes = self.figure.add_subplot()
        mapper = mm.MapMaker(self.current_df)
        self.assign_v_values()
        self.plot_data(df=self.current_df, vmin=self.vmin, vmax=self.vmax, contour=contour)
        self.update_current_plot(ymin=self.vmin, ymax=self.vmax)

    def filtered_scale_changed(self, df, contour=None, status_message=None, filters=None):
        #checks if v values were assigned
        if not self.assign_optional_v_values():
            return
        #filters lists every filter now applied to df, used to label the time-series plots
        if filters is not None:
            self.active_filters = list(filters)
        if self.map_view_type.currentText() == CONTOUR_MAP:
            contour=True
        #refreshs the graph after clearing
        self.figure.clear()
        #replot the figure widget
        self.axes = self.figure.add_subplot()
        mapper = mm.MapMaker(df)
        self.assign_optional_v_values()
       # if (vmin, vmax) is None:
        mapper.showMap(self.map_view(df), ax=self.axes, vmin=self.vmin, vmax=self.vmax, contour=contour,
                        cbar_label=self.colorbar_label())
        if status_message is None:
            status_message = f'Continuation Height={self.H}m' if hasattr(self, 'H') else 'Filter applied'
        if self.residual_selected() and self.residual_mode() is None:
            status_message += f' | {IGRF_SKIPPED_MESSAGE}'
        self.statusBar().showMessage(status_message)
       # else:
       #     mapper.showMap(df, ax=self.axes, vmin=vmin, vmax=vmax)
        self.canvas.draw()
        self.current_df = df
        self.map_vmin, self.map_vmax = self.vmin, self.vmax
        #redraw the BT time series so it matches the filtered map
        if 'Mag_Time (s)' in df.columns:
            self.plot_tabs.clear()
            self.new_plot(df=df, name='BT', column=df['BT'], ymin=self.vmin, ymax=self.vmax)
        self.refresh_web_map()

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
        """Redraw the map, web map and BT time series from the current data."""
        if getattr(self, 'current_df', None) is None:
            return
        contour = True if self.map_view_type.currentText() == CONTOUR_MAP else None
        self.plot_data(self.current_df, vmin=self.map_vmin, vmax=self.map_vmax, contour=contour)
        if 'Mag_Time (s)' in self.current_df.columns:
            self.plot_tabs.clear()
            self.new_plot(df=self.current_df, name='BT', column=self.current_df['BT'])
        mode = self.residual_mode()
        if mode is not None:
            self.statusBar().showMessage(f'Showing {RESIDUAL_LABELS[mode]} BT')
        elif self.residual_selected():
            self.statusBar().showMessage(IGRF_SKIPPED_MESSAGE)
        else:
            self.statusBar().showMessage('Showing total BT')


    def clear_data(self, df):
        #clear previous plots
        self.axes.clear()
        self.figure.clear()
        self.canvas.draw()

    def upward_continuation(self, df):
        #calls the magnetic filtering class
        filters = mf.MapFilter(self.df)
        #reads the continuation height assigned by the user
        self.assign_continuation_height()
        if self.H == 0:
            self.scale_changed(self.df)
            #self.plot_data(self.df)
        else:
            #runs data through upward continuation filter
            df = filters.upward_continuation(H=self.H)
            self.filtered_scale_changed(df, filters=['Upward Continuation'])


    def downward_continuation(self, df):
        #calls the magnetic filtering class
        filters = mf.MapFilter(self.df)
        #reads the continuation height assigned by the user
        self.assign_continuation_height()
        if self.H == 0:
            self.scale_changed(self.df)
            #self.plot_data(self.df)
        else:
            #runs data through downward continuation filter
            df = filters.downward_continuation(H=self.H)
            self.filtered_scale_changed(df, filters=['Downward Continuation'])
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
            filters=self.active_filters + ['Reduction to Pole']
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
            filters=self.active_filters + ['VMD']
        )

    def reset_map(self):
        #clear the user-entered scale so later filters don't reapply it
        self.set_vmin.clear()
        self.set_vmax.clear()
        self.vmin = None
        self.vmax = None
        #the file selector stays at -1 after an import, so fall back to the last displayed dataset
        index = self.select_file.currentIndex()
        if index == -1:
            index = self.active_dataset_index
        if index not in self.processed_dfs:
            self.statusBar().showMessage('No data loaded to reset.')
            return
        #redisplay the cached unfiltered data, copied so later filters can't modify the cache
        self.display_processed_df(self.processed_dfs[index].copy())
        self.new_plot(df=self.df, name='BT', column=self.df['BT'])
        self.statusBar().showMessage('Data Successfully Reset')

    def reset_chart(self):
        self.plot.clear()
        if self.select_file.currentIndex()!= -1:
            self.select_display_file(self.select_file.currentIndex())
        else:
            self.update_current_plot()
        #self.plot.draw()

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
            pd.DataFrame(self.map_view(self.current_df)).to_csv(csv_path, index=False)
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
        """Save the OrphaMag results: scored points, candidate clusters, summary and engineering map."""
        if self.ow_annotated_df is None:
            self.statusBar().showMessage('No orphan-well results to export. Import a dataset first.')
            return

        # suggest a name next to the source file
        default_path = ''
        index = self.ow_selected_dataset_index
        if index is not None and 0 <= index < self.select_file.count():
            source_path = Path(self.select_file.itemData(index, Qt.ItemDataRole.UserRole))
            default_path = str(source_path.with_name(f'{source_path.stem}_orphamag.csv'))
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            'Export OrphaMag Results',
            default_path,
            'CSV files (*.csv)',
        )
        if not file_path:
            return

        base_path = Path(file_path).with_suffix('')
        points_path = base_path.with_suffix('.csv')
        output_paths = [points_path] + [
            base_path.with_name(f'{base_path.name}{suffix}')
            for suffix in ('_clusters.csv', '_summary.txt', '_engineering_map.png')
        ]
        if any(self.is_imported_file(path) for path in output_paths):
            QMessageBox.warning(self, 'OrphaMag Export', 'That name would overwrite an imported data file. Choose a different name.')
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
            self.ow_cluster_figure.savefig(map_path, dpi=200, bbox_inches='tight')
            written.append(map_path)
        except Exception as exc:
            QMessageBox.warning(self, 'OrphaMag Export', f'Export failed:\n{exc}')
            self.statusBar().showMessage('OrphaMag export failed.')
            return

        self.statusBar().showMessage(f'OrphaMag results exported to {base_path.parent} ({len(written)} files)')

    #def sampling frequency
    #   add ability to set sampling frequency and adjust the filters class so it's not static at d=1

    #def rewind action
    #   allows users to go back one step
#%% Executing app
if __name__ == '__main__':
    catchErrors() # prevent crash of the app
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        startup_file = sys.argv[1]
        QTimer.singleShot(250, lambda: window.load_orphan_well_file(startup_file))
    sys.exit(app.exec())
