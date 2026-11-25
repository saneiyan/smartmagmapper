"""Project lifecycle, filter history and application-wide settings in one menu layer."""
from pathlib import Path
from datetime import datetime,timezone
import uuid,weakref,math,zipfile,json
from PyQt6.QtCore import QObject,QTimer,QSettings,QStandardPaths,QEvent,QSignalBlocker,Qt,QDate
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (QApplication,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QTextEdit,QSpinBox,QCheckBox,QPushButton,QDialogButtonBox,QFileDialog,QMessageBox,QListWidget,QTableView)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg,NavigationToolbar2QT
from processing import project_io as ProjectIO
from processing import labels, coordinates as coords
from ui import table_model as TableModel

UNTITLED='Untitled survey project'

def project_name_from_path(path):
    """Project name from a project or backup file name.

    Parameters
    ----------
    path : str or pathlib.Path
        For example 'site3.smmproj' or the backup 'site3.smmproj.bak2'.

    Returns
    -------
    str
        For example 'site3'.
    """
    name=Path(path).name
    return name[:name.lower().index('.smmproj')] if '.smmproj' in name.lower() else Path(path).stem

CONTROL_NAMES=['analysis_startup_samples','analysis_spatial_mad','analysis_fallback_percentile','analysis_window_length','analysis_step_ratio','analysis_gamma','analysis_dbscan_eps','analysis_min_samples']

