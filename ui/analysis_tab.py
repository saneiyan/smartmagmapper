"""Automated Anomaly Analysis tab: settings, reference location, running the analysis and its plots."""
from processing import labels
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget, QVBoxLayout, QLineEdit, QComboBox, QTabWidget, QGroupBox, QFormLayout, QDoubleSpinBox, QSpinBox, QTextEdit, QSplitter, QScrollArea
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from pathlib import Path
from ui.theme import panel_toggle, TabArrows
from ui.vmd_panel import VMDPanel
from ui.busy import loading, watch_web_view
from processing import data_analysis_pipeline as dap
from processing import geoxai_interpreter as gx
import json


class AnalysisTabMixin:
    """Automated Anomaly Analysis tab: settings, reference location, running the analysis and its plots.

    Mixed into GUI.MainWindow; methods use the main window's widgets and state through self.
    """

    def create_analysis_tab(self):
        """Build the Automated Anomaly Analysis tab: the settings panel (analysis input, reference location,
        window, threshold and clustering settings, summary) and the result views (magnetic field, VMD modes, anomaly
        scores, Explainable AI). The location views created here move to the Location Estimate tab.

        Returns
        -------
        QWidget
            The tab page.
        """
        widget = QWidget()
        root_layout = QVBoxLayout(widget)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)
        controls = QGroupBox('Workflow and parameters')
        controls_layout = QVBoxLayout()

        self.analysis_dataset_label = QLabel('Active survey: none')
        self.analysis_dataset_label.setWordWrap(True)
        controls_layout.addWidget(self.analysis_dataset_label)
        self.analysis_input = QComboBox()
        self.analysis_input.addItems([labels.total_field_label(), 'Saved filter result'])
        self.analysis_input.setToolTip('Use the shared cleaned baseline, or explicitly analyze the field currently shown on the map.')
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

        # Tools > Recalculate Analysis and File > Export Analysis Results run and export the analysis.
        controls_layout.addLayout(form)
        controls_layout.addSpacing(8)
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
        watch_web_view(self.analysis_web_map, 'Loading location web map...')
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

        self.analysis_geoxai_text = QTextEdit()
        self.analysis_geoxai_text.setReadOnly(True)
        self.analysis_geoxai_text.setMinimumHeight(230)
        self.analysis_geoxai_text.setText('Import a survey to generate a GeoXAI candidate explanation.')
        self.analysis_geoxai_figure = Figure(figsize=(8.5, 4.8), constrained_layout=True)
        self.analysis_geoxai_canvas = FigureCanvas(self.analysis_geoxai_figure)
        self.analysis_geoxai_canvas.setMinimumHeight(280)

        def plot_page(canvas):
            """Wrap a figure canvas in a page with margins.

            Parameters
            ----------
            canvas : FigureCanvasQTAgg
                Canvas to show.

            Returns
            -------
            QWidget
                The page.
            """
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.addWidget(canvas)
            return page

        geoxai_page = QWidget()
        geoxai_layout = QVBoxLayout(geoxai_page)
        geoxai_layout.setContentsMargins(12, 12, 12, 12)
        geoxai_layout.setSpacing(10)
        geoxai_layout.addWidget(self.analysis_geoxai_text)
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
        settings_column.addStretch(0)

        # Previous / next view: small arrows at the right end of the sub-tab bar.
        self.analysis_tab_arrows = TabArrows(self.analysis_visual_tabs)

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

        return widget

    def analysis_settings_toggled(self, visible):
        """Shrink the splitter section to the toggle while collapsed; restore the split when reopened.

        Parameters
        ----------
        visible : bool
            Whether the settings panel is now shown.
        """
        column = getattr(self, 'analysis_settings_column', None)
        splitter = getattr(self, 'analysis_splitter', None)
        if column is None or splitter is None:
            return
        column.setMaximumWidth(380 if visible else self.analysis_settings_toggle.sizeHint().width())
        total = sum(splitter.sizes())
        side = 390 if visible else self.analysis_settings_toggle.sizeHint().width()
        splitter.setSizes([side, max(0, total - side)])

    def clear_analysis_results(self, message):
        """Remove the analysis results from every view and show a message instead.

        Parameters
        ----------
        message : str
            Text shown in the summary, headline and views (e.g. why no result is available).
        """
        self.analysis_clean_df = self.analysis_annotated_df = None
        self.location_results = None
        if hasattr(self,'result_headline'): self.result_headline.setText(message)
        self.analysis_clusters = None
        self.analysis_summary_data = {}
        self.analysis_modes = self.analysis_mode_metrics = None
        self.analysis_selected_modes = []
        self.analysis_summary.setPlainText(message)
        self.analysis_input_label.setText('Analysis input: pending')
        if hasattr(self, 'analysis_vmd_panel'): self.analysis_vmd_panel.clear(message)
        for name in ('analysis_field', 'analysis_score', 'analysis_cluster', 'analysis_geoxai'):
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
        """Reference location entered by the user.

        Parameters
        ----------
        report : bool, optional
            Explain problems (one coordinate missing, not a number, out of range) in the status bar.

        Returns
        -------
        tuple of float or None
            (latitude, longitude) in decimal degrees, or None if left blank or invalid.
        """
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

    def reference_coordinates_changed(self):
        #editingFinished also fires when the field just loses focus, so only rerun on a real change
        """Rerun the analysis when the reference location really changed (editingFinished also fires on focus loss)."""
        coordinates = self.reference_coordinates(report=True)
        if coordinates == getattr(self, 'analysis_last_reference_coordinates', None):
            return
        self.analysis_last_reference_coordinates = coordinates
        if coordinates is not None:
            self.statusBar().showMessage(f'Reference location set to {coordinates[0]:.6f}, {coordinates[1]:.6f}')
        self.schedule_analysis()

    def analysis_params(self):
        """Analysis settings from the Data & Cleaning and Automated Anomaly Analysis controls.

        Returns
        -------
        processing.data_analysis_pipeline.AnalysisParams
            Cleaning, window, threshold, clustering and reference settings.
        """
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
        """Rerun the analysis shortly after a setting changes (several quick changes trigger one run)."""
        if self.active_session() is not None:
            self.analysis_update_timer.start(350)

    def process_analysis_dataset(self, *_args):
        """Analysis input dropdown changed: rerun the analysis.

        Parameters
        ----------
        *_args : object
            Ignored signal arguments.
        """
        self.run_anomaly_analysis()

    def run_anomaly_analysis(self):
        """Run the automated anomaly analysis with a loading message over the result views and location maps."""
        views = [self.analysis_visual_tabs, getattr(self, 'location_views', None)]
        with loading(views, 'Running anomaly analysis and drawing results...'):
            self._run_anomaly_analysis()

    def _run_anomaly_analysis(self):
        """Run the automated anomaly analysis on the chosen input and show the results.

        The input is the cleaned total field or the stored filter result. The VMD decomposition is cached per input and
        settings; the input, processing history and cleaning settings are recorded with the results. Errors are shown in
        the views instead of raised.
        """
        session = self.active_session()
        if session is None:
            return
        self.analysis_update_timer.stop()
        self.clear_analysis_results('Updating candidate analysis...')
        params = self.analysis_params()
        try:
            if self.analysis_input.currentIndex() == 1:
                source = session.working
                input_name = self.current_map_field_name()
            else:
                source = session.cleaned
                input_name = f'Cleaned {labels.total_field_label()}'
            frame = source.copy(deep=True)
            frame['Analysis_Field'] = frame['BT'].to_numpy(dtype=float)
            frame['Analysis_Input'] = input_name
            frame['Source_Survey'] = Path(session.path).name
            history = session.filter_history if self.analysis_input.currentIndex() == 1 else []
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
            self.analysis_clusters = clusters
            self.analysis_summary_data, self.analysis_annotated_df = summary, annotated
            self.analysis_input_label.setText(f'Analysis input: {input_name}')
            self.plot_analysis_results(annotated, points, clusters, summary)
            self.analysis_summary.setText(self.format_analysis_summary(summary))
            self.result_headline.setText(f"{summary.get('n_clusters',0)} candidate clusters\n{summary.get('n_hits',0)} hit windows")
            self.statusBar().showMessage(f"{Path(session.path).name}: {len(frame)} shared samples | {summary['n_clusters']} candidate clusters")
        except Exception as exc:
            self.clear_analysis_results(f'Analysis unavailable: {exc}')
            self.statusBar().showMessage(f'Candidate analysis unavailable: {exc}')

    def format_analysis_summary(self, summary):
        """Text of the analysis summary panel.

        Parameters
        ----------
        summary : dict
            Analysis summary (see data_analysis_pipeline.summarize_analysis).

        Returns
        -------
        str
            Candidate estimate, processing summary, scoring parameters and cluster results.
        """
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
        """Draw every analysis view and keep the results for the Location Estimate tab.

        Parameters
        ----------
        clean_df : pandas.DataFrame
            Annotated survey.
        score_points, clusters : pandas.DataFrame
            Score windows and clusters.
        summary : dict
            Analysis summary.
        """
        self.location_results = (clean_df, score_points, clusters, summary)
        self.plot_analysis_total_field(clean_df)
        self.plot_analysis_score_trace(score_points)
        self.plot_analysis_engineering_map(clean_df, score_points, clusters)
        self.plot_analysis_mode_metrics()
        self.refresh_analysis_geoxai(clean_df, score_points, clusters, summary)
        self.refresh_analysis_web_map(clean_df, score_points, clusters, summary)

    def style_analysis_axis(self, ax):
        """Light background, soft grid and dark text for an analysis plot.

        Parameters
        ----------
        ax : matplotlib.axes.Axes
            Axes to style.
        """
        ax.set_facecolor('#FFFFFF')
        ax.grid(color='#E5E7EB', linewidth=0.8, alpha=0.9)
        for spine in ax.spines.values():
            spine.set_color('#CBD5E1')
        ax.tick_params(colors='#111827')
        ax.title.set_color('#111827')
        ax.xaxis.label.set_color('#111827')
        ax.yaxis.label.set_color('#111827')

    def plot_analysis_total_field(self, clean_df):
        """Plot the analysed magnetic field against time.

        Parameters
        ----------
        clean_df : pandas.DataFrame
            Analysed survey.
        """
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
        """Plot the anomaly score of each window with the threshold and the hit windows.

        Parameters
        ----------
        score_points : pandas.DataFrame
            Score windows.
        """
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
        """Show the analysis VMD decomposition (read-only) in the VMD Modes view."""
        if self.analysis_modes is None or self.analysis_clean_df is None:
            self.analysis_vmd_panel.clear();return
        frame=self.analysis_clean_df.sort_values('Time (s)').reset_index(drop=True)
        self.analysis_vmd_panel.set_data(frame['Time (s)'].to_numpy(),frame['Analysis_Field'].to_numpy(),
            self.analysis_modes,self.analysis_mode_metrics,self.analysis_selected_modes,'Time (s)')

    def refresh_analysis_geoxai(self, clean_df, score_points, clusters, summary):
        """Explain the candidate (GeoXAI): narrative text, the candidate's factor contributions and every
        cluster's evidence score.

        Parameters
        ----------
        clean_df : pandas.DataFrame
            Analysed survey.
        score_points, clusters : pandas.DataFrame
            Score windows and clusters.
        summary : dict
            Analysis summary.
        """
        if not hasattr(self, 'analysis_geoxai_text'):
            return
        report = gx.explain_candidate(
            clean_df,
            score_points,
            clusters,
            summary,
            reference_known='candidate_distance_to_reference_m' in summary,
        )
        self.analysis_geoxai_report=report
        self.analysis_geoxai_text.setPlainText(report.narrative)

        self.analysis_geoxai_figure.clear()
        if report.contributions.empty and report.cluster_scores.empty:
            ax = self.analysis_geoxai_figure.add_subplot(111)
            ax.text(0.5, 0.5, 'No GeoXAI evidence to plot', ha='center', va='center', transform=ax.transAxes)
            ax.set_axis_off()
            self.analysis_geoxai_canvas.draw_idle()
            return

        ax_factors, ax_clusters = self.analysis_geoxai_figure.subplots(1, 2)
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
        self.style_analysis_axis(ax_factors)

        if not report.cluster_scores.empty:
            scored = report.cluster_scores.sort_values('geo_xai_confidence', ascending=True)
            cluster_names = [f"C{int(v)}" for v in scored['cluster_label']]
            colors = [
                '#111827' if bool(v) else '#94A3B8'
                for v in scored['selected_by_support_compactness'].astype(bool)
            ]
            ax_clusters.barh(cluster_names, 100*scored['geo_xai_confidence'], color=colors)
            ax_clusters.set_xlim(0, 100)
            ax_clusters.set_title('Cluster Evidence Scores', pad=12)
            ax_clusters.set_xlabel('XAI Evidence Score (0–100)')
            for index, value in enumerate(scored['geo_xai_confidence']):
                ax_clusters.text(100.0*float(value) + 1.5, index, f'{100.0 * float(value):.0f}', va='center', fontsize=8)
        else:
            ax_clusters.text(0.5, 0.5, 'No clusters', ha='center', va='center', transform=ax_clusters.transAxes)
        self.style_analysis_axis(ax_clusters)
        self.analysis_geoxai_canvas.draw_idle()
