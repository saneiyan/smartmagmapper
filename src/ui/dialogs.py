"""Import Data and Export Data dialogs."""
from PyQt6.QtWidgets import (QPushButton, QDialog,QDialogButtonBox,
                             QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QFileDialog, QCheckBox, QRadioButton, QComboBox,
                             QButtonGroup, QTableView, QHeaderView,
                             QMessageBox, QGroupBox, QFormLayout, QDoubleSpinBox)
from PyQt6.QtGui import QFont
import os
import re
from pathlib import Path
from ui import table_model as TableModel
import pandas as pd
from processing import data_analysis_pipeline as dap
from ui.confirm import confirm
from processing import labels, coordinates as co

class CustomDialog(QDialog):
   """Import Data dialog: choose a survey file, its magnetic, coordinate and time columns, the magnetic unit
   and the coordinate format.

   Column choices, the unit and the coordinate format are suggested from the file's headers and values.

   Parameters
   ----------
   parent : QWidget, optional
       Main window (the dialog opens above it).
   """
   def __init__(self, parent=None):
        """Build the file, magnetic field, coordinate and time sections and the preview table."""
        super().__init__(parent)

        #sets the title for the pop up dialog window
        self.setWindowTitle("Import magnetic survey")

        #creates the layouts for the window
        self.layout = QVBoxLayout()
        self.sub_layout = QHBoxLayout()
        self.button_layout = QHBoxLayout()
        self.mag_layout = QHBoxLayout()
        self.coordinates_layout = QHBoxLayout()
        self.time_layout = QHBoxLayout()
        self.single_time_layout = QHBoxLayout()

        bold = QFont()
        bold.setBold(True)

        #Buttons to apply file settings or cancel; the main window connects OK to its import handler,
        #which closes the dialog only when the import succeeds
        self.FinishBtn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                QDialogButtonBox.StandardButton.Cancel)
        self.FinishBtn.rejected.connect(self.reject)

        #Text box for File Name
        self.FileName = QLineEdit()
        self.FileName.setReadOnly(True)
        self.FileNameLabel = QLabel('File Name')

        #Opens system file dialog selector
        self.FileDialog = QPushButton('Select File')
        self.FileDialog.clicked.connect(self.select_file)

        #creating independent button group for magnetic field data type
        self.MagDataTypeLabel = QLabel('Magnetic Field Data')
        #Making the header bold
        self.MagDataTypeLabel.setFont(bold)
        self.MagButtonGroup = QButtonGroup()
        #User checks if the mag data is vector or scalar
        self.VectorMag = QRadioButton('Vector')
        self.VectorMag.toggled.connect(self.toggle_vector)
        self.ScalarMag = QRadioButton('Scalar')
        self.ScalarMag.toggled.connect(self.toggle_scalar)
        #adding the two buttons to the magnetic field data type button group
        self.MagButtonGroup.addButton(self.VectorMag)
        self.MagButtonGroup.addButton(self.ScalarMag)
        # Unit of the magnetic values as recorded (values are kept as they are; the unit labels them everywhere).
        self.MagUnitLabel = QLabel('Unit:')
        self.MagUnit = QComboBox()
        for unit, name in labels.UNIT_NAMES.items():
            self.MagUnit.addItem(f'{unit} ({name})', unit)
        self.MagUnit.setCurrentIndex(self.MagUnit.findData(labels.DEFAULT_UNIT))
        self.MagUnit.setToolTip('Unit of the magnetic values in the file. Values are kept as recorded and every label shows this unit.\n'
                                'It is filled in automatically when the column headers state the unit, e.g. "X (nT)".')

        #showing 5 samples rows of data
        self.SampleData = QTableView()
        self.SampleLabel = QLabel('Preview Data')
        #Making the header bold
        self.SampleLabel.setFont(bold)

        #User selects the x direction of magnetic field
        self.XMagField = QComboBox()
        self.XMagField.setPlaceholderText('Select X column')

        #User selects the y direction of magnetic field
        self.YMagField = QComboBox()
        self.YMagField.setPlaceholderText('Select Y column')

        #User selects the z direction of magnetic field
        self.ZMagField = QComboBox()
        self.ZMagField.setPlaceholderText('Select Z column')

        #User selects TMI of magnetic field
        self.TotalMagField = QComboBox()
        self.TotalMagField.setPlaceholderText('Select total magnetic field (BT) column')

        #creating header for coordinate subsection
        self.CoordinatesHeader = QLabel('Coordinates')
        #making header bold
        self.CoordinatesHeader.setFont(bold)
        #User selects the x direction of coordinates
        self.XLatitude = QComboBox()
        self.XLatitude.setPlaceholderText('Select Latitude')
        #User selects the y direction of coordinates
        self.YLongitude = QComboBox()
        self.YLongitude.setPlaceholderText('Select Longitude')
        # How the coordinates are written; everything is converted to decimal degrees for maps and analysis.
        self.CoordFormatLabel = QLabel('Format:')
        self.CoordFormat = QComboBox()
        for key, name in co.FORMATS.items():
            self.CoordFormat.addItem(name, key)
        self.CoordFormat.setToolTip('How the coordinates in the file are written. They are converted to decimal degrees for maps and\n'
                                    'analysis; the original values are kept in the Raw GPS table and exports.')
        self.EPSG = QLineEdit()
        self.EPSG.setPlaceholderText('EPSG, e.g. 32618')
        self.EPSG.setToolTip('EPSG code of the projected coordinate system (UTM zone N: 326 + zone, UTM zone S: 327 + zone).')
        self.EPSG.hide()
        self.CoordFormat.currentIndexChanged.connect(self.coordinate_format_changed)

        #creating header for time subsection
        self.TimeHeader = QLabel('Time')
        #making header bold
        self.TimeHeader.setFont(bold)
        self.TimeButtonGroup = QButtonGroup()
        #User checks if the magnetometer and GPS share one time column or have their own
        self.ComboTime = QRadioButton('Independent sensor timestamps')
        self.ComboTime.toggled.connect(self.toggle_combo_time)
        self.SingleTime = QRadioButton('Shared sensor timestamps')
        self.SingleTime.toggled.connect(self.toggle_single_time)
        #adding the two buttons to the time button group
        self.TimeButtonGroup.addButton(self.ComboTime)
        self.TimeButtonGroup.addButton(self.SingleTime)

        #User selects the time of data
        self.TotalTime = QComboBox()
        self.TotalTime.setPlaceholderText('Select Time (sec)')
        self.MagTime = QComboBox()
        self.MagTime.setPlaceholderText('Select Magnetic Time (sec)')
        self.LocTime = QComboBox()
        self.LocTime.setPlaceholderText('Select GPS Time (sec)')

        #adding widgets to the first section of the dialog box
        self.sub_layout.addWidget(self.FileNameLabel)
        self.sub_layout.addWidget(self.FileName)
        self.sub_layout.addWidget(self.FileDialog)
        self.layout.addLayout(self.sub_layout)

        #magnetic field data type and unit
        self.layout.addWidget(self.MagDataTypeLabel)
        self.mag_layout.addWidget(self.VectorMag)
        self.mag_layout.addWidget(self.ScalarMag)
        self.mag_layout.addSpacing(24)
        self.mag_layout.addWidget(self.MagUnitLabel)
        self.mag_layout.addWidget(self.MagUnit, 1)
        self.VectorMag.setChecked(True)
        self.layout.addLayout(self.mag_layout)

        #magnetic and time column selectors
        self.button_layout.addWidget(self.XMagField)
        self.button_layout.addWidget(self.YMagField)
        self.button_layout.addWidget(self.ZMagField)
        self.time_layout.addWidget(self.MagTime)
        self.time_layout.addWidget(self.LocTime)

        #sets the layout for the widgets in the dialog box
        self.layout.addLayout(self.button_layout)
        self.layout.addWidget(self.TotalMagField)
        self.layout.addWidget(self.CoordinatesHeader)
        coord_format_layout = QHBoxLayout()
        coord_format_layout.addWidget(self.CoordFormatLabel)
        coord_format_layout.addWidget(self.CoordFormat, 1)
        coord_format_layout.addWidget(self.EPSG, 1)
        self.layout.addLayout(coord_format_layout)
        self.coordinates_layout.addWidget(self.XLatitude)
        self.coordinates_layout.addWidget(self.YLongitude)
        self.layout.addLayout(self.coordinates_layout)
        self.layout.addWidget(self.TimeHeader)
        self.single_time_layout.addWidget(self.SingleTime)
        self.single_time_layout.addWidget(self.ComboTime)
        self.ComboTime.setChecked(True)
        self.layout.addLayout(self.single_time_layout)
        self.layout.addLayout(self.time_layout)
        self.layout.addWidget(self.TotalTime)

        #sets the sample data table widget in the dialog box
        self.layout.addWidget(self.SampleLabel)
        self.layout.addWidget(self.SampleData)

        #adding the dialog box action buttons to the bottom of the box
        self.layout.addWidget(self.FinishBtn)
        #setting the main layout to the dialog box
        self.setLayout(self.layout)

   def reject(self):
       # Cancel, Esc and the window's close button all come through here.
       """Cancel, Esc or the close button: close only after the user confirms."""
       name = os.path.basename(self.FileName.text()) or 'this survey'
       if confirm(self, 'Cancel Import', f'Are you sure you would like to cancel importing {name}?',
                  'The file and column selections in this window will be lost.',
                  yes_text='Cancel Import', no_text='Keep Editing'):
           super().reject()

   def select_file(self):
       """Choose a survey file and read its columns."""
       path, _ = QFileDialog.getOpenFileName(self, 'Import survey', '',
           'Survey files (*.csv *.txt *.xls *.xlsx *.xlsm)')
       if not path:
           return
       self.file_paths = [path]
       self.FileName.setText(path)
       try:
           self.read_file()
       except Exception as exc:
           self.file_paths = []
           self.raw_file = None
           QMessageBox.warning(self, 'Survey import', str(exc))

   def read_file(self):
        # read raw file and import the column headers into the drop-down menus
        """Read the selected file and fill the column dropdowns (Excel sheets are placed side by side)."""
        if not getattr(self, 'file_paths', None):
            return

        path = self.file_paths[0]
        ext = os.path.splitext(path)[1].lower()

        # read CSV-like files (try to infer separator, fallback to default)
        if ext in ('.csv', '.txt'):
            try:
                df = pd.read_csv(path, sep=None, engine='python', encoding='utf-8')
            except Exception:
                df = pd.read_csv(path)

        # read Excel files (concatenate all sheets)
        elif ext in ('.xls', '.xlsx', '.xlsm'):
            df = pd.concat(pd.read_excel(path, sheet_name=None), axis=1)
            # flatten MultiIndex columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = ['_'.join(map(str, col)).strip() for col in df.columns.values]

        # fallback: try CSV then Excel
        else:
            try:
                df = pd.read_csv(path)
            except Exception:
                df = pd.concat(pd.read_excel(path, sheet_name=None), axis=1)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = ['_'.join(map(str, col)).strip() for col in df.columns.values]

        self.raw_file = df
        columns = list(self.raw_file.columns)

        # clear combo boxes before populating to avoid duplicates
        for combo in (self.XMagField, self.YMagField, self.ZMagField,
                      self.XLatitude, self.YLongitude, self.TotalMagField,
                      self.MagTime, self.LocTime, self.TotalTime):
            combo.clear()

        for column in columns:
            for combo in (self.XMagField, self.YMagField, self.ZMagField,
                          self.XLatitude, self.YLongitude, self.TotalMagField,
                          self.MagTime, self.LocTime, self.TotalTime):
                combo.addItem(str(column))

        for combo in (self.XMagField, self.YMagField, self.ZMagField,
                      self.XLatitude, self.YLongitude, self.TotalMagField,
                      self.MagTime, self.LocTime, self.TotalTime):
            combo.setCurrentIndex(-1)
        self.suggest_columns()
        self.sample_data()


   def coordinate_format_changed(self, *_):
       """Show the EPSG box for projected coordinates and suggest matching coordinate columns.

       Parameters
       ----------
       *_ : object
           Ignored signal arguments.
       """
       projected = self.CoordFormat.currentData() == 'projected'
       self.EPSG.setVisible(projected)
       self.XLatitude.setPlaceholderText('Select Easting (m)' if projected else 'Select Latitude')
       self.YLongitude.setPlaceholderText('Select Northing (m)' if projected else 'Select Longitude')
       if getattr(self, 'raw_file', None) is not None:
           first, second = ((['easting', 'east', 'utm_e', 'utme'], ['northing', 'north', 'utm_n', 'utmn']) if projected else
                            (['Location_Latitude (degree)', 'latitude', 'lat'], ['Location_Longitude (degree)', 'longitude', 'lon']))
           for combo, aliases in ((self.XLatitude, first), (self.YLongitude, second)):
               found = dap._find_column(self.raw_file, aliases, required=False)
               combo.setCurrentIndex(combo.findText(str(found)) if found is not None else -1)

   def suggest_unit(self, *_):
       """Use the unit written in the chosen magnetic columns' headers, e.g. 'X (nT)', if there is one.

       Parameters
       ----------
       *_ : object
           Ignored signal arguments.
       """
       combos = (self.XMagField, self.YMagField, self.ZMagField) if self.VectorMag.isChecked() else (self.TotalMagField,)
       unit = labels.detect_unit(*[combo.currentText() for combo in combos if combo.currentIndex() >= 0])
       if unit is not None:
           self.MagUnit.setCurrentIndex(self.MagUnit.findData(unit))

   def suggest_coordinate_format(self):
       """Guess degrees + minutes or DMS when the latitude column holds text such as 45°07'24.4"N."""
       if self.XLatitude.currentIndex() < 0:
           return
       column = self.raw_file[self.XLatitude.currentText()].dropna()
       if column.empty or pd.api.types.is_numeric_dtype(column):
           return
       parts = len(co._NUMBER.findall(str(column.iloc[0])))
       guess = {2: 'degrees_minutes', 3: 'dms'}.get(parts)
       if guess is not None:
           self.CoordFormat.setCurrentIndex(self.CoordFormat.findData(guess))

   def suggest_columns(self):
       """Pre-select columns whose headers look like magnetic components, total field, coordinates and times,
       then suggest the data type, time layout, unit and coordinate format.
       """
       def choose(combo, aliases):
           """Select the first column matching one of the aliases.

           Parameters
           ----------
           combo : QComboBox
               Column dropdown.
           aliases : list of str
               Accepted header names.
           """
           found = dap._find_column(self.raw_file, aliases, required=False)
           if found is not None:
               combo.setCurrentText(str(found))
       for combo, aliases in [
           # headers in any unit, e.g. 'X', 'X (nT)', 'Magnetometer_X (uT)'
           (self.XMagField, ['X'] + [f'X ({unit})' for unit in dap._UNIT_TAGS] + ['Magnetometer_X (uT)', 'BX']),
           (self.YMagField, ['Y'] + [f'Y ({unit})' for unit in dap._UNIT_TAGS] + ['Magnetometer_Y (uT)', 'BY']),
           (self.ZMagField, ['Z'] + [f'Z ({unit})' for unit in dap._UNIT_TAGS] + ['Magnetometer_Z (uT)', 'BZ']),
           (self.TotalMagField, ['BT'] + [f'BT ({unit})' for unit in dap._UNIT_TAGS] + ['Total_Field_uT', 'Total magnetic field (uT)']),
           (self.XLatitude, ['Location_Latitude (degree)', 'latitude', 'lat']),
           (self.YLongitude, ['Location_Longitude (degree)', 'longitude', 'lon']),
           (self.MagTime, ['Magnetometer_Time (s)', 'Mag_Time (s)', 'Time (s)']),
           (self.LocTime, ['Location_Time (s)', 'Loc_Time (s)', 'Time (s)']),
           (self.TotalTime, ['Time (s)', 'time']),
       ]:
           choose(combo, aliases)
       if all(combo.currentIndex() >= 0 for combo in (self.XMagField, self.YMagField, self.ZMagField)):
           self.VectorMag.setChecked(True)
       elif self.TotalMagField.currentIndex() >= 0:
           self.ScalarMag.setChecked(True)
       if self.MagTime.currentText() == self.LocTime.currentText() and self.MagTime.currentIndex() >= 0:
           self.SingleTime.setChecked(True)
           self.TotalTime.setCurrentText(self.MagTime.currentText())
       self.suggest_unit()
       self.suggest_coordinate_format()
       for combo in (self.XMagField, self.YMagField, self.ZMagField, self.TotalMagField):
           try:
               combo.currentIndexChanged.disconnect(self.suggest_unit)
           except TypeError:
               pass
           combo.currentIndexChanged.connect(self.suggest_unit)

   def build_streams(self):
       """Build the magnetometer and GPS streams from the dialog choices.

       Coordinates are converted to decimal degrees; the original columns are kept in the GPS stream. The unit and
       coordinate format are stored in `import_settings`.

       Returns
       -------
       mag : pandas.DataFrame
           'Mag_Time (s)' with X, Y, Z (vector) or BT (scalar), unit-free.
       gps : pandas.DataFrame
           'Loc_Time (s)', 'Latitude (°)', 'Longitude (°)' and the original coordinate columns.

       Raises
       ------
       ValueError
           If no file is selected, a column is missing or chosen twice, or the coordinates cannot be converted.
       """
       if not getattr(self, 'file_paths', None) or getattr(self, 'raw_file', None) is None:
           raise ValueError('Select a survey file first.')
       def selected(combo):
           """Column chosen in a dropdown.

           Parameters
           ----------
           combo : QComboBox
               Column dropdown.

           Returns
           -------
           str
               Column name.

           Raises
           ------
           ValueError
               If nothing valid is selected.
           """
           text = combo.currentText()
           if combo.currentIndex() < 0 or text not in self.raw_file.columns:
               raise ValueError('Assign all required magnetic, coordinate, and time fields.')
           return text
       mag_time = selected(self.TotalTime if self.SingleTime.isChecked() else self.MagTime)
       gps_time = selected(self.TotalTime if self.SingleTime.isChecked() else self.LocTime)
       magnetic_columns = [selected(combo) for combo in
                           ((self.XMagField, self.YMagField, self.ZMagField) if self.VectorMag.isChecked()
                            else (self.TotalMagField,))]
       if self.VectorMag.isChecked() and len(set(magnetic_columns)) != 3:
           raise ValueError('Assign a different column to each magnetic component.')
       lat, lon = selected(self.XLatitude), selected(self.YLongitude)
       if lat == lon:
           raise ValueError('The two coordinate columns must be different.')
       mag = self.raw_file[[mag_time] + magnetic_columns].copy()
       # Unit-free column names; the unit is kept with the survey (import_settings).
       mag.columns = ['Mag_Time (s)'] + (['X', 'Y', 'Z'] if self.VectorMag.isChecked() else ['BT'])
       fmt = self.CoordFormat.currentData()
       epsg = self.EPSG.text().strip() or None
       latitude, longitude = co.to_decimal_degrees(self.raw_file[lat], self.raw_file[lon], fmt, epsg)
       gps = pd.DataFrame({'Loc_Time (s)': self.raw_file[gps_time].to_numpy(),
                           'Latitude (°)': latitude, 'Longitude (°)': longitude})
       # Keep the coordinates exactly as recorded alongside the converted decimal degrees.
       if fmt == 'projected':
           gps[f'Easting (m, EPSG:{epsg})'] = self.raw_file[lat].to_numpy()
           gps[f'Northing (m, EPSG:{epsg})'] = self.raw_file[lon].to_numpy()
       elif fmt != 'decimal_degrees':
           gps[f'Latitude (original, {co.FORMATS[fmt]})'] = self.raw_file[lat].to_numpy()
           gps[f'Longitude (original, {co.FORMATS[fmt]})'] = self.raw_file[lon].to_numpy()
       self.import_settings = {'field_unit': self.MagUnit.currentData(),
                               'coordinates': {'format': fmt, 'epsg': int(epsg) if epsg else None, 'columns': [lat, lon]}}
       return mag, gps

   def sample_data(self):
       """Show the file in the preview table."""
       self.model = TableModel.TableModel(self.raw_file)
       self.SampleData.setModel(self.model)
       header = self.SampleData.horizontalHeader()
       header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

   def toggle_vector(self):
       """Vector data: enable the X, Y, Z column choices."""
       self.TotalMagField.setEnabled(False)
       self.XMagField.setEnabled(True)
       self.YMagField.setEnabled(True)
       self.ZMagField.setEnabled(True)

   def toggle_scalar(self):
       """Scalar data: enable the total field column choice."""
       self.TotalMagField.setEnabled(True)
       self.XMagField.setEnabled(False)
       self.YMagField.setEnabled(False)
       self.ZMagField.setEnabled(False)

   def toggle_combo_time(self):
       """Independent timestamps: enable the magnetometer and GPS time columns."""
       self.TotalTime.setEnabled(False)
       self.MagTime.setEnabled(True)
       self.LocTime.setEnabled(True)

   def toggle_single_time(self):
       """Shared timestamps: enable the single time column."""
       self.TotalTime.setEnabled(True)
       self.MagTime.setEnabled(False)
       self.LocTime.setEnabled(False)

