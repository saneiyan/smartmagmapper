"""Immutable filter previews compared on identical survey rows and input values."""
from ui.theme import compact_toolbar
from processing.comparison_spectrum import comparison_spectra
from ui.busy import busy, show_status, loading
from processing import labels
from processing.labels import signal_label
from copy import deepcopy
import hashlib,json
from pathlib import Path
import numpy as np,pandas as pd
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QFileDialog,QListWidget,QListWidgetItem,QGroupBox,QAbstractItemView
from PyQt6.QtCore import Qt
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas,NavigationToolbar2QT

class FilterComparison(QWidget):
    """Compare Filters tab: stored filter results (A, B, C...) compared on identical survey rows and input.

    The tab shows the comparison plot; its controls (self.panel) sit in the Filter Lab's settings panel and are only
    shown while this tab is open. Stored results are cleared when the survey or its cleaning changes.

    Parameters
    ----------
    lab : FilterWorkspace
        The Filter Lab that owns this tab.
    """
    def __init__(self,lab):
        """Build the plot, the record text and the Compare filters control panel."""
        super().__init__();self.lab=lab;self.slots={};self.session_key=None;self.next_index=0;self._export_all=False
        # The tab itself only shows the comparison plot; its controls live in self.panel, which the Filter Lab
        # places in its settings panel and shows only while this tab is open.
        layout=QVBoxLayout(self)
        self.figure=Figure(figsize=(12,6),constrained_layout=True);self.canvas=FigureCanvas(self.figure)
        toolbar=NavigationToolbar2QT(self.canvas,self);compact_toolbar(toolbar)
        layout.addWidget(toolbar);layout.addWidget(self.canvas,1)
        self.record=QLabel();self.record.setWordWrap(True);layout.addWidget(self.record)

        self.panel=QGroupBox('Compare filters');panel=QVBoxLayout(self.panel)
        hint=QLabel('Stored results are named A, B, C\u2026 Tick up to three to plot them side by side; click one to select it.')
        hint.setWordWrap(True);panel.addWidget(hint)
        self.library=QListWidget();self.library.setMaximumHeight(150)
        self.library.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.library.setToolTip('Tick to show in the comparison plot (up to three).\nClick a row to select it for the buttons below.')
        self.library.itemChanged.connect(self.library_changed);self.library.currentItemChanged.connect(self.selection_changed)
        panel.addWidget(self.library)
        self.use=QPushButton('Use selected result for anomaly analysis')
        self.use.setToolTip('Use the selected stored result as the filtered field for anomaly analysis (the current field).')
        self.use.clicked.connect(self.use_saved);panel.addWidget(self.use)
        self.clear=QPushButton('Delete selected');self.clear.setToolTip('Delete the selected stored result.');self.clear.clicked.connect(self.clear_slot)
        panel.addWidget(self.clear)
        self.view=QComboBox();self.view.addItems(['Filtered maps','Input and filtered traces','Removed signal','All saved traces (overlay)','Frequency Spectra (PSD)','All Saved Spectra (Overlay)'])
        self.view.setToolTip('What the comparison plot shows. The overlay views include every stored result.')
        self.view.currentIndexChanged.connect(self.draw)
        view_row=QHBoxLayout();view_row.addWidget(QLabel('Plot:'));view_row.addWidget(self.view,1);panel.addLayout(view_row)
        exports=QHBoxLayout()
        self.export=QPushButton('Export shown');self.export.setToolTip('Export the results in the plot: values, settings and the figure.');self.export.clicked.connect(self.export_saved)
        self.export_all=QPushButton('Export all');self.export_all.setToolTip('Export every stored result: values, settings and an overlay figure.');self.export_all.clicked.connect(self.export_library)
        exports.addWidget(self.export,1);exports.addWidget(self.export_all,1);panel.addLayout(exports)
        self.message=QLabel('No stored results yet. Apply a filter, then click Store filter results for comparison.');self.message.setWordWrap(True)
        panel.addWidget(self.message)
        self.draw()

    def notify(self,text):
        """Show a message in the Compare filters box and the status bar (visible from any tab).

        Parameters
        ----------
        text : str
            Message.
        """
        self.message.setText(text);show_status(self.lab,text,8000)

    def selected_name(self):
        """Name of the stored result selected in the list.

        Returns
        -------
        str or None
            For example 'A', or None when nothing is selected.
        """
        item=self.library.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def selection_changed(self,*_):
        """Enable the buttons that need a selected result.

        Parameters
        ----------
        *_ : object
            Ignored signal arguments.
        """
        selected=self.selected_name() in self.slots
        self.clear.setEnabled(selected);self.use.setEnabled(selected)

    def key(self):
        """Identity of the active survey and its cleaned data; stored results are only valid for this key.

        Returns
        -------
        tuple or None
            (session id, path, cleaning settings, hash of the cleaned data), or None without a survey.
        """
        session=self.lab.get_session()
        if session is None:return None
        frame=session.cleaned
        digest=hashlib.sha256(frame[['Time (s)','Easting (m)','Northing (m)','BT']].to_numpy(dtype=float).tobytes()).hexdigest()
        return (id(session),session.path,session.cleaning_key,digest)

    def session_changed(self):
        """Clear the stored results if the survey or its cleaning changed."""
        key=self.key()
        if key!=self.session_key:
            self.slots.clear();self.next_index=0;self.session_key=key;self.refresh_library();self.draw()
            self.message.setText('Stored results cleared because the survey or cleaning changed.')

    def save_preview(self,name):
        """Store the Filter Lab's current preview under a name.

        Results can only be compared on the same input, so a preview of a different signal or cleaned baseline is refused.

        Parameters
        ----------
        name : str
            Name to store it under, e.g. 'A'.

        Returns
        -------
        bool
            True if stored.
        """
        self.session_changed();r=self.lab.result;session=self.lab.get_session()
        if r is None or session is None:
            self.notify('Apply a filter before storing it for comparison.');return False
        # Reject comparisons with different input values, even if lengths match.
        for other,item in self.slots.items():
            if other==name:continue
            old=item['result']
            if old.settings['field']!=r.settings['field'] or not np.array_equal(old.before,r.before):
                self.notify('Inputs differ. Choose the same signal and cleaned baseline for a fair comparison, or delete the other stored results.');return False
        self.slots[name]={'result':deepcopy(r),'frame':session.cleaned.copy(deep=True)}
        if hasattr(self.window(),'project_tools'):self.window().project_tools.changed()
        self.refresh_library(select=name);self.draw()
        return True

    def clear_slot(self):
        """Delete the selected stored result."""
        name=self.selected_name()
        if name not in self.slots:self.notify('Select a stored result in the list first.');return
        self.slots.pop(name,None);self.refresh_library();self.draw()
        self.notify(f'Deleted stored result {name}.')
        if hasattr(self.window(),'project_tools'):self.window().project_tools.changed()

    @staticmethod
    def preview_name(index):
        """Spreadsheet-style name of a stored result.

        Parameters
        ----------
        index : int
            Zero-based index.

        Returns
        -------
        str
            'A' ... 'Z', then 'AA', 'AB', ...
        """
        name='';index+=1
        while index:
            index,remainder=divmod(index-1,26);name=chr(65+remainder)+name
        return name

    def add_preview(self):
        """Store the current preview under the next free name (A, B, C, ...) and show the comparison.

        Returns
        -------
        bool
            True if stored.
        """
        self.session_changed()
        self.next_index=0
        while self.preview_name(self.next_index) in self.slots:self.next_index+=1
        name=self.preview_name(self.next_index)
        if not self.save_preview(name):return False
        self.next_index+=1
        self.lab.tabs.setCurrentWidget(self)
        self.notify(f'Stored result {name}: {self.lab.settings_description(self.slots[name]["result"].settings)}. '
                    'Change the filter or its settings, apply it again and store another to compare.')
        return True

    def refresh_library(self,select=None):
        """Rebuild the stored-results list, keeping ticks and the selection.

        New results are ticked while fewer than three are ticked.

        Parameters
        ----------
        select : str, optional
            Name to select instead of the current selection.
        """
        checked={self.library.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.library.count()) if self.library.item(i).checkState()==Qt.CheckState.Checked}
        known={self.library.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.library.count())}
        target=select or self.selected_name()
        self.library.blockSignals(True);self.library.clear()
        for name,item in self.slots.items():
            result=item['result'];entry=QListWidgetItem(name+' - '+self.lab.settings_description(result.settings))
            entry.setData(Qt.ItemDataRole.UserRole,name);entry.setFlags(entry.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            select=name in checked or (name not in known and len(checked)<3)
            if select:checked.add(name)
            entry.setCheckState(Qt.CheckState.Checked if select else Qt.CheckState.Unchecked)
            entry.setToolTip(self.lab.settings_description(result.settings));self.library.addItem(entry)
            if name==target:self.library.setCurrentItem(entry)
        self.library.blockSignals(False);self.selection_changed()

    def library_changed(self,item):
        """A result was ticked or unticked: allow at most three, then redraw.

        Parameters
        ----------
        item : QListWidgetItem
            The changed entry.
        """
        if len(self.visible_names())>3:
            self.library.blockSignals(True);item.setCheckState(Qt.CheckState.Unchecked);self.library.blockSignals(False)
            self.notify('Tick up to three for readable side-by-side plots. Untick another, or choose an overlay plot to see them all.')
        self.draw()

    def visible_names(self):
        """Names of the ticked stored results.

        Returns
        -------
        list of str
            Names in list order.
        """
        return [self.library.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.library.count()) if self.library.item(i).checkState()==Qt.CheckState.Checked and self.library.item(i).data(Qt.ItemDataRole.UserRole) in self.slots]

    def export_library(self):
        """Export every stored result (values, settings and an overlay figure).

        Returns
        -------
        bool
            True if exported.
        """
        self._export_all=True;previous=self.view.currentIndex();self.view.setCurrentIndex(5 if previous in (4,5) else 3)
        try:return self.export_saved()
        finally:
            self._export_all=False;self.view.setCurrentIndex(previous)

    def draw(self,*_):
        """Redraw the comparison plot with a loading message over it (see _draw).

        Parameters
        ----------
        *_ : object
            Ignored signal arguments.
        """
        with loading(self.canvas,'Drawing filter comparison...'):
            self._draw()

    def _draw(self):
        """Draw the chosen comparison: filtered maps, input and filtered traces, removed signal, an overlay of every
        stored trace, or Welch spectra (side by side or overlaid)."""
        self.figure.clear();names=list(self.slots) if self.view.currentIndex() in (3,5) else self.visible_names()
        self.export.setEnabled(bool(names));self.export_all.setEnabled(bool(self.slots));self.selection_changed()
        if not names:
            text=('Tick a stored result in the Compare filters box to plot it.' if self.slots else
                  'Apply a filter, then click "Store filter results for comparison" to compare filters here.')
            ax=self.figure.add_subplot();ax.text(.5,.5,text,ha='center',va='center',wrap=True);ax.set_axis_off();self.record.setText('');self.canvas.draw_idle();return
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
                ax.set_xlabel('Frequency (Hz)');ax.set_ylabel(f'Power density ({labels.display_unit()}\u00b2/Hz)');ax.grid(alpha=.2);ax.legend(fontsize=8)
                ax.set_title('All Saved Spectra' if self.view.currentIndex()==5 else name+' - '+self.slots[name]['result'].settings['method'])
            self.record.setText(f"Welch PSD | Hann window | {metadata['segment_samples']} samples/segment | 50% overlap | segment mean removed | shared time grid, {metadata['sampling_rate_hz']:.4g} Hz. Temporal spectra along the survey; not 2D spatial spectra. Zero power is omitted on the logarithmic axis.")
            self.canvas.draw_idle();return
        if self.view.currentIndex()==3:
            ax=self.figure.add_subplot();first=self.slots[names[0]];time=first['frame']['Time (s)']
            ax.plot(time,first['result'].before,color='#94a3b8',lw=1,label='Input')
            for name in names:ax.plot(time,self.slots[name]['result'].after,lw=.8,label=name+' - '+self.slots[name]['result'].settings['method'])
            ax.set_xlabel('Time (s)');ax.set_ylabel(signal_label(first['result'].settings['field']));ax.legend(fontsize=8,ncol=2);ax.grid(alpha=.15)
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
                im=ax.scatter(frame['Easting (m)']-frame['Easting (m)'].mean(),frame['Northing (m)']-frame['Northing (m)'].mean(),c=r.after,s=7,cmap=self.lab.map_colors.currentData(),vmin=low,vmax=high)
                ax.set_aspect('equal',adjustable='box');ax.set_xlabel('Relative easting (m)');ax.set_ylabel('Relative northing (m)');self.figure.colorbar(im,ax=ax,label=signal_label(r.settings['field']))
            elif self.view.currentIndex()==1:
                ax.plot(time,r.before,color='#94a3b8',lw=.7,label='Input');ax.plot(time,r.after,color='#0f766e',lw=.8,label='Filtered')
                ax.set_xlabel('Time (s)');ax.set_ylabel(signal_label(r.settings['field']));ax.set_ylim(low-.05*(high-low or 1),high+.05*(high-low or 1));ax.legend(fontsize=8)
            else:
                ax.plot(time,delta,color='#b45309',lw=.8);ax.set_xlabel('Time (s)');ax.set_ylabel(f'After \u2212 input ({labels.display_unit()})');ax.grid(alpha=.2);ax.set_ylim(-limit*1.05,limit*1.05)
            records.append(name+': '+self.lab.settings_description(r.settings)+f" | Coordinate: {r.settings['domain']} | RMS change {np.sqrt(np.mean(delta**2)):.4g} {labels.display_unit()} | Input std {np.std(r.before):.4g}; output std {np.std(r.after):.4g} {labels.display_unit()}")
        self.record.setText('\n'.join(records));self.canvas.draw_idle()

    def spectra(self,names):
        """Welch spectra of the shared input and the named stored results.

        Parameters
        ----------
        names : list of str
            Stored results to include.

        Returns
        -------
        tuple
            (frequency, densities, metadata) as returned by comparison_spectrum.comparison_spectra.
        """
        first=self.slots[names[0]]
        return comparison_spectra(first['frame']['Time (s)'],{'Input':first['result'].before,**{n:self.slots[n]['result'].after for n in names}},unit=labels.display_unit())

    def use_saved(self):
        """Make the selected stored result the current field for anomaly analysis.

        Its recorded settings are loaded back into the Filter Lab and applied. A result computed on a previous filter
        result is only reusable while that input is unchanged.

        Returns
        -------
        bool
            True if applied.
        """
        self.session_changed();name=self.selected_name();item=self.slots.get(name);session=self.lab.get_session()
        if item is None or session is None:self.notify('Select a stored result in the list first.');return False
        r=deepcopy(item['result'])
        # A chained snapshot is only reusable while its recorded input history still matches.
        if r.settings['field']=='Current result' and r.settings.get('input_history',[])!=session.filter_history:
            self.notify('The chained input changed. Apply the filter again using the desired input field.');return False
        self.lab.method.setCurrentText(r.settings['method'])
        self.lab.field.setCurrentIndex(max(0,self.lab.field.findData(r.settings['field'])))
        self.lab.domain.setCurrentText(r.settings['domain'])
        for key,control in [('window',self.lab.window_length),('low',self.lab.low),('high',self.lab.high),('k_modes',self.lab.k),('alpha',self.lab.alpha),('cell_size',self.lab.cell),('height',self.lab.height),('max_gain',self.lab.gain),('inclination',self.lab.inc),('declination',self.lab.dec)]:
            if key in r.settings:control.setValue(r.settings[key])
        if r.settings['method']=='Reduction to pole':self.lab.direction_confirm.setCurrentIndex(1)
        with busy(self,f'Loading stored result {name}...'):
            self.lab.result=r;self.lab.preview_revision=session.revision
            self.lab.draw_comparison()
            self.lab.vmd.clear()
            if r.modes is not None:self.lab.vmd.set_data(r.mode_axis,r.mode_signal,r.modes,r.metrics,r.selected,r.axis_label)
        # Apply uses recorded settings rather than whatever is currently selected in the form.
        ok=self.lab.apply()
        if ok:self.notify(f'Stored result {name} is now the filter result for anomaly analysis (the current field).')
        return ok

    def export_saved(self):
        """Export the compared results: values (input, filtered, difference), settings, the figure and, for
        spectrum views, the spectra and their settings.

        Returns
        -------
        bool
            True if exported.
        """
        self.session_changed();names=list(self.slots) if self._export_all or self.view.currentIndex() in (3,5) else self.visible_names()
        if not names:return False
        path,_=QFileDialog.getSaveFileName(self,'Export filter approaches','','CSV files (*.csv)')
        if not path:return False
        base=Path(path).with_suffix('');targets=[base.with_suffix('.csv'),base.with_name(base.name+'_settings.json'),base.with_name(base.name+'_comparison.png')]
        if self.view.currentIndex() in (4,5):targets.extend([base.with_name(base.name+'_spectra.csv'),base.with_name(base.name+'_spectra_settings.json')])
        owner=self.lab.window()
        if any(getattr(owner,'is_imported_file',lambda _:False)(p) for p in targets):self.notify('Choose a name that preserves the imported data.');return False
        try:
            data=self.slots[names[0]]['frame'][['Time (s)','Easting (m)','Northing (m)']].copy()
            unit=labels.display_unit()
            data[f'Input ({unit})']=self.slots[names[0]]['result'].before
            for n in names:
                r=self.slots[n]['result'];data[f'{n} Filtered ({unit})']=r.after;data[f'{n} Difference ({unit})']=r.after-r.before
            if self.view.currentIndex() in (4,5):
                frequency,densities,metadata=self.spectra(names)
                pd.DataFrame({'Frequency_Hz':frequency,**{f'{n} PSD ({unit}\u00b2/Hz)':v for n,v in densities.items()}}).to_csv(targets[3],index=False)
                targets[4].write_text(json.dumps(metadata,indent=2),encoding='utf-8')
            data.to_csv(targets[0],index=False)
            targets[1].write_text(json.dumps({n:self.slots[n]['result'].settings for n in names},indent=2),encoding='utf-8')
            self.figure.savefig(targets[2],dpi=180)
            self.notify('Comparison exported with input, stored results, settings and figure.');return True
        except Exception as exc:self.notify('Comparison export failed: '+str(exc));return False
