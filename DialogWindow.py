from PyQt6 import QtCore
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QPushButton, QDialog,QDialogButtonBox,
                             QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QFileDialog, QCheckBox, QRadioButton, QComboBox,
                             QButtonGroup, QGroupBox, QTableView, QHeaderView,
                             QMessageBox)
from PyQt6.QtGui import QFont
import TableModel
import pandas as pd

class CustomDialog(QDialog):
   def __init__(self, parent=None):
        super().__init__(parent)

        #sets the title for the pop up dialog window
        self.setWindowTitle("Add/Edit File")

        #creates the layouts for the window
        self.layout = QVBoxLayout()
        self.sub_layout = QHBoxLayout()
        self.button_layout = QHBoxLayout()
        self.layer_layout = QHBoxLayout()
        self.mag_layout = QHBoxLayout()
        self.coordinates_layout = QHBoxLayout()
        self.time_layout = QHBoxLayout()
        self.single_time_layout = QHBoxLayout()

        bold = QFont()
        bold.setBold(True)

        #Buttons to apply file settings or cancel
        self.FinishBtn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                QDialogButtonBox.StandardButton.Cancel)
        self.FinishBtn.accepted.connect(self.accept)
        #self.FinishBtn.accepted.connect(self.assign_variables)
            #self.ok_button_clicked()
        self.FinishBtn.rejected.connect(self.reject)

        #Text box for File Name
        self.FileName = QLineEdit()
        self.FileName.setReadOnly(True)
        self.FileNameLabel = QLabel('File Name')

        #Optional Layer Name (if not, main window does autoname)
        self.LayerName = QLineEdit()
        self.LayerNameLabel = QLabel('Layer Name')
        #Opens system file dialog selector
        self.FileDialog = QPushButton('Select File')

        #FileTypeGroupBox = QGroupBox('File Type')
        #creating independent button group for file type
        self.FileTypeLabel = QLabel('File Type')
        #making the header bold
        self.FileTypeLabel.setFont(bold)
        self.FileButtonGroup = QButtonGroup()
        #User selects data file type
        self.FileType_Excel = QRadioButton('Excel')
        self.FileType_CSV = QRadioButton('CSV')
        #adding the two buttons to the file type button group
        self.FileButtonGroup.addButton(self.FileType_Excel)
        self.FileButtonGroup.addButton(self.FileType_CSV)

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

        #showing 5 samples rows of data
        self.SampleData = QTableView()
        self.SampleLabel = QLabel('Preview Data')
        #Making the header bold
        self.SampleLabel.setFont(bold)

        #User selects the x direction of magnetic field
        self.XMagField = QComboBox()
        self.XMagField.setPlaceholderText('Select BX')

        #User selects the y direction of magnetic field
        self.YMagField = QComboBox()
        self.YMagField.setPlaceholderText('Select BY')

        #User selects the y direction of magnetic field
        self.ZMagField = QComboBox()
        self.ZMagField.setPlaceholderText('Select BZ')

        #For detecting file headers vs first line of data. Needed?
        self.FileHasHeaders = QCheckBox()
        self.FileHeadersLabel = QLabel('File Has Headers')

        #User selects TMI of magnetic field
        self.TotalMagField = QComboBox()
        self.TotalMagField.setPlaceholderText('Select TMI (BT)')

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

        #creating header for time subsection
        self.TimeHeader = QLabel('Time')
        #making header bold
        self.TimeHeader.setFont(bold)
        self.TimeButtonGroup = QButtonGroup()
        #User checks if the mag data is vector or scalar
        self.ComboTime = QRadioButton('Independent sensor timestamps')
        self.ComboTime.toggled.connect(self.toggle_combo_time)
        self.SingleTime = QRadioButton('Shared sensor timestamps')
        self.SingleTime.toggled.connect(self.toggle_single_time)
        #adding the two buttons to the magnetic field data type button group
        self.TimeButtonGroup.addButton(self.ComboTime)
        self.TimeButtonGroup.addButton(self.SingleTime)

        #User selects the time of data
        self.TotalTime = QComboBox()
        self.TotalTime.setPlaceholderText('Select Time (sec)')
        self.MagTime = QComboBox()
        self.LocTime = QComboBox()
        self.MagTime.setPlaceholderText('Select Magnetic Time (sec)')
        self.LocTime = QComboBox()
        self.LocTime.setPlaceholderText('Select GPS Time (sec)')

        #adding widgets to the first section of the dialog box
        self.sub_layout.addWidget(self.FileNameLabel)
        self.sub_layout.addWidget(self.FileName)
        self.sub_layout.addWidget(self.FileDialog)
        self.layout.addLayout(self.sub_layout)

        #adding widgets to the fourth section of the dialog box
        self.layout.addWidget(self.MagDataTypeLabel)
        self.mag_layout.addWidget(self.VectorMag)
        self.mag_layout.addWidget(self.ScalarMag)
        self.VectorMag.setChecked(True)
        self.layout.addLayout(self.mag_layout)

        #adding widgets to the fifth section of the dialog box
        self.button_layout.addWidget(self.XMagField)
        self.button_layout.addWidget(self.YMagField)
        self.button_layout.addWidget(self.ZMagField)
        self.time_layout.addWidget(self.MagTime)
        self.time_layout.addWidget(self.LocTime)

        #sets the layout for the widgets in the dialog box
        self.layout.addLayout(self.button_layout)
        self.layout.addWidget(self.TotalMagField)
        self.layout.addWidget(self.CoordinatesHeader)
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

   def select_file_button_clicked(self):
       #calls the select file function
       self.select_file()

   def select_file(self):
       #assigns the file path selected by the user to a stored variable
       #filter to show CSV and Excel files by default
       self.file_paths, _ = QFileDialog.getOpenFileNames(parent=self,
                                                         caption='Select File(s)',
                                                         filter='Dataset Files (*.csv *.xls *.xlsx *.txt)')
       #only occurs if a file is selected by the user
       if self.file_paths:
           #removes the [brackets] placed on filepath for the users
           self.file_path_shown = str(self.file_paths).strip('[]')
           self.FileName.setText(f'{self.file_path_shown}')

           self.read_file()

   def read_file(self):
        # read raw file and import the column headers into the drop-down menus
        import os
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
            self.FileType_CSV.setChecked(True)

        # read Excel files (concatenate all sheets)
        elif ext in ('.xls', '.xlsx'):
            df = pd.concat(pd.read_excel(path, sheet_name=None), axis=1)
            # flatten MultiIndex columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = ['_'.join(map(str, col)).strip() for col in df.columns.values]
            self.FileType_Excel.setChecked(True)

        # fallback: try CSV then Excel
        else:
            try:
                df = pd.read_csv(path)
                self.FileType_CSV.setChecked(True)
            except Exception:
                df = pd.concat(pd.read_excel(path, sheet_name=None), axis=1)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = ['_'.join(map(str, col)).strip() for col in df.columns.values]
                self.FileType_Excel.setChecked(True)

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
                combo.addItem(str(column), columns)

        self.sample_data()


   def assign_variables(self):
        self.BX = self.XMagField.currentText()
        self.BY = self.YMagField.currentText()
        self.BZ = self.ZMagField.currentText()
        self.Lat = self.XLatitude.currentText()
        self.Lon = self.YLongitude.currentText()
        self.BT = self.TotalMagField.currentText()
        self.TotalTime = self.TotalTime.currentText()
        self.MagTime = self.MagTime.currentText()
        self.LocTime = self.LocTime.currentText()

        if self.VectorMag.isChecked():
            mag_data = [self.BX, self.BY, self.BZ]
        elif self.ScalarMag.isChecked():
            mag_data = [self.BT]

        if self.SingleTime.isChecked():
            time_data = [self.TotalTime]
        elif self.ComboTime.isChecked():
            time_data = [self.MagTime, self.LocTime]

        coord_data = [self.Lat, self.Lon]
        data = mag_data + time_data + coord_data

        self.raw_file = self.raw_file[data]

