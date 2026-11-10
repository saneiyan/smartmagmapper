"""Project lifecycle, filter history and application-wide settings in one menu layer."""
from pathlib import Path
from datetime import datetime,timezone
import uuid,weakref,math,zipfile,json
from PyQt6.QtCore import QObject,QTimer,QSettings,QStandardPaths,QEvent,QSignalBlocker,Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QApplication,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QTextEdit,QSpinBox,QCheckBox,QPushButton,QDialogButtonBox,QFileDialog,QMessageBox,QListWidget,QTableView)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg,NavigationToolbar2QT
import ProjectIO
import TableModel

UNTITLED='Untitled survey project'

def project_name_from_path(path):
    """'site3.smmproj' or the backup 'site3.smmproj.bak2' -> 'site3'."""
    name=Path(path).name
    return name[:name.lower().index('.smmproj')] if '.smmproj' in name.lower() else Path(path).stem

CONTROL_NAMES=['ow_startup_samples','ow_spatial_mad','ow_fallback_percentile','ow_window_length','ow_step_ratio','ow_gamma','ow_dbscan_eps','ow_min_samples']

class ProjectTools(QObject):
    def __init__(self,window):
        super().__init__(window);self.w=window;self.path=None;self.metadata={'id':str(uuid.uuid4()),'title':UNTITLED,'author':'','notes':''}
        self.recovered=False;self.dirty=False;self.loading=False;self.project_active=False;self.last_recovery=None;self.connected=set();self.view_hooks=weakref.WeakKeyDictionary();self.measure_points=[];self.measure_artists=[]
        self.preferences=QSettings('SmartMagMapper','Desktop')
        self.precision=int(self.preferences.value('table_precision',4));self.grid=self.preferences.value('plot_grid',True,type=bool)
        self.auto_enabled=self.preferences.value('autosave',True,type=bool);self.interval=int(self.preferences.value('autosave_minutes',2))
        self.recovery_dir=Path(self.preferences.value('recovery_dir',str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))/'SmartMagMapper'/'Recovery')))
        TableModel.DISPLAY_PRECISION=self.precision
        self.build_menus()
        for name in CONTROL_NAMES:getattr(window,name).valueChanged.connect(self.changed)
        window.ow_input.currentIndexChanged.connect(self.changed)
        for edit in [window.ow_well_lat,window.ow_well_lon]:edit.textChanged.connect(self.changed)
        window.select_file.currentIndexChanged.connect(self.update_actions)
        for tabs in [window.tabs,window.data_workspace.tabs,window.location_views]:tabs.currentChanged.connect(self.update_actions)
        self.timer=QTimer(self);self.timer.timeout.connect(self.autosave);self.timer.start(self.interval*60000)
        QApplication.instance().installEventFilter(self)
        self.update_actions();self.connect_canvases()

    def action(self,menu,title,callback,shortcut=None,checkable=False):
        action=QAction(title,self.w);action.setCheckable(checkable);action.triggered.connect(callback)
        if shortcut:action.setShortcut(shortcut)
        menu.addAction(action);return action

    def build_menus(self):
        w=self.w;w.menu=w.menuBar();w.file_menu=w.menu.addMenu('File')
        self.action(w.file_menu,'New Project',self.new_project,'Ctrl+N')
        self.action(w.file_menu,'Open Project...',self.open_project,'Ctrl+O')
        self.action(w.file_menu,'Recover Project...',self.recover)
        w.file_menu.addSeparator()
        self.save_action=self.action(w.file_menu,'Save Project',self.save_project,'Ctrl+S')
        self.action(w.file_menu,'Save Project As...',lambda:self.save_project(save_as=True),'Ctrl+Shift+S')
        w.file_menu.addSeparator()
        self.import_action=self.action(w.file_menu,'Import Data...',w.import_data_action,'Ctrl+Shift+I')
        self.data_export=self.action(w.file_menu,'Export Cleaned Survey...',w.export_dialog)
        w.file_menu.addSeparator()
        self.filter_export=self.action(w.file_menu,'Export Current Filter Preview...',lambda:w.filters_workspace.export())
        self.analysis_export=self.action(w.file_menu,'Export Analysis Results...',w.export_orphan_results)
        w.file_menu.aboutToShow.connect(self.update_actions)
        w.file_menu.addSeparator()
        self.properties_action=self.action(w.file_menu,'Current Project Properties...',self.properties)
        self.backups_action=self.action(w.file_menu,'Curent Project Backups...',self.backups)
        edit=w.menu.addMenu('Edit')
        self.undo_action=self.action(edit,'Undo Applied Filter',lambda:self.history(False),'Ctrl+Z')
        self.redo_action=self.action(edit,'Redo Applied Filter',lambda:self.history(True),'Ctrl+Shift+Z')
        edit.aboutToShow.connect(self.update_actions)
        view=w.menu.addMenu('View')
        self.grid_action=self.action(view,'Show Plot Grid',self.toggle_grid,checkable=True);self.grid_action.setChecked(self.grid)
        self.action(view,'Reset Plot View',self.reset_plot,'Ctrl+0')
        tools=w.menu.addMenu('Tools')
        self.recalculate_action=self.action(tools,'Recalculate Analysis',self.recalculate,'F5')
        self.measure_action=self.action(tools,'Measure Map Distance',self.enable_measure,'Ctrl+M',checkable=True)
        self.action(tools,'Settings...',self.settings)
        # The existing analysis button uses this same global action; hide its duplicate control.
        w.ow_apply_button.hide();w.ow_export_button.hide()

    def changed(self,*_):
        if self.loading:return
        self.dirty=True;self.update_actions()

    def update_actions(self,*_):
        session=self.w.active_session()
        # Project-level actions stay disabled until New Project or Open Project succeeds.
        for action in [self.import_action,self.properties_action,self.backups_action]:action.setEnabled(self.project_active)
        self.undo_action.setEnabled(session is not None and bool(session.undo_states))
        self.redo_action.setEnabled(session is not None and bool(session.redo_states))
        self.recalculate_action.setEnabled(session is not None)
        if self.data_export:self.data_export.setEnabled(session is not None)
        if self.filter_export:self.filter_export.setEnabled(self.w.filters_workspace.result is not None)
        if self.analysis_export:self.analysis_export.setEnabled(self.w.ow_annotated_df is not None)
        eligible=session is not None and bool(self.measure_targets())
        self.measure_action.setEnabled(eligible)
        if not eligible:
            if self.measure_action.isChecked():self.measure_action.setChecked(False);self.enable_measure(False)
            self.measure_points=[]
        # Recovered/backup snapshots are flagged until they are saved as a project file.
        title=self.metadata['title']+(' (recovered)' if self.recovered else '')+(' *' if self.dirty else '')
        self.w.setWindowTitle('SmartMagMapper | Project Workspace'+(' | '+title if self.project_active else ''))

    def state(self):
        w=self.w
        params={name:getattr(w,name).value() for name in CONTROL_NAMES}
        params.update(well_lat=w.ow_well_lat.text(),well_lon=w.ow_well_lon.text(),analysis_input=w.ow_input.currentIndex(),main_tab=w.tabs.currentIndex(),signal_column=w.data_workspace.column_picker.currentData())
        lab=w.filters_workspace
        params['filter_form']={'method':lab.method.currentText(),'field':lab.field.currentText(),'domain':lab.domain.currentText(),'parameters':lab.active_parameters()}
        params['comparison_next']=lab.comparisons.next_index
        params['comparison_checked']=lab.comparisons.visible_names()
        return params

    def save_to(self,path,backup=True):
        if self.w.is_imported_file(Path(path)):raise ValueError('Choose a project name that does not overwrite imported data.')
        return ProjectIO.write_project(path,self.w.sessions,self.w.active_dataset_index,self.state(),self.metadata,self.w.filters_workspace.comparisons.slots,backup=backup)

    def save_project(self,checked=False,save_as=False):
        path=self.path
        if save_as or path is None:
            suggested=''.join('_' if c in '\\/:*?"<>|' else c for c in self.metadata['title']).strip() if self.metadata['title']!=UNTITLED else 'survey'
            selected,_=QFileDialog.getSaveFileName(self.w,'Save Survey Project',str(path or Path.home()/(suggested+'.smmproj')),'SmartMagMapper project (*.smmproj)')
            if not selected:return False
            path=Path(selected)
            if path.suffix.lower()!='.smmproj':path=path.with_suffix('.smmproj')
        previous_title=self.metadata['title']
        # The title follows the file name (first save and Save As) unless the user set a
        # custom title in Project Properties, i.e. one that differs from the current file name.
        current_name=project_name_from_path(self.path) if self.path else None
        if previous_title in (UNTITLED,current_name):self.metadata['title']=project_name_from_path(path)
        try:
            self.save_to(path);self.path=Path(path);self.dirty=False;self.recovered=False;self.last_recovery=None;self.update_actions()
            self.w.statusBar().showMessage('Project saved: '+self.path.name);return True
        except Exception as exc:self.metadata['title']=previous_title;QMessageBox.warning(self.w,'Project Save',str(exc));return False

    def confirm_replace(self):
        if not self.dirty:return True
        answer=QMessageBox.question(self.w,'Unsaved Project','Save this project before replacing it?',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save)
        if answer==QMessageBox.StandardButton.Cancel:return False
        return self.save_project() if answer==QMessageBox.StandardButton.Save else True

    def select_survey_cleaning(self,session):
        if self.loading or session.cleaning_key is None:return
        controls=[self.w.ow_startup_samples,self.w.ow_spatial_mad,self.w.ow_fallback_percentile]
        blockers=[QSignalBlocker(control) for control in controls]
        for control,value in zip(controls,session.cleaning_key):control.setValue(value)
        del blockers

    def reset_workspace(self):
        w=self.w;w.ow_update_timer.stop();w.ow_reload_timer.stop()
        w.select_file.blockSignals(True);w.select_file.clear();w.select_file.blockSignals(False)
        w.sessions=[];w.df_list=[];w.processed_dfs={};w.dialog_configs={};w.mag_gps_dfs={};w.active_dataset_index=None
        w.current_df=w.df=w.ow_selected_dataset=None;w.ow_file_path=None;w.ow_selected_dataset_index=None;w.active_filters=[]
        w.plot_tabs.clear();w.data_workspace.raw=None;w.data_workspace.raw_session=None;w.data_workspace.column_picker.clear()
        for table in [w.data,w.data_workspace.raw_table,*w.data_workspace.stream_tables]:table.setModel(None)
        for figure,canvas in [(w.figure,w.canvas),(w.data_workspace.figure,w.data_workspace.canvas)]:figure.clear();canvas.draw_idle()
        w.filters_workspace.session_changed();w.clear_orphan_results('No survey loaded.');w.data_workspace.status.hide();w.data_workspace.cleaning_details.setText('Import a survey to inspect cleaning.')
        w.shared_field_label.setText('Current field: No survey');w.ow_dataset_label.setText('Active survey: None');w.ow_input_label.setText('Analysis input: No survey')
        w.residual_cache=None;w.residual_date=None;w.map_vmin=w.map_vmax=w.vmin=w.vmax=None
        w.tabs.setCurrentIndex(0)

    def set_parameters(self,values):
        w=self.w;widgets=[getattr(w,name) for name in CONTROL_NAMES]+[w.ow_well_lat,w.ow_well_lon,w.ow_input]
        blockers=[QSignalBlocker(widget) for widget in widgets]
        for name in CONTROL_NAMES:
            if name in values:getattr(w,name).setValue(values[name])
        w.ow_well_lat.setText(values.get('well_lat',''));w.ow_well_lon.setText(values.get('well_lon',''));w.ow_input.setCurrentIndex(values.get('analysis_input',0))
        del blockers

    def new_project(self):
        if not self.confirm_replace():return False
        self.loading=True
        try:
            self.reset_workspace();self.set_parameters(dict(zip(CONTROL_NAMES,[10,6.,95.,5.,.25,2.,4.,5])))
            self.path=None;self.metadata={'id':str(uuid.uuid4()),'title':UNTITLED,'author':'','notes':''};self.recovered=False;self.dirty=False;self.last_recovery=None;self.project_active=True
        finally:self.loading=False;self.update_actions()
        return True

    def open_project(self,checked=False,path=None,recovery=False):
        if path is None:
            selected,_=QFileDialog.getOpenFileName(self.w,'Open Survey Project','','SmartMagMapper projects (*.smmproj *.bak1 *.bak2 *.bak3)')
            if not selected:return False
            path=Path(selected)
        try:
            # Parse and validate everything before changing the current workspace.
            manifest,sessions,comparisons=ProjectIO.read_project(path)
        except Exception as exc:QMessageBox.warning(self.w,'Open Project',str(exc));return False
        if not self.confirm_replace():return False
        w=self.w;self.loading=True
        try:
            self.reset_workspace();self.set_parameters(manifest['settings'])
            w.sessions=sessions;w.df_list=[None]*len(sessions)
            w.select_file.blockSignals(True)
            for i,session in enumerate(sessions):w.select_file.addItem(Path(session.path).name,session.path)
            active=manifest['active'];w.select_file.setCurrentIndex(-1 if active is None else active);w.select_file.blockSignals(False)
            if active is not None:w.activate_survey(active)
            c=w.filters_workspace.comparisons;c.slots=comparisons;c.session_key=c.key();c.next_index=0;c.refresh_library()
            selected=set(manifest['settings'].get('comparison_checked',list(comparisons)[:3]))
            c.library.blockSignals(True)
            for i in range(c.library.count()):c.library.item(i).setCheckState(Qt.CheckState.Checked if c.library.item(i).data(Qt.ItemDataRole.UserRole) in selected else Qt.CheckState.Unchecked)
            c.library.blockSignals(False);c.draw()
            form=manifest['settings'].get('filter_form',{});lab=w.filters_workspace
            if form:
                lab.method.setCurrentText(form['method']);lab.field.setCurrentText(form['field']);lab.domain.setCurrentText(form['domain'])
                for key,control in [('window',lab.window_length),('low',lab.low),('high',lab.high),('k_modes',lab.k),('alpha',lab.alpha),('cell_size',lab.cell),('height',lab.height),('max_gain',lab.gain),('inclination',lab.inc),('declination',lab.dec)]:
                    if key in form['parameters']:control.setValue(form['parameters'][key])
            signal=manifest['settings'].get('signal_column');picker=w.data_workspace.column_picker
            index=picker.findData(signal)
            if index>=0:picker.setCurrentIndex(index)
            w.tabs.setCurrentIndex(manifest['settings'].get('main_tab',0))
            self.metadata=manifest['metadata'];self.recovered=recovery
            # Projects saved without a title are shown by their file name (recovery files have no meaningful name).
            if not self.metadata.get('title','').strip() or self.metadata['title']==UNTITLED:
                stored=project_name_from_path(path)
                self.metadata['title']=UNTITLED if stored.startswith('recovery-') else stored
            self.path=None if recovery else Path(path);self.dirty=recovery;self.last_recovery=None;self.project_active=True
            self.w.statusBar().showMessage('Recovery opened; use Save Project As to retain it.' if recovery else 'Project opened: '+Path(path).name)
        finally:self.loading=False;self.update_actions();self.connect_canvases()
        return True

    def history(self,redo):
        session=self.w.active_session()
        if session is None:return False
        result=session.redo_field() if redo else session.undo_field()
        if result:self.w.activate_survey(self.w.active_dataset_index);self.changed()
        return result

    def recalculate(self):
        session=self.w.active_session()
        if session is None:return
        self.w.ow_update_timer.stop();self.w.ow_reload_timer.stop()
        try:
            changed=session.ensure_cleaned(self.w.orphan_params())
            session.mode_cache.clear()
            if changed:self.w.activate_survey(self.w.active_dataset_index)
            else:self.w.run_orphan_analysis()
            if self.w.ow_summary_data:self.w.statusBar().showMessage('Analysis recalculated from the selected input.')
        except Exception as exc:QMessageBox.warning(self.w,'Recalculate Analysis',str(exc))
        self.changed()

    def properties(self):
        dialog=QDialog(self.w);dialog.setWindowTitle('Project Properties');layout=QVBoxLayout(dialog);form=QFormLayout()
        title=QLineEdit(self.metadata['title']);author=QLineEdit(self.metadata.get('author',''));notes=QTextEdit(self.metadata.get('notes',''))
        form.addRow('Project Title',title);form.addRow('Author',author);form.addRow('Notes',notes)
        form.addRow('Units',QLabel('Magnetic field: microtesla (uT) | Position: metres | Time: seconds'))
        session=self.w.active_session()
        form.addRow('Surveys',QLabel(str(len(self.w.sessions))))
        form.addRow('Coordinate System',QLabel('UTM EPSG '+str(int(session.cleaned['UTM_EPSG'].iloc[0])) if session is not None else 'Determined when a survey is imported'))
        layout.addLayout(form);buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec():self.metadata.update(title=title.text().strip() or UNTITLED,author=author.text(),notes=notes.toPlainText());self.changed()

    def backups(self):
        paths=[Path(str(self.path)+f'.bak{i}') for i in range(1,4)] if self.path else []
        self.choose_snapshot([p for p in paths if p.exists()],'Project Backups',recovery=True)

    def recover(self):
        self.choose_snapshot(sorted(self.recovery_dir.glob('recovery-*.smmproj'),key=lambda p:p.stat().st_mtime,reverse=True) if self.recovery_dir.exists() else [],'Recover Project',recovery=True)

    def choose_snapshot(self,paths,title,recovery=True):
        if not paths:QMessageBox.information(self.w,title,'No saved snapshots are available yet.');return
        dialog=QDialog(self.w);dialog.setWindowTitle(title);layout=QVBoxLayout(dialog);items=QListWidget();layout.addWidget(items)
        for path in paths:
            try:
                with zipfile.ZipFile(path) as archive:data=json.loads(archive.read('project.json'))
                items.addItem(data['metadata']['title']+' | '+data['saved_utc']+' | '+path.name)
            except Exception:items.addItem(path.name)
        items.setCurrentRow(0);buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Open|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec() and items.currentRow()>=0:self.open_project(path=paths[items.currentRow()],recovery=recovery)

    def autosave(self):
        if self.loading or not self.auto_enabled or not self.dirty or not self.w.sessions:return False
        try:
            self.recovery_dir.mkdir(parents=True,exist_ok=True)
            name='recovery-'+self.metadata['id']+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.smmproj'
            path=self.recovery_dir/name;self.save_to(path,backup=False);self.last_recovery=path
            snapshots=sorted(self.recovery_dir.glob('recovery-'+self.metadata['id']+'-*.smmproj'),key=lambda p:p.stat().st_mtime,reverse=True)
            for old in snapshots[5:]:old.unlink()
            self.w.statusBar().showMessage('Project recovery snapshot saved.');return True
        except Exception as exc:self.w.statusBar().showMessage('Recovery snapshot failed: '+str(exc));return False

    def settings(self):
        dialog=QDialog(self.w);dialog.setWindowTitle('Application Settings');layout=QVBoxLayout(dialog);form=QFormLayout()
        precision=QSpinBox();precision.setRange(0,8);precision.setValue(self.precision)
        auto=QCheckBox('Save recovery snapshots for unsaved work');auto.setChecked(self.auto_enabled)
        minutes=QSpinBox();minutes.setRange(1,30);minutes.setValue(self.interval);minutes.setSuffix(' min')
        folder=QLineEdit(str(self.recovery_dir));browse=QPushButton('Browse...');row=QHBoxLayout();row.addWidget(folder);row.addWidget(browse)
        def choose():
            selected=QFileDialog.getExistingDirectory(dialog,'Recovery Folder',folder.text())
            if selected:folder.setText(selected)
        browse.clicked.connect(choose)
        form.addRow('Table Decimal Places',precision);form.addRow('Automatic Recovery',auto);form.addRow('Snapshot Interval',minutes);form.addRow('Recovery Folder',row)
        layout.addLayout(form);layout.addWidget(QLabel('Display precision does not round data or exports. Recovery retains five snapshots per project; Save Project retains three backups.'))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec():
            proposed=Path(folder.text().strip()).expanduser()
            if not folder.text().strip() or not proposed.is_absolute():QMessageBox.warning(self.w,'Recovery Folder','Choose an absolute folder path for recovery snapshots.');return
            self.precision=precision.value();self.auto_enabled=auto.isChecked();self.interval=minutes.value();self.recovery_dir=proposed
            for key,value in [('table_precision',self.precision),('autosave',self.auto_enabled),('autosave_minutes',self.interval),('recovery_dir',str(self.recovery_dir))]:self.preferences.setValue(key,value)
            TableModel.DISPLAY_PRECISION=self.precision
            for table in self.w.findChildren(QTableView):table.viewport().update()
            self.timer.start(self.interval*60000)

    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.Show and isinstance(obj,FigureCanvasQTAgg) and obj.window() is self.w:self.hook_canvas(obj)
        return False

    def hook_canvas(self,canvas):
        if id(canvas) in self.connected:return
        self.connected.add(id(canvas))
        def on_draw(event):
            for axis in canvas.figure.axes:
                if axis not in self.view_hooks:self.view_hooks[axis]=(axis.get_xlim(),axis.get_ylim())
            if self.apply_grid(canvas):canvas.draw_idle()
        canvas.mpl_connect('draw_event',on_draw);canvas.mpl_connect('button_press_event',self.measure_click);self.apply_grid(canvas)

    def connect_canvases(self):
        for canvas in self.w.findChildren(FigureCanvasQTAgg):self.hook_canvas(canvas)

    def apply_grid(self,canvas):
        changed=False
        for ax in canvas.figure.axes:
            if not ax.axison or getattr(ax,'_colorbar',None) is not None:continue
            states=[line.get_visible() for line in ax.get_xgridlines()+ax.get_ygridlines()]
            if any(value!=self.grid for value in states):
                if self.grid:ax.grid(True,alpha=.2)
                else:ax.grid(False)
                changed=True
        return changed

    def toggle_grid(self,checked):
        self.grid=checked;self.preferences.setValue('plot_grid',checked);self.connect_canvases()
        for canvas in self.w.findChildren(FigureCanvasQTAgg):self.apply_grid(canvas);canvas.draw_idle()

    def measure_targets(self):
        w=self.w
        if w.tabs.currentWidget() is w.data_workspace and w.data_workspace.tabs.currentIndex()==0:return w.data_workspace.figure.axes[:1] if w.data_workspace.canvas.isVisible() else []
        if w.tabs.currentIndex()==3 and w.location_views.currentIndex()==0:return w.ow_cluster_figure.axes[:1]
        return []

    def enable_measure(self,checked):
        self.measure_points=[]
        if not checked:
            for artist in self.measure_artists:
                try:artist.remove()
                except ValueError:pass
            self.measure_artists=[]
            for canvas in self.w.findChildren(FigureCanvasQTAgg):
                if canvas.isVisible():canvas.draw_idle()
        if checked:
            for toolbar in self.w.findChildren(NavigationToolbar2QT):
                if toolbar.isVisible():
                    if str(toolbar.mode).startswith('pan'):toolbar.pan()
                    elif str(toolbar.mode).startswith('zoom'):toolbar.zoom()
            self.connect_canvases();self.w.statusBar().showMessage('Distance tool: click two positions on the same map. Coordinates and distance are in metres.')

    def measure_click(self,event):
        if not self.measure_action.isChecked() or event.button!=1 or event.inaxes not in self.measure_targets() or event.xdata is None or event.ydata is None:return
        point=(event.inaxes,float(event.xdata),float(event.ydata))
        if not self.measure_points or self.measure_points[0][0] is not event.inaxes:
            self.measure_points=[point];self.w.statusBar().showMessage('First point selected. Click the second position on this map.');return
        _,x,y=self.measure_points.pop();distance=math.hypot(point[1]-x,point[2]-y)
        self.measure_artists.extend(event.inaxes.plot([x,point[1]],[y,point[2]],color='#2563eb',ls='--',marker='+',lw=1.2))
        self.measure_artists.append(event.inaxes.annotate(f'{distance:.3f} m',((x+point[1])/2,(y+point[2])/2),color='#1d4ed8',xytext=(5,5),textcoords='offset points'))
        event.canvas.draw_idle();self.w.statusBar().showMessage(f'Projected map distance: {distance:.3f} m. Click two more points to measure again.')

    def reset_plot(self):
        # Reset the currently visible interactive figure, not hidden workspaces.
        for toolbar in self.w.findChildren(NavigationToolbar2QT):
            if toolbar.isVisible():toolbar.home();return
        for canvas in self.w.findChildren(FigureCanvasQTAgg):
            if canvas.isVisible():
                for ax in canvas.figure.axes:
                    if getattr(ax,'_colorbar',None) is None and ax in self.view_hooks:
                        xlim,ylim=self.view_hooks[ax];ax.set_xlim(xlim);ax.set_ylim(ylim)
                canvas.draw_idle();return
