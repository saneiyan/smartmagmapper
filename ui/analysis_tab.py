"""Automated Anomaly Analysis tab: settings, reference location, running the analysis and its plots."""
from processing import labels
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QLabel,
    QWidget,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QLineEdit,
    QComboBox,
    QTabBar,
    QTabWidget,
    QGroupBox,
    QFormLayout,
    QDoubleSpinBox,
    QSpinBox,
    QTextEdit,
    QSplitter,
    QScrollArea,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from pathlib import Path
from ui.theme import panel_toggle, TabArrows
from ui.vmd_panel import VMDPanel
from ui.xai_help import FEATURE_HELP, show_picked_feature
from processing import data_analysis_pipeline as dap
from processing import geoxai_interpreter as gx
import json


class AnalysisTabMixin:
    """Automated Anomaly Analysis tab: settings, reference location, running the analysis and its plots.

    Mixed into GUI.MainWindow; methods use the main window's widgets and state through self.
    """

    def create_analysis_tab(self):
        widget = QWidget()
        widget.setObjectName('analysisPage')
        root_layout = QVBoxLayout(widget)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)
        widget.setStyleSheet("""
            QWidget#analysisPage {
                background: #111827;
                color: #E5E7EB;
            }
            QWidget#analysisPage QGroupBox {
                border: 1px solid #374151;
                border-radius: 6px;
                margin-top: 14px;
                padding: 10px;
                font-weight: 600;
            }
            QWidget#analysisPage QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QWidget#analysisPage QPushButton {
                min-height: 30px;
                border: 1px solid #4B5563;
                border-radius: 5px;
                background: #1F2937;
                color: #F9FAFB;
            }
            QWidget#analysisPage QPushButton:hover {
                background: #263244;
                border-color: #64748B;
            }
            QWidget#analysisPage QComboBox {
                background: #1F2937;
                color: #F9FAFB;
                border: 1px solid #4B5563;
                border-radius: 5px;
                min-height: 28px;
                padding: 4px;
            }
            QWidget#analysisPage QComboBox::drop-down {
                border: none;
            }
            QWidget#analysisPage QComboBox QAbstractItemView {
                background: #1F2937;
                color: #F9FAFB;
                selection-background-color: #4B5563;
            }
            QWidget#analysisPage QDoubleSpinBox,
            QWidget#analysisPage QSpinBox,
            QWidget#analysisPage QTextEdit {
                background: #1F2937;
                color: #F9FAFB;
                border: 1px solid #4B5563;
                border-radius: 5px;
                min-height: 28px;
            }
            QWidget#analysisPage QTabWidget::pane {
                border: 1px solid #374151;
                border-radius: 6px;
                background: #0F172A;
            }
            QWidget#analysisPage QTabBar::tab {
                background: #1F2937;
                color: #D1D5DB;
                padding: 8px 14px;
                border: 1px solid #374151;
                border-bottom: none;
                min-width: 96px;
            }
            QWidget#analysisPage QTabBar::tab:selected {
                background: #F9FAFB;
                color: #111827;
            }
            QWidget#analysisPage QScrollArea {
                border: none;
                background: #111827;
            }
        """)

        controls = QGroupBox('Workflow and parameters')
        controls_layout = QVBoxLayout()

        self.analysis_dataset_label = QLabel('Active survey: none')
        self.analysis_dataset_label.setWordWrap(True)
        controls_layout.addWidget(self.analysis_dataset_label)
        self.analysis_input = QComboBox()
        self.analysis_input.addItem(labels.total_field_label())
        self.analysis_input.setEnabled(False)
        self.analysis_input.setToolTip(
            'Source-location analysis always uses the cleaned total magnetic field.'
        )
        self.analysis_input.currentIndexChanged.connect(self.process_analysis_dataset)
        controls_layout.addWidget(QLabel('Analyze:'))
        controls_layout.addWidget(self.analysis_input)
        self.analysis_input_label = QLabel('Analysis input: no survey')
        self.analysis_input_label.setWordWrap(True)
        controls_layout.addWidget(self.analysis_input_label)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.analysis_window_length = QDoubleSpinBox()
        self.analysis_window_length.setRange(1.0, 50.0)
        self.analysis_window_length.setDecimals(1)
        self.analysis_window_length.setSingleStep(1.0)
        self.analysis_window_length.setValue(5.0)

        self.analysis_step_ratio = QDoubleSpinBox()
        self.analysis_step_ratio.setRange(0.05, 1.0)
        self.analysis_step_ratio.setDecimals(2)
        self.analysis_step_ratio.setSingleStep(0.05)
        self.analysis_step_ratio.setValue(0.25)

        self.analysis_gamma = QDoubleSpinBox()
        self.analysis_gamma.setRange(0.5, 10.0)
        self.analysis_gamma.setDecimals(1)
        self.analysis_gamma.setSingleStep(0.5)
        self.analysis_gamma.setValue(2.0)

        self.analysis_dbscan_eps = QDoubleSpinBox()
        self.analysis_dbscan_eps.setRange(0.5, 30.0)
        self.analysis_dbscan_eps.setDecimals(1)
        self.analysis_dbscan_eps.setSingleStep(0.5)
        self.analysis_dbscan_eps.setValue(4.0)

        self.analysis_min_samples = QSpinBox()
        self.analysis_min_samples.setRange(1, 100)
        self.analysis_min_samples.setValue(5)

        #optional known reference location (e.g. a known target), left blank when there is none
        self.analysis_reference_lat = QLineEdit()
        self.analysis_reference_lat.setPlaceholderText('Optional latitude in degrees')
        self.analysis_reference_lon = QLineEdit()
        self.analysis_reference_lon.setPlaceholderText('Optional longitude in degrees')
        for reference_field in (self.analysis_reference_lat, self.analysis_reference_lon):
            reference_field.setAlignment(Qt.AlignmentFlag.AlignRight)
            reference_field.setClearButtonEnabled(True)

        form.addRow('Reference latitude', self.analysis_reference_lat)
        form.addRow('Reference longitude', self.analysis_reference_lon)
        # Cleaning controls are built by the Data & Cleaning tab (ui/data_workspace.py).
        form.addRow('Score window length (m)', self.analysis_window_length)
        form.addRow('Window step ratio', self.analysis_step_ratio)
        form.addRow('Threshold gamma', self.analysis_gamma)
        form.addRow('DBSCAN eps (m)', self.analysis_dbscan_eps)
        form.addRow('DBSCAN min samples', self.analysis_min_samples)

        button_column = QVBoxLayout()
        self.analysis_apply_button = QPushButton('Update Results')
        self.analysis_apply_button.clicked.connect(self.run_anomaly_analysis)
        self.analysis_export_button = QPushButton('Export Results')
        self.analysis_export_button.clicked.connect(self.export_analysis_results)
        self.analysis_export_button.setEnabled(False)
        for button in [
            self.analysis_apply_button,
            self.analysis_export_button,
        ]:
            button_column.addWidget(button)

        controls_layout.addLayout(form)
        controls_layout.addSpacing(8)
        controls_layout.addLayout(button_column)
        controls.setLayout(controls_layout)

        self.analysis_summary = QTextEdit()
        self.analysis_summary.setReadOnly(True)
        self.analysis_summary.setMinimumHeight(180)
        self.analysis_summary.setMaximumHeight(340)
        self.analysis_summary.setText('Import a survey using File > Import Data. Inspect the result map, then follow the numbered stages for supporting evidence.')

        controls_panel = QWidget()
        controls_panel_layout = QVBoxLayout(controls_panel)
        controls_panel_layout.setContentsMargins(0, 0, 0, 0)
        controls_panel_layout.setSpacing(10)
        controls_panel_layout.addWidget(controls)
        # Detailed location summary lives in the final workspace.
        controls_panel_layout.addWidget(self.analysis_summary)
        controls_panel_layout.addStretch()

        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setWidget(controls_panel)
        controls_scroll.setMinimumWidth(310)
        controls_scroll.setMaximumWidth(380)

        self.analysis_visual_tabs = QTabWidget()
        self.analysis_visual_tabs.setDocumentMode(True)

        self.analysis_web_map = QWebEngineView()
        self.analysis_web_map.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self.analysis_web_map.setHtml(
            "<html><body style='margin:0;background:#0f172a;color:#e5e7eb;"
            "font-family:Segoe UI,Arial,sans-serif;display:flex;align-items:center;"
            "justify-content:center;height:100vh;'>Import a survey to draw the cluster map.</body></html>"
        )

        self.analysis_cluster_figure = Figure(figsize=(8.5, 6.2), constrained_layout=True)
        self.analysis_cluster_canvas = FigureCanvas(self.analysis_cluster_figure)
        self.analysis_cluster_canvas.setMinimumHeight(300)

        self.analysis_score_figure = Figure(figsize=(8.5, 4.8), constrained_layout=True)
        self.analysis_score_canvas = FigureCanvas(self.analysis_score_figure)
        self.analysis_score_canvas.setMinimumHeight(280)

        self.analysis_field_figure = Figure(figsize=(8.5, 4.8), constrained_layout=True)
        self.analysis_field_canvas = FigureCanvas(self.analysis_field_figure)
        self.analysis_field_canvas.setMinimumHeight(280)

        self.analysis_vmd_panel = VMDPanel(editable=False)
        self.analysis_modes_figure = Figure(figsize=(8.5, 4.8), constrained_layout=True)
        self.analysis_modes_canvas = FigureCanvas(self.analysis_modes_figure)
        self.analysis_modes_canvas.setMinimumHeight(280)

        self.analysis_geoxai_text = QTextEdit()
        self.analysis_geoxai_text.setReadOnly(True)
        self.analysis_geoxai_text.setMinimumHeight(230)
        self.analysis_geoxai_text.setText('Import a survey to generate a GeoXAI candidate explanation.')
        self.analysis_geoxai_figure = Figure(figsize=(8.5, 4.8), constrained_layout=True)
        self.analysis_geoxai_canvas = FigureCanvas(self.analysis_geoxai_figure)
        self.analysis_geoxai_canvas.setMinimumHeight(280)

        self.analysis_figure = self.analysis_cluster_figure
        self.analysis_canvas = self.analysis_cluster_canvas

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

        xai_controls = QHBoxLayout()
        xai_controls.addWidget(QLabel('Explanation'))

        self.xai_view = QComboBox()
        self.xai_view.addItems([
            'Global: survey overview',
            'Local: selected window',
        ])
        self.xai_view.setToolTip(
            'Global summarizes the survey. '
            'Local explains one actual scored window.'
        )
        xai_controls.addWidget(self.xai_view)

        xai_controls.addWidget(QLabel('Window'))
        self.xai_window = QSpinBox()
        self.xai_window.setRange(1, 1)
        self.xai_window.setKeyboardTracking(False)
        self.xai_window.setEnabled(False)
        self.xai_window.setToolTip(
            'Choose a scored window, or use Choose on score plot.'
        )
        xai_controls.addWidget(self.xai_window)

        self.xai_window_label = QLabel(
            'Run analysis to select a window.'
        )
        self.xai_window_label.setWordWrap(True)

        self.xai_choose_score = QPushButton('Choose on score plot')
        self.xai_choose_score.clicked.connect(
            self.arm_xai_score_selection
        )
        self.xai_choose_score.setEnabled(False)
        xai_controls.addWidget(self.xai_choose_score)
        xai_controls.addStretch(1)

        geoxai_layout.addLayout(xai_controls)
        geoxai_layout.addWidget(self.xai_window_label)

        self.xai_selection_guide = QLabel(
            'For a local explanation, choose Local, then select a '
            'window number or click Choose on score plot.'
        )
        self.xai_selection_guide.setWordWrap(True)
        geoxai_layout.addWidget(self.xai_selection_guide)

        self.xai_view.currentIndexChanged.connect(
            self.render_analysis_geoxai
        )
        self.xai_window.valueChanged.connect(
            self.render_analysis_geoxai
        )
        self.analysis_score_canvas.mpl_connect(
            'button_press_event',
            self.select_xai_window_on_score,
        )
        self.analysis_geoxai_canvas.mpl_connect(
            'pick_event',
            lambda event: show_picked_feature(self, event),
        )

        geoxai_layout.addWidget(self.analysis_geoxai_text)

        self.xai_chart_view = QTabBar()
        self.xai_chart_view.addTab('SHAP explanation')
        self.xai_chart_view.addTab('Cluster evidence')
        self.xai_chart_view.currentChanged.connect(
            self.render_analysis_geoxai
        )
        geoxai_layout.addWidget(self.xai_chart_view)
        geoxai_layout.addWidget(self.analysis_geoxai_canvas)

        self.analysis_visual_tabs.addTab(self.analysis_web_map, 'Web Map')
        self.analysis_visual_tabs.addTab(plot_page(self.analysis_cluster_canvas), 'Location Map')
        self.analysis_visual_tabs.addTab(plot_page(self.analysis_field_canvas), 'Magnetic Field')
        self.analysis_visual_tabs.addTab(self.analysis_vmd_panel, 'VMD Modes')
        self.analysis_visual_tabs.addTab(plot_page(self.analysis_score_canvas), 'Anomaly Scores')
        self.analysis_visual_tabs.addTab(geoxai_page, 'Explainable AI (XAI)')
        for source,target in [(2,0),(3,1),(4,2),(4,3),(5,4)]:
            self.analysis_visual_tabs.tabBar().moveTab(source,target)
        self.analysis_visual_tabs.setCurrentIndex(0)

        # Settings column: a small collapse toggle directly above the analysis settings panel.
        self.analysis_settings_column = QWidget()
        settings_column = QVBoxLayout(self.analysis_settings_column)
        settings_column.setContentsMargins(0, 0, 0, 0)
        settings_column.setSpacing(4)
        self.analysis_settings_toggle = panel_toggle(controls_scroll, 'Hide analysis settings', 'Settings', 'analysis settings',
                                               on_change=self.analysis_settings_toggled)
        settings_column.addWidget(self.analysis_settings_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        settings_column.addWidget(controls_scroll, 1)
        settings_column.addStretch(0)  # keeps the toggle at the top while the panel is collapsed

        # Previous / next view: small arrows at the right end of the sub-tab bar.
        self.analysis_tab_arrows = TabArrows(self.analysis_visual_tabs)
        self.previous_stage, self.next_stage = self.analysis_tab_arrows.previous, self.analysis_tab_arrows.next

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.analysis_splitter = splitter
        splitter.addWidget(self.analysis_settings_column)
        splitter.addWidget(self.analysis_visual_tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([390, 1040])
        self.result_headline = QLabel('Import data to begin anomaly exploration.')
        self.result_headline.setObjectName('analysisMetrics')
        self.result_headline.setWordWrap(True)
        controls_layout.addWidget(self.result_headline)
        root_layout.addWidget(splitter)

        analysis_widgets = [
            self.analysis_window_length,
            self.analysis_step_ratio,
            self.analysis_gamma,
            self.analysis_dbscan_eps,
            self.analysis_min_samples,
        ]
        for spinbox in analysis_widgets:
            spinbox.valueChanged.connect(self.schedule_analysis)
        #rerun once a coordinate is finished being typed, not on every keystroke
        for reference_field in (self.analysis_reference_lat, self.analysis_reference_lon):
            reference_field.editingFinished.connect(self.reference_coordinates_changed)
            #the clear button empties the field without finishing an edit
            reference_field.textChanged.connect(lambda text: None if text else self.reference_coordinates_changed())

        # Initialize the dataset selector with any existing datasets
        if hasattr(self, 'df_list') and self.df_list:
            self._populate_dataset_selector()

        return widget

    def analysis_settings_toggled(self, visible):
        """Shrink the splitter section to the toggle while collapsed; restore the split when reopened."""
        column = getattr(self, 'analysis_settings_column', None)
        splitter = getattr(self, 'analysis_splitter', None)
        if column is None or splitter is None:
            return
        column.setMaximumWidth(380 if visible else self.analysis_settings_toggle.sizeHint().width())
        total = sum(splitter.sizes())
        side = 390 if visible else self.analysis_settings_toggle.sizeHint().width()
        splitter.setSizes([side, max(0, total - side)])

    def clear_analysis_results(self, message):
        self.analysis_clean_df = self.analysis_annotated_df = None
        self.location_results = None
        if hasattr(self,'result_headline'): self.result_headline.setText(message)
        if hasattr(self,'location_headline'): self.location_headline.setText(message)
        self.analysis_score_points = self.analysis_clusters = None
        self.analysis_summary_data = {}
        self.analysis_modes = self.analysis_mode_metrics = None
        self.analysis_selected_modes = []
        self.analysis_export_button.setEnabled(False)
        self.analysis_summary.setPlainText(message)
        self.analysis_input_label.setText('Analysis input: pending')
        if hasattr(self, 'analysis_vmd_panel'): self.analysis_vmd_panel.clear(message)
        for name in ('analysis_field', 'analysis_score', 'analysis_cluster', 'analysis_modes', 'analysis_geoxai'):
            figure = getattr(self, name + '_figure', None)
            canvas = getattr(self, name + '_canvas', None)
            if figure is not None:
                figure.clear()
            if canvas is not None:
                canvas.draw_idle()
        self.analysis_geoxai_report=None
        self.analysis_geoxai_text.setPlainText(message)
        self.analysis_web_map.setHtml('<html><body>' + 'Candidate results pending' + '</body></html>')

    def reference_coordinates(self, report=False):
        """(lat, lon) of the reference location the user entered, or None if left blank or invalid.
        With report=True, problems are shown in the status bar."""
        lat_text = self.analysis_reference_lat.text().strip()
        lon_text = self.analysis_reference_lon.text().strip()
        if not lat_text and not lon_text:
            return None
        if not lat_text or not lon_text:
            if report:
                self.statusBar().showMessage('Enter both latitude and longitude for the reference location.')
            return None
        try:
            lat, lon = float(lat_text), float(lon_text)
        except ValueError:
            if report:
                self.statusBar().showMessage('Reference coordinates must be numbers in decimal degrees.')
            return None
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            if report:
                self.statusBar().showMessage('Reference latitude must be -90 to 90 and longitude -180 to 180.')
            return None
        return lat, lon

    def reference_known(self):
        return self.reference_coordinates() is not None

    def reference_coordinates_changed(self):
        #editingFinished also fires when the field just loses focus, so only rerun on a real change
        coordinates = self.reference_coordinates(report=True)
        if coordinates == getattr(self, 'analysis_last_reference_coordinates', None):
            return
        self.analysis_last_reference_coordinates = coordinates
        if coordinates is not None:
            self.statusBar().showMessage(f'Reference location set to {coordinates[0]:.6f}, {coordinates[1]:.6f}')
        self.schedule_analysis()

    def analysis_params(self):
        reference = self.reference_coordinates()
        startup, multiplier, percentile = self.data_workspace.cleaning_values()
        return dap.AnalysisParams(
            reference_lat=reference[0] if reference else None,
            reference_lon=reference[1] if reference else None,
            startup_samples=startup,
            spatial_mad_multiplier=multiplier,
            spatial_fallback_percentile=percentile,
            window_length_m=float(self.analysis_window_length.value()),
            step_ratio=float(self.analysis_step_ratio.value()),
            gamma=float(self.analysis_gamma.value()),
            dbscan_eps_m=float(self.analysis_dbscan_eps.value()),
            dbscan_min_samples=int(self.analysis_min_samples.value()),
        )

    def schedule_analysis(self):
        if self.active_session() is not None:
            self.analysis_update_timer.start(350)

    def schedule_analysis_reload(self):
        if self.active_session() is not None:
            self.analysis_reload_timer.start(650)

    def process_analysis_dataset(self, *_args):
        self._analysis_mode_key = None
        self.run_anomaly_analysis()

    def run_anomaly_analysis(self):
        session = self.active_session()
        if session is None:
            return
        self.analysis_update_timer.stop()
        self.clear_analysis_results('Updating candidate analysis...')
        params = self.analysis_params()
        try:
            source = session.cleaned
            input_name = f'Cleaned {labels.total_field_label()}'
            frame = source.copy(deep=True)
            frame['Analysis_Field'] = frame['BT'].to_numpy(dtype=float)  # in the survey's unit
            frame['Analysis_Input'] = input_name
            frame['Source_Survey'] = Path(session.path).name
            history = []
            frame['Analysis_Processing_History'] = json.dumps(history, sort_keys=True)
            frame['Analysis_Startup_Samples'] = session.cleaning_key[0]
            frame['Analysis_Spatial_MAD'] = session.cleaning_key[1]
            frame['Analysis_Spatial_Fallback_Percentile'] = session.cleaning_key[2]
            modes, metrics, selected = session.modes_for(frame, params)
            self.analysis_clean_df, self.analysis_audit = frame, session.audit
            self.analysis_modes, self.analysis_mode_metrics, self.analysis_selected_modes = modes, metrics, selected
            points, clusters, summary = dap.analyze_with_cached_modes(frame, modes, selected, params)
            summary.update(source_survey=Path(session.path).name, analysis_input=input_name,
                           processing_history=history, dataset_revision=session.revision)
            annotated = dap.annotate_clean_points(dap.add_reference_distance(frame, params), points, clusters)
            self.analysis_score_points, self.analysis_clusters = points, clusters
            self.analysis_summary_data, self.analysis_annotated_df = summary, annotated
            self.analysis_input_label.setText(f'Analysis input: {input_name}')
            self.plot_analysis_results(annotated, points, clusters, summary)
            self.analysis_summary.setText(self.format_analysis_summary(summary))
            radius=summary.get('candidate_radius_m')
            spread=f'{radius:.2f} m cluster spread' if radius is not None else 'No selected candidate'
            self.result_headline.setText(f"{summary.get('n_clusters',0)} candidate clusters\n{summary.get('n_hits',0)} hit windows")
            self.location_headline.setText(f"{spread}. This is a magnetic anomaly candidate requiring field verification. Cluster spread is not a confidence interval.")
            self.analysis_export_button.setEnabled(True)
            self.statusBar().showMessage(f"{Path(session.path).name}: {len(frame)} shared samples | {summary['n_clusters']} candidate clusters")
        except Exception as exc:
            self.clear_analysis_results(f'Analysis unavailable: {exc}')
            self.statusBar().showMessage(f'Candidate analysis unavailable: {exc}')

    def format_analysis_summary(self, summary):
        if not summary:
            return 'No anomaly analysis has been run.'
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
            if 'candidate_distance_to_reference_m' in summary:
                lines.append(f"Offset to reference location: {summary['candidate_distance_to_reference_m']:.2f} m")
            else:
                lines.append("Mode: unknown-location estimate")
        else:
            lines.append('No selected candidate cluster.')

        audit = self.analysis_audit or {}
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

    def plot_analysis_results(self, clean_df, score_points, clusters, summary):
        self.location_results = (clean_df, score_points, clusters, summary)
        self.plot_analysis_total_field(clean_df)
        self.plot_analysis_score_trace(score_points)
        self.plot_analysis_engineering_map(clean_df, score_points, clusters)
        self.plot_analysis_mode_metrics()
        self.refresh_analysis_geoxai(clean_df, score_points, clusters, summary)
        self.refresh_analysis_web_map(clean_df, score_points, clusters, summary)

    def style_analysis_axis(self, ax):
        ax.set_facecolor('#FFFFFF')
        ax.grid(color='#E5E7EB', linewidth=0.8, alpha=0.9)
        for spine in ax.spines.values():
            spine.set_color('#CBD5E1')
        ax.tick_params(colors='#111827')
        ax.title.set_color('#111827')
        ax.xaxis.label.set_color('#111827')
        ax.yaxis.label.set_color('#111827')

    def plot_analysis_total_field(self, clean_df):
        self.analysis_field_figure.clear()
        ax_field = self.analysis_field_figure.add_subplot(111)
        ordered = clean_df.sort_values('Time (s)').reset_index(drop=True)
        ax_field.plot(ordered['Time (s)'], ordered['BT'], color='#111827', linewidth=0.9)
        ax_field.set_title('Analysis field: ' + self.analysis_summary_data.get('analysis_input', f'Cleaned {labels.total_field_label()}'), pad=12)
        ax_field.set_xlabel('Time (s)')
        ax_field.set_ylabel(labels.total_field_label())
        ax_field.margins(x=0.01)
        self.style_analysis_axis(ax_field)
        self.analysis_field_canvas.draw_idle()

    def plot_analysis_score_trace(self, score_points):
        self.analysis_score_figure.clear()
        ax_score = self.analysis_score_figure.add_subplot(111)
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
        self.style_analysis_axis(ax_score)
        self.analysis_score_canvas.draw_idle()

    def plot_analysis_mode_metrics(self):
        if self.analysis_modes is None or self.analysis_clean_df is None:
            self.analysis_vmd_panel.clear();return
        frame=self.analysis_clean_df.sort_values('Time (s)').reset_index(drop=True)
        self.analysis_vmd_panel.set_data(frame['Time (s)'].to_numpy(),frame['Analysis_Field'].to_numpy(),
            self.analysis_modes,self.analysis_mode_metrics,self.analysis_selected_modes,'Time (s)')

    def refresh_analysis_geoxai(self, clean_df, score_points, clusters, summary):
        if not hasattr(self, 'analysis_geoxai_text'):
            return

        report = gx.explain_candidate(
            clean_df,
            score_points,
            clusters,
            summary,
            reference_known='candidate_distance_to_reference_m' in summary,
        )

        self.analysis_geoxai_report = report
        self._xai_score_points = score_points.copy(deep=True)

        self.xai_window.blockSignals(True)
        self.xai_window.setRange(1, max(1, len(score_points)))

        initial = 0

        if not report.features.empty and not clusters.empty:
            chosen = clusters.loc[
                clusters['selected_by_support_compactness'].astype(bool)
            ]

            if len(chosen) == 1:
                selected = chosen.iloc[0]

                positions = score_points[
                    ['e_m', 'n_m']
                ].to_numpy(dtype=float)

                distances = (
                    (positions[:, 0] - selected['centroid_e_m']) ** 2
                    + (positions[:, 1] - selected['centroid_n_m']) ** 2
                )

                members = (
                    score_points['cluster_label'].to_numpy()
                    == selected['cluster_label']
                )

                distances[~members] = float('inf')
                initial = int(distances.argmin())

        self.xai_window.setValue(initial + 1)
        self.xai_window.blockSignals(False)

        self.render_analysis_geoxai()

    def render_analysis_geoxai(self, *_):
        report = getattr(self, 'analysis_geoxai_report', None)
        if report is None:
            return

        local = self.xai_view.currentIndex() == 1
        ready = report.metadata.get('status') == 'available'

        self.xai_window.setEnabled(local and ready)
        self.xai_choose_score.setEnabled(local and ready)

        position = self.xai_window.value() - 1
        points = getattr(self, '_xai_score_points', None)

        if points is not None and len(points) > position:
            point = points.iloc[position]
            margin = float(point['threshold_margin'])
            status = (
                'above' if margin > 0
                else ('below' if margin < 0 else 'at')
            )

            cluster = point.get('cluster_label', -1)
            cluster = float(cluster) if cluster is not None else -1.0
            cluster_text = (
                f'C{int(cluster)}'
                if cluster == cluster and cluster >= 0
                else 'no cluster'
            )

            self.xai_window_label.setText(
                f"Anomaly score: {float(point['score']):.3f} "
                f"({status} threshold by {abs(margin):.3f}) | "
                f"Cluster: {cluster_text} | "
                f"Time: {point['t_center_s']:.2f} s"
            )

        if (
            local
            and ready
            and points is not None
            and len(points) > position
        ):
            category = report.features[
                'pipeline_neighborhood'
            ].iloc[position]

            self.xai_window_label.setText(
                self.xai_window_label.text()
                + f' | Category: {category}'
            )

        report.local_contributions = report.contributions.iloc[0:0].copy()
        report.local_metadata = {}
        report.metadata['displayed_view'] = 'local' if local else 'global'
        narrative = report.narrative

        if local and ready:
            try:
                table, scope = gx.explain_window(
                    report.features,
                    points,
                    report.metadata['coordinate_epsg'],
                    position,
                )

                report.local_contributions = table
                report.local_metadata = scope

                narrative = (
                    f"Local SHAP | Window {scope['window_number']} | "
                    f"Time {scope['t_center_s']:.2f} s\n"
                    "Explained category: selected neighborhood | "
                    f"Model prediction: {scope['predicted_class']}\n"
                    f"Pipeline category: "
                    f"{scope.get('pipeline_neighborhood', 'unavailable')}\n"
                    f"Window position: Easting {scope['e_m']:.3f} m; "
                    f"Northing {scope['n_m']:.3f} m.\n"
                    f"Model base value {scope['base_value']:.4f} "
                    f"+ signed contributions "
                    f"{scope['sum_of_contributions']:+.4f} "
                    f"= selected-neighborhood output "
                    f"{scope['model_output']:.4f}.\n"
                    "Teal contributions increase this category's model "
                    "output; orange contributions decrease it. "
                    "This explains a recorded window's classification, "
                    "not a probability that a well exists."
                )

            except (
                ValueError,
                ImportError,
                OSError,
                KeyError,
                AssertionError,
            ) as exc:
                report.local_metadata = {
                    'status': 'unavailable',
                    'reason': str(exc),
                }
                narrative = 'Local SHAP unavailable: ' + str(exc)

        elif local:
            narrative = 'Local SHAP unavailable. ' + report.narrative

        self.analysis_geoxai_text.setPlainText(narrative)
        report.display_narrative = narrative

        self.analysis_geoxai_figure.clear()

        if report.contributions.empty and report.cluster_scores.empty:
            axis = self.analysis_geoxai_figure.add_subplot(111)
            axis.text(
                0.5,
                0.5,
                'No GeoXAI evidence to plot',
                ha='center',
                va='center',
                transform=axis.transAxes,
            )
            axis.set_axis_off()
            self.analysis_geoxai_canvas.draw_idle()
            return

        evidence_view = self.xai_chart_view.currentIndex() == 1

        if evidence_view:
            ax_support, ax_spread = (
                self.analysis_geoxai_figure.subplots(1, 2)
            )
            evidence = report.cluster_scores.sort_values('cluster_label')

            if not evidence.empty:
                cluster_labels = [
                    f'C{int(value)}'
                    for value in evidence['cluster_label']
                ]
                colors = [
                    '#0F766E' if bool(value) else '#94A3B8'
                    for value in evidence[
                        'selected_by_support_compactness'
                    ]
                ]

                bars = ax_support.barh(
                    cluster_labels,
                    evidence['n_points'],
                    color=colors,
                    picker=True,
                )
                for bar in bars:
                    bar._xai_feature_key = 'cluster_support'

                bars = ax_spread.barh(
                    cluster_labels,
                    evidence['uncertainty_radius_m'],
                    color=colors,
                    picker=True,
                )
                for bar in bars:
                    bar._xai_feature_key = 'cluster_spread'

            ax_support.set_title(
                'Supporting anomaly windows',
                fontsize=12,
            )
            ax_support.set_xlabel(
                'Number of windows',
                fontsize=10,
            )
            ax_spread.set_title('Spatial spread', fontsize=12)
            ax_spread.set_xlabel(
                'Weighted RMS distance to center (m)',
                fontsize=10,
            )

            for axis in (ax_support, ax_spread):
                self.style_analysis_axis(axis)

        else:
            axis = self.analysis_geoxai_figure.add_subplot(111)
            table = (
                report.local_contributions
                if local
                else report.contributions
            )
            column = 'shap_value' if local else 'mean_abs_shap'

            if not table.empty and column in table:
                importance = table.sort_values(column)
                names = [
                    FEATURE_HELP[feature][0]
                    for feature in importance['feature']
                ]
                colors = [
                    '#0F766E' if value >= 0 else '#B05C38'
                    for value in importance[column]
                ]

                axis.barh(
                    names,
                    importance[column],
                    color=colors,
                )

                for tick, key in zip(
                    axis.get_yticklabels(),
                    importance['feature'],
                ):
                    tick.set_picker(True)
                    tick._xai_feature_key = key

                axis.tick_params(axis='y', labelsize=10)

                if local:
                    axis.axvline(
                        0,
                        color='#6B7280',
                        linewidth=0.8,
                    )
                    axis.set_title(
                        f'Local SHAP: window {position + 1}',
                        fontsize=12,
                    )
                    axis.set_xlabel(
                        'Signed contribution to selected-neighborhood output',
                        fontsize=10,
                    )
                else:
                    axis.set_title(
                        'Global SHAP: selected-neighborhood class',
                        fontsize=12,
                    )
                    axis.set_xlabel(
                        'Average absolute SHAP contribution',
                        fontsize=10,
                    )

            else:
                axis.text(
                    0.5,
                    0.5,
                    'SHAP unavailable. See the explanation above.',
                    ha='center',
                    va='center',
                    transform=axis.transAxes,
                )
                axis.set_axis_off()

            self.style_analysis_axis(axis)

        self.analysis_geoxai_canvas.draw_idle()    

    def arm_xai_score_selection(self):
        """Enable one explicit selection on the existing score trace."""
        report = getattr(self, 'analysis_geoxai_report', None)

        if report is None or report.metadata.get('status') != 'available':
            return

        self._xai_score_pick_armed = True

        self.xai_selection_guide.setText(
            'Click near a point on the anomaly-score trace. '
            'Its time, score and cluster will identify the selected window.'
        )

        for index in range(self.analysis_visual_tabs.count()):
            if self.analysis_visual_tabs.tabText(index) == 'Anomaly Scores':
                self.analysis_visual_tabs.setCurrentIndex(index)
                break

        self.statusBar().showMessage(
            'Choose a scored window: click near a point '
            'on the anomaly-score trace.'
        )

    def select_xai_window_on_score(self, event):
        """Explain the real window at a selected score-plot point."""
        if (
            not getattr(self, '_xai_score_pick_armed', False)
            or event.button != 1
        ):
            return

        report = getattr(self, 'analysis_geoxai_report', None)

        if report is None or report.metadata.get('status') != 'available':
            return

        if (
            not self.analysis_score_figure.axes
            or event.inaxes is not self.analysis_score_figure.axes[0]
        ):
            return

        toolbar = getattr(self.analysis_score_canvas, 'toolbar', None)

        if toolbar is not None and getattr(toolbar, 'mode', ''):
            return

        import numpy as np

        xy = self._xai_score_points[
            ['t_center_s', 'score']
        ].to_numpy(dtype=float)

        pixels = event.inaxes.transData.transform(xy)

        distance = np.hypot(
            pixels[:, 0] - event.x,
            pixels[:, 1] - event.y,
        )

        position = int(distance.argmin())

        if distance[position] > 12:
            return

        self._xai_score_pick_armed = False

        self.xai_view.blockSignals(True)
        self.xai_window.blockSignals(True)

        self.xai_view.setCurrentIndex(1)
        self.xai_window.setValue(position + 1)

        self.xai_view.blockSignals(False)
        self.xai_window.blockSignals(False)

        self.render_analysis_geoxai()

        point = self._xai_score_points.iloc[position]
        label = int(point['cluster_label'])
        cluster = f'C{label}' if label >= 0 else 'no cluster'

        category = report.features[
            'pipeline_neighborhood'
        ].iloc[position]

        self.xai_selection_guide.setText(
            f"Selected window {position + 1}: "
            f"score {point['score']:.3f}, "
            f"time {point['t_center_s']:.2f} s, "
            f"{cluster}, {category}."
        )

        for index in range(self.analysis_visual_tabs.count()):
            if 'Explainable' in self.analysis_visual_tabs.tabText(index):
                self.analysis_visual_tabs.setCurrentIndex(index)
                break

        self.statusBar().showMessage(
            f'Local explanation for scored window {position + 1}.'
        )