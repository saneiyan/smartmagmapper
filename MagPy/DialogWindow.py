from PyQt6 import QtCore
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QPushButton, QDialog,QDialogButtonBox, 
                             QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
                             QFileDialog, QCheckBox, QRadioButton, QComboBox, 
                             QButtonGroup, QGroupBox, QTableView, QHeaderView)
from PyQt6.QtGui import QFont
import pandas as pd


#class MainWindow(QMainWindow):
    #def __init__(self):
        #super().__init__()
        
        #sets title for the main application
        #self.setWindowTitle("My App")
        
        #creates the button that prompts a dialog when clicked
        #button = QPushButton("Import Data")
        #connects the button to a function when clicked
        #button.clicked.connect(self.button_clicked)
        #sets the button in the center of the main window
        #self.setCentralWidget(button)
        
    
class TableModel(QtCore.QAbstractTableModel):
    def __init__(self, df):
        super().__init__()
        self.df = df
        
    def data(self, index, role):
        if role == Qt.ItemDataRole.DisplayRole:
            value = self.df.iloc[index.row(), index.column()]
            return str(value)
    
    def rowCount(self, index):
        return self.df.shape[0]
    
    def columnCount(self, index):
        return self.df.shape[1]
    
    def headerData(self, section, orientation, role):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return str(self.df.columns[section])
            
            if orientation == Qt.Orientation.Vertical:
                return str(self.df.index[section])

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
        #self.FileDialog.clicked.connect(self.select_file_button_clicked)
        
        
        #FileTypeGroupBox = QGroupBox('File Type')
        #creating independent button group for file type
        self.FileTypeLabel = QLabel('File Type')
        #making the header bold
        self.FileTypeLabel.setFont(bold)
        self.FileButtonGroup = QButtonGroup()
        #User selects data file type
        self.FileType_Excel = QRadioButton('Excel')
#        self.FileType_Excel.triggered.connect(self.file_type)
        self.FileType_CSV = QRadioButton('CSV')
#        self.FileType_Excel.triggered.connect(self.file_type)
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
        #User selects the time of data (optional)
        self.MagTime = QComboBox()
        self.LocTime = QComboBox()
        self.MagTime.setPlaceholderText('Select Magnetic Time')
        self.LocTime = QComboBox()
        self.LocTime.setPlaceholderText('Select GPS Time')
        
        #adding widgets to the first section of the dialog box
        self.sub_layout.addWidget(self.FileNameLabel)
        self.sub_layout.addWidget(self.FileName)
        self.sub_layout.addWidget(self.FileDialog)
        self.layout.addLayout(self.sub_layout)
        
        #adding widgets to the second second of the dialog box
        self.layer_layout.addWidget(self.FileHeadersLabel)
        self.layer_layout.addWidget(self.FileHasHeaders)
        self.layer_layout.addWidget(self.LayerNameLabel)
        self.layer_layout.addWidget(self.LayerName)
        self.layout.addLayout(self.layer_layout)
        
        #adding widgets to the third section of the dialog box
        self.layout.addWidget(self.FileTypeLabel)
        self.layout.addWidget(self.FileType_Excel)
        self.layout.addWidget(self.FileType_CSV)
        #self.FileType_Excel.setChecked(True)
        
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
        self.layout.addLayout(self.time_layout)
        
        #sets the sample data table widget in the dialog box
        self.layout.addWidget(self.SampleLabel)
        self.layout.addWidget(self.SampleData)
        
        #adding the dialog box action buttons to the bottom of the box
        self.layout.addWidget(self.FinishBtn)
        #setting the main layout to the dialog box
        self.setLayout(self.layout)

#   def select_file_typed(self):
#        try:
#            self.file_paths = self.FileName.text()
#            self.file_paths = f'[{self.file_paths}]'
#        except AttributeError:
#            print(':(')

 
#   def file_type(self):
       #send to different file readers depending on excel vs csv
       
   def select_file_button_clicked(self):
       #calls the select file function
       self.select_file()

   def select_file(self): 
       #assigns the file path selected by the user to a stored variable
       self.file_paths, _ = QFileDialog.getOpenFileNames(parent=self, caption='Select Directory')
       #only occurs if a file is selected by the user
       if self.file_paths:
           #removes the [brackets] placed on filepath for the users
           self.file_path_shown = str(self.file_paths).strip('[]')
           self.FileName.setText(f'{self.file_path_shown}')
           
#           self.read_csv()
           self.read_file()
        
   def read_file(self):
        #read raw file and import the column headers in the drop down menus
#        if self.FileType_CSV.toggled:
#            self.raw_file = pd.read_csv(self.file_paths[0])
#        elif self.FileType_Excel.toggled:
        self.raw_file = pd.concat(pd.read_excel(self.file_paths[0], sheet_name=None), axis=1)
        self.raw_file.to_csv('raw_file.csv')
#        else:
#            print(':(')
        columns = self.raw_file.columns
        columns = ['_'.join(col).strip() for col in self.raw_file.columns.values]
        self.raw_file.columns = columns
        for column in self.raw_file.columns:
            self.XMagField.addItem(f"{column}", columns)
            #self.XMagField.setPlaceholderText(f'{columns[0]}')
            
            
            self.YMagField.addItem(f"{column}", columns)
            #self.YMagField.setPlaceholderText(f'{columns[0]}')
            
            
            self.ZMagField.addItem(f"{column}", columns)
            #self.ZMagField.setPlaceholderText(f'{columns[0]}')
                  
            self.XLatitude.addItem(f"{column}", columns)
            #self.XLatitude.setPlaceholderText(f'{columns[0]}')
            
            
            self.YLongitude.addItem(f"{column}", columns)
            #self.YLongitude.setPlaceholderText(f'{columns[0]}')
            
            
            self.TotalMagField.addItem(f"{column}", columns)
            #self.TotalMagField.setPlaceholderText(f'{columns[0]}')
            
            self.MagTime.addItem(f"{column}", columns)
            #self.Time.setPlaceholderText(f'{columns[0]}')
            
            self.LocTime.addItem(f"{column}", columns)
        #self.assign_variables()  
        self.sample_data()
       
        
   def assign_variables(self):     
        self.BX = self.XMagField.currentText()
        #print(self.BX)
        self.BY = self.YMagField.currentText()
        #print(self.BY)
        self.BZ = self.ZMagField.currentText()
        #print(self.BZ)
        self.Lat = self.XLatitude.currentText()
        #print(self.Lat)
        self.Lon = self.YLongitude.currentText()
        #print(self.Lon)
        self.MagTime = self.MagTime.currentText()
        #print(self.Tim)
        self.LocTime = self.LocTime.currentText()
        
#        data = [f'{self.BX}', f'{self.BY}', f'{self.BZ}', f'{self.Lat}', 
#               f'{self.Lon}', f'{self.MagTime}', f'{self.LocTime}']
        data2 = [self.BX, self.BY, self.BZ, self.Lat, self.Lon, self.MagTime, self.LocTime]
        #data2 = str(data2).strip('('')')
        
        self.raw_file = self.raw_file[data2]
        
#        print(self.raw_file)
        self.raw_file.to_csv('raw file test.csv')
        
#       need to reset when new file selected

   def sample_data(self):
       self.model = TableModel(self.raw_file)
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
        
        
#   def select_xmag(self):
#   def select_ymag(self):
#   def select_zmag(self):
            