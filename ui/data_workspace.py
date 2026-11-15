"""Synchronized observations and interactive, auditable cleaning comparison."""
import numpy as np
from pandas.api.types import is_numeric_dtype
from PyQt6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QComboBox,QTabWidget,QGroupBox,QPushButton,QLineEdit,
    QTableView,QHeaderView,QSpinBox,QDoubleSpinBox)
from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtCore import Qt,QUrl,QSortFilterProxyModel,QSignalBlocker
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT
from processing import data_analysis_pipeline as dap
from ui import table_model as TableModel
from processing import web_map as WebMap
from processing.map_maker import MapMaker
from ui.theme import compact_toolbar, TabArrows, color_scale_combo, color_list
from ui.confirm import confirm
from processing import labels
from processing.labels import FIELD_COLUMNS, field_label

class DataWorkspace(QWidget):
    def __init__(self, window):
        super().__init__(); self.window=window;self.raw=None;self.raw_session=None
        root=QVBoxLayout(self)
        # The selected workspace tab supplies its heading.
        self.status=QLabel();self.status.setWordWrap(True);root.addWidget(self.status);self.status.hide()
        self.controls=QGroupBox('Cleaning settings')
        self.controls.setMaximumWidth(310);self.controls.setMinimumWidth(265)
        self.form=QFormLayout(self.controls);self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        body=QHBoxLayout();root.addLayout(body,1)
        body.addWidget(self.controls,0)
        # Labels (with units) are shown; the data column is the item data.
        self.signal=QComboBox()
        for column in FIELD_COLUMNS:self.signal.addItem(field_label(column),column)
        self.signal.currentIndexChanged.connect(self.update_scale_context)
        self.signal.currentIndexChanged.connect(self.draw)
        self.form.addRow('Display signal',self.signal)
        # Per-column scale: follows the plot on screen (map signal or signal-plot tab);
        # a column's map and signal plot share the same limits.
        self.scale_widget=QWidget();scale_layout=QVBoxLayout(self.scale_widget);scale_layout.setContentsMargins(0,0,0,0)
        box_row=QHBoxLayout();button_row=QHBoxLayout();scale_layout.addLayout(box_row);scale_layout.addLayout(button_row)
        self.scale_min=QLineEdit();self.scale_max=QLineEdit()
        for edit,name in [(self.scale_min,'Min'),(self.scale_max,'Max')]:
            edit.setValidator(QDoubleValidator());edit.setPlaceholderText(name+' (auto)');edit.setClearButtonEnabled(True)
            edit.setToolTip(name+'imum value for the plot currently shown (shared by its cleaning map and signal plot). Press Enter or click Apply.')
            edit.returnPressed.connect(self.scale_edited);edit.textChanged.connect(self.scale_text_changed)
            box_row.addWidget(edit,1)
        self.scale_apply=QPushButton('Apply Scale');self.scale_apply.setObjectName('primaryButton');self.scale_apply.setEnabled(False)
        self.scale_apply.setToolTip('Apply the min/max to the plot currently shown and its matching map or signal plot.')
        self.scale_apply.clicked.connect(self.scale_edited);button_row.addWidget(self.scale_apply,1)
        self.scale_auto=QPushButton('Auto Scale');self.scale_auto.setToolTip('Fill the min/max with the full data range and apply it.')
        self.scale_auto.clicked.connect(self.reset_scale);button_row.addWidget(self.scale_auto,1)
        self.scales={};self.scale_column='BT'
        self.scale_label=QLabel(f"{field_label('BT')} scale")
        self.form.addRow(self.scale_label,self.scale_widget)
        # Cleaning settings: filled in from each survey on import, applied with Update Cleaning Settings.
        self.startup_samples=QSpinBox();self.startup_samples.setRange(0,500);self.startup_samples.setValue(10)
        self.spatial_mad=QDoubleSpinBox();self.spatial_mad.setRange(0.5,100.0);self.spatial_mad.setDecimals(1)
        self.spatial_mad.setSingleStep(0.5);self.spatial_mad.setValue(6.0)
        self.fallback_percentile=QDoubleSpinBox();self.fallback_percentile.setRange(50,100);self.fallback_percentile.setValue(95)
        self.fallback_percentile.setSuffix(' %')
        self.form.addRow('Startup samples removed',self.startup_samples)
        self.form.addRow('Spatial rejection (MAD multiplier)',self.spatial_mad)
        self.form.addRow('Percentile fallback (only if MAD = 0)',self.fallback_percentile)
        self.startup_samples.setToolTip('Removes this many synchronized observations at the beginning of the survey.\n'
                                        'Suggested on import: the samples before the sampling interval, distance travelled and change in total field\n'
                                        'per sample become steady (e.g. GPS settling or magnetometer warm-up). Later magnetic anomalies are never removed.')
        self.spatial_mad.setToolTip('Rejects positions beyond median radial distance + multiplier x radial MAD. Larger values retain more positions.\n'
                                    'Suggested on import: just large enough to keep every position reached by a normal step (not a GPS jump).')
        self.fallback_percentile.setToolTip('Only used if radial MAD is zero. This is not a general magnetic amplitude percentile filter.')
        # Cleaning re-runs only when "Update Cleaning Settings" is clicked.
        for box in (self.startup_samples,self.spatial_mad,self.fallback_percentile):
            box.valueChanged.connect(window.cleaning_settings_edited)
        self.tabs=QTabWidget();body.addWidget(self.tabs,1)
        self.figure=Figure(figsize=(12,7),constrained_layout=True);self.figure.set_constrained_layout_pads(w_pad=.04,h_pad=.07,hspace=.06,wspace=.05);self.canvas=FigureCanvas(self.figure)
        page=QWidget();plot_layout=QVBoxLayout(page);plot_layout.setContentsMargins(0,0,0,0)
        self.toolbar=NavigationToolbar2QT(self.canvas,page);toolbar=self.toolbar;compact_toolbar(toolbar)
        plot_layout.addWidget(toolbar);plot_layout.addWidget(self.canvas,1)
        self.map_page=page
        self.map_style=QComboBox();self.map_style.addItems(['Scatter Plot','Contour Plot','Web Map'])
        self.map_stage=QComboBox();self.map_stage.addItems(['Synchronized Data (Before Cleaning)','Cleaned Data (After Cleaning)']);self.map_stage.setCurrentIndex(1)
        map_options=QHBoxLayout()
        map_options.addStretch(1)
        map_options.addWidget(QLabel('Cleaning Stage:'))
        self.map_stage.setMinimumWidth(210)
        map_options.addWidget(self.map_stage)
        map_options.addSpacing(18)
        map_options.addWidget(QLabel('Map Type:'))
        self.map_style.setMinimumWidth(160)
        map_options.addWidget(self.map_style)
        map_options.addSpacing(18)
        map_options.addWidget(QLabel('Colour Scale:'))
        self.map_colors=color_scale_combo('viridis')
        self.map_colors.setMinimumWidth(190)
        map_options.addWidget(self.map_colors)
        map_options.addStretch(1)
        plot_layout.insertLayout(0,map_options)
        self.map_stage.currentIndexChanged.connect(self.draw)
        self.map_style.currentIndexChanged.connect(self.draw)
        self.map_colors.currentIndexChanged.connect(self.draw)
        self.web_comparison=QWebEngineView()
        # Satellite tiles are remote; the map html is a local temp file.
        self.web_comparison.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,True)
        plot_layout.addWidget(self.web_comparison,1);self.web_comparison.hide()
        self.tabs.addTab(page,'Cleaning Maps')
        self.cleaned_table=QTableView();self.cleaned_table.setAlternatingRowColors(True)
        self.tables=QTabWidget();self.tables.addTab(self.cleaned_table,'Cleaned Data (After Cleaning)')
        self.tabs.addTab(self.tables,'Data Tables')
        self.column_picker=QComboBox();self.column_picker.setMinimumWidth(240)
        signal_controls=QHBoxLayout();signal_controls.addWidget(QLabel('Signal Column:'));signal_controls.addWidget(self.column_picker,1)
        self.signal_source=QComboBox();self.signal_source.addItems(['Cleaned Data (After Cleaning)','Synchronized Data (Before Cleaning)'])
        self.signal_style=QComboBox();self.signal_style.addItems(['Line','Scatter'])
        signal_controls.addWidget(QLabel('Data:'));signal_controls.addWidget(self.signal_source)
        signal_controls.addWidget(QLabel('Display:'));signal_controls.addWidget(self.signal_style)
        self.signal_source.currentIndexChanged.connect(self.redraw_signal_plots)
        self.signal_style.currentIndexChanged.connect(self.redraw_signal_plots)
        self.column_picker.currentIndexChanged.connect(self.show_signal_column)
        # Signal Plots: one closable tab per plotted column, below the column / data / display controls.
        self.plot_tabs=QTabWidget();self.plot_tabs.setTabsClosable(True);self.plot_tabs.tabCloseRequested.connect(self.close_signal_plot)
        self.signal_page=QWidget();signal_layout=QVBoxLayout(self.signal_page)
        signal_layout.addLayout(signal_controls);signal_layout.addWidget(self.plot_tabs)
        self.tabs.addTab(self.signal_page,'Signal Plots')
        #self.tab_arrows=TabArrows(self.tabs)
        self.tabs.currentChanged.connect(self.update_context_controls)
        self.plot_tabs.currentChanged.connect(self.sync_signal_column)
        self.plot_tabs.currentChanged.connect(self.update_scale_context)
        self.tabs.setTabToolTip(2,'Individual cleaned-data columns plotted against measurement time. Choose a numeric column using Signal Column in this view.')
        self.tabs.setTabToolTip(0,'Before cleaning shows synchronized observations before startup removal and position rejection. Colors represent magnetic field values.')
        self.raw_table=QTableView();self.tables.insertTab(0,self.raw_table,'Synchronized Data (Before Cleaning)')
        self.stream_tables=[]
        for title in ['Raw Magnetometer','Raw GPS']:
            table=QTableView();self.tables.addTab(table,title);self.stream_tables.append(table)
        # Raw input streams come first; synchronized and cleaned tables follow.
        self.tables.tabBar().moveTab(2,0);self.tables.tabBar().moveTab(3,1);self.tables.setCurrentIndex(0)
        self.cleaning_details=QLabel('Import data to inspect cleaning.');self.cleaning_details.setWordWrap(True);self.form.addRow(self.cleaning_details)
        self.reset=QPushButton('Restore suggested settings')
        self.reset.setToolTip("Reset the cleaning settings to the values suggested from this survey's sampling interval and distance travelled.")
        self.reset.clicked.connect(self.restore_defaults);self.form.addRow(self.reset)
        self.update_cleaning=QPushButton('Update Cleaning Settings');self.update_cleaning.setObjectName('primaryButton')
        self.update_cleaning.setToolTip('Re-clean the active survey with the settings above and rerun the analysis.')
        self.update_cleaning.clicked.connect(window.apply_cleaning_settings);self.update_cleaning.setEnabled(False)
        self.form.addRow(self.update_cleaning)

    def cleaning_values(self):
        """(startup samples, MAD multiplier, fallback percentile) as entered in the Cleaning Settings panel."""
        return int(self.startup_samples.value()),float(self.spatial_mad.value()),float(self.fallback_percentile.value())

    def set_cleaning_values(self,startup=None,multiplier=None,percentile=None):
        """Show cleaning settings without marking them as a pending change (None leaves a box as it is)."""
        blockers=[QSignalBlocker(box) for box in (self.startup_samples,self.spatial_mad,self.fallback_percentile)]
        for box,value in ((self.startup_samples,startup),(self.spatial_mad,multiplier),(self.fallback_percentile,percentile)):
            if value is not None:box.setValue(value)
        del blockers

    def show_survey(self,cleaned):
        """Show a survey's cleaned data: the Cleaned Data table and a fresh total-field signal plot."""
        signals_blocked=self.plot_tabs.blockSignals(True)
        try:
            self.plot_tabs.clear()
            self.show_cleaned_table(cleaned)
            self.new_plot(df=cleaned,name=field_label('BT'),column=cleaned['BT'])
        finally:
            self.plot_tabs.blockSignals(signals_blocked)

    def show_cleaned_table(self,df):
        """Fill the Cleaned Data table (sortable; rows labelled with their synchronized record number)."""
        model=TableModel.TableModel(df,row_labels=self.record_labels(df))
        proxy=QSortFilterProxyModel(self.cleaned_table);proxy.setSourceModel(model);proxy.setSortRole(Qt.ItemDataRole.EditRole)
        self.cleaned_model=model
        self.cleaned_table.setSortingEnabled(True);self.cleaned_table.setModel(proxy)
        self.cleaned_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    def open_signal_plot(self,column):
        """Open (or switch to) the signal plot for a cleaned-data column and bring the Signal Plots tab forward."""
        session=self.window.active_session()
        if session is not None and column in session.cleaned:
            frame=session.cleaned
            self.new_plot(name=column,df=frame,column=frame[column])
            self.window.tabs.setCurrentWidget(self)
            self.tabs.setCurrentWidget(self.signal_page)

    def close_signal_plot(self,index):
        """Close only this display; the survey column remains available to reopen."""
        page=self.plot_tabs.widget(index)
        if page is None:return
        self.plot_tabs.removeTab(index);page.deleteLater()

    def new_plot(self,df,name,column=None):
        """Add a signal plot (column versus time) as a new tab, or switch to it if it is already open."""
        if column is None:return
        for index in range(self.plot_tabs.count()):
            if getattr(self.plot_tabs.widget(index),'signal_column',None)==getattr(column,'name',None):
                self.plot_tabs.setCurrentIndex(index);return
        name=field_label(getattr(column,'name',name)) if getattr(column,'name',None) in FIELD_COLUMNS else name
        fig=Figure(constrained_layout=True);axes=fig.add_subplot()
        axes.set_title(name+' versus time');axes.set_xlabel('Time (s)');axes.set_ylabel(field_label(getattr(column,'name',name)))
        canvas=FigureCanvas(fig);page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0)
        toolbar=NavigationToolbar2QT(canvas,page);compact_toolbar(toolbar)
        layout.addWidget(toolbar);layout.addWidget(canvas,1)
        page.canvas=canvas;page.column=column;page.df=df;page.signal_column=getattr(column,'name',None);page.title=name+' versus time'
        def draw_signal(frame,style):
            key=page.signal_column
            if key not in frame:return
            axes.clear();x=frame['Time (s)'];y=frame[key]
            if style=='Line':axes.plot(x,y,lw=.8,color='#0f766e')
            if style=='Scatter':axes.scatter(x,y,s=36,marker='o',color='#0f766e',edgecolors='black',linewidths=1.0)
            axes.set_title(page.title);axes.set_xlabel('Time (s)');axes.set_ylabel(field_label(key));axes.grid(alpha=.2)
            # Before-cleaning data: mark the samples cleaning removed, as on the cleaning map.
            removed=self.excluded_rows(frame)
            if removed is not None and len(removed):
                axes.scatter(removed['Time (s)'],removed[key],marker='x',c='#b91c1c',s=28,linewidths=1,zorder=3,label='Excluded')
                axes.legend(loc='best',fontsize=9)
            # Each column uses its Data & Cleaning scale, shared with its cleaning map.
            user_lo,user_hi=self.field_scale(key)
            bottom,top=axes.get_ylim()
            bottom=bottom if user_lo is None else user_lo;top=top if user_hi is None else user_hi
            if bottom<top:axes.set_ylim(bottom,top)
            page.df=frame;page.column=frame[key];toolbar.update();canvas.draw_idle()
        page.draw_signal=draw_signal
        source=self.raw if self.signal_source.currentIndex()==1 and self.raw is not None else df
        draw_signal(source,self.signal_style.currentText())
        self.plot_tabs.addTab(page,name);self.plot_tabs.setCurrentWidget(page);canvas.draw_idle()

    def refresh_unit_labels(self):
        """Show the active survey's unit in the Display signal dropdown and scale label."""
        for index in range(self.signal.count()):self.signal.setItemText(index,field_label(self.signal.itemData(index)))
        self.scale_label.setText(self.scale_title(self.scale_column))

    def update_context_controls(self,*_):
        self.form.setRowVisible(self.signal,self.tabs.currentIndex()==0)
        # Scale applies to Cleaning Maps (0) and Signal Plots (2), not the data tables.
        self.form.setRowVisible(self.scale_widget,self.tabs.currentIndex() in (0,2))
        self.update_scale_context()

    @property
    def applied_scale(self):
        return self.scales.get(self.scale_column,('',''))

    @applied_scale.setter
    def applied_scale(self,texts):
        if self.scale_column is not None:self.scales[self.scale_column]=tuple(texts)

    def map_column(self):
        return self.signal.currentData()

    @staticmethod
    def scale_title(column):
        if column is None:return 'Scale (no plot shown)'
        return f'{field_label(column)} scale'

    def update_scale_context(self,*_):
        """Point the scale boxes at the plot on screen and show its limits."""
        index=self.tabs.currentIndex() if hasattr(self,'tabs') else 0
        if index==0:column=self.map_column()
        elif index==2:column=getattr(self.plot_tabs.currentWidget(),'signal_column',None)
        else:return
        self.scale_column=column
        self.scale_label.setText(self.scale_title(column));self.scale_widget.setEnabled(column is not None)
        for edit,text in zip((self.scale_min,self.scale_max),self.applied_scale):edit.blockSignals(True);edit.setText(text);edit.blockSignals(False)
        if column is not None and '' in self.applied_scale:self.fill_auto_scale(only_empty=True)
        self.scale_text_changed()

    def field_scale(self,column=None):
        """Applied limits for a column (default: the one shown) as (min, max); None means automatic."""
        def value(text):
            try:return float(text) if text else None
            except ValueError:return None
        # Only applied values count, so redraws never pick up half-typed entries.
        texts=self.scales.get(self.scale_column if column is None else column,('',''))
        lo,hi=value(texts[0]),value(texts[1])
        if lo is not None and hi is not None and lo>=hi:return None,None
        return lo,hi

    def scale_text(self):
        return (self.scale_min.text().strip(),self.scale_max.text().strip())

    def scale_text_changed(self,*_):
        # Apply is only available while the boxes differ from what is displayed.
        self.scale_apply.setEnabled(self.scale_text()!=self.applied_scale)

    def auto_field_scale(self,column=None):
        """Full range of a column over the before/after cleaning data, rounded outward to a tidy step (any unit)."""
        column=self.scale_column if column is None else column
        session=self.window.active_session()
        if session is None or column is None:return None
        frames=[frame for frame in (self.raw,session.cleaned) if frame is not None and column in frame]
        if not frames:return None
        try:values=np.concatenate([frame[column].to_numpy(dtype=float) for frame in frames])
        except (TypeError,ValueError):return None
        if not np.isfinite(values).any():return None
        low,high,self._auto_step=labels.nice_range(float(np.nanmin(values)),float(np.nanmax(values)))
        return low,high

    def scale_edited(self,*_):
        current=self.scale_text()
        if current==self.applied_scale:return
        self.applied_scale=current;self.scale_apply.setEnabled(False)
        lo,hi=self.field_scale()
        title=self.scale_title(self.scale_column)
        if current[0] and current[1] and lo is None:
            self.window.statusBar().showMessage(f'{title} ignored: minimum must be less than maximum.')
        else:
            self.window.statusBar().showMessage(f'{title}: {current[0] or "auto"} to {current[1] or "auto"}',6000)
        self.draw();self.redraw_signal_plots()

    def auto_scale_text(self):
        auto=self.auto_field_scale()
        if not auto:return ('','')
        decimals=labels.step_decimals(getattr(self,'_auto_step',0.01))
        if decimals>8:return (f'{auto[0]:.4g}',f'{auto[1]:.4g}')  # very small units (e.g. tesla): scientific notation
        return (f'{auto[0]:.{decimals}f}',f'{auto[1]:.{decimals}f}')

    def fill_auto_scale(self,only_empty=False):
        """Show the data range in the boxes and treat it as the applied scale (no redraw)."""
        auto=self.auto_scale_text();applied=list(self.applied_scale)
        for i,edit in enumerate((self.scale_min,self.scale_max)):
            if only_empty and applied[i]:continue  # leave set limits (and any pending edit) alone
            applied[i]=auto[i];edit.blockSignals(True);edit.setText(auto[i]);edit.blockSignals(False)
        self.applied_scale=tuple(applied);self.scale_text_changed()

    def reset_scale(self,*_):
        texts=self.auto_scale_text()
        title=self.scale_title(self.scale_column)
        full_range=f' ({texts[0]} to {texts[1]})' if texts[0] else ''
        if not confirm(self,'Reset Scale',f"Are you sure you'd like to reset the {title}?",
                       f'The min and max will be set to the full data range{full_range} and applied to the matching cleaning map and signal plot.',
                       yes_text='Reset Scale',no_text='Cancel'):return
        for edit,text in zip((self.scale_min,self.scale_max),texts):edit.blockSignals(True);edit.setText(text);edit.blockSignals(False)
        self.scale_edited()

    def sync_signal_column(self,*_):
        page=self.plot_tabs.currentWidget()
        if page is None:return
        index=self.column_picker.findData(getattr(page,'signal_column',None))
        if index>=0:
            self.column_picker.blockSignals(True);self.column_picker.setCurrentIndex(index);self.column_picker.blockSignals(False)

    def update_signal_columns(self, frame):
        selected=self.column_picker.currentData()
        self.column_picker.blockSignals(True);self.column_picker.clear()
        excluded={'Time (s)','UTM_EPSG'}
        for column in frame.columns:
            if column not in excluded and is_numeric_dtype(frame[column]):
                self.column_picker.addItem(field_label(column),column)
        index=self.column_picker.findData(selected if selected in frame.columns else 'BT')
        self.column_picker.setCurrentIndex(max(0,index));self.column_picker.blockSignals(False)
        current=self.column_picker.currentData()
        if current is not None and current!='BT':self.new_plot(name=current,df=frame,column=frame[current])

    def show_signal_column(self,*_):
        column=self.column_picker.currentData()
        if column is not None:self.open_signal_plot(column)

    def set_cleaning_pending(self,pending):
        if not hasattr(self,'update_cleaning'):return
        self.update_cleaning.setEnabled(pending)
        self.update_cleaning.setText('Update Cleaning Settings *' if pending else 'Update Cleaning Settings')

    def restore_defaults(self):
        """Restore the survey's data-based suggestion (fixed defaults 10 / 6.0 only if there is no suggestion)."""
        w=self.window;session=w.active_session()
        suggestion=w.suggested_cleaning(session) if session is not None else {}
        startup=suggestion.get('startup_samples',10)
        multiplier=suggestion.get('spatial_mad_multiplier') or 6.0
        if self.cleaning_values()==(startup,multiplier,95.0):
            w.statusBar().showMessage('Cleaning settings are already at the suggested values.',5000);return
        basis=(f"Suggested from this survey's typical sampling interval ({suggestion['median_interval_s']:.3f} s), "
               f"distance travelled per sample ({suggestion['median_step_m']:.2f} m) and change in total field per sample "
               f"(noise {labels.format_value(suggestion['field_change_noise'],3)} {labels.display_unit()}).\n\n") if suggestion else 'Standard defaults (no survey loaded).\n\n'
        if not confirm(self,'Restore Suggested Settings',"Are you sure you'd like to reset the cleaning settings to the suggested values?",
                       f'Startup samples removed: {startup}\nSpatial rejection (MAD multiplier): {multiplier:g}\nPercentile fallback: 95 %\n\n'
                       +basis+'The settings take effect when you click Update Cleaning Settings.',yes_text='Restore Settings',no_text='Cancel'):return
        # setValue (not set_cleaning_values) so the change shows as pending until Update Cleaning Settings
        self.startup_samples.setValue(startup);self.spatial_mad.setValue(multiplier);self.fallback_percentile.setValue(95)

    def load_session(self,session):
        """Load a newly active survey's synchronized data and tables (once per survey)."""
        if self.raw_session is session and self.raw is not None:return
        self.raw,_=dap.clean_survey(session.magnetometer,session.location,self.window.analysis_params(),synchronized_only=True)
        self.raw_session=session
        self.set_table(self.raw_table,self.raw)
        for table,frame in zip(self.stream_tables,[session.magnetometer,session.location]):self.set_table(table,frame)
        # A different survey has different ranges (and possibly a different unit); every plot starts from its full range.
        self.scales.clear();self.update_scale_context()

    def refresh(self):
        session=self.window.active_session()
        if session is None:return
        self.load_session(session)
        a=session.audit
        self.status.hide()
        suggestion=self.window.suggested_cleaning(session)
        reasons=', '.join(name for name,count in suggestion.get('startup_reasons',{}).items() if count) if suggestion else ''
        suggested=(f"\nSuggested for this survey: {suggestion['startup_samples']} startup samples{f' ({reasons})' if reasons else ''}, MAD \u00d7 "
                   f"{suggestion['spatial_mad_multiplier'] if suggestion['spatial_mad_multiplier'] is not None else 'n/a'} "
                   f"(typical interval {suggestion['median_interval_s']:.3f} s, step {suggestion['median_step_m']:.2f} m)") if suggestion else ''
        self.cleaning_details.setText(f"Spatial rule: {a['spatial_rule']}\nPosition cutoff: {a['spatial_limit_m']:.2f} m{suggested}\nCleaning changes clear filters and comparison previews.")
        self.fallback_percentile.setEnabled(a['spatial_rule']=='percentile fallback')
        for index in range(self.signal.count()):
            self.signal.model().item(index).setEnabled(self.signal.itemData(index) in session.cleaned)
        if self.signal.currentData() not in session.cleaned:self.signal.setCurrentIndex(0)
        self.draw()
        self.redraw_signal_plots()

    def record_labels(self,frame):
        session=self.window.active_session()
        if session is None or 'Time (s)' not in frame:return None
        self.load_session(session)
        lookup=dict(zip(self.raw['Time (s)'],self.raw.index))
        return [lookup.get(t,i) for i,t in enumerate(frame['Time (s)'])]

    @staticmethod
    def set_table(table,frame):
        table.setModel(TableModel.TableModel(frame));table.setAlternatingRowColors(True)

    def excluded_rows(self,frame):
        """Rows of the before-cleaning data that cleaning removed (empty for any other frame)."""
        session=self.window.active_session()
        if session is None or frame is None or frame is not self.raw or 'Time (s)' not in frame:return frame.iloc[0:0] if frame is not None else None
        return frame.loc[~frame['Time (s)'].isin(session.cleaned['Time (s)'])]

    def redraw_signal_plots(self,*_):
        session=self.window.active_session()
        if session is None:return
        frame=self.raw if self.signal_source.currentIndex()==1 else session.cleaned
        if frame is None:return
        for index in range(self.plot_tabs.count()):
            page=self.plot_tabs.widget(index)
            if hasattr(page,'draw_signal'):page.draw_signal(frame,self.signal_style.currentText())

    def draw(self,*_):
        session=self.window.active_session()
        if session is None or self.raw is None:return
        col=self.map_column()
        if col not in session.cleaned:return
        lo,hi=self.map_limits(col,update_boxes=True)
        web=self.map_style.currentText()=='Web Map'
        self.canvas.setVisible(not web);self.toolbar.setVisible(not web);self.web_comparison.setVisible(web)
        if web:
            self.draw_web_maps(session.cleaned,self.excluded_rows(self.raw),col,lo,hi);return
        self.render_map(self.figure,self.map_stage.currentIndex(),self.map_style.currentText(),col,lo,hi)
        self.toolbar.update();self.canvas.draw_idle()

    def map_limits(self,col,update_boxes=False):
        """Colour limits for a column: the before/after data range, replaced by any applied user scale."""
        session=self.window.active_session()
        values=np.concatenate([self.raw[col].to_numpy(),session.cleaned[col].to_numpy()])
        lo,hi=float(np.nanmin(values)),float(np.nanmax(values))
        if hi==lo:hi=lo+max(abs(lo)*1e-9,np.finfo(float).tiny)
        if update_boxes and col==self.scale_column:
            # Boxes always show the limits in use; an empty applied box shows its automatic value.
            if '' in self.applied_scale:self.fill_auto_scale(only_empty=True)
            self.scale_min.setPlaceholderText(f'Min (auto {labels.format_value(lo,2)})');self.scale_max.setPlaceholderText(f'Max (auto {labels.format_value(hi,2)})')
        user_lo,user_hi=self.field_scale(col)
        new_lo=lo if user_lo is None else user_lo;new_hi=hi if user_hi is None else user_hi
        if new_lo<new_hi:lo,hi=new_lo,new_hi
        elif update_boxes:self.window.statusBar().showMessage(f'{self.scale_title(col)} ignored: the limit is outside the data range.')
        return lo,hi

    def render_map(self,figure,stage_index,style,col,lo,hi,cmap=None):
        """Draw one cleaning-map view into figure (used for the screen and for exports).

        stage_index 0 = synchronized data (before cleaning), 1 = cleaned data; style is 'Scatter Plot' or 'Contour Plot';
        cmap defaults to the Colour Scale dropdown.
        """
        cmap=cmap or self.map_colors.currentData()
        session=self.window.active_session()
        removed=self.excluded_rows(self.raw)
        figure.clear()
        grid=figure.add_gridspec(1,3,width_ratios=[.045,1,.045],wspace=.06)
        ax=figure.add_subplot(grid[0,1])
        color_axis=figure.add_subplot(grid[0,2])
        origin=self.raw[['Easting (m)','Northing (m)']].mean()
        e=self.raw['Easting (m)']-origin.iloc[0];n=self.raw['Northing (m)']-origin.iloc[1]
        pad=max(float(np.ptp(e)),float(np.ptp(n)))*.06 or 1
        frame,title=(self.raw,'Synchronized Data (Before Cleaning)') if stage_index==0 else (session.cleaned,'Cleaned Data (After Cleaning)')
        # One shared norm keeps scatter, contour and web map colours identical.
        norm=Normalize(lo,hi)
        x=frame['Easting (m)']-origin.iloc[0];y=frame['Northing (m)']-origin.iloc[1]
        if style=='Contour Plot':
            self.draw_contour(ax,x,y,frame[col],lo,hi,cmap)
            ax.scatter(x,y,c='k',s=1.5,alpha=.35,linewidths=0,zorder=2,label='Samples')
        else:
            ax.scatter(x,y,c=frame[col],cmap=cmap,norm=norm,s=9,zorder=2)
        # Check the stage by position, not title text, so renaming the stages can't hide the markers.
        if stage_index==0 and len(removed):
            ax.scatter(removed['Easting (m)']-origin.iloc[0],removed['Northing (m)']-origin.iloc[1],marker='x',c='#b91c1c',s=28,label='Excluded',linewidths=1,zorder=3)
            ax.legend(loc='best',fontsize=9)
        ax.set_title(f'{title} | {len(frame):,} Samples')
        ax.set_xlabel('Relative Easting (m)');ax.set_ylabel('Relative Northing (m)')
        ax.set_xlim(e.min()-pad,e.max()+pad);ax.set_ylim(n.min()-pad,n.max()+pad)
        ax.set_aspect('equal',adjustable='box');ax.grid(alpha=.15)
        figure.colorbar(ScalarMappable(norm=norm,cmap=cmap),cax=color_axis,label=field_label(col))

    @staticmethod
    def draw_contour(ax,x,y,z,lo,hi,cmap='viridis'):
        keep=np.isfinite(np.asarray(z,dtype=float))
        x,y,z=np.asarray(x,dtype=float)[keep],np.asarray(y,dtype=float)[keep],np.asarray(z,dtype=float)[keep]
        if len(np.unique(np.column_stack([x,y]),axis=0))<3:return
        try:MapMaker(None).tricontourf_clipped(x,y,z,ax=ax,levels=np.linspace(lo,hi,25),cmap=cmap,extend='both')
        except (ValueError,RuntimeError):pass

    def draw_web_maps(self,cleaned,removed,col,lo,hi):
        before=self.map_stage.currentIndex()==0
        frame=self.raw if before else cleaned
        # Same colour scale and limits as the scatter/contour colour bar.
        colors=color_list(self.map_colors.currentData())
        path=WebMap.build_map(frame,value_column=col,caption=field_label(col),vmin=lo,vmax=hi,colors=colors,
                              excluded=removed if before else None,layer_name=f'<span style="display:inline-block;vertical-align:top">'
                                                                              f'{self.map_stage.currentText()}<br>{len(frame):,} Samples</span>')
        self.web_comparison.load(QUrl.fromLocalFile(path))
