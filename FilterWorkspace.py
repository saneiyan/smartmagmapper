"""One filter workspace: explicit inputs, preview, mode inspection, commit, export."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QGroupBox,QLabel,
    QComboBox,QSpinBox,QDoubleSpinBox,QPushButton,QTabWidget,QSplitter,QScrollArea,QFileDialog,QApplication)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
import ScientificFilters as sf
from VMDPanel import VMDPanel
from PlotTheme import light_figure
from FilterComparison import FilterComparison


class OddWindowSpinBox(QSpinBox):
    def valueFromText(self, text):
        value=super().valueFromText(text)
        return min(self.maximum(), value if value%2 else value+1)


class FilterWorkspace(QWidget):
    def __init__(self, session_getter, commit, reset, parent=None):
        super().__init__(parent)
        self.get_session,self.commit,self.reset_callback=session_getter,commit,reset
        self.result=None;self.preview_revision=None
        root=QHBoxLayout(self);root.setContentsMargins(12,12,12,12)
        side=QWidget();side.setMaximumWidth(335);side.setMinimumWidth(280)
        controls=QVBoxLayout(side)
        # The selected workspace tab supplies its heading.
        intro=QLabel('Choose a signal and filter. Only settings supported by that filter are shown.')
        intro.setWordWrap(True);controls.addWidget(intro)
        form=QFormLayout();self.input_form=form
        self.field=QComboBox();self.field.addItems(['Total magnitude','X','Y','Z','Current result'])
        self.domain=QComboBox();self.domain.addItems(['Time','Path distance','Spatial grid'])
        self.method=QComboBox();self.method.addItems(sf.SERIES_FILTERS+sf.SPATIAL_FILTERS)
        form.addRow('Signal',self.field);form.addRow('Filter',self.method);form.addRow('Series coordinate',self.domain)
        self.domain.view().setRowHidden(2,True)
        self.processing_label=QLabel();self.processing_label.setWordWrap(True);form.addRow(self.processing_label)
        controls.addLayout(form)
        self.series_group=QGroupBox('Series settings');f=QFormLayout(self.series_group);self.series_form=f
        self.window_length=OddWindowSpinBox();self.window_length.setRange(3,2001);self.window_length.setSingleStep(2);self.window_length.setValue(11)
        self.low=QDoubleSpinBox();self.low.setDecimals(5);self.low.setRange(.00001,10000);self.low.setValue(.05);self.low.setSingleStep(.01)
        self.high=QDoubleSpinBox();self.high.setDecimals(5);self.high.setRange(.00001,10000);self.high.setValue(.5);self.high.setSingleStep(.01)
        self.frequency_label=QLabel('Frequency in Hz')
        f.addRow('Window (samples)',self.window_length);f.addRow('Lower / high-pass',self.low);f.addRow('Upper / low-pass',self.high);f.addRow(self.frequency_label)
        self.polynomial_label=QLabel(f'Quadratic - degree {sf.SAVITZKY_POLYORDER} (fixed)')
        self.series_form.addRow('Polynomial',self.polynomial_label)
        controls.addWidget(self.series_group)
        self.vmd_group=QGroupBox('VMD decomposition');f=QFormLayout(self.vmd_group)
        self.k=QSpinBox();self.k.setRange(2,20);self.k.setValue(10)
        self.alpha=QDoubleSpinBox();self.alpha.setRange(10,100000);self.alpha.setValue(2000);self.alpha.setSingleStep(100)
        f.addRow('Number of modes',self.k);f.addRow('Penalty α',self.alpha);controls.addWidget(self.vmd_group)
        self.spatial_group=QGroupBox('Metric grid / field direction');f=QFormLayout(self.spatial_group);self.spatial_form=f
        self.cell=QDoubleSpinBox();self.cell.setRange(.05,1000);self.cell.setValue(2);self.cell.setSuffix(' m')
        self.height=QDoubleSpinBox();self.height.setRange(0,1000);self.height.setValue(5);self.height.setSuffix(' m')
        self.gain=QDoubleSpinBox();self.gain.setRange(1,100);self.gain.setValue(10)
        self.inc=QDoubleSpinBox();self.inc.setRange(-90,90);self.inc.setValue(60);self.inc.setSuffix('°')
        self.dec=QDoubleSpinBox();self.dec.setRange(-180,180);self.dec.setValue(0);self.dec.setSuffix('°')
        self.direction_confirm=QComboBox();self.direction_confirm.addItems(['Enter survey field direction…','Direction entered for this survey'])
        f.addRow('Grid spacing',self.cell);f.addRow('Continuation height',self.height);f.addRow('Inverse gain cap',self.gain)
        f.addRow('Field inclination',self.inc);f.addRow('Field declination',self.dec);f.addRow(self.direction_confirm)
        controls.addWidget(self.spatial_group)
        self.preview_button=QPushButton('Preview filter');self.preview_button.setObjectName('primaryButton')
        self.apply_button=QPushButton('Use result as current field');self.apply_button.setEnabled(False)
        self.reset_button=QPushButton('Reset to cleaned baseline')
        self.export_button=QPushButton('Export comparison / modes');self.export_button.setEnabled(False)
        for button in [self.preview_button,self.apply_button,self.reset_button,self.export_button]:controls.addWidget(button)
        self.message=QLabel('Import a survey once to begin.');self.message.setWordWrap(True);controls.addWidget(self.message)
        controls.addStretch()
        sc=QScrollArea();sc.setWidgetResizable(True);sc.setWidget(side);sc.setMaximumWidth(360);root.addWidget(sc)
        right=QVBoxLayout();root.addLayout(right,1)
        self.show_settings=QPushButton('Filter settings');self.show_settings.setCheckable(True);self.show_settings.setChecked(True)
        self.show_settings.toggled.connect(sc.setVisible);right.addWidget(self.show_settings)
        self.summary=QLabel('No preview yet — original data are preserved.');self.summary.setWordWrap(True);self.summary.setObjectName('processingSummary')
        self.applied_label=QLabel('Applied result: cleaned baseline — no filter applied.');self.applied_label.setWordWrap(True);self.applied_label.setObjectName('processingHistory');self.applied_label.hide()
        self.tabs=QTabWidget();right.addWidget(self.tabs)
        self.figure=Figure(facecolor='white',figsize=(12,7),constrained_layout=True);self.canvas=FigureCanvas(self.figure)
        self.tabs.addTab(self.canvas,'Before / After / Difference')
        self.vmd=VMDPanel(editable=True);self.tabs.addTab(self.vmd,'VMD Modes and Selection')
        self.spectrum=Figure(facecolor='white',figsize=(10,5),constrained_layout=True);self.spectrum_canvas=FigureCanvas(self.spectrum)
        self.tabs.addTab(self.spectrum_canvas,'Spectrum')
        self.details=QLabel('Processing notes and settings appear here.');self.details.setWordWrap(True);self.details.setAlignment(Qt.AlignmentFlag.AlignTop)
        notes=QWidget();nl=QVBoxLayout(notes);nl.addWidget(self.summary);nl.addWidget(self.details);nl.addStretch();self.tabs.addTab(notes,'Processing Record')
        self.comparisons=FilterComparison(self)
        self.tabs.addTab(self.comparisons,'Compare Filters')
        self.save_comparison=QPushButton('Save preview for comparison');self.save_comparison.setEnabled(False)
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
        for index,name in enumerate(['Total magnitude','X','Y','Z','Current result']):
            available=session is not None and (name not in 'XYZ' or f'{name} (\u00b5T)' in session.cleaned)
            self.field.model().item(index).setEnabled(available and (not spatial or name not in 'XYZ'))
        if spatial and self.field.currentText() in ('X','Y','Z'):self.field.setCurrentIndex(0)
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
        if session is not None and self.field.currentText() in ('X','Y','Z') and f'{self.field.currentText()} (µT)' not in session.cleaned:
            self.field.setCurrentIndex(0)
        for i,name in enumerate(['Total magnitude','X','Y','Z','Current result']):
            self.field.model().item(i).setEnabled(session is not None and (name not in 'XYZ' or (f'{name} (µT)' in session.cleaned and self.method.currentText() not in sf.SPATIAL_FILTERS)))

    def preview(self):
        session=self.get_session()
        if session is None:self.message.setText('Import a survey first.');return False
        self.invalidate()
        if self.method.currentText()=='Reduction to pole' and self.direction_confirm.currentIndex()!=1:
            self.message.setText('Enter the field inclination/declination for this survey and confirm them. Displayed defaults are not site estimates.');return False
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if self.domain.currentText() == 'Spatial grid' and self.field.currentText() == 'Current result':
                history=session.filter_history
                if any(step['parameters'].get('field') in ('X','Y','Z') for step in history):
                    raise ValueError('Choose Total magnitude for spatial transforms; the current result came from a phone component.')
            frame=session.working if self.field.currentText()=='Current result' else session.cleaned
            result=sf.run_filter(frame,self.field.currentText(),self.domain.currentText(),self.method.currentText(),**self.active_parameters())
            result.settings['input_history']=json.loads(json.dumps(session.filter_history)) if self.field.currentText()=='Current result' else []
            result.settings['cleaning']={'startup_samples':session.cleaning_key[0],'spatial_mad_multiplier':session.cleaning_key[1],'fallback_percentile':session.cleaning_key[2]}
            result.settings['source_survey']=Path(session.path).name
            self.vmd.table.setEnabled(True)
            self.result=result;self.preview_revision=session.revision
            self.draw_comparison()
            if result.modes is not None:
                self.vmd.set_data(result.mode_axis,result.mode_signal,result.modes,result.metrics,result.selected,result.axis_label)
            self.tabs.setTabVisible(1,result.modes is not None)
            self.tabs.setCurrentIndex(0)
            self.apply_button.setEnabled(True);self.export_button.setEnabled(True)
            self.save_comparison.setEnabled(True)
            self.message.setText('PREVIEW ONLY — '+self.selection_description()+'. Click Apply to change the current result.')
            return True
        except Exception as exc:
            self.message.setText(str(exc));return False
        finally:QApplication.restoreOverrideCursor()

    def reconstruct(self,selected):
        if self.result is None:return
        self.result.select_modes(selected);self.draw_comparison()
        self.message.setText('Manual retained modes: '+', '.join(map(str,selected))+'. Apply to use this reconstruction.')
        self.apply_button.setEnabled(True)

    def draw_comparison(self):
        r=self.result;session=self.get_session()
        if r is None or session is None:return
        delta=r.after-r.before
        self.summary.setText(f"{r.settings['field']} · {r.settings['method']} · {r.settings['domain']} | {len(r.before)} samples | RMS change {np.sqrt(np.mean(delta**2)):.4g} µT | Before std {np.std(r.before):.4g} → after std {np.std(r.after):.4g} µT")
        self.figure.clear();axes=self.figure.subplots(2,3)
        values=[r.before,r.after,delta];titles=['Before','After','Difference (after − before)']
        lo=min(r.before.min(),r.after.min());hi=max(r.before.max(),r.after.max())
        for j,(value,title) in enumerate(zip(values,titles)):
            ax=axes[0,j];ax.plot(r.axis,value,lw=.8,color=['#475569','#0f766e','#b45309'][j]);ax.set_title(title);ax.set_xlabel(r.axis_label);ax.set_ylabel('µT');ax.grid(alpha=.2)
            if j<2:ax.set_ylim(lo-.05*(hi-lo or 1),hi+.05*(hi-lo or 1))
            ax=axes[1,j]
            e=session.cleaned['Easting (m)'];n=session.cleaned['Northing (m)']
            options=dict(cmap='viridis',vmin=lo,vmax=hi) if j<2 else dict(cmap='coolwarm',vmin=-max(abs(delta).max(),1e-12),vmax=max(abs(delta).max(),1e-12))
            im=ax.scatter(e-e.mean(),n-n.mean(),c=value,s=8,**options)
            ax.set_aspect('equal',adjustable='box');ax.set_xlabel('Relative easting (m)');ax.set_ylabel('Relative northing (m)')
            self.figure.colorbar(im,ax=ax,label='µT',shrink=.8)
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
            ax.set_xlabel('Frequency (Hz)' if r.settings['domain']=='Time' else 'Spatial rate (cycles/m)');ax.set_ylabel('Squared FFT amplitude / N (µT²)');ax.legend();ax.grid(alpha=.2)
        light_figure(self.spectrum)
        self.spectrum_canvas.draw_idle()
        self.details.setText('\n\n'.join(r.notes)+'\n\nSettings:\n'+json.dumps(r.settings,indent=2,ensure_ascii=False))

    def apply(self):
        session=self.get_session()
        if self.result is None or session is None:return False
        if session.revision!=self.preview_revision:
            self.invalidate();self.message.setText('The survey changed. Preview again before applying.');return False
        r=self.result
        frame=session.working.copy(deep=True)
        # Keep the measured components intact; selected-axis results get their own scalar field.
        frame['Filtered_Field_uT']=r.after
        frame['BT']=r.after
        self.commit(frame,r.settings)
        self.preview_revision=None
        self.vmd.table.setEnabled(False)
        self.apply_button.setEnabled(False)
        self.update_applied_label()
        self.details.setText(self.applied_label.text()+"\n\n"+json.dumps(r.settings,indent=2)+"\n\n"+"\n".join(r.notes))
        self.message.setText('APPLIED — '+self.settings_description(r.settings)+'. This result is now available to Anomaly Explorer; its default analysis remains unchanged.')
        return True

    def reset(self):
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
        data['Before_uT']=r.before;data['After_uT']=r.after;data['Difference_uT']=r.after-r.before
        data.to_csv(targets[0],index=False)
        targets[1].write_text(json.dumps(dict(r.settings,notes=r.notes),indent=2,ensure_ascii=False),encoding='utf-8')
        self.figure.savefig(targets[2],dpi=180)
        if r.modes is not None:
            modes=pd.DataFrame(r.modes.T,columns=[f'Mode_{i+1}' for i in range(len(r.modes))]);modes.insert(0,r.axis_label,r.mode_axis);modes.to_csv(targets[3],index=False)
            metrics=r.metrics.copy();metrics['retained']=metrics['mode'].isin(r.selected);metrics.to_csv(targets[4],index=False)
        self.message.setText('Comparison, processing settings, and available mode diagnostics exported.')