class ProjectTools(QObject):
    """Project files and the File / Edit / View / Tools menus.

    Handles new, open, save and recover, automatic recovery snapshots, backups, project properties, undo/redo of
    applied filters, application settings, the plot grid, plot view reset and the map distance tool.

    Parameters
    ----------
    window : GUI.MainWindow
        Main window.
    """
    def __init__(self,window):
        """Load the preferences, build the menus, watch the settings for unsaved changes and start autosave."""
        super().__init__(window);self.w=window;self.path=None;self.metadata={'id':str(uuid.uuid4()),'title':UNTITLED,'author':'','notes':''}
        self.recovered=False;self.dirty=False;self.loading=False;self.project_active=False;self.connected=set();self.view_hooks=weakref.WeakKeyDictionary();self.measure_points=[];self.measure_artists=[]
        self.preferences=QSettings('SmartMagMapper','Desktop')
        self.precision=int(self.preferences.value('table_precision',4));self.grid=self.preferences.value('plot_grid',True,type=bool)
        self.auto_enabled=self.preferences.value('autosave',True,type=bool);self.interval=int(self.preferences.value('autosave_minutes',2))
        self.recovery_dir=Path(self.preferences.value('recovery_dir',str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))/'SmartMagMapper'/'Recovery')))
        TableModel.DISPLAY_PRECISION=self.precision
        self.build_menus()
        for name in CONTROL_NAMES:self.control(name).valueChanged.connect(self.changed)
        window.analysis_input.currentIndexChanged.connect(self.changed)
        for edit in [window.analysis_reference_lat,window.analysis_reference_lon]:edit.textChanged.connect(self.changed)
        window.select_file.currentIndexChanged.connect(self.update_actions)
        for tabs in [window.tabs,window.data_workspace.tabs,window.location_views]:tabs.currentChanged.connect(self.update_actions)
        self.timer=QTimer(self);self.timer.timeout.connect(self.autosave);self.timer.start(self.interval*60000)
        QApplication.instance().installEventFilter(self)
        self.update_actions();self.connect_canvases()

    def action(self,menu,title,callback,shortcut=None,checkable=False):
        """Add a menu action.

        Parameters
        ----------
        menu : QMenu
            Menu to add to.
        title : str
            Action text.
        callback : callable
            Run when triggered.
        shortcut : str, optional
            Keyboard shortcut, e.g. 'Ctrl+S'.
        checkable : bool, optional
            Make it an on/off action.

        Returns
        -------
        QAction
            The action.
        """
        action=QAction(title,self.w);action.setCheckable(checkable);action.triggered.connect(callback)
        if shortcut:action.setShortcut(shortcut)
        menu.addAction(action);return action

    def build_menus(self):
        """Build the File, Edit, View and Tools menus."""
        w=self.w;w.menu=w.menuBar();w.file_menu=w.menu.addMenu('File')
        self.action(w.file_menu,'New Project',self.new_project,'Ctrl+N')
        self.action(w.file_menu,'Open Project...',self.open_project,'Ctrl+O')
        self.action(w.file_menu,'Recover Project...',self.recover)
        w.file_menu.addSeparator()
        self.action(w.file_menu,'Save Project',self.save_project,'Ctrl+S')
        self.action(w.file_menu,'Save Project As...',lambda:self.save_project(save_as=True),'Ctrl+Shift+S')
        w.file_menu.addSeparator()
        self.import_action=self.action(w.file_menu,'Import Data...',w.import_data_action,'Ctrl+Shift+I')
        self.data_export=self.action(w.file_menu,'Export Data...',w.export_dialog)
        w.file_menu.addSeparator()
        self.filter_export=self.action(w.file_menu,'Export Current Filter Preview...',lambda:w.filters_workspace.export())
        self.analysis_export=self.action(w.file_menu,'Export Analysis Results...',w.export_analysis_results)
        w.file_menu.aboutToShow.connect(self.update_actions)
        w.file_menu.addSeparator()
        self.properties_action=self.action(w.file_menu,'Current Project Properties...',self.properties)
        self.backups_action=self.action(w.file_menu,'Current Project Backups...',self.backups)
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

    def data_imported(self):
        """Importing a survey with no project open starts an untitled, unsaved project."""
        self.project_active=True;self.changed()

    def changed(self,*_):
        """Mark the project as having unsaved changes (ignored while a project is loading).

        Parameters
        ----------
        *_ : object
            Ignored signal arguments.
        """
        if self.loading:return
        self.dirty=True;self.update_actions()

    def update_actions(self,*_):
        """Enable the menu actions that apply now and show the project name and unsaved marker in the title.

        Parameters
        ----------
        *_ : object
            Ignored signal arguments.
        """
        session=self.w.active_session()
        # Import Data is always available
        self.import_action.setEnabled(True)
        #project-level actions wait for a project
        for action in [self.properties_action,self.backups_action]:action.setEnabled(self.project_active)
        self.undo_action.setEnabled(session is not None and bool(session.undo_states))
        self.redo_action.setEnabled(session is not None and bool(session.redo_states))
        self.recalculate_action.setEnabled(session is not None)
        if self.data_export:self.data_export.setEnabled(session is not None)
        if self.filter_export:self.filter_export.setEnabled(self.w.filters_workspace.result is not None)
        if self.analysis_export:self.analysis_export.setEnabled(self.w.analysis_annotated_df is not None)
        eligible=session is not None and bool(self.measure_targets())
        self.measure_action.setEnabled(eligible)
        if not eligible:
            if self.measure_action.isChecked():self.measure_action.setChecked(False);self.enable_measure(False)
            self.measure_points=[]
        # Recovered/backup snapshots are flagged until they are saved as a project file.
        title=self.metadata['title']+(' (recovered)' if self.recovered else '')+(' *' if self.dirty else '')
        self.w.setWindowTitle('SmartMagMapper | Project Workspace'+(' | '+title if self.project_active else ''))

    def control(self,name):
        """Widget for a saved setting name (the cleaning boxes belong to the Data & Cleaning tab).

        Parameters
        ----------
        name : str
            One of CONTROL_NAMES.

        Returns
        -------
        QAbstractSpinBox
            The spin box holding that setting.
        """
        workspace=self.w.data_workspace
        cleaning={'analysis_startup_samples':workspace.startup_samples,'analysis_spatial_mad':workspace.spatial_mad,
                  'analysis_fallback_percentile':workspace.fallback_percentile}
        return cleaning.get(name) or getattr(self.w,name)

    def state(self):
        """Window settings saved with a project.

        Returns
        -------
        dict
            Analysis and cleaning settings, reference location, analysis input, open tab, signal column, colour scales,
            Location Estimate map type, Filter Lab form and view, and the stored-comparison state.
        """
        w=self.w
        params={name:self.control(name).value() for name in CONTROL_NAMES}
        params.update(reference_lat=w.analysis_reference_lat.text(),reference_lon=w.analysis_reference_lon.text(),analysis_input=w.analysis_input.currentIndex(),main_tab=w.tabs.currentIndex(),signal_column=w.data_workspace.column_picker.currentData(),
                      map_colormap=w.data_workspace.map_colors.currentData(),location_colormap=w.location_colors.currentData(),
                      filter_colormap=w.filters_workspace.map_colors.currentData(),
                      location_map_type=w.location_map_type.currentText())
        lab=w.filters_workspace
        params['filter_form']={'method':lab.method.currentText(),'field':lab.field.currentData(),'domain':lab.domain.currentText(),'parameters':lab.active_parameters(),
                               'survey_date':lab.survey_date.date().toString(Qt.DateFormat.ISODate)}
        params['filter_view']={'before':lab.show_before.isChecked(),'difference':lab.show_difference.isChecked(),'plots':lab.plot_views.currentText()}
        params['comparison_next']=lab.comparisons.next_index
        params['comparison_checked']=lab.comparisons.visible_names()
        return params

    def save_to(self,path,backup=True):
        """Write the project to a file.

        Parameters
        ----------
        path : str or pathlib.Path
            Project file.
        backup : bool, optional
            Keep previous versions as .bak1-.bak3.

        Returns
        -------
        dict
            The saved manifest.

        Raises
        ------
        ValueError
            If the path is an imported data file.
        """
        if self.w.is_imported_file(Path(path)):raise ValueError('Choose a project name that does not overwrite imported data.')
        return ProjectIO.write_project(path,self.w.sessions,self.w.active_dataset_index,self.state(),self.metadata,self.w.filters_workspace.comparisons.slots,backup=backup)

    def save_project(self,checked=False,save_as=False):
        """Save Project / Save Project As.

        The project title follows the file name on the first save and on Save As, unless a custom title was set in
        Project Properties.

        Parameters
        ----------
        checked : bool, optional
            Ignored (sent by the menu action).
        save_as : bool, optional
            Always ask for a file name.

        Returns
        -------
        bool
            True if saved.
        """
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
            self.save_to(path);self.path=Path(path);self.dirty=False;self.recovered=False;self.update_actions()
            self.w.statusBar().showMessage('Project saved: '+self.path.name);return True
        except Exception as exc:self.metadata['title']=previous_title;QMessageBox.warning(self.w,'Project Save',str(exc));return False

    def confirm_replace(self,action='replacing it'):
        """With unsaved changes, ask Save / Discard / Cancel before an action that replaces the project.

        Parameters
        ----------
        action : str, optional
            What is about to happen, for the question (e.g. 'exiting').

        Returns
        -------
        bool
            True if the action may go ahead.
        """
        if not self.dirty:return True
        answer=QMessageBox.question(self.w,'Unsaved Project',f'Save this project before {action}?',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save)
        if answer==QMessageBox.StandardButton.Cancel:return False
        return self.save_project() if answer==QMessageBox.StandardButton.Save else True

    def select_survey_cleaning(self,session):
        """Show a survey's own cleaning settings when switching to it.

        Parameters
        ----------
        session : processing.survey_session.SurveySession
            Survey being activated.
        """
        if self.loading or session.cleaning_key is None:return
        self.w.data_workspace.set_cleaning_values(*session.cleaning_key)

    def reset_workspace(self):
        """Remove every survey and result from the window and return to the first tab."""
        w=self.w;w.analysis_update_timer.stop()
        w.select_file.blockSignals(True);w.select_file.clear();w.select_file.blockSignals(False)
        w.sessions=[];w.active_dataset_index=None
        w.analysis_selected_dataset_index=None;w.active_filters=[]
        w.data_workspace.plot_tabs.clear();w.data_workspace.raw=None;w.data_workspace.raw_session=None;w.data_workspace.column_picker.clear()
        for table in [w.data_workspace.cleaned_table,w.data_workspace.raw_table,*w.data_workspace.stream_tables]:table.setModel(None)
        w.data_workspace.figure.clear();w.data_workspace.canvas.draw_idle()
        w.filters_workspace.session_changed();w.clear_analysis_results('No survey loaded.');w.data_workspace.status.hide();w.data_workspace.cleaning_details.setText('Import a survey to inspect cleaning.')
        labels.set_display_unit(labels.DEFAULT_UNIT);w.refresh_unit_labels()
        w.shared_field_label.setText('Current field: No survey');w.analysis_dataset_label.setText('Active survey: None');w.analysis_input_label.setText('Analysis input: No survey')
        w.tabs.setCurrentIndex(0)

    @staticmethod
    def current_setting_names(values):
        """Translate setting names saved by earlier versions (ow_*, well_lat/well_lon).

        Parameters
        ----------
        values : dict
            Saved settings.

        Returns
        -------
        dict
            Settings with current names.
        """
        renamed={'well_lat':'reference_lat','well_lon':'reference_lon'}
        out={}
        for key,value in values.items():
            key=renamed.get(key,'analysis_'+key[3:] if key.startswith('ow_') else key)
            out.setdefault(key,value)
        return out

    def set_parameters(self,values):
        """Put saved analysis settings into the controls without triggering a rerun.

        Parameters
        ----------
        values : dict
            Saved settings (older names are translated).
        """
        values=self.current_setting_names(values)
        w=self.w;widgets=[self.control(name) for name in CONTROL_NAMES]+[w.analysis_reference_lat,w.analysis_reference_lon,w.analysis_input]
        blockers=[QSignalBlocker(widget) for widget in widgets]
        for name in CONTROL_NAMES:
            if name in values:self.control(name).setValue(values[name])
        w.analysis_reference_lat.setText(values.get('reference_lat',''));w.analysis_reference_lon.setText(values.get('reference_lon',''));w.analysis_input.setCurrentIndex(values.get('analysis_input',0))
        del blockers

    def new_project(self):
        """File > New Project: after the unsaved-changes check, clear the window and restore default settings.

        Returns
        -------
        bool
            True if a new project was started.
        """
        if not self.confirm_replace():return False
        self.loading=True
        try:
            self.reset_workspace();self.set_parameters(dict(zip(CONTROL_NAMES,[10,6.,95.,5.,.25,2.,4.,5])))
            self.path=None;self.metadata={'id':str(uuid.uuid4()),'title':UNTITLED,'author':'','notes':''};self.recovered=False;self.dirty=False;self.project_active=True
        finally:self.loading=False;self.update_actions()
        return True

    def open_project(self,checked=False,path=None,recovery=False):
        """Open a project (or a recovery snapshot / backup) and restore its surveys, settings and comparisons.

        The file is fully read and checked before the current project is replaced.

        Parameters
        ----------
        checked : bool, optional
            Ignored (sent by the menu action).
        path : str or pathlib.Path, optional
            File to open; asks when not given.
        recovery : bool, optional
            Open as an unsaved recovery (must be saved with Save Project As).

        Returns
        -------
        bool
            True if opened.
        """
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
            w.sessions=sessions
            w.select_file.blockSignals(True)
            for i,session in enumerate(sessions):w.select_file.addItem(Path(session.path).name,session.path)
            active=manifest['active'];w.select_file.setCurrentIndex(-1 if active is None else active);w.select_file.blockSignals(False)
            if active is not None:w.activate_survey(active)
            c=w.filters_workspace.comparisons;c.slots=comparisons;c.session_key=c.key();c.next_index=0;c.refresh_library()
            selected=set(manifest['settings'].get('comparison_checked',list(comparisons)[:3]))
            c.library.blockSignals(True)
            for i in range(c.library.count()):c.library.item(i).setCheckState(Qt.CheckState.Checked if c.library.item(i).data(Qt.ItemDataRole.UserRole) in selected else Qt.CheckState.Unchecked)
            c.library.blockSignals(False);c.draw()
            c.message.setText(f'Restored {len(comparisons)} stored filter result(s) from the project.' if comparisons else
                              'No stored results yet. Apply a filter, then click Store filter results for comparison.')
            form=manifest['settings'].get('filter_form',{});lab=w.filters_workspace
            view=manifest['settings'].get('filter_view',{})
            lab.show_before.setChecked(view.get('before',False));lab.show_difference.setChecked(view.get('difference',False))
            lab.plot_views.setCurrentText(view.get('plots','Map only') if lab.plot_views.findText(view.get('plots',''))>=0 else 'Map only')
            if form:
                lab.method.setCurrentText(form['method']);lab.field.setCurrentIndex(max(0,lab.field.findData(form['field']) if lab.field.findData(form['field'])>=0 else lab.field.findText(form['field'])));lab.domain.setCurrentText(form['domain'])
                saved_date=QDate.fromString(form.get('survey_date',''),Qt.DateFormat.ISODate)
                if saved_date.isValid():lab.survey_date.setDate(saved_date)
                for key,control in [('window',lab.window_length),('low',lab.low),('high',lab.high),('k_modes',lab.k),('alpha',lab.alpha),('cell_size',lab.cell),('height',lab.height),('max_gain',lab.gain),('inclination',lab.inc),('declination',lab.dec)]:
                    if key in form['parameters']:control.setValue(form['parameters'][key])
            signal=manifest['settings'].get('signal_column');picker=w.data_workspace.column_picker
            index=picker.findData(signal)
            if index>=0:picker.setCurrentIndex(index)
            # Colour scales and Location Estimate map type (older projects keep the defaults).
            for combo,key in [(w.data_workspace.map_colors,'map_colormap'),(w.location_colors,'location_colormap'),
                              (w.filters_workspace.map_colors,'filter_colormap')]:
                index=combo.findData(manifest['settings'].get(key))
                if index>=0:combo.setCurrentIndex(index)
            index=w.location_map_type.findText(manifest['settings'].get('location_map_type',''))
            if index>=0:w.location_map_type.setCurrentIndex(index)
            w.tabs.setCurrentIndex(manifest['settings'].get('main_tab',0))
            self.metadata=manifest['metadata'];self.recovered=recovery
            # Projects saved without a title are shown by their file name (recovery files have no meaningful name).
            if not self.metadata.get('title','').strip() or self.metadata['title']==UNTITLED:
                stored=project_name_from_path(path)
                self.metadata['title']=UNTITLED if stored.startswith('recovery-') else stored
            self.path=None if recovery else Path(path);self.dirty=recovery;self.project_active=True
            self.w.statusBar().showMessage('Recovery opened; use Save Project As to retain it.' if recovery else 'Project opened: '+Path(path).name)
        finally:self.loading=False;self.update_actions();self.connect_canvases()
        return True

    def history(self,redo):
        """Edit > Undo / Redo Applied Filter.

        Parameters
        ----------
        redo : bool
            Redo instead of undo.

        Returns
        -------
        bool
            True if the current field changed.
        """
        session=self.w.active_session()
        if session is None:return False
        result=session.redo_field() if redo else session.undo_field()
        if result:self.w.activate_survey(self.w.active_dataset_index);self.changed()
        return result

    def recalculate(self):
        """Tools > Recalculate Analysis: re-clean if the settings changed and rerun the analysis from scratch."""
        session=self.w.active_session()
        if session is None:return
        self.w.analysis_update_timer.stop()
        try:
            changed=session.ensure_cleaned(self.w.analysis_params())
            session.mode_cache.clear()
            if changed:self.w.activate_survey(self.w.active_dataset_index)
            else:self.w.run_anomaly_analysis()
            if self.w.analysis_summary_data:self.w.statusBar().showMessage('Analysis recalculated from the selected input.')
        except Exception as exc:QMessageBox.warning(self.w,'Recalculate Analysis',str(exc))
        self.changed()

    def properties(self):
        """File > Current Project Properties: edit the title, author and notes; show units and coordinate system."""
        dialog=QDialog(self.w);dialog.setWindowTitle('Project Properties');layout=QVBoxLayout(dialog);form=QFormLayout()
        title=QLineEdit(self.metadata['title']);author=QLineEdit(self.metadata.get('author',''));notes=QTextEdit(self.metadata.get('notes',''))
        form.addRow('Project Title',title);form.addRow('Author',author);form.addRow('Notes',notes)
        session=self.w.active_session()
        unit=session.field_unit if session is not None else labels.display_unit()
        coordinates=coords.FORMATS.get((session.coordinates if session is not None else {}).get('format','decimal_degrees'),'Decimal degrees')
        form.addRow('Units',QLabel(f'Magnetic field: {labels.UNIT_NAMES.get(unit,unit)} ({unit}) | Coordinates: {coordinates} | Position: metres | Time: seconds'))
        form.addRow('Surveys',QLabel(str(len(self.w.sessions))))
        form.addRow('Coordinate System',QLabel('UTM EPSG '+str(int(session.cleaned['UTM_EPSG'].iloc[0])) if session is not None else 'Determined when a survey is imported'))
        layout.addLayout(form);buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec():self.metadata.update(title=title.text().strip() or UNTITLED,author=author.text(),notes=notes.toPlainText());self.changed()

    def backups(self):
        """File > Current Project Backups: open one of the project's .bak files."""
        paths=[Path(str(self.path)+f'.bak{i}') for i in range(1,4)] if self.path else []
        self.choose_snapshot([p for p in paths if p.exists()],'Project Backups',recovery=True)

    def recover(self):
        """File > Recover Project: open an automatic recovery snapshot."""
        self.choose_snapshot(sorted(self.recovery_dir.glob('recovery-*.smmproj'),key=lambda p:p.stat().st_mtime,reverse=True) if self.recovery_dir.exists() else [],'Recover Project',recovery=True)

    def choose_snapshot(self,paths,title,recovery=True):
        """List project snapshots and open the chosen one.

        Parameters
        ----------
        paths : list of pathlib.Path
            Snapshot files, newest first.
        title : str
            Dialog title.
        recovery : bool, optional
            Open as an unsaved recovery.
        """
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
        """Save a recovery snapshot of unsaved work (keeps the five newest per project).

        Returns
        -------
        bool
            True if a snapshot was written.
        """
        if self.loading or not self.auto_enabled or not self.dirty or not self.w.sessions:return False
        try:
            self.recovery_dir.mkdir(parents=True,exist_ok=True)
            name='recovery-'+self.metadata['id']+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.smmproj'
            path=self.recovery_dir/name;self.save_to(path,backup=False)
            snapshots=sorted(self.recovery_dir.glob('recovery-'+self.metadata['id']+'-*.smmproj'),key=lambda p:p.stat().st_mtime,reverse=True)
            for old in snapshots[5:]:old.unlink()
            self.w.statusBar().showMessage('Project recovery snapshot saved.');return True
        except Exception as exc:self.w.statusBar().showMessage('Recovery snapshot failed: '+str(exc));return False

    def settings(self):
        """Tools > Settings: table decimal places, automatic recovery, snapshot interval and recovery folder."""
        dialog=QDialog(self.w);dialog.setWindowTitle('Application Settings');layout=QVBoxLayout(dialog);form=QFormLayout()
        precision=QSpinBox();precision.setRange(0,8);precision.setValue(self.precision)
        auto=QCheckBox('Save recovery snapshots for unsaved work');auto.setChecked(self.auto_enabled)
        minutes=QSpinBox();minutes.setRange(1,30);minutes.setValue(self.interval);minutes.setSuffix(' min')
        folder=QLineEdit(str(self.recovery_dir));browse=QPushButton('Browse...');row=QHBoxLayout();row.addWidget(folder);row.addWidget(browse)
        def choose():
            """Browse for the recovery folder."""
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
        """Connect plot canvases (grid, view reset, distance tool) when they are first shown.

        Parameters
        ----------
        obj : QObject
            Object receiving the event.
        event : QEvent
            The event.

        Returns
        -------
        bool
            Always False, so the event is handled normally.
        """
        if event.type()==QEvent.Type.Show and isinstance(obj,FigureCanvasQTAgg) and obj.window() is self.w:self.hook_canvas(obj)
        return False

    def hook_canvas(self,canvas):
        """Connect a plot canvas once: remember its initial view, apply the grid setting, and route clicks to the
        distance tool.

        Parameters
        ----------
        canvas : FigureCanvasQTAgg
            Canvas to connect.
        """
        if id(canvas) in self.connected:return
        self.connected.add(id(canvas))
        def on_draw(event):
            """Remember each new axes' initial limits and keep the grid setting after redraws.

            Parameters
            ----------
            event : matplotlib.backend_bases.DrawEvent
                Draw event.
            """
            for axis in canvas.figure.axes:
                if axis not in self.view_hooks:self.view_hooks[axis]=(axis.get_xlim(),axis.get_ylim())
            if self.apply_grid(canvas):canvas.draw_idle()
        canvas.mpl_connect('draw_event',on_draw);canvas.mpl_connect('button_press_event',self.measure_click);self.apply_grid(canvas)

    def connect_canvases(self):
        """Connect every plot canvas in the window."""
        for canvas in self.w.findChildren(FigureCanvasQTAgg):self.hook_canvas(canvas)

    def apply_grid(self,canvas):
        """Show or hide the grid on a canvas's plots (colour bars are skipped).

        Parameters
        ----------
        canvas : FigureCanvasQTAgg
            Canvas.

        Returns
        -------
        bool
            True if any axes changed.
        """
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
        """View > Show Plot Grid.

        Parameters
        ----------
        checked : bool
            Show the grid.
        """
        self.grid=checked;self.preferences.setValue('plot_grid',checked);self.connect_canvases()
        for canvas in self.w.findChildren(FigureCanvasQTAgg):self.apply_grid(canvas);canvas.draw_idle()

    def measure_targets(self):
        """Maps the distance tool can measure on now (the cleaning map or the location map, in metres).

        Returns
        -------
        list of matplotlib.axes.Axes
            Axes on screen that use metric coordinates.
        """
        w=self.w
        if w.tabs.currentWidget() is w.data_workspace and w.data_workspace.tabs.currentIndex()==0:return w.data_workspace.figure.axes[:1] if w.data_workspace.canvas.isVisible() else []
        if w.tabs.currentIndex()==3 and w.location_views.currentIndex()==0:return w.analysis_cluster_figure.axes[:1]
        return []

    def enable_measure(self,checked):
        """Tools > Measure Map Distance: turn the distance tool on (leaving pan/zoom) or off (removing its marks).

        Parameters
        ----------
        checked : bool
            Turn the tool on.
        """
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
        """Distance tool click: the first click sets a point, the second draws the line and shows the distance.

        Parameters
        ----------
        event : matplotlib.backend_bases.MouseEvent
            Mouse click.
        """
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
        """View > Reset Plot View: restore the original limits of the plot on screen."""
        for toolbar in self.w.findChildren(NavigationToolbar2QT):
            if toolbar.isVisible():toolbar.home();return
        for canvas in self.w.findChildren(FigureCanvasQTAgg):
            if canvas.isVisible():
                for ax in canvas.figure.axes:
                    if getattr(ax,'_colorbar',None) is None and ax in self.view_hooks:
                        xlim,ylim=self.view_hooks[ax];ax.set_xlim(xlim);ax.set_ylim(ylim)
                canvas.draw_idle();return
