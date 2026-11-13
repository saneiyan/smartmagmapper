"""The current map field: residual (trend / IGRF) fields, continuation, reduction to pole and VMD map filters."""
from processing import labels
from processing.labels import field_label, signal_label
from PyQt6.QtWidgets import QMessageBox
from pathlib import Path
from processing import map_filter as mf
from processing import map_maker as mm
from ui.web_map_widget import MapWidget


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


class MapFieldMixin:
    """The current map field: residual (trend / IGRF) fields, continuation, reduction to pole and VMD map filters.

    Mixed into GUI.MainWindow; methods use the main window's widgets and state through self.
    """

    def current_map_field_name(self):
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
        mode=self.residual_mode()
        if mode: parts.append(RESIDUAL_LABELS[mode])
        return ' \u2192 '.join(parts)

    def update_field_labels(self):
        session = self.active_session()
        if session:
            self.analysis_dataset_label.setText(f'Active survey: {Path(session.path).name} | {len(session.cleaned)} shared samples')
            self.shared_field_label.setText(f'Current filter result: {self.current_map_field_name()}')

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
            caption = field_label('BT', short=True) + self.filter_suffix(self.current_df['BT'])
            self.web_map_widget = MapWidget(self.map_view(self.current_df), caption=caption,
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
        return f'{RESIDUAL_LABELS[mode]} ({labels.display_unit()})' if mode else labels.total_field_label()

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
                residual = filters.residual_igrf(*self.residual_date, unit=labels.display_unit())
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
        if self.analysis_input.currentIndex() == 1:
            self.run_anomaly_analysis()

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
