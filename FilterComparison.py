"""Immutable filter previews compared on identical survey rows and input values."""
from PlotTheme import compact_toolbar
from ComparisonSpectrum import comparison_spectra
from copy import deepcopy
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QCheckBox,QFileDialog,QListWidget,QListWidgetItem
from PyQt6.QtCore import Qt
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas,NavigationToolbar2QT

class FilterComparison(QWidget):
    def __init__(self,lab):
        super().__init__();self.lab=lab;self.slots={};self.session_key=None
        layout=QVBoxLayout(self)
        note=QLabel('Preview a filter, then Save preview for comparison. Previews are named A, B, C, D... automatically. Check up to three for large side-by-side plots, or choose All saved traces to overlay every saved result. All previews must use the same input signal. Save the project to retain previews, or export their values and figures.')
        note.setWordWrap(True);layout.addWidget(note)
        row=QHBoxLayout();self.slot=QComboBox();self.slot.addItems(['A','B','C'])
        self.save=QPushButton('Add current preview');self.save.clicked.connect(self.add_preview)
        self.clear=QPushButton('Delete selected preview');self.clear.clicked.connect(self.clear_slot)
        self.third=QCheckBox('Include C');self.third.hide();self.third.toggled.connect(self.draw)
        self.use=QPushButton('Use selected saved result');self.use.clicked.connect(self.use_saved)
        self.export=QPushButton('Export comparison');self.export.clicked.connect(self.export_saved)
        for widget in [self.slot,self.save,self.clear,self.use,self.export]:row.addWidget(widget)
        layout.addLayout(row)
        self.library=QListWidget();self.library.setMaximumHeight(90);self.library.itemChanged.connect(self.library_changed);self.library.currentItemChanged.connect(lambda current,previous:self.slot.setCurrentText(current.data(Qt.ItemDataRole.UserRole)) if current else None);layout.addWidget(self.library)
        self.next_index=0;self._export_all=False
        self.export_all=QPushButton('Export all saved previews');self.export_all.clicked.connect(self.export_library);
        self.message=QLabel('No saved previews yet. Add a preview from the filter settings or this page.');self.message.setWordWrap(True);layout.addWidget(self.message)
        self.view=QComboBox();self.view.addItems(['Filtered maps','Input and filtered traces','Removed signal','All saved traces (overlay)','Frequency Spectra (PSD)','All Saved Spectra (Overlay)']);self.view.currentIndexChanged.connect(self.draw);view_row=QHBoxLayout();view_row.addWidget(self.view,1);view_row.addWidget(self.export_all);layout.addLayout(view_row)
        self.figure=Figure(figsize=(12,6),constrained_layout=True);self.canvas=FigureCanvas(self.figure)
        toolbar=NavigationToolbar2QT(self.canvas,self);compact_toolbar(toolbar)
        layout.addWidget(toolbar);layout.addWidget(self.canvas,1)
        self.record=QLabel();self.record.setWordWrap(True);layout.addWidget(self.record)
        self.draw()

    def key(self):
        session=self.lab.get_session()
        if session is None:return None
        frame=session.cleaned
        digest=hashlib.sha256(frame[['Time (s)','Easting (m)','Northing (m)','BT']].to_numpy(dtype=float).tobytes()).hexdigest()
        return (id(session),session.path,session.cleaning_key,digest)

    def session_changed(self):
        key=self.key()
        if key!=self.session_key:
            self.slots.clear();self.next_index=0;self.session_key=key;self.refresh_library();self.draw()
            self.message.setText('Comparison slots cleared because the survey or cleaning changed.')

    def save_preview(self):
        self.session_changed();r=self.lab.result;session=self.lab.get_session()
        if r is None or session is None:
            self.message.setText('Create a valid preview before saving a comparison.');return False
        name=self.slot.currentText()
        # Reject comparisons with different input values, even if lengths match.
        for other,item in self.slots.items():
            if other==name:continue
            old=item['result']
            if old.settings['field']!=r.settings['field'] or not np.array_equal(old.before,r.before):
                self.message.setText('Inputs differ. Choose the same signal and cleaned baseline for a fair comparison, or clear the other slots.');return False
        self.slots[name]={'result':deepcopy(r),'frame':session.cleaned.copy(deep=True)}
        if hasattr(self.window(),'project_tools'):self.window().project_tools.changed()
        self.refresh_library();self.draw();self.message.setText(f'Saved immutable preview {name}: '+self.lab.settings_description(r.settings))
        return True

    def clear_slot(self):
        self.slots.pop(self.slot.currentText(),None);self.refresh_library();self.draw()
        if hasattr(self.window(),'project_tools'):self.window().project_tools.changed()

    @staticmethod
    def preview_name(index):
        name='';index+=1
        while index:
            index,remainder=divmod(index-1,26);name=chr(65+remainder)+name
        return name

    def add_preview(self):
        self.session_changed()
        self.next_index=0
        while self.preview_name(self.next_index) in self.slots:self.next_index+=1
        name=self.preview_name(self.next_index)
        if self.slot.findText(name)<0:self.slot.addItem(name)
        self.slot.setCurrentText(name)
        if not self.save_preview():return False
        self.next_index+=1
        self.lab.tabs.setCurrentWidget(self)
        self.message.setText('Saved preview '+name+'. Change the method or its parameters, preview again, and save another. Check the results to compare below.')
        return True

    def refresh_library(self):
        checked={self.library.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.library.count()) if self.library.item(i).checkState()==Qt.CheckState.Checked}
        known={self.library.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.library.count())}
        self.library.blockSignals(True);self.library.clear()
        for name,item in self.slots.items():
            if self.slot.findText(name)<0:self.slot.addItem(name)
            result=item['result'];entry=QListWidgetItem(name+' - '+self.lab.settings_description(result.settings))
            entry.setData(Qt.ItemDataRole.UserRole,name);entry.setFlags(entry.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            select=name in checked or (name not in known and len(checked)<3)
            if select:checked.add(name)
            entry.setCheckState(Qt.CheckState.Checked if select else Qt.CheckState.Unchecked)
            entry.setToolTip(self.lab.settings_description(result.settings));self.library.addItem(entry)
        self.library.blockSignals(False)

    def library_changed(self,item):
        if len(self.visible_names())>3:
            self.library.blockSignals(True);item.setCheckState(Qt.CheckState.Unchecked);self.library.blockSignals(False)
            self.message.setText('Keep up to three side by side for readable plots. Uncheck another preview or select All saved traces for an overlay.')
        self.draw()

    def visible_names(self):
        return [self.library.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.library.count()) if self.library.item(i).checkState()==Qt.CheckState.Checked and self.library.item(i).data(Qt.ItemDataRole.UserRole) in self.slots]

    def export_library(self):
        self._export_all=True;previous=self.view.currentIndex();self.view.setCurrentIndex(5 if previous in (4,5) else 3)
        try:return self.export_saved()
        finally:
            self._export_all=False;self.view.setCurrentIndex(previous)

    def draw(self,*_):
        self.figure.clear();names=list(self.slots) if self.view.currentIndex() in (3,5) else self.visible_names()
        self.use.setEnabled(bool(self.slots));self.export.setEnabled(bool(names));self.export_all.setEnabled(bool(self.slots))
        if not names:
            ax=self.figure.add_subplot();ax.text(.5,.5,'Save filter previews to compare their effects.',ha='center',va='center');ax.set_axis_off();self.record.setText('');self.canvas.draw_idle();return
        if self.view.currentIndex() in (4,5):
            try:
                frequency,densities,metadata=self.spectra(names)
            except ValueError as exc:
                ax=self.figure.add_subplot();ax.text(.5,.5,str(exc),ha='center',va='center',wrap=True);ax.set_axis_off()
                self.record.setText('Spectrum unavailable: '+str(exc));self.canvas.draw_idle();return
            axes=self.figure.subplots(1,1 if self.view.currentIndex()==5 else len(names),squeeze=False,sharex=True,sharey=True)
            for j,name in enumerate(names):
                ax=axes[0,0 if self.view.currentIndex()==5 else j]
                if j==0 or self.view.currentIndex()!=5:
                    ax.semilogy(frequency,np.where(densities['Input']>0,densities['Input'],np.nan),color='#94a3b8',label='Input',lw=1)
                ax.semilogy(frequency,np.where(densities[name]>0,densities[name],np.nan),label=name+' - '+self.slots[name]['result'].settings['method'],lw=1)
                ax.set_xlabel('Frequency (Hz)');ax.set_ylabel('Power density (uT²/Hz)');ax.grid(alpha=.2);ax.legend(fontsize=8)
                ax.set_title('All Saved Spectra' if self.view.currentIndex()==5 else name+' - '+self.slots[name]['result'].settings['method'])
            self.record.setText(f"Welch PSD | Hann window | {metadata['segment_samples']} samples/segment | 50% overlap | segment mean removed | shared time grid, {metadata['sampling_rate_hz']:.4g} Hz. Temporal spectra along the survey; not 2D spatial spectra. Zero power is omitted on the logarithmic axis.")
            self.canvas.draw_idle();return
        if self.view.currentIndex()==3:
            ax=self.figure.add_subplot();first=self.slots[names[0]];time=first['frame']['Time (s)']
            ax.plot(time,first['result'].before,color='#94a3b8',lw=1,label='Input')
            for name in names:ax.plot(time,self.slots[name]['result'].after,lw=.8,label=name+' - '+self.slots[name]['result'].settings['method'])
            ax.set_xlabel('Time (s)');ax.set_ylabel('Field (uT)');ax.legend(fontsize=8,ncol=2);ax.grid(alpha=.15)
            self.record.setText(f'{len(names)} saved previews overlaid on the same input. Export all saved previews to retain their exact settings and values.')
            self.canvas.draw_idle();return
        axes=self.figure.subplots(1,len(names),squeeze=False)
        arrays=[self.slots[n]['result'].after for n in names]+[self.slots[n]['result'].before for n in names]
        low=min(np.min(v) for v in arrays);high=max(np.max(v) for v in arrays)
        limit=max(max(np.abs(self.slots[n]['result'].after-self.slots[n]['result'].before)) for n in names) or 1
        records=[]
        for j,name in enumerate(names):
            item=self.slots[name];r=item['result'];frame=item['frame'];time=frame['Time (s)'].to_numpy();delta=r.after-r.before;ax=axes[0,j]
            ax.set_title(name+' - '+r.settings['method'])
            if self.view.currentIndex()==0:
                im=ax.scatter(frame['Easting (m)']-frame['Easting (m)'].mean(),frame['Northing (m)']-frame['Northing (m)'].mean(),c=r.after,s=7,cmap='viridis',vmin=low,vmax=high)
                ax.set_aspect('equal',adjustable='box');ax.set_xlabel('Relative easting (m)');ax.set_ylabel('Relative northing (m)');self.figure.colorbar(im,ax=ax,label='Field (uT)')
            elif self.view.currentIndex()==1:
                ax.plot(time,r.before,color='#94a3b8',lw=.7,label='Input');ax.plot(time,r.after,color='#0f766e',lw=.8,label='Filtered')
                ax.set_xlabel('Time (s)');ax.set_ylabel('Field (uT)');ax.set_ylim(low-.05*(high-low or 1),high+.05*(high-low or 1));ax.legend(fontsize=8)
            else:
                ax.plot(time,delta,color='#b45309',lw=.8);ax.set_xlabel('Time (s)');ax.set_ylabel('After - input (uT)');ax.grid(alpha=.2);ax.set_ylim(-limit*1.05,limit*1.05)
            records.append(name+': '+self.lab.settings_description(r.settings)+f" | Coordinate: {r.settings['domain']} | RMS change {np.sqrt(np.mean(delta**2)):.4g} uT | Input std {np.std(r.before):.4g}; output std {np.std(r.after):.4g} uT")
        self.record.setText('\n'.join(records));self.canvas.draw_idle()

    def spectra(self,names):
        first=self.slots[names[0]]
        return comparison_spectra(first['frame']['Time (s)'],{'Input':first['result'].before,**{n:self.slots[n]['result'].after for n in names}})

    def use_saved(self):
        self.session_changed();item=self.slots.get(self.slot.currentText());session=self.lab.get_session()
        if item is None or session is None:self.message.setText('Choose an occupied slot.');return False
        r=deepcopy(item['result'])
        # A chained snapshot is only reusable while its recorded input history still matches.
        if r.settings['field']=='Current result' and r.settings.get('input_history',[])!=session.filter_history:
            self.message.setText('The chained input changed. Preview again using the desired input field.');return False
        self.lab.method.setCurrentText(r.settings['method'])
        self.lab.field.setCurrentText(r.settings['field'])
        self.lab.domain.setCurrentText(r.settings['domain'])
        for key,control in [('window',self.lab.window_length),('low',self.lab.low),('high',self.lab.high),('k_modes',self.lab.k),('alpha',self.lab.alpha),('cell_size',self.lab.cell),('height',self.lab.height),('max_gain',self.lab.gain),('inclination',self.lab.inc),('declination',self.lab.dec)]:
            if key in r.settings:control.setValue(r.settings[key])
        if r.settings['method']=='Reduction to pole':self.lab.direction_confirm.setCurrentIndex(1)
        from Busy import busy
        with busy(self,f'Loading saved result {self.slot.currentText()}...'):
            self.lab.result=r;self.lab.preview_revision=session.revision
            self.lab.draw_comparison()
            self.lab.vmd.clear()
            if r.modes is not None:self.lab.vmd.set_data(r.mode_axis,r.mode_signal,r.modes,r.metrics,r.selected,r.axis_label)
        # Apply uses recorded settings rather than whatever is currently selected in the form.
        ok=self.lab.apply()
        if ok:self.message.setText('Saved result '+self.slot.currentText()+' is now the current field. Analysis input remains an explicit choice.')
        return ok

    def export_saved(self):
        self.session_changed();names=list(self.slots) if self._export_all or self.view.currentIndex() in (3,5) else self.visible_names()
        if not names:return False
        path,_=QFileDialog.getSaveFileName(self,'Export filter approaches','','CSV files (*.csv)')
        if not path:return False
        base=Path(path).with_suffix('');targets=[base.with_suffix('.csv'),base.with_name(base.name+'_settings.json'),base.with_name(base.name+'_comparison.png')]
        if self.view.currentIndex() in (4,5):targets.extend([base.with_name(base.name+'_spectra.csv'),base.with_name(base.name+'_spectra_settings.json')])
        owner=self.lab.window()
        if any(getattr(owner,'is_imported_file',lambda _:False)(p) for p in targets):self.message.setText('Choose a name that preserves the imported data.');return False
        try:
            data=self.slots[names[0]]['frame'][['Time (s)','Easting (m)','Northing (m)']].copy()
            data['Input_uT']=self.slots[names[0]]['result'].before
            for n in names:
                r=self.slots[n]['result'];data[n+'_Filtered_uT']=r.after;data[n+'_Difference_uT']=r.after-r.before
            if self.view.currentIndex() in (4,5):
                frequency,densities,metadata=self.spectra(names)
                pd.DataFrame({'Frequency_Hz':frequency,**{n+'_PSD_uT2_per_Hz':v for n,v in densities.items()}}).to_csv(targets[3],index=False)
                targets[4].write_text(json.dumps(metadata,indent=2),encoding='utf-8')
            data.to_csv(targets[0],index=False)
            targets[1].write_text(json.dumps({n:self.slots[n]['result'].settings for n in names},indent=2),encoding='utf-8')
            self.figure.savefig(targets[2],dpi=180)
            self.message.setText('Comparison exported with input, saved results, settings, and figure.');return True
        except Exception as exc:self.message.setText('Comparison export failed: '+str(exc));return False
