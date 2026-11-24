"""Location Estimate tab: map type and colour scale, location map and web map."""
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWidgets import QLabel, QWidget, QPushButton, QVBoxLayout, QHBoxLayout, QComboBox, QSplitter, QStackedWidget
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
import numpy as np
import folium
import branca.colormap as cm
from pathlib import Path
from ui.theme import color_scale_combo, color_list
from ui.data_workspace import DataWorkspace
from processing import web_map as wm
from processing import data_analysis_pipeline as dap
import tempfile


class LocationTabMixin:
    """Location Estimate tab: map type and colour scale, location map and web map.

    Mixed into GUI.MainWindow; methods use the main window's widgets and state through self.
    """

    def create_location_tab(self):
        page=QWidget();layout=QVBoxLayout(page)
        # The selected workspace tab supplies its heading.
        self.location_headline=QLabel('Inspect the anomaly evidence first. Location estimates appear here after analysis.')
        self.location_headline.setWordWrap(True);self.location_headline.hide()
        # Map Type and Colour Scale dropdowns, matching the Data & Cleaning cleaning maps.
        options=QHBoxLayout();options.addStretch(1)
        options.addWidget(QLabel('Map Type:'))
        self.location_map_type=QComboBox();self.location_map_type.addItems(['Scatter Plot','Contour Plot','Web Map'])
        self.location_map_type.setMinimumWidth(160);options.addWidget(self.location_map_type)
        options.addSpacing(18);options.addWidget(QLabel('Colour Scale:'))
        self.location_colors=color_scale_combo('RdYlBu_r');self.location_colors.setMinimumWidth(190)
        options.addWidget(self.location_colors);options.addStretch(1)
        # One view at a time: page 0 = location map (scatter or contour), page 1 = web map.
        # Move the candidate-location views here from Automated Anomaly Analysis; preserve canvas objects.
        self.location_views=QStackedWidget()
        for name in ['Location Map','Web Map']:
            index=next(i for i in range(self.analysis_visual_tabs.count()) if self.analysis_visual_tabs.tabText(i)==name)
            widget=self.analysis_visual_tabs.widget(index);self.analysis_visual_tabs.removeTab(index)
            self.location_views.addWidget(widget)
        maps=QWidget();maps_layout=QVBoxLayout(maps);maps_layout.setContentsMargins(0,0,0,0)
        maps_layout.addLayout(options);maps_layout.addWidget(self.location_views,1)
        self.location_map_type.currentIndexChanged.connect(self.location_map_changed)
        self.location_colors.currentIndexChanged.connect(self.location_map_changed)
        splitter=QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(maps)
        self.analysis_summary.setParent(None);self.analysis_summary.setMaximumHeight(16777215)
        self.analysis_summary.setMinimumWidth(260);splitter.addWidget(self.analysis_summary)
        splitter.setSizes([1000,320]);layout.addWidget(splitter,1)
        footer=QHBoxLayout();back=QPushButton('Review anomaly evidence');back.clicked.connect(lambda:self.tabs.setCurrentWidget(self.analysis_widget))
        export=QPushButton('Export location results');export.clicked.connect(self.export_analysis_results)
        footer.addWidget(back);footer.addStretch();footer.addWidget(export);layout.addLayout(footer)
        # Two views moved to this tab, so the Automated Anomaly Analysis arrows need refreshing.
        #self.analysis_visual_tabs.setCurrentIndex(0);self.analysis_tab_arrows.refresh()
        return page

    def location_map_changed(self, *_):
        """Show the chosen Location Estimate map type and redraw it with the chosen colour scale."""
        web = self.location_map_type.currentText() == 'Web Map'
        self.location_views.setCurrentIndex(1 if web else 0)
        results = getattr(self, 'location_results', None)
        if results is None:
            return
        clean_df, score_points, clusters, summary = results
        if web:
            self.refresh_analysis_web_map(clean_df, score_points, clusters, summary)
        else:
            self.plot_analysis_engineering_map(clean_df, score_points, clusters)

    def plot_analysis_engineering_map(self, clean_df, score_points, clusters):
        contour = getattr(self, 'location_map_type', None) is not None and self.location_map_type.currentText() == 'Contour Plot'
        cmap = self.location_colors.currentData() if hasattr(self, 'location_colors') else 'RdYlBu_r'
        self.analysis_cluster_figure.clear()
        ax_map = self.analysis_cluster_figure.add_subplot(111)
        ax_map.plot(
            clean_df['Easting (m)'],
            clean_df['Northing (m)'],
            color='#94A3B8',
            linewidth=0.6 if contour else 1.0,
            alpha=0.6 if contour else 0.9,
            label='survey track',
            zorder=3 if contour else 1,  # over the contours, under the scatter points
        )
        if score_points is not None and not score_points.empty:
            scores = score_points['score'].to_numpy(dtype=float)
            low, high = float(np.nanmin(scores)), float(np.nanmax(scores))
            if high <= low:
                high = low + 1e-9
            norm = Normalize(low, high)
            if contour:
                DataWorkspace.draw_contour(ax_map, score_points['e_m'], score_points['n_m'], scores, low, high, cmap)
            else:
                ax_map.scatter(
                    score_points['e_m'],
                    score_points['n_m'],
                    c=scores,
                    s=16,
                    cmap=cmap,
                    norm=norm,
                    alpha=0.82,
                    edgecolors='none',
                    zorder=2,
                )
            self.analysis_cluster_figure.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=ax_map, fraction=0.038, pad=0.02, label='Anomaly score', panchor=False)
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
        epsg = dap.survey_epsg(clean_df)
        reference = dap.reference_utm(self.analysis_params(), epsg)
        if reference is not None:
            ax_map.scatter(
                [reference[0]],
                [reference[1]],
                marker='*',
                s=220,
                c='#B91C1C',
                edgecolors='black',
                linewidths=0.5,
                label='reference location',
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
        zone = dap.utm_zone_label(epsg)
        ax_map.set_xlabel(f'UTM {zone} Easting (m)')
        ax_map.set_ylabel(f'UTM {zone} Northing (m)')
        ax_map.set_aspect('equal', adjustable='box')
        ax_map.set_anchor('C')
        ax_map.legend(loc='upper left', fontsize=8, frameon=True)
        self.style_analysis_axis(ax_map)
        self.analysis_cluster_canvas.draw_idle()

    def refresh_analysis_web_map(self, clean_df, score_points, clusters, summary):
        if not hasattr(self, 'analysis_web_map') or clean_df is None or clean_df.empty:
            return
        try:
            map_path = wm.build_analysis_map(
                clean_df, score_points, clusters, summary,
                reference_point=self.reference_coordinates(),
                colors_name=self.location_colors.currentData() if hasattr(self, 'location_colors') else 'RdYlBu_r',
            )
            self.analysis_web_map.load(QUrl.fromLocalFile(str(map_path)))
        except Exception as exc:
            self.analysis_web_map.setHtml(
                "<html><body style='margin:0;background:#0f172a;color:#e5e7eb;"
                "font-family:Segoe UI,Arial,sans-serif;padding:24px;'>"
                f"<h3>Map could not be rendered</h3><p>{str(exc)}</p></body></html>"
            )