class DataExportDialog(QDialog):
    """Choose what File > Export Data writes: data tables, map and signal-plot figures, and a GeoTIFF raster.

    The dialog only collects choices and builds the output file names; the main window writes the files.

    Parameters
    ----------
    parent : QWidget
        Main window.
    base_path : pathlib.Path
        Suggested folder and base name; every file starts with it.
    signal_plots : list of tuple
        (tab index, title) of the open signal plots.
    current_signal_plot : int
        Signal plot ticked by default.
    map_stage : int
        Cleaning stage ticked by default (0 before, 1 after cleaning).
    map_style : str
        Map type shown on screen.
    has_filter : bool
        Whether a filter result is stored (enables the current-field exports, the default GeoTIFF dataset).
    fields : list of tuple
        (label, column) of the magnetic field columns.
    current_field : str
        Column shown on the cleaning map.
    raster_available : bool
        Whether rasterio is installed.
    kriging_available : bool
        Whether pykrige is installed.
    default_cell_size : float
        Suggested GeoTIFF cell size in metres.
    """
    STAGES = [('synchronized', 'Synchronized Data (Before Cleaning)'), ('cleaned', 'Cleaned Data (After Cleaning)')]
    INTERPOLATION = [('linear', 'Linear'), ('cubic', 'Cubic'), ('nearest', 'Nearest neighbour'), ('idw', 'Inverse distance (IDW)')]

    def __init__(self, parent, base_path, *, signal_plots, current_signal_plot, map_stage, map_style,
                 has_filter, fields, current_field, raster_available, kriging_available, default_cell_size):
        """Build the destination, data table, figure and GeoTIFF sections (see the class description)."""
        super().__init__(parent)
        self.setWindowTitle('Export Data')
        layout = QVBoxLayout(self)

        # where the files go: a folder plus a base name that every file starts with
        destination = QHBoxLayout()
        self.base = QLineEdit(str(base_path))
        self.base.setToolTip('Folder and base name. Every exported file starts with this name.')
        browse = QPushButton('Browse...')
        browse.clicked.connect(self.choose_base)
        destination.addWidget(QLabel('Save as:'))
        destination.addWidget(self.base, 1)
        destination.addWidget(browse)
        layout.addLayout(destination)

        tables = QGroupBox('Data tables (CSV)')
        tables_layout = QVBoxLayout(tables)
        self.csv_choices = {}
        for key, label, enabled in [('cleaned', 'Cleaned Data (After Cleaning)', True),
                                    ('synchronized', 'Synchronized Data (Before Cleaning)', True),
                                    ('current', 'Current field (with applied filters)', has_filter)]:
            box = QCheckBox(label)
            box.setChecked(key == 'cleaned')
            box.setEnabled(enabled)
            if not enabled:
                box.setToolTip('Apply a filter in the Filter Lab to export a filtered field.')
            tables_layout.addWidget(box)
            self.csv_choices[key] = box
        layout.addWidget(tables)

        figures = QGroupBox('Figures')
        figures_layout = QFormLayout(figures)
        self.map_choices = {}
        maps = QVBoxLayout()
        for index, (key, label) in enumerate(self.STAGES):
            box = QCheckBox(label)
            box.setChecked(index == map_stage)
            maps.addWidget(box)
            self.map_choices[index] = (key, box)
        figures_layout.addRow('Cleaning maps:', maps)
        self.map_style = QComboBox()
        self.map_style.addItems(['Scatter Plot', 'Contour Plot'])
        self.map_style.setCurrentText(map_style if map_style in ('Scatter Plot', 'Contour Plot') else 'Scatter Plot')
        figures_layout.addRow('Map type:', self.map_style)
        signals = QVBoxLayout()
        self.signal_choices = {}
        for key, label in signal_plots:
            box = QCheckBox(label)
            box.setChecked(key == current_signal_plot)
            signals.addWidget(box)
            self.signal_choices[key] = (label, box)
        if not signal_plots:
            signals.addWidget(QLabel('No signal plots are open.'))
        figures_layout.addRow('Signal plots:', signals)
        self.figure_format = QComboBox()
        self.figure_format.addItem('PNG image (300 dpi)', 'png')
        self.figure_format.addItem('PDF (vector)', 'pdf')
        figures_layout.addRow('Format:', self.figure_format)
        layout.addWidget(figures)

        self.raster = QGroupBox('Georeferenced raster (GeoTIFF)')
        self.raster.setCheckable(True)
        self.raster.setChecked(False)
        raster_form = QFormLayout(self.raster)
        self.raster_dataset = QComboBox()
        for key, label in self.STAGES:
            self.raster_dataset.addItem(label, key)
        if has_filter:
            self.raster_dataset.addItem('Current field (with applied filters)', 'current')
        # with a stored filter result, the processed field is the natural map to export
        self.raster_dataset.setCurrentIndex(self.raster_dataset.findData('current') if has_filter else 1)
        self.raster_field = QComboBox()
        self.raster_fields = fields
        self.raster_current_field = current_field
        self.raster_dataset.currentIndexChanged.connect(self.update_raster_fields)
        self.update_raster_fields()
        self.raster_method = QComboBox()
        for key, label in self.INTERPOLATION + ([('kriging', 'Ordinary kriging')] if kriging_available else []):
            self.raster_method.addItem(label, key)
        self.raster_cell = QDoubleSpinBox()
        self.raster_cell.setRange(0.01, 1000)
        self.raster_cell.setDecimals(2)
        self.raster_cell.setSuffix(' m')
        self.raster_cell.setValue(default_cell_size)
        self.raster_projection = QComboBox()
        self.raster_projection.addItem('UTM (survey zone, metres)', 'utm')
        self.raster_projection.addItem('WGS 84 (latitude / longitude)', 'wgs84')
        self.raster_output = QComboBox()
        self.raster_output.addItem('Field values (32-bit float, for GIS analysis)', 'values')
        self.raster_output.addItem('Coloured image (RGBA, current colour scale)', 'rgba')
        raster_form.addRow('Dataset:', self.raster_dataset)
        raster_form.addRow('Field:', self.raster_field)
        raster_form.addRow('Interpolation:', self.raster_method)
        raster_form.addRow('Cell size:', self.raster_cell)
        raster_form.addRow('Coordinate system:', self.raster_projection)
        raster_form.addRow('Raster content:', self.raster_output)
        layout.addWidget(self.raster)
        if not raster_available:
            self.raster.setEnabled(False)
            note = QLabel('GeoTIFF export needs the rasterio package (pip install rasterio).')
            note.setWordWrap(True)
            layout.addWidget(note)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.export_button = self.buttons.addButton('Export', QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        # keep the file list and the Export button in step with every choice
        for widget in [self.base, self.map_style, self.figure_format, self.raster_dataset, self.raster_field, self.raster_method,
                       self.raster_cell, self.raster_projection, self.raster_output]:
            signal = getattr(widget, 'textChanged', None) if isinstance(widget, QLineEdit) else (
                widget.valueChanged if isinstance(widget, QDoubleSpinBox) else widget.currentIndexChanged)
            signal.connect(self.update_summary)
        for box in list(self.csv_choices.values()) + [b for _, b in self.map_choices.values()] + [b for _, b in self.signal_choices.values()]:
            box.toggled.connect(self.update_summary)
        self.raster.toggled.connect(self.update_summary)
        self.update_summary()

    def update_raster_fields(self, *_):
        """Fill the raster Field list for the chosen dataset.

        Filters write their result to the total field (BT) only; the X, Y and Z columns of the current field are the
        unfiltered cleaned components, so they are not offered for it.

        Parameters
        ----------
        *_ : object
            Ignored signal arguments.
        """
        keep = self.raster_field.currentData() or self.raster_current_field
        current = self.raster_dataset.currentData() == 'current'
        self.raster_field.blockSignals(True)
        self.raster_field.clear()
        for label, column in self.raster_fields:
            if not current or column == 'BT':
                self.raster_field.addItem(label, column)
        self.raster_field.setCurrentIndex(max(0, self.raster_field.findData(keep)))
        self.raster_field.blockSignals(False)
        self.raster_field.setToolTip('The filter result is stored in the total field (BT).' if current else '')

    @staticmethod
    def slug(text):
        """File-name-safe version of a label.

        Parameters
        ----------
        text : str
            Label, e.g. 'BT (µT)'.

        Returns
        -------
        str
            For example 'BT_uT' ('field' if nothing is left).
        """
        return re.sub(r'[^A-Za-z0-9]+', '_', str(text).replace('\u00b5', 'u').replace('\u03bc', 'u')).strip('_') or 'field'

    def choose_base(self):
        """Browse for the export folder and base name."""
        path, _ = QFileDialog.getSaveFileName(self, 'Export Data: folder and base name', self.base.text(), 'All files (*)')
        if path:
            self.base.setText(str(Path(path).with_suffix('')))

    def options(self):
        """Selected exports with their output paths.

        Returns
        -------
        dict
            'csv': list of (dataset key, path); 'maps': list of (stage index, path); 'map_style'; 'signals': list of
            (tab index, path); 'figure_format' ('png' or 'pdf'); 'raster': GeoTIFF settings and path, or None.
        """
        base = Path(self.base.text().strip())
        ext = self.figure_format.currentData()
        named = lambda suffix: base.with_name(f'{base.name}_{suffix}')
        csv = [(key, named(f'{"current_field" if key == "current" else key}.csv'))
               for key, box in self.csv_choices.items() if box.isChecked() and box.isEnabled()]
        maps = [(index, named(f'map_{key}.{ext}')) for index, (key, box) in self.map_choices.items() if box.isChecked()]
        signals = [(key, named(f'signal_{self.slug(label)}.{ext}')) for key, (label, box) in self.signal_choices.items() if box.isChecked()]
        raster = None
        if self.raster.isEnabled() and self.raster.isChecked():
            dataset = self.raster_dataset.currentData()
            raster = {'dataset': dataset, 'field': self.raster_field.currentData(),
                      'method': self.raster_method.currentData(), 'cell_size': self.raster_cell.value(),
                      'projection': self.raster_projection.currentData(), 'output': self.raster_output.currentData(),
                      'path': named(f'raster_{dataset}_{self.slug(self.raster_field.currentData())}.tif')}
        return {'csv': csv, 'maps': maps, 'map_style': self.map_style.currentText(), 'signals': signals,
                'figure_format': ext, 'raster': raster}

    def update_summary(self, *_):
        """List the files that will be written and enable Export when there is at least one.

        Parameters
        ----------
        *_ : object
            Ignored signal arguments.
        """
        options = self.options()
        paths = ([p for _, p in options['csv']] + [p for _, p in options['maps']] + [p for _, p in options['signals']]
                 + ([options['raster']['path']] if options['raster'] else []))
        valid = bool(paths) and bool(self.base.text().strip())
        self.export_button.setEnabled(valid)
        if not paths:
            self.summary.setText('Select at least one item to export.')
        else:
            names = ', '.join(p.name for p in paths)
            self.summary.setText(f'{len(paths)} file(s) will be written to {Path(self.base.text().strip()).parent}:\n{names}')
