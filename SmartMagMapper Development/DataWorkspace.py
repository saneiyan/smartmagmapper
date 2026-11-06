from PlotTheme import compact_toolbar
"""Synchronized observations and interactive, auditable cleaning comparison."""
import numpy as np
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QComboBox,QTabWidget,QGroupBox,QPushButton
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT
import OrphanWellPipeline as ow

class DataWorkspace(QWidget):
    def __init__(self, window):
        super().__init__(); self.window=window;self.raw=None;self.raw_session=None
        root=QVBoxLayout(self)
        # The selected workspace tab supplies its heading.
        self.status=QLabel();self.status.setWordWrap(True);root.addWidget(self.status);self.status.hide()
        self.controls=QGroupBox('Cleaning settings (live)')
        self.controls.setMaximumWidth(310);self.controls.setMinimumWidth(265)
        self.form=QFormLayout(self.controls);self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        body=QHBoxLayout();root.addLayout(body,1)
        body.addWidget(self.controls,0)
        self.signal=QComboBox();self.signal.addItems(['Total magnitude','X','Y','Z'])
        self.signal.currentIndexChanged.connect(self.draw)
        self.form.addRow('Display signal',self.signal)
        self.tabs=QTabWidget();body.addWidget(self.tabs,1)
        self.figure=Figure(figsize=(12,7),constrained_layout=True);self.figure.set_constrained_layout_pads(w_pad=.04,h_pad=.07,hspace=.06,wspace=.05);self.canvas=FigureCanvas(self.figure)
        page=QWidget();plot_layout=QVBoxLayout(page);plot_layout.setContentsMargins(0,0,0,0)
        self.toolbar=NavigationToolbar2QT(self.canvas,page);toolbar=self.toolbar;compact_toolbar(toolbar)
        plot_layout.addWidget(toolbar);plot_layout.addWidget(self.canvas,1)
        self.map_page=page
        self.map_style=QComboBox();self.map_style.addItems(['Point Map','Contour Map','Web Map'])
        self.form.addRow('Map Display',self.map_style)
        self.map_stage=QComboBox();self.map_stage.addItems(['Before Cleaning','After Cleaning']);self.map_stage.setCurrentIndex(1)
        map_options=QHBoxLayout()
        map_options.addStretch(1)
        map_options.addWidget(QLabel('Cleaning Stage:'))
        self.map_stage.setMinimumWidth(210)
        map_options.addWidget(self.map_stage)
        map_options.addStretch(1)
        plot_layout.insertLayout(0,map_options)
        self.map_stage.currentIndexChanged.connect(self.draw)
        self.map_style.currentIndexChanged.connect(self.draw)
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        self.web_comparison=QWebEngineView();plot_layout.addWidget(self.web_comparison,1);self.web_comparison.hide()
        self.tabs.addTab(page,'Cleaning Maps')
        self.tables=QTabWidget();self.tables.addTab(window.data,'Cleaned Samples')
        self.tabs.addTab(self.tables,'Data Tables')
        self.column_picker=QComboBox();self.column_picker.setMinimumWidth(240)
        self.show_column=QPushButton('Show Plot');self.show_column.setEnabled(False)
        signal_controls=QHBoxLayout();signal_controls.addWidget(QLabel('Signal Column:'));signal_controls.addWidget(self.column_picker,1);signal_controls.addWidget(self.show_column)
        self.signal_source=QComboBox();self.signal_source.addItems(['Cleaned Samples','Before Cleaning'])
        self.signal_style=QComboBox();self.signal_style.addItems(['Line','Scatter'])
        signal_controls.addWidget(QLabel('Data:'));signal_controls.addWidget(self.signal_source)
        signal_controls.addWidget(QLabel('Display:'));signal_controls.addWidget(self.signal_style)
        self.signal_source.currentIndexChanged.connect(self.redraw_signal_plots)
        self.signal_style.currentIndexChanged.connect(self.redraw_signal_plots)
        window.plot_layout.insertLayout(0,signal_controls)
        self.column_picker.currentIndexChanged.connect(self.show_signal_column)
        self.show_column.clicked.connect(self.show_signal_column)
        self.tabs.addTab(window.plot_widget,'Signal Plots')
        self.tabs.currentChanged.connect(self.update_context_controls)
        window.plot_tabs.currentChanged.connect(self.sync_signal_column)
        self.tabs.setTabToolTip(2,'Individual cleaned-data columns plotted against measurement time. Choose a numeric column using Signal Column in this view.')
        self.tabs.setTabToolTip(0,'Before cleaning shows synchronized observations before startup removal and position rejection. Colors represent magnetic field values.')

    def update_context_controls(self,*_):
        self.form.setRowVisible(self.signal,self.tabs.currentIndex()==0)
        self.form.setRowVisible(self.map_style,self.tabs.currentIndex()==0)

    def sync_signal_column(self,*_):
        page=self.window.plot_tabs.currentWidget()
        if page is None:return
        index=self.column_picker.findData(getattr(page,'signal_column',None))
        if index>=0:
            self.column_picker.blockSignals(True);self.column_picker.setCurrentIndex(index);self.column_picker.blockSignals(False)

    def update_signal_columns(self, frame):
        from pandas.api.types import is_numeric_dtype
        selected=self.column_picker.currentData()
        self.column_picker.blockSignals(True);self.column_picker.clear()
        excluded={'Time (s)','Mag_Time (s)','UTM_EPSG','easting','northing','Total_Field_uT'}
        for column in frame.columns:
            if column not in excluded and is_numeric_dtype(frame[column]):
                self.column_picker.addItem('Total Magnitude' if column=='BT' else str(column),column)
        index=self.column_picker.findData(selected if selected in frame.columns else 'BT')
        self.column_picker.setCurrentIndex(max(0,index));self.column_picker.blockSignals(False)
        self.show_column.setEnabled(self.column_picker.count()>0)
        current=self.column_picker.currentData()
        if current is not None and current!='BT':self.window.new_plot(name=current,df=frame,column=frame[current])

    def show_signal_column(self,*_):
        column=self.column_picker.currentData()
        if column is not None:self.window.plot_changed(val=column)

    def bind_controls(self):
        w=self.window
        self.form.addRow('Startup samples removed',w.ow_startup_samples)
        self.form.addRow('Spatial rejection (MAD multiplier)',w.ow_spatial_mad)
        self.form.addRow('Percentile fallback (only if MAD = 0)',w.ow_fallback_percentile)
        w.ow_startup_samples.setToolTip('Removes this many synchronized observations at the beginning of the survey.')
        w.ow_spatial_mad.setToolTip('Rejects positions beyond median radial distance + multiplier x radial MAD. Larger values retain more positions.')
        w.ow_fallback_percentile.setToolTip('Only used if radial MAD is zero. This is not a general magnetic amplitude percentile filter.')
        self.raw_table=type(w.data)();self.tables.insertTab(0,self.raw_table,'Synchronized Before Cleaning')
        self.stream_tables=[]
        for title in ['Raw Magnetometer','Raw GPS']:
            table=type(w.data)();self.tables.addTab(table,title);self.stream_tables.append(table)
