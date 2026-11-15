"""Survey import, cleaning and current-field actions of the main window."""
from processing import labels
from PyQt6.QtWidgets import QFileDialog, QMessageBox
from pathlib import Path
from processing.survey_session import SurveySession
from processing import map_maker as mm
from ui import dialogs as dw
from processing import data_analysis_pipeline as dap
from ui.busy import busy
import os
from ui.map_field import TOTAL_FIELD


class SurveyActionsMixin:
    """Survey import, cleaning and current-field actions of the main window.

    Mixed into GUI.MainWindow; methods use the main window's widgets and state through self.
    """

    def commit_filter_result(self,frame,settings):
        filters = [settings['method']]
        self.filtered_scale_changed(
            frame,
            filters=filters,
            parameters=settings,
            replace_history=True,
            status_message='Filter Lab working data updated.'
        )

    def suggested_cleaning(self, session):
        """Data-based startup / MAD suggestion for a survey, computed once and kept on the session."""
        if session.suggested_cleaning is None:
            try:
                session.suggested_cleaning = dap.suggest_cleaning_settings(session.magnetometer, session.location)
            except Exception:
                session.suggested_cleaning = {}  # e.g. too few samples: keep the current settings
        return session.suggested_cleaning

    def apply_suggested_cleaning(self, session):
        """Fill the startup and MAD boxes with the survey's data-based suggestion (no pending-change marker)."""
        suggestion = self.suggested_cleaning(session)
        if not suggestion:
            return
        self.data_workspace.set_cleaning_values(suggestion['startup_samples'], suggestion['spatial_mad_multiplier'])

    def register_survey(self, path, mag, gps, field_unit=labels.DEFAULT_UNIT, coordinates=None):
        candidate = SurveySession(path, mag, gps, field_unit=field_unit,
                                  coordinates=coordinates or {'format': 'decimal_degrees'})
        # Startup removal and the MAD multiplier start from this survey's own sampling and movement.
        self.apply_suggested_cleaning(candidate)
        candidate.ensure_cleaned(self.analysis_params())
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
        if hasattr(self,'project_tools'):self.project_tools.data_imported()
        return index

    def refresh_unit_labels(self):
        """Update fixed text (dropdown entries, labels) to the active survey's magnetic unit."""
        unit = labels.display_unit()
        self.data_workspace.refresh_unit_labels()
        self.filters_workspace.refresh_unit_labels()
        self.analysis_input.setItemText(0, labels.total_field_label())
        self.vmax_label.setText(f'Maximum BT ({unit}):');self.vmin_label.setText(f'Minimum BT ({unit}):')
        self.set_vmax.setPlaceholderText(f'Max BT ({unit})');self.set_vmin.setPlaceholderText(f'Min BT ({unit})')

    def activate_survey(self, index):
        if index is None or not 0 <= index < len(self.sessions):
            return
        self.analysis_update_timer.stop()
        self.analysis_reload_timer.stop()
        self.clear_analysis_results('Loading shared survey...')
        session = self.sessions[index]
        # Every label shows the active survey's magnetic unit.
        labels.set_display_unit(session.field_unit)
        self.refresh_unit_labels()
        if hasattr(self,'project_tools') and self.active_dataset_index!=index:self.project_tools.select_survey_cleaning(session)
        session.ensure_cleaned(self.analysis_params())
        self.active_dataset_index = index
        self.analysis_selected_dataset_index = index
        self.analysis_selected_dataset = session.cleaned
        self.analysis_file_path = session.path
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
        self.run_anomaly_analysis()

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

    def read_from_dialog(self):
        dlg = self.dlg
        mag, gps = dlg.build_streams()
        settings = dlg.import_settings
        return self.register_survey(dlg.file_paths[0], mag, gps, field_unit=settings['field_unit'],
                                    coordinates=settings['coordinates'])

    def store_dataset(self, file_path, raw_file):
        raise RuntimeError('Use register_survey so both workspaces share validated survey streams.')

    def _populate_dataset_selector(self, select_index=None):
        # Compatibility hook: the only dataset selector is now the global one.
        if select_index is not None:
            self.select_file.setCurrentIndex(select_index)

    def _update_dataset(self, index):
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
            ok = self.reload_active_survey()
        if ok:
            workspace.set_cleaning_pending(False)
            session = self.active_session()
            self.statusBar().showMessage(f'Cleaning settings updated: {len(session.cleaned):,} samples retained.', 8000)
        else:
            workspace.update_cleaning.setEnabled(True)

    def import_survey_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            'Select Magnetic Survey',
            '',
            'Survey files (*.xls *.xlsx *.xlsm *.csv);;All files (*.*)',
        )
        if file_path:
            self.load_survey_file(file_path)

    def reload_active_survey(self):
        if self.active_session() is not None:
            try:
                self.activate_survey(self.active_dataset_index)
                return True
            except Exception as exc:
                self.data_workspace.status.show()
                self.data_workspace.status.setText(f'Cleaning settings could not be applied: {exc}. Displayed data retain the last successful settings.')
                self.filters_workspace.invalidate()
                self.clear_analysis_results(f'Cleaning settings could not be applied: {exc}')
                self.statusBar().showMessage('Adjust cleaning settings to retain enough valid samples.')
        return False

    def load_survey_file(self, file_path):
        # Startup paths and file-dialog imports enter the same registration path.
        try:
            mag, gps = dap.read_survey_file(file_path)
            # unit from the column headers (e.g. 'X (nT)'); the default unit when the headers do not say
            self.register_survey(file_path, mag, gps, field_unit=mag.attrs.get('field_unit') or labels.DEFAULT_UNIT)
        except Exception as exc:
            QMessageBox.warning(self, 'Survey import', str(exc))
            return False
        return True

    def select_display_file(self, index):
        if not hasattr(self, 'sessions') or index < 0 or index >= len(self.sessions):
            return
        try:
            self.activate_survey(index)
        except Exception as exc:
            self.select_file.blockSignals(True)
            self.select_file.setCurrentIndex(self.active_dataset_index)
            self.select_file.blockSignals(False)
            self.clear_analysis_results(f'Survey unavailable: {exc}')
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
        # Original Map and Data Table remain the reproducible cleaned baseline.
        self.figure.clear();self.axes=self.figure.add_subplot()
        mapper=mm.MapMaker(original)
        mapper.showMap(original,ax=self.axes,cbar_label=f'Cleaned {labels.total_field_label()}')
        self.axes.set_title('Original survey — cleaned total magnetic field')
        self.canvas.draw_idle()
        self.data_workspace.show_survey(original)
        self.add_menu(original.columns)

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
        self.statusBar().showMessage(status_message or 'Working magnetic field updated.')

    def clear_data(self, df):
        #clear previous plots
        self.axes.clear()
        self.figure.clear()
        self.canvas.draw()

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
        self.run_anomaly_analysis()
        self.filters_workspace.session_changed()
        self.statusBar().showMessage('Restored the shared cleaned survey field.')
        if hasattr(self,'project_tools'):self.project_tools.changed()
