"""One filter workspace: explicit inputs, preview, mode inspection, commit, export."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QGroupBox,QLabel,
    QComboBox,QSpinBox,QDoubleSpinBox,QPushButton,QTabWidget,QScrollArea,QFileDialog,QMessageBox,QCheckBox)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from processing import scientific_filters as sf
from ui.vmd_panel import VMDPanel
from processing import labels
from processing.labels import signal_label
from ui.theme import light_figure, panel_toggle, TabArrows, color_scale_combo
from ui.filter_comparison import FilterComparison
from ui.busy import busy, show_status
from ui.confirm import confirm


class FilterWorkspace(QWidget):
    def __init__(self, session_getter, commit, reset, parent=None):
        super().__init__(parent)
        self.get_session,self.commit,self.reset_callback=session_getter,commit,reset
        self.result=None;self.preview_revision=None
        root=QHBoxLayout(self);root.setContentsMargins(12,12,12,12)
        side=QWidget();side.setMaximumWidth(335);side.setMinimumWidth(280)
        outer=QVBoxLayout(side)
        # Filter preview / apply controls as one block, so they can be hidden together on the Compare Filters tab
        # (each control inside keeps its own filter-specific visibility).
        self.filter_controls=QWidget();controls=QVBoxLayout(self.filter_controls);controls.setContentsMargins(0,0,0,0)
        outer.addWidget(self.filter_controls)
        # The selected workspace tab supplies its heading.
        intro=QLabel('Choose a signal and filter. Only settings supported by that filter are shown.')
        intro.setWordWrap(True);controls.addWidget(intro)
        form=QFormLayout();self.input_form=form
        # Labels (with units) are shown; the internal signal name is the item data used by the filters and projects.
        self.field=QComboBox()
        for signal in ['Total magnitude','X','Y','Z']:self.field.addItem(signal_label(signal),signal)
        self.domain=QComboBox();self.domain.addItems(['Time','Path distance','Spatial grid'])
        # Alphabetical list; VMD stays the default selection.
        self.method=QComboBox();self.method.addItems(sorted(sf.SERIES_FILTERS+sf.SPATIAL_FILTERS,key=str.casefold));self.method.setCurrentText('VMD')
        form.addRow('Signal',self.field);form.addRow('Filter',self.method);form.addRow('Series coordinate',self.domain)
        self.domain.view().setRowHidden(2,True)
        self.processing_label=QLabel();self.processing_label.setWordWrap(True);form.addRow(self.processing_label)
        controls.addLayout(form)
        self.series_group=QGroupBox('Series settings');f=QFormLayout(self.series_group);self.series_form=f
        # Limits are deliberately wide: values stay as typed and Preview reports invalid ones in a pop-up.
        self.window_length=QSpinBox();self.window_length.setRange(1,2001);self.window_length.setSingleStep(2);self.window_length.setValue(11)
        self.low=QDoubleSpinBox();self.low.setDecimals(5);self.low.setRange(0,10000);self.low.setValue(.05);self.low.setSingleStep(.01)
        self.high=QDoubleSpinBox();self.high.setDecimals(5);self.high.setRange(0,10000);self.high.setValue(.5);self.high.setSingleStep(.01)
        self.frequency_label=QLabel('Frequency in Hz')
        f.addRow('Window (samples)',self.window_length);f.addRow('Lower / high-pass',self.low);f.addRow('Upper / low-pass',self.high);f.addRow(self.frequency_label)
        self.polynomial_label=QLabel(f'Quadratic - degree {sf.SAVITZKY_POLYORDER} (fixed)')
        self.series_form.addRow('Polynomial',self.polynomial_label)
        controls.addWidget(self.series_group)
        self.vmd_group=QGroupBox('VMD decomposition');f=QFormLayout(self.vmd_group)
        self.k=QSpinBox();self.k.setRange(1,100);self.k.setValue(10)
        self.alpha=QDoubleSpinBox();self.alpha.setRange(0,1000000);self.alpha.setValue(2000);self.alpha.setSingleStep(100)
        f.addRow('Number of modes',self.k);f.addRow('Penalty α',self.alpha);controls.addWidget(self.vmd_group)
        self.spatial_group=QGroupBox('Metric grid / field direction');f=QFormLayout(self.spatial_group);self.spatial_form=f
        self.cell=QDoubleSpinBox();self.cell.setRange(0,1000);self.cell.setValue(2);self.cell.setSuffix(' m')
        self.height=QDoubleSpinBox();self.height.setRange(-1000,1000);self.height.setValue(5);self.height.setSuffix(' m')
        self.gain=QDoubleSpinBox();self.gain.setRange(0,1000);self.gain.setValue(10)
        self.inc=QDoubleSpinBox();self.inc.setRange(-90,90);self.inc.setValue(60);self.inc.setSuffix('°')
        self.dec=QDoubleSpinBox();self.dec.setRange(-180,180);self.dec.setValue(0);self.dec.setSuffix('°')
        self.direction_confirm=QComboBox();self.direction_confirm.addItems(['Enter survey field direction…','Direction entered for this survey'])
        f.addRow('Grid spacing',self.cell);f.addRow('Continuation height',self.height);f.addRow('Inverse gain cap',self.gain)
        f.addRow('Field inclination',self.inc);f.addRow('Field declination',self.dec);f.addRow(self.direction_confirm)
        controls.addWidget(self.spatial_group)
        self.preview_button=QPushButton('Preview Filter');self.preview_button.setObjectName('primaryButton')
        self.preview_button.setToolTip('Preview the filter without changing the working magnetic data. '
                                       'Click Apply Filter Result to apply the output.')
        self.apply_button=QPushButton('Apply Filter Result');self.apply_button.setEnabled(False)
        self.reset_button=QPushButton('Reset (Clear Filter)')
        self.export_button=QPushButton('Export comparison / modes');self.export_button.setEnabled(False)
        for button in [self.preview_button,self.apply_button,self.reset_button,self.export_button]:controls.addWidget(button)
        self.message=QLabel('Import a survey once to begin.');self.message.setWordWrap(True);controls.addWidget(self.message)
        outer.addStretch()
        sc=QScrollArea();sc.setWidgetResizable(True);sc.setWidget(side);sc.setMaximumWidth(360);self.settings_panel=sc
        # Small collapse toggle directly above the settings panel. When collapsed it stays in
        # place as a slim "Settings" button so the panel can always be reopened.
        self.show_settings=panel_toggle(sc,'Hide filter settings','Settings','filter settings')
        settings_column=QVBoxLayout();settings_column.setContentsMargins(0,0,0,0);settings_column.setSpacing(4)
        settings_column.addWidget(self.show_settings,0,Qt.AlignmentFlag.AlignLeft);settings_column.addWidget(sc,1)
        settings_column.addStretch(0)  # keeps the toggle at the top while the panel is collapsed
        root.addLayout(settings_column)
        right=QVBoxLayout();root.addLayout(right,1)
        self.summary=QLabel('No preview yet — original data are preserved.');self.summary.setWordWrap(True);self.summary.setObjectName('processingSummary')
        self.applied_label=QLabel('Applied result: cleaned baseline — no filter applied.');self.applied_label.setWordWrap(True);self.applied_label.setObjectName('processingHistory');self.applied_label.hide()
        # Colour scale for the field maps (Before / After and the Compare Filters maps).
        colors_row=QHBoxLayout();colors_row.addStretch(1);colors_row.addWidget(QLabel('Colour Scale:'))
        self.map_colors=color_scale_combo('viridis');self.map_colors.setMinimumWidth(190)
        self.map_colors.setToolTip('Colour scale for the Before / After maps and the Compare Filters maps.\n'
                                   'The Difference map keeps a blue\u2013red scale centred on zero, so increases and decreases stay distinguishable.')
        colors_row.addWidget(self.map_colors);right.addLayout(colors_row)
        self.tabs=QTabWidget();right.addWidget(self.tabs)
        self.figure=Figure(facecolor='white',figsize=(12,7),constrained_layout=True);self.canvas=FigureCanvas(self.figure)
        # Which panels and plot types the Before / After / Difference view shows; After (the filtered data) is always shown.
        # Starts with just the filtered map; Before, Difference and time series are opt-in.
        self.show_before=QCheckBox('Before');self.show_before.setChecked(False)
        show_after=QCheckBox('After (filtered)');show_after.setChecked(True);show_after.setEnabled(False)
        show_after.setToolTip('The filtered result is always shown.')
        self.show_difference=QCheckBox('Difference');self.show_difference.setChecked(False)
        self.plot_views=QComboBox();self.plot_views.addItems(['Map and time series','Map only','Time series only'])
        self.plot_views.setCurrentText('Map only')
        view_row=QHBoxLayout();view_row.addWidget(QLabel('Show:'))
        for box in (self.show_before,show_after,self.show_difference):view_row.addWidget(box)
        view_row.addSpacing(24);view_row.addWidget(QLabel('Plots:'));view_row.addWidget(self.plot_views);view_row.addStretch(1)
        self.comparison_page=QWidget();page_layout=QVBoxLayout(self.comparison_page);page_layout.setContentsMargins(6,6,6,0)
        page_layout.addLayout(view_row);page_layout.addWidget(self.canvas,1)
        self.tabs.addTab(self.comparison_page,'Before / After / Difference')
        for box in (self.show_before,self.show_difference):box.toggled.connect(self.redraw_preview)
        self.plot_views.currentIndexChanged.connect(self.redraw_preview)
        self.vmd=VMDPanel(editable=True);self.tabs.addTab(self.vmd,'VMD Modes and Selection')
        self.spectrum=Figure(facecolor='white',figsize=(10,5),constrained_layout=True);self.spectrum_canvas=FigureCanvas(self.spectrum)
        self.tabs.addTab(self.spectrum_canvas,'Spectrum')
        self.details=QLabel('Processing notes and settings appear here.');self.details.setWordWrap(True);self.details.setAlignment(Qt.AlignmentFlag.AlignTop)
        notes=QWidget();nl=QVBoxLayout(notes);nl.addWidget(self.summary);nl.addWidget(self.details);nl.addStretch();self.tabs.addTab(notes,'Processing Record')
        self.comparisons=FilterComparison(self)
        self.tabs.addTab(self.comparisons,'Compare Filters')
        # The Compare filters box sits in the settings panel (above the stretch) and shows only on the Compare Filters tab.
        outer.insertWidget(outer.count()-1,self.comparisons.panel)
        self.tabs.currentChanged.connect(self.update_compare_panel);self.update_compare_panel()
        self.tab_arrows=TabArrows(self.tabs)
        self.map_colors.currentIndexChanged.connect(self.redraw_maps)
        self.save_comparison=QPushButton('Store filter results for comparison');self.save_comparison.setEnabled(False)
        controls.insertWidget(controls.indexOf(self.preview_button)+1,self.save_comparison)
        self.save_comparison.clicked.connect(lambda:self.comparisons.add_preview())
        self.preview_button.clicked.connect(self.preview)
        self.apply_button.clicked.connect(self.apply)
        self.reset_button.clicked.connect(self.reset)
        self.export_button.clicked.connect(self.export)
        self.vmd.selectionChanged.connect(self.reconstruct)
        self.domain.currentIndexChanged.connect(self._domain_changed)
        self.method.currentIndexChanged.connect(self._method_changed)
        for widget in [self.field,self.window_length,self.low,self.high,self.k,self.alpha,self.cell,self.height,self.gain,self.inc,self.dec,self.direction_confirm]:
            (widget.currentIndexChanged if isinstance(widget,QComboBox) else widget.valueChanged).connect(self.invalidate)
        self._domain_changed()

    def _domain_changed(self,*_):
        # A coordinate choice never changes the selected filter.
        self._method_changed()

    def _method_changed(self,*_):
        method=self.method.currentText();spatial=method in sf.SPATIAL_FILTERS
        self.domain.blockSignals(True)
        if method=='VMD':self.domain.setCurrentIndex(0)
        elif spatial:self.domain.setCurrentIndex(2)
        elif self.domain.currentIndex()==2:self.domain.setCurrentIndex(0)
        self.domain.blockSignals(False)
        self.input_form.setRowVisible(self.domain,not spatial and method!='VMD')
        self.processing_label.setText('Processing: time series (automatic for VMD).' if method=='VMD' else
            'Processing: projected spatial map (automatic for this transform).' if spatial else
            'Processing: '+self.domain.currentText().lower()+'. Choose time or distance only for this series filter.')
        self.frequency_label.setText('Frequency in Hz' if self.domain.currentText()=='Time' else 'Spatial rate in cycles/m')
        self.series_group.setVisible(not spatial and method not in ('VMD','Linear detrend'))
        self.vmd_group.setVisible(method=='VMD');self.spatial_group.setVisible(spatial)
        self.window_length.setEnabled(method in ('Moving average','Savitzky–Golay'))
        self.low.setEnabled(method in ('High-pass','Band-pass'));self.high.setEnabled(method in ('Low-pass','Band-pass'))
        for control in [self.inc,self.dec,self.direction_confirm]:control.setEnabled(method=='Reduction to pole')
        self.height.setEnabled(spatial and method!='Reduction to pole')
        self.gain.setEnabled(method=='Regularized downward continuation')
        self.tabs.setTabVisible(1,method=='VMD')
        self.tabs.setTabVisible(2,not spatial)
        self.tab_arrows.refresh()
        self.series_form.setRowVisible(self.polynomial_label,method==sf.SERIES_FILTERS[1])
        self.series_form.setRowVisible(self.window_length,method in ('Moving average','Savitzky–Golay'))
        self.series_form.setRowVisible(self.low,method in ('High-pass','Band-pass'))
        self.series_form.setRowVisible(self.high,method in ('Low-pass','Band-pass'))
        self.series_form.setRowVisible(self.frequency_label,method in ('High-pass','Low-pass','Band-pass'))
        for control in [self.inc,self.dec,self.direction_confirm]:self.spatial_form.setRowVisible(control,method=='Reduction to pole')
        self.spatial_form.setRowVisible(self.height,spatial and method!='Reduction to pole')
        self.spatial_form.setRowVisible(self.gain,method=='Regularized downward continuation')
        if method!='VMD' and self.tabs.currentWidget() is self.vmd:self.tabs.setCurrentIndex(0)
        session=self.get_session()
        for index,name in enumerate(['Total magnitude','X','Y','Z']):
            available=session is not None and (name not in 'XYZ' or name in session.cleaned)
            self.field.model().item(index).setEnabled(available and (not spatial or name not in 'XYZ'))
        if spatial and self.field.currentData() in ('X','Y','Z'):self.field.setCurrentIndex(0)
        self.invalidate()

    def invalidate(self,*_):
        self.result=None;self.preview_revision=None
        self.apply_button.setEnabled(False);self.export_button.setEnabled(False)
        if hasattr(self,'save_comparison'):self.save_comparison.setEnabled(False)
        self.vmd.clear();self.figure.clear();self.canvas.draw_idle();self.spectrum.clear();self.spectrum_canvas.draw_idle()
        self.summary.setText('Selected (not applied): '+self.selection_description()+'. Preview again after any setting change.')
        self.update_applied_label()
        if self.get_session() is not None:
            self.details.setText(self.applied_label.text()+"\n\n"+self.selection_description())

    def active_parameters(self):
        method=self.method.currentText()
        if method=='VMD':return {'k_modes':self.k.value(),'alpha':self.alpha.value()}
        if method==sf.SERIES_FILTERS[1]:return {'window':self.window_length.value(),'polyorder':sf.SAVITZKY_POLYORDER}
        if method=='Moving average':return {'window':self.window_length.value()}
        if method=='Low-pass':return {'high':self.high.value()}
        if method=='High-pass':return {'low':self.low.value()}
        if method=='Band-pass':return {'low':self.low.value(),'high':self.high.value()}
        if method=='Linear detrend':return {}
        if method=='Reduction to pole':return {'cell_size':self.cell.value(),'inclination':self.inc.value(),'declination':self.dec.value()}
        values={'cell_size':self.cell.value(),'height':self.height.value()}
        if method=='Regularized downward continuation':values['max_gain']=self.gain.value()
        return values

    @staticmethod
    def settings_description(settings):
        name=settings.get('method','Unknown filter')
        labels={'polyorder':'polynomial degree','window':'window samples','k_modes':'modes','alpha':'α','low':'lower cutoff','high':'upper cutoff',
                'height':'height m','cell_size':'grid m','max_gain':'gain cap','inclination':'inclination°','declination':'declination°'}
        values=[f"{label}={settings[key]}" for key,label in labels.items() if key in settings]
        if 'selected_modes' in settings:values.append('retained '+','.join(map(str,settings['selected_modes'])))
        return name+(' ['+'; '.join(values)+']' if values else '')

    def selection_description(self):
        return self.field.currentText()+' / '+self.domain.currentText()+' / '+self.settings_description(dict(self.active_parameters(),method=self.method.currentText()))

    def update_applied_label(self):
        if not hasattr(self,'applied_label'):return
        session=self.get_session()
        if session is None or not session.filter_history:
            self.applied_label.setText('Applied result: cleaned baseline — no filter applied.')
            return
        history=session.filter_history
        chain=' → '.join(self.settings_description(dict(step['parameters'],method=step['filter'])) for step in history)
        origin=history[0]['parameters'].get('field','cleaned baseline')
        self.applied_label.setText('APPLIED to '+origin+': '+chain+' | Selected controls do not change this result until Preview → Apply.')

    def session_changed(self):
        self.invalidate()
        self.comparisons.session_changed()
        session=self.get_session()
        self.message.setText('Active survey: '+Path(session.path).name if session else 'Import a survey once to begin.')
        if session is not None and self.field.currentData() in ('X','Y','Z') and self.field.currentData() not in session.cleaned:
            self.field.setCurrentIndex(0)
        for i,name in enumerate(['Total magnitude','X','Y','Z']):
            self.field.model().item(i).setEnabled(session is not None and (name not in 'XYZ' or (name in session.cleaned and self.method.currentText() not in sf.SPATIAL_FILTERS)))

    def preview(self):
        session=self.get_session()
        if session is None:self.message.setText('Import a survey first.');return False
        self.invalidate()
        if self.method.currentText()=='Reduction to pole' and self.direction_confirm.currentIndex()!=1:
            text='Enter the field inclination/declination for this survey and confirm them. Displayed defaults are not site estimates.'
            self.message.setText(text);self.show_filter_error('Field Direction Not Confirmed',text,'direction');return False
        error=None
        # Long filters (VMD, spatial grids) block the window; say so in the status bar.
        with busy(self,f'Running {self.method.currentText()} preview on {self.field.currentText()}... VMD and spatial-grid filters can take a while.'):
            try:
                frame=session.cleaned
                result=sf.run_filter(frame,self.field.currentData(),self.domain.currentText(),self.method.currentText(),**self.active_parameters())
                result.settings['input_history']=[]
                result.settings['cleaning']={'startup_samples':session.cleaning_key[0],'spatial_mad_multiplier':session.cleaning_key[1],'fallback_percentile':session.cleaning_key[2]}
                result.settings['source_survey']=Path(session.path).name
                self.vmd.table.setEnabled(True)
                self.result=result;self.preview_revision=session.revision
                self.draw_comparison()
                if result.modes is not None:
                    self.vmd.set_data(result.mode_axis,result.mode_signal,result.modes,result.metrics,result.selected,result.axis_label)
                self.tabs.setTabVisible(1,result.modes is not None);self.tab_arrows.refresh()
                self.tabs.setCurrentIndex(0)
                self.apply_button.setEnabled(True);self.export_button.setEnabled(True)
                self.save_comparison.setEnabled(True)
                self.message.setText('PREVIEW ONLY — '+self.selection_description()+'. Working magnetic data are unchanged.')
                show_status(self,'Filter preview ready: '+self.method.currentText()+'. Review it, then click Apply Filter Result to update the working magnetic data.',8000)
                return True
            except sf.FilterSettingError as exc:error=('Invalid Filter Setting',exc,exc.setting)
            except Exception as exc:error=('Filter Could Not Run',exc,None)
        # Report after the busy cursor is restored so the dialog gets a normal pointer.
        title,exc,setting=error
        self.message.setText(str(exc));show_status(self,'Filter preview failed: '+str(exc))
        self.show_filter_error(title,str(exc),setting)
        return False

    SETTING_CONTROLS={'window':('window_length','Window (samples)'),'low':('low','Lower / high-pass'),'high':('high','Upper / low-pass'),
                      'k_modes':('k','Number of modes'),'alpha':('alpha','Penalty \u03b1'),'cell_size':('cell','Grid spacing'),
                      'height':('height','Continuation height'),'max_gain':('gain','Inverse gain cap'),
                      'inclination':('inc','Field inclination'),'direction':('direction_confirm','Field direction')}

    def show_filter_error(self,title,text,setting=None):
        """Pop up a filter error; for a bad setting, name it and put the cursor in it."""
        control,label=None,None
        if setting in self.SETTING_CONTROLS:
            name,label=self.SETTING_CONTROLS[setting];control=getattr(self,name)
        detail=f'Adjust "{label}" and click Preview Filter again.' if label else 'Check the selected signal, filter, and survey, then preview again.'
        # macOS hides dialog titles, so the title is also the bold heading inside the box.
        box=QMessageBox(QMessageBox.Icon.Warning,title,title,QMessageBox.StandardButton.Ok,self)
        box.setInformativeText(text+'\n\n'+detail);box.exec()
        if control is not None:
            control.setFocus()
            if hasattr(control,'selectAll'):control.selectAll()

    def refresh_unit_labels(self):
        """Show the active survey's unit in the Signal dropdown (the item data stays the internal signal name)."""
        for index in range(self.field.count()):self.field.setItemText(index,signal_label(self.field.itemData(index)))

    def update_compare_panel(self,*_):
        # On Compare Filters only the comparison controls are shown; on the other tabs only the filter controls.
        showing=self.tabs.currentWidget() is self.comparisons
        self.comparisons.panel.setVisible(showing);self.filter_controls.setVisible(not showing)
        if showing:  # scroll the settings panel so the Compare filters box is on screen (after the layout updates)
            QTimer.singleShot(0,lambda:self.settings_panel.ensureWidgetVisible(self.comparisons.panel,0,0))

    def redraw_preview(self,*_):
        if self.result is not None:self.draw_comparison()

    def redraw_maps(self,*_):
        """Redraw the maps that use the colour scale (the current preview and the filter comparison)."""
        if self.result is not None:self.draw_comparison()
        self.comparisons.draw()

    def reconstruct(self,selected):
        if self.result is None:return
        with busy(self,'Reconstructing the filtered signal from the selected VMD modes...'):
            self.result.select_modes(selected);self.draw_comparison()
        show_status(self,'Reconstruction ready. Click Apply Filter Result to update the working magnetic data.',6000)
        self.message.setText('Manual retained modes: '+', '.join(map(str,selected))+'. Click Apply Filter Result to apply this reconstruction.')
        self.apply_button.setEnabled(True)

    def draw_comparison(self):
        r=self.result;session=self.get_session()
        if r is None or session is None:return
        delta=r.after-r.before
        self.summary.setText(f"{signal_label(r.settings['field'])} · {r.settings['method']} · {r.settings['domain']} | {len(r.before)} samples | RMS change {np.sqrt(np.mean(delta**2)):.4g} {labels.display_unit()} | Before std {np.std(r.before):.4g} → after std {np.std(r.after):.4g} {labels.display_unit()}")
        self.figure.clear()
        # Columns: Before (optional), After (always), Difference (optional); rows: time series and/or map.
        panels=([('Before',r.before,'#475569')] if self.show_before.isChecked() else [])+[('After',r.after,'#0f766e')]
        if self.show_difference.isChecked():panels.append(('Difference (after − before)',delta,'#b45309'))
        view=self.plot_views.currentText()
        rows=(['series'] if view!='Map only' else [])+(['map'] if view!='Time series only' else [])
        axes=self.figure.subplots(len(rows),len(panels),squeeze=False)
        # Before and After share limits even when Before is hidden, so the After plots look the same either way.
        lo=min(r.before.min(),r.after.min());hi=max(r.before.max(),r.after.max())
        limit=max(abs(delta).max(),1e-12)
        e=session.cleaned['Easting (m)'];n=session.cleaned['Northing (m)']
        signal_name=signal_label(r.settings['field'])
        for j,(title,value,color) in enumerate(panels):
            difference=title.startswith('Difference')
            units_label=labels.difference_label() if difference else signal_name
            for i,row in enumerate(rows):
                ax=axes[i,j]
                if i==0:ax.set_title(title)
                if row=='series':
                    ax.plot(r.axis,value,lw=.8,color=color);ax.set_xlabel(r.axis_label);ax.set_ylabel(units_label);ax.grid(alpha=.2)
                    if not difference:ax.set_ylim(lo-.05*(hi-lo or 1),hi+.05*(hi-lo or 1))
                else:
                    options=dict(cmap='coolwarm',vmin=-limit,vmax=limit) if difference else dict(cmap=self.map_colors.currentData(),vmin=lo,vmax=hi)
                    im=ax.scatter(e-e.mean(),n-n.mean(),c=value,s=8,**options)
                    ax.set_aspect('equal',adjustable='box');ax.set_xlabel('Relative easting (m)');ax.set_ylabel('Relative northing (m)')
                    self.figure.colorbar(im,ax=ax,label=units_label,shrink=.8)
        light_figure(self.figure)
        self.canvas.draw_idle()
        self.spectrum.clear();ax=self.spectrum.add_subplot()
        if r.settings['domain']=='Spatial grid':
            ax.text(.5,.5,'A time spectrum is not used to describe a two-dimensional spatial transform.',ha='center',va='center',wrap=True);ax.set_axis_off()
        else:
            # Use the recorded uniform processing spacing, not an assumed sample rate.
            count=int(round((r.axis.max()-r.axis.min())/r.settings['spacing']))+1
            x=np.linspace(r.axis.min(),r.axis.max(),count)
            for value,label,color in [(r.before,'Before','#475569'),(r.after,'After','#0f766e')]:
                y=np.interp(x,r.axis,value);freq=np.fft.rfftfreq(len(x),x[1]-x[0]);power=abs(np.fft.rfft(y-y.mean()))**2/len(y)
                ax.semilogy(freq,np.maximum(power,1e-16),label=label,color=color)
            ax.set_xlabel('Frequency (Hz)' if r.settings['domain']=='Time' else 'Spatial rate (cycles/m)');ax.set_ylabel(f'Squared FFT amplitude / N ({labels.display_unit()}\u00b2)');ax.legend();ax.grid(alpha=.2)
        light_figure(self.spectrum)
        self.spectrum_canvas.draw_idle()
        self.details.setText('\n\n'.join(r.notes)+'\n\nSettings:\n'+json.dumps(r.settings,indent=2,ensure_ascii=False))

    def apply(self):
        session=self.get_session()
        if self.result is None or session is None:return False
        if session.revision!=self.preview_revision:
            self.invalidate();self.message.setText('The survey changed. Preview the filter again before storing it.');return False
        r=self.result
        frame=session.cleaned.copy(deep=True)
        # Preserve the cleaned components and store the selected filter output for display and export.
        frame['BT']=r.after
        # commit()updates the working data and redraw the map.
        with busy(self,'Applying filter result... updating working data and maps.'):
            self.commit(frame,r.settings)
        self.preview_revision=None
        self.vmd.table.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.update_applied_label()
        self.details.setText(self.applied_label.text()+"\n\n"+json.dumps(r.settings,indent=2)+"\n\n"+"\n".join(r.notes))
        self.message.setText('APPLIED — '+self.settings_description(r.settings)+'. Working magnetic data updated.')
        return True

    def reset(self):
        session=self.get_session()
        history=session.filter_history if session is not None else []
        detail=('This removes the applied filter result ('+' \u2192 '.join(step['filter'] for step in history)+') from the current field and restores the cleaned data.'
                if history else 'No filter is currently applied; the current field is already the cleaned data.')
        if not confirm(self,'Reset to Cleaned Baseline',"Are you sure you'd like to reset to the cleaned baseline?",
                       detail+' Saved comparison previews are kept.',yes_text='Reset',no_text='Cancel'):return
        with busy(self,'Restoring the cleaned baseline... updating maps and analysis.'):
            self.reset_callback();self.session_changed()

    def export(self):
        if self.result is None:return
        path,_=QFileDialog.getSaveFileName(self,'Export filter comparison','','CSV files (*.csv)')
        if not path:return
        base=Path(path).with_suffix('');session=self.get_session();r=self.result
        targets=[base.with_suffix('.csv'),base.with_name(base.name+'_settings.json'),base.with_name(base.name+'_comparison.png')]
        if r.modes is not None:targets += [base.with_name(base.name+'_modes.csv'),base.with_name(base.name+'_mode_metrics.csv')]
        parent=self.parent()
        owner=self.window()
        if any(getattr(owner,'is_imported_file',lambda _:False)(q) for q in targets):
            self.message.setText('Choose another output name to preserve imported source files.');return
        data=session.cleaned[['Time (s)','Easting (m)','Northing (m)']].copy()
        unit=session.field_unit  # exported column names carry the survey's unit
        data[f'Before ({unit})']=r.before;data[f'After ({unit})']=r.after;data[f'Difference ({unit})']=r.after-r.before
        data.to_csv(targets[0],index=False)
        targets[1].write_text(json.dumps(dict(r.settings,notes=r.notes),indent=2,ensure_ascii=False),encoding='utf-8')
        self.figure.savefig(targets[2],dpi=180)
        if r.modes is not None:
            modes=pd.DataFrame(r.modes.T,columns=[f'Mode_{i+1}' for i in range(len(r.modes))]);modes.insert(0,r.axis_label,r.mode_axis);modes.to_csv(targets[3],index=False)
            metrics=r.metrics.copy();metrics['retained']=metrics['mode'].isin(r.selected);metrics.to_csv(targets[4],index=False)
        self.message.setText('Comparison, processing settings, and available mode diagnostics exported.')