# Raw input streams come first; synchronized and cleaned tables follow.
        self.tables.tabBar().moveTab(2,0);self.tables.tabBar().moveTab(3,1);self.tables.setCurrentIndex(0)
        self.cleaning_details=QLabel('Import data to inspect cleaning.');self.cleaning_details.setWordWrap(True);self.form.addRow(self.cleaning_details)
        self.reset=QPushButton('Restore cleaning defaults')
        self.reset.clicked.connect(self.restore_defaults);self.form.addRow(self.reset)

    def restore_defaults(self):
        self.window.ow_startup_samples.setValue(10)
        self.window.ow_spatial_mad.setValue(6)
        self.window.ow_fallback_percentile.setValue(95)

    def refresh(self):
        session=self.window.active_session()
        if session is None:return
        if self.raw_session is not session:
            self.raw,_=ow.clean_survey(session.magnetometer,session.location,self.window.orphan_params(),synchronized_only=True)
            self.raw_session=session
            self.set_table(self.raw_table,self.raw)
            for table,frame in zip(self.stream_tables,[session.magnetometer,session.location]):self.set_table(table,frame)
        a=session.audit
        self.status.hide()
        self.cleaning_details.setText(f"Spatial rule: {a['spatial_rule']}\nPosition cutoff: {a['spatial_limit_m']:.2f} m\nCleaning changes clear filters and comparison previews.")
        self.window.ow_fallback_percentile.setEnabled(a['spatial_rule']=='percentile fallback')
        for index,name in enumerate(['Total magnitude','X','Y','Z']):
            self.signal.model().item(index).setEnabled(index==0 or name+' (\u00b5T)' in session.cleaned)
        if self.signal.currentIndex()>0 and self.signal.currentText()+' (\u00b5T)' not in session.cleaned:self.signal.setCurrentIndex(0)
        self.draw()
        self.redraw_signal_plots()

    def record_labels(self,frame):
        session=self.window.active_session()
        if session is None or 'Mag_Time (s)' not in frame:return None
        if self.raw_session is not session or self.raw is None:
            self.raw,_=ow.clean_survey(session.magnetometer,session.location,self.window.orphan_params(),synchronized_only=True)
            self.raw_session=session
            self.set_table(self.raw_table,self.raw)
            for table,stream in zip(self.stream_tables,[session.magnetometer,session.location]):self.set_table(table,stream)
        lookup=dict(zip(self.raw['Mag_Time (s)'],self.raw.index))
        return [lookup.get(t,i) for i,t in enumerate(frame['Mag_Time (s)'])]

    @staticmethod
    def set_table(table,frame):
        import TableModel
        table.setModel(TableModel.TableModel(frame));table.setAlternatingRowColors(True)

    def redraw_signal_plots(self,*_):
        session=self.window.active_session()
        if session is None:return
        frame=self.raw if self.signal_source.currentIndex()==1 else session.cleaned
        if frame is None:return
        for index in range(self.window.plot_tabs.count()):
            page=self.window.plot_tabs.widget(index)
            if hasattr(page,'draw_signal'):page.draw_signal(frame,self.signal_style.currentText())

    def draw(self,*_):
        session=self.window.active_session()
        if session is None or self.raw is None:return
        col='BT' if self.signal.currentIndex()==0 else self.signal.currentText()+' (\u00b5T)'
        if col not in session.cleaned:return
        values=np.concatenate([self.raw[col].to_numpy(),session.cleaned[col].to_numpy()])
        lo,hi=float(np.nanmin(values)),float(np.nanmax(values))
        if hi==lo:hi=lo+1e-9
        removed=self.raw.loc[~self.raw['Mag_Time (s)'].isin(session.cleaned['Mag_Time (s)'])]
        web=self.map_style.currentText()=='Web Map'
        self.canvas.setVisible(not web);self.toolbar.setVisible(not web);self.web_comparison.setVisible(web)
        if web:
            self.draw_web_maps(session.cleaned,removed,col,lo,hi);return
        self.figure.clear()
        grid=self.figure.add_gridspec(1,3,width_ratios=[.045,1,.045],wspace=.06)
        axes=[self.figure.add_subplot(grid[0,1])]
        color_axis=self.figure.add_subplot(grid[0,2])
        origin=self.raw[['Easting (m)','Northing (m)']].mean()
        e=self.raw['Easting (m)']-origin.iloc[0];n=self.raw['Northing (m)']-origin.iloc[1]
        pad=max(float(np.ptp(e)),float(np.ptp(n)))*.06 or 1
        stage=(self.raw,'Before Cleaning') if self.map_stage.currentIndex()==0 else (session.cleaned,'After Cleaning')
        for ax,(frame,title) in zip(axes,[stage]):
            x=frame['Easting (m)']-origin.iloc[0];y=frame['Northing (m)']-origin.iloc[1]
            if self.map_style.currentText()=='Contour Map' and len(np.unique(np.column_stack([x,y]),axis=0))>=3:
                try:ax.tricontourf(x,y,frame[col],levels=np.linspace(lo,hi,25),cmap='viridis',vmin=lo,vmax=hi)
                except (ValueError,RuntimeError):pass
            im=ax.scatter(x,y,c=frame[col],cmap='viridis',vmin=lo,vmax=hi,s=9,zorder=2)
            if title=='Before Cleaning' and len(removed):
                ax.scatter(removed['Easting (m)']-origin.iloc[0],removed['Northing (m)']-origin.iloc[1],marker='x',c='#b91c1c',s=28,label='Excluded',linewidths=1,zorder=3)
                ax.legend(loc='best',fontsize=9)
            ax.set_title(f'{title} | {len(frame):,} Samples')
            ax.set_xlabel('Relative Easting (m)');ax.set_ylabel('Relative Northing (m)')
            ax.set_xlim(e.min()-pad,e.max()+pad);ax.set_ylim(n.min()-pad,n.max()+pad)
            ax.set_aspect('equal',adjustable='box');ax.grid(alpha=.15)
        self.figure.colorbar(im,cax=color_axis,label=col+' (\u00b5T)' if col=='BT' else col)
        self.toolbar.update();self.canvas.draw_idle()

    def draw_web_maps(self,cleaned,removed,col,lo,hi):
        import folium,tempfile
        from pathlib import Path
        from branca.colormap import LinearColormap
        from PyQt6.QtCore import QUrl
        lat=next(c for c in self.raw if c.startswith('Latitude'))
        lon=next(c for c in self.raw if c.startswith('Longitude'))
        maps=folium.Map(location=[float(self.raw[lat].median()),float(self.raw[lon].median())],zoom_start=18,tiles='OpenStreetMap')
        frame=self.raw if self.map_stage.currentIndex()==0 else cleaned
        title=self.map_stage.currentText()
        from matplotlib import colormaps
        from matplotlib.colors import to_hex
        cmap=LinearColormap([to_hex(colormaps['viridis'](v)) for v in np.linspace(0,1,16)],vmin=lo,vmax=hi,caption=col+' (microtesla)')
        layer=folium.FeatureGroup(name=title+' | '+str(len(frame))+' Samples')
        for _,row in frame.iterrows():
            color=cmap(float(row[col]))
            folium.CircleMarker([row[lat],row[lon]],radius=3,color=color,fill=True,fill_color=color,fill_opacity=.9,weight=0,tooltip=f"Time: {row['Mag_Time (s)']:.3f} s; {col}: {row[col]:.3f}").add_to(layer)
        layer.add_to(maps)
        if self.map_stage.currentIndex()==0 and len(removed):
            excluded=folium.FeatureGroup(name='Excluded Positions')
            for _,row in removed.iterrows():folium.CircleMarker([row[lat],row[lon]],radius=5,color='#b91c1c',weight=2,fill=False).add_to(excluded)
            excluded.add_to(maps)
        cmap.add_to(maps);folium.LayerControl(collapsed=False).add_to(maps)
        maps.fit_bounds([[float(self.raw[lat].min()),float(self.raw[lon].min())],[float(self.raw[lat].max()),float(self.raw[lon].max())]])
        path=Path(tempfile.gettempdir())/f'smartmagmapper_cleaning_{id(self)}.html'
        maps.save(str(path));self.web_comparison.load(QUrl.fromLocalFile(str(path)))
