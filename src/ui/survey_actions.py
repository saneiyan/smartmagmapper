"""Survey import, cleaning and current-field actions of the main window."""
from processing import labels
from processing.labels import signal_label
from PyQt6.QtWidgets import QMessageBox
from pathlib import Path
from processing.survey_session import SurveySession
from ui import dialogs as dw
from processing import data_analysis_pipeline as dap
from ui.busy import busy
import os


class SurveyActionsMixin:
    """Survey import, cleaning and current-field actions of the main window.

    Mixed into GUI.MainWindow; methods use the main window's widgets and state through self.
    """

    def commit_filter_result(self,frame,settings):
        """Make a stored Filter Lab result the working magnetic data (filters run independently on the cleaned data).

        Parameters
        ----------
        frame : pandas.DataFrame
            Cleaned data with the filtered values in BT.
        settings : dict
            Filter settings; the new result replaces any earlier filter.
        """
        filters = [settings['method']]
        self.filtered_scale_changed(
            frame,
            filters=filters,
            parameters=settings,
            replace_history=True,
            status_message='Filter Lab working data updated.'
        )

    def suggested_cleaning(self, session):
        """Data-based startup / MAD suggestion for a survey, computed once and kept on the session.

        Parameters
        ----------
        session : processing.survey_session.SurveySession
            Survey.

        Returns
        -------
        dict
            Output of data_analysis_pipeline.suggest_cleaning_settings, or an empty dict if it could not be computed.
        """
        if session.suggested_cleaning is None:
            try:
                session.suggested_cleaning = dap.suggest_cleaning_settings(session.magnetometer, session.location)
            except Exception:
                session.suggested_cleaning = {}
        return session.suggested_cleaning

    def apply_suggested_cleaning(self, session):
        """Fill the startup and MAD boxes with the survey's data-based suggestion (no pending-change marker).

        Parameters
        ----------
        session : processing.survey_session.SurveySession
            Survey.
        """
        suggestion = self.suggested_cleaning(session)
        if not suggestion:
            return
        self.data_workspace.set_cleaning_values(suggestion['startup_samples'], suggestion['spatial_mad_multiplier'])

    def register_survey(self, path, mag, gps, field_unit=labels.DEFAULT_UNIT, coordinates=None):
        """Add a survey (or replace the one with the same path), clean it and make it the active survey.

        Parameters
        ----------
        path : str
            Source file path.
        mag, gps : pandas.DataFrame
            Magnetometer and GPS streams.
        field_unit : str, optional
            Unit of the magnetic values.
        coordinates : dict, optional
            How the coordinates were recorded; decimal degrees by default.

        Returns
        -------
        int
            Index of the survey in the survey list.
        """
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
        self.data_workspace.refresh_unit_labels()
        self.filters_workspace.refresh_unit_labels()
        self.analysis_input.setItemText(0, labels.total_field_label())

    def activate_survey(self, index):
        """Show a survey in every tab and rerun the analysis.

        Parameters
        ----------
        index : int
            Index in the survey list; out-of-range values are ignored.
        """
        if index is None or not 0 <= index < len(self.sessions):
            return
        self.analysis_update_timer.stop()
        self.clear_analysis_results('Loading shared survey...')
        session = self.sessions[index]
        # Every label shows the active survey's magnetic unit.
        labels.set_display_unit(session.field_unit)
        self.refresh_unit_labels()
        if hasattr(self,'project_tools') and self.active_dataset_index!=index:self.project_tools.select_survey_cleaning(session)
        session.ensure_cleaned(self.analysis_params())
        self.active_dataset_index = index
        self.analysis_selected_dataset_index = index
        self.active_filters = list(session.filters)
        self.display_processed_df(session.working)
        self.update_field_labels()
        self.filters_workspace.session_changed()
        self.data_workspace.refresh()
        # Displayed data now match the cleaning controls.
        self.data_workspace.set_cleaning_pending(False)
        self.run_anomaly_analysis()

    def import_data_action(self):
        """File > Import Data: open the import dialog."""
        self.file_editor_window()

    def file_editor_window(self):
        # parented to the main window so the dialog opens above it
        """Open the Import Data dialog; OK imports the survey (the dialog stays open if the import fails)."""
        self.dlg = dw.CustomDialog(self)
        # OK validates and imports first; the dialog only closes when that succeeds
        self.dlg.FinishBtn.accepted.connect(self._dialog_finish_handler)
        self.dlg.exec()

    def read_from_dialog(self):
        """Import the survey described in the Import Data dialog.

        Returns
        -------
        int
            Index of the new survey.

        Raises
        ------
        ValueError
            If the file or column choices are incomplete or the coordinates cannot be converted.
        """
        dlg = self.dlg
        mag, gps = dlg.build_streams()
        settings = dlg.import_settings
        return self.register_survey(dlg.file_paths[0], mag, gps, field_unit=settings['field_unit'],
                                    coordinates=settings['coordinates'])

    def _dialog_finish_handler(self):
        """OK in the Import Data dialog: import, or show what is wrong and keep the dialog open."""
        try:
            self.read_from_dialog()
        except Exception as exc:
            QMessageBox.warning(self.dlg, 'Survey import', str(exc))
            return
        self.dlg.accept()

    def cleaning_settings_edited(self, *_):
        """Mark the cleaning settings as changed until Update Cleaning Settings is clicked.

        Parameters
        ----------
        *_ : object
            Ignored signal arguments.
        """
        if self.active_session() is None:
            return
        self.data_workspace.set_cleaning_pending(True)
        self.statusBar().showMessage('Cleaning settings changed. Click "Update Cleaning Settings" to apply them.')

    def apply_cleaning_settings(self):
        """Update Cleaning Settings: re-clean the active survey and rerun the analysis."""
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

    def reload_active_survey(self):
        """Re-activate the active survey with the current cleaning settings.

        Returns
        -------
        bool
            True on success; on failure the previous data stay on screen and the problem is shown.
        """
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
        """Import a survey file directly (no dialog), e.g. one given on the command line.

        The magnetic unit is taken from the column headers when they state it, otherwise the default unit.

        Parameters
        ----------
        file_path : str
            Survey file (see data_analysis_pipeline.read_survey_file).

        Returns
        -------
        bool
            True if the survey was imported; problems are shown in a message box.
        """
        try:
            mag, gps = dap.read_survey_file(file_path)
            # unit from the column headers (e.g. 'X (nT)'); the default unit when the headers do not say
            self.register_survey(file_path, mag, gps, field_unit=mag.attrs.get('field_unit') or labels.DEFAULT_UNIT)
        except Exception as exc:
            QMessageBox.warning(self, 'Survey import', str(exc))
            return False
        return True

    def select_display_file(self, index):
        """Active survey dropdown changed: show that survey (or go back to the previous one if it fails).

        Parameters
        ----------
        index : int
            Index in the survey list.
        """
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

    def display_processed_df(self,df):
        """Show the active survey's cleaned baseline in the Data & Cleaning tables and signal plots.

        Parameters
        ----------
        df : pandas.DataFrame
            Current field; used only when no survey is active.
        """
        session=self.active_session()
        original=session.cleaned if session else df
        # The Data & Cleaning tables and signal plots always show the reproducible cleaned baseline.
        self.data_workspace.show_survey(original)
        if session is not None:self.data_workspace.update_signal_columns(session.cleaned)

    def current_map_field_name(self):
        """Describe the current field, e.g. 'Total Magnetic Field (BT) (nT) → High-pass'.

        Returns
        -------
        str
            The input signal followed by every applied filter (VMD modes and continuation heights included).
        """
        session=self.active_session()
        if session is None or not session.filter_history:
            return f'Cleaned {labels.total_field_label()}'
        history=session.filter_history
        signal=history[0]['parameters'].get('field','Total magnitude')
        parts=[signal_label(signal)]
        for step in history:
            settings=step['parameters'];name=step['filter']
            if name=='VMD' and settings.get('selected_modes'):
                name+=' (modes '+', '.join(map(str,settings['selected_modes']))+')'
            elif 'continuation' in name.lower() and 'height' in settings:
                name+=f" ({settings['height']:g} m)"
            parts.append(name)
        return ' \u2192 '.join(parts)

    def update_field_labels(self):
        """Update the active-survey and current-field labels."""
        session = self.active_session()
        if session:
            self.analysis_dataset_label.setText(f'Active survey: {Path(session.path).name} | {len(session.cleaned)} shared samples')
            self.shared_field_label.setText(f'Current filter result: {self.current_map_field_name()}')

    def filtered_scale_changed(self, df, status_message=None, filters=None, parameters=None, replace_history=False):
        """Store a new current field and update every view.

        Parameters
        ----------
        df : pandas.DataFrame
            New current field.
        status_message : str, optional
            Status bar message after the update.
        filters : list of str, optional
            All filters applied to the new field; defaults to the active filters.
        parameters : dict, optional
            Settings of the filter just applied.
        replace_history : bool, optional
            Start a new filter history instead of adding to it.
        """
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
        self.display_processed_df(session.working)
        self.update_field_labels()
        self.statusBar().showMessage(status_message or 'Working magnetic field updated.')

    def reset_map(self):
        """Reset (Clear Filter): restore the current field to the cleaned baseline and rerun the analysis."""
        session = self.active_session()
        if session is None:
            return
        session.reset_field()
        self.active_filters = []
        self.display_processed_df(session.working)
        self.update_field_labels()
        self.data_workspace.refresh()
        self.run_anomaly_analysis()
        self.filters_workspace.session_changed()
        self.statusBar().showMessage('Restored the shared cleaned survey field.')
        if hasattr(self,'project_tools'):self.project_tools.changed()
