"""File > Export Data and the anomaly-results export."""
from processing import labels
from processing.labels import FIELD_COLUMNS, field_label
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QMessageBox
from matplotlib.figure import Figure
import numpy as np
from pathlib import Path
from processing import map_maker as mm
from ui import dialogs as dw
from ui.busy import busy
from ui.confirm import confirm


class ExportsMixin:
    """File > Export Data and the anomaly-results export.

    Mixed into GUI.MainWindow; methods use the main window's widgets and state through self.
    """

    def is_imported_file(self, path):
        """True if path is one of the imported source files, so exports never overwrite raw data."""
        target = Path(path).resolve()
        for index in range(self.select_file.count()):
            source = self.select_file.itemData(index, Qt.ItemDataRole.UserRole)
            if source and Path(source).resolve() == target:
                return True
        return False

    def export_dialog(self):
        session = self.active_session()
        if session is None:
            self.statusBar().showMessage('No data to export. Import a dataset first.')
            return
        # suggest a base name next to the source file
        default_path = Path.home() / 'survey_export'
        index = self.select_file.currentIndex()
        if index == -1:
            index = self.active_dataset_index
        if index is not None and 0 <= index < self.select_file.count():
            source_path = Path(self.select_file.itemData(index, Qt.ItemDataRole.UserRole))
            default_path = source_path.with_name(f'{source_path.stem}_export')
        workspace = self.data_workspace
        cleaned = session.cleaned
        fields = [(field_label(column), column) for column in FIELD_COLUMNS if column in cleaned]
        # default raster cell: about 200 cells across the survey, rounded to 1, 2, 2.5 or 5 x 10^n metres
        extent = max(float(np.ptp(cleaned['Easting (m)'])), float(np.ptp(cleaned['Northing (m)'])), 1.0)
        raw_cell = extent / 200
        power = 10 ** np.floor(np.log10(raw_cell))
        cell = min((step * power for step in (1, 2, 2.5, 5, 10) if step * power >= raw_cell), default=raw_cell)
        dialog = dw.DataExportDialog(
            self, default_path,
            signal_plots=[(i, workspace.plot_tabs.tabText(i)) for i in range(workspace.plot_tabs.count())],
            current_signal_plot=workspace.plot_tabs.currentIndex(),
            map_stage=workspace.map_stage.currentIndex(),
            map_style=workspace.map_style.currentText(),
            has_filter=bool(session.filter_history),
            fields=fields,
            current_field=workspace.map_column(),
            raster_available=mm.rasterio is not None,
            kriging_available=mm.OrdinaryKriging is not None,
            default_cell_size=float(round(cell, 2)) or 0.01,
        )
        if dialog.exec():
            self.export_data(dialog.options())

    def export_data(self, options):
        """Write the exports chosen in the Export Data dialog (see DataExportDialog.options)."""
        session = self.active_session()
        workspace = self.data_workspace
        frames = {'cleaned': session.cleaned, 'synchronized': workspace.raw, 'current': session.working}
        raster = options['raster']
        targets = ([path for _, path in options['csv']] + [path for _, path in options['maps']]
                   + [path for _, path in options['signals']] + ([raster['path']] if raster else []))
        if not targets:
            return
        if any(self.is_imported_file(path) for path in targets):
            QMessageBox.warning(self, 'Export Data', 'That name would overwrite an imported data file. Choose a different name.')
            return
        existing = [path for path in targets if path.exists()]
        if existing and not confirm(self, 'Overwrite Files', f'{len(existing)} of these files already exist. Overwrite them?',
                                    '\n'.join(path.name for path in existing[:10]) + ('\n...' if len(existing) > 10 else ''),
                                    yes_text='Overwrite', no_text='Cancel'):
            return
        targets[0].parent.mkdir(parents=True, exist_ok=True)
        dpi = 300 if options['figure_format'] == 'png' else None
        written = []
        try:
            with busy(self, f'Exporting {len(targets)} file(s)...'):
                for key, path in options['csv']:
                    # magnetic columns are named with the survey's unit, e.g. 'BT (nT)'
                    labels.with_units(frames[key], session.field_unit).to_csv(path, index=False)
                    written.append(path)
                if options['maps']:
                    column = workspace.map_column()
                    low, high = workspace.map_limits(column)
                    for stage, path in options['maps']:
                        # drawn off-screen, so maps export even while the Web Map is showing
                        figure = Figure(figsize=(10, 7), constrained_layout=True)
                        workspace.render_map(figure, stage, options['map_style'], column, low, high)
                        figure.savefig(path, dpi=dpi)
                        written.append(path)
                for key, path in options['signals']:
                    page = workspace.plot_tabs.widget(key)
                    if getattr(page, 'canvas', None) is not None:
                        page.canvas.figure.savefig(path, dpi=dpi)
                        written.append(path)
                if raster:
                    frame = frames[raster['dataset']]
                    low, high = workspace.map_limits(raster['field'])
                    info = mm.MapMaker(None).saveMap(
                        str(raster['path']), df=frame, value_column=raster['field'], cell_size=raster['cell_size'],
                        method=raster['method'], projection=raster['projection'], output=raster['output'], vmin=low, vmax=high,
                        units=session.field_unit,
                        cmap=workspace.map_colors.currentData())
                    written.append(raster['path'])
        except Exception as exc:
            done = f'\n\nFiles written before the error:\n' + '\n'.join(p.name for p in written) if written else ''
            QMessageBox.warning(self, 'Export Data', f'Export failed:\n{exc}{done}')
            self.statusBar().showMessage('Export failed.')
            return
        detail = f' | raster {info["width"]} x {info["height"]} cells, {info["crs"]}' if raster else ''
        self.statusBar().showMessage(f'Exported {len(written)} file(s) to {targets[0].parent}{detail}', 12000)

    def export_analysis_results(self):
        """Save the Automated Anomaly Analysis results: scored points, candidate clusters, summary and engineering map."""
        if self.analysis_annotated_df is None:
            self.statusBar().showMessage('No anomaly analysis results to export. Import a dataset first.')
            return

        # suggest a name next to the source file
        default_path = ''
        index = self.analysis_selected_dataset_index
        if index is not None and 0 <= index < self.select_file.count():
            source_path = Path(self.select_file.itemData(index, Qt.ItemDataRole.UserRole))
            default_path = str(source_path.with_name(f'{source_path.stem}_anomalies.csv'))
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            'Export Automated Anomaly Analysis Results',
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
            QMessageBox.warning(self, 'Automated Anomaly Analysis Export', 'That name would overwrite an imported data file. Choose a different name.')
            return
        written = [points_path]
        try:
            unit = self.active_session().field_unit if self.active_session() is not None else labels.display_unit()
            labels.with_units(self.analysis_annotated_df, unit).to_csv(points_path, index=False)
            if self.analysis_clusters is not None and not self.analysis_clusters.empty:
                clusters_path = base_path.with_name(f'{base_path.name}_clusters.csv')
                self.analysis_clusters.to_csv(clusters_path, index=False)
                written.append(clusters_path)
            summary_path = base_path.with_name(f'{base_path.name}_summary.txt')
            summary_path.write_text(self.analysis_summary.toPlainText(), encoding='utf-8')
            written.append(summary_path)
            map_path = base_path.with_name(f'{base_path.name}_engineering_map.png')
            report=getattr(self,'analysis_geoxai_report',None)
            if report is not None:
                for suffix,content in [('_xai_explanation.txt',report.narrative),('_xai_contributions.csv',report.contributions),('_xai_clusters.csv',report.cluster_scores)]:
                    path=base_path.with_name(base_path.name+suffix)
                    if isinstance(content,str):path.write_text(content,encoding='utf-8')
                    else:content.to_csv(path,index=False)
                    written.append(path)
                xai_path=base_path.with_name(base_path.name+'_xai.png');self.analysis_geoxai_figure.savefig(xai_path,dpi=200,bbox_inches='tight');written.append(xai_path)
            self.analysis_cluster_figure.savefig(map_path, dpi=200, bbox_inches='tight')
            written.append(map_path)
        except Exception as exc:
            QMessageBox.warning(self, 'Automated Anomaly Analysis Export', f'Export failed:\n{exc}')
            self.statusBar().showMessage('Automated Anomaly Analysis export failed.')
            return

        self.statusBar().showMessage(f'Automated Anomaly Analysis results exported to {base_path.parent} ({len(written)} files)')