#       need to reset when new file selected

   def sample_data(self):
       self.model = TableModel.TableModel(self.raw_file)
       self.SampleData.setModel(self.model)
       #self.SampleData.resizeColumnsToContents()
       header = self.SampleData.horizontalHeader()
       header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

   def toggle_vector(self):
       self.TotalMagField.setEnabled(False)
       self.XMagField.setEnabled(True)
       self.YMagField.setEnabled(True)
       self.ZMagField.setEnabled(True)

   def toggle_scalar(self):
       self.TotalMagField.setEnabled(True)
       self.XMagField.setEnabled(False)
       self.YMagField.setEnabled(False)
       self.ZMagField.setEnabled(False)

   def toggle_combo_time(self):
       self.TotalTime.setEnabled(False)
       self.MagTime.setEnabled(True)
       self.LocTime.setEnabled(True)

   def toggle_single_time(self):
       self.TotalTime.setEnabled(True)
       self.MagTime.setEnabled(False)
       self.LocTime.setEnabled(False)

   def missing_variable_warning(self):
       self.variablemissing = QMessageBox.warning(self, 'Missing Variable', 'Some variables have not been assigned. Please assign values to the missing variables before proceeding.')

class ExportDialog(QDialog):
    def __init__(self, parent=None):
         super().__init__(parent)

         #sets the title for the pop up dialog window
         self.setWindowTitle("Export Map as Image")

         #creates the layouts for the window
         self.layout2 = QVBoxLayout()

         self.label = QLabel('Map name:')
         self.write_name = QLineEdit()

         self.layout2.addWidget(self.label)
         self.layout2.addWidget(self.write_name)

         #Buttons to apply file settings or cancel
         self.FinishBtn2 = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                 QDialogButtonBox.StandardButton.Cancel)
         self.FinishBtn2.accepted.connect(self.accept)
         #self.FinishBtn.accepted.connect(self.assign_variables)
             #self.ok_button_clicked()
         self.FinishBtn2.rejected.connect(self.reject)
         self.layout2.addWidget(self.FinishBtn2)
         self.setLayout(self.layout2)

    def extractname(self):
        self.file_name = self.write_name.text()
