from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QIcon, QKeySequence
from PyQt6.QtWidgets import (QApplication, QCheckBox, QLabel, QMainWindow, 
                             QStatusBar, QToolBar, QWidget, QPushButton, 
                             QVBoxLayout, QHBoxLayout, QFileDialog, QTableWidget, 
                             QTableWidgetItem, QLineEdit, QMessageBox, 
                             QRadioButton, QComboBox)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import ExcelReader as er
import MapFilter as mf
import MapMaker as mm
import DialogWindow as dw
import sys, os

#%% General crash ERROR
import threading
import traceback

def errorMessage(etype, value, tb):
    print('ERROR begin:')
    traceback.print_exception(etype, value, tb)
    print('ERROR end.')
    errorMsg = traceback.format_exception(etype, value, tb,limit=None, chain=True)
    finalError =''
    for errs in errorMsg:
        finalError += errs
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Icon.Critical)
    msg.setText("<b>Critical error:</b>")
    msg.setInformativeText('''Please see the detailed error below:''')
    msg.setWindowTitle("Error!")
    msg.setDetailedText('%s' % (finalError))
    msg.setStandardButtons(QMessageBox.StandardButton.Retry)
    msg.exec()

def catchErrors():
    sys.excepthook = errorMessage
    threading.Thread.__init__

#%% Main app

class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)
        self.initUI()
        self.df_list = list()
        
    def initUI(self):
        #sets the window title
        self.setWindowTitle('MagPy')
        #creates a figure and axes
        #self.figure, self.ax = plt.subplots()
        self.figure = Figure()
        self.axes = self.figure.add_subplot()
        #creates a canvas to display figure
        self.canvas = FigureCanvas(self.figure)
        #creates the toolbar
        self.create_toolbar()
        #creating a status bar
        self.setStatusBar(QStatusBar(self))
        #add text boxes for changing the vmin and vmax
        self.set_vmax = QLineEdit()
        self.set_vmax.setPlaceholderText('Max BT (µT)')
        self.set_vmax.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        self.set_vmin = QLineEdit()
        self.set_vmin.setPlaceholderText('Min BT (µT)')
        self.set_vmin.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        
        self.set_continuation_height = QLineEdit()
        self.set_continuation_height.setPlaceholderText('Continuation Height (m)')
        self.set_continuation_height.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        self.select_file = QComboBox()
        self.select_file.setPlaceholderText('Select File to Display')
        self.select_file.currentIndexChanged.connect(self.select_display_file)
        #self.select_file.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        self.toggle_map_type = QCheckBox('Contour Map')
        self.toggle_map_type.stateChanged.connect(self.map_type_changed)
        
        #creating the layout
        main_layout = QVBoxLayout()
        button_layout = QHBoxLayout()
        #assigning a widget to the layout
        button_layout.addWidget(self.set_vmin)
        button_layout.addWidget(self.set_vmax)
        button_layout.addWidget(self.set_continuation_height)
        button_layout.addWidget(self.select_file)
        button_layout.addWidget(self.toggle_map_type)
        main_layout.addLayout(button_layout)
        main_layout.addWidget(self.canvas)
        
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        #sets a fixed window size
        self.setFixedSize(1300, 850)
        
        
    def create_toolbar(self):
        #creates the toolbar
        toolbar = QToolBar('Main Toolbar')
        #sets the toolbar to the main window
        self.addToolBar(toolbar)
        #creates action for opening files
        open_action = QAction('Import Data', self)
        open_action.setStatusTip('Import Excel Data')
        open_action.triggered.connect(self.file_editor_window)
        toolbar.addAction(open_action)
        
        #filter_actions
        filter_action = QAction('Upward Continuation', self)
        #filter_action.setStatusTip('Filter Applied to Data')
        filter_action.triggered.connect(self.upward_continuation)
        #toolbar.addAction(filter_action)
        
        filter2_action = QAction('Downward Continuation', self)
        filter2_action.triggered.connect(self.downward_continuation)
        #toolbar.addAction(filter2_action)
        
        #reset_canvas_actions
        reset_canvas_action = QAction('Clear Figure', self)
        #filter_action.setStatusTip('Filter Applied to Data')
        reset_canvas_action.triggered.connect(self.clear_data)
        toolbar.addAction(reset_canvas_action)
        
        #set v values action
        set_value_action = QAction('Change Scale', self)
        set_value_action.triggered.connect(self.scale_changed)
        toolbar.addAction(set_value_action)
        
        #reset map action
        reset_map = QAction('Reset Map', self)
        reset_map.triggered.connect(self.reset_map)
        toolbar.addAction(reset_map)
        
        #export cleaned dataset
        export_data = QAction('Export Data', self)
        export_data.triggered.connect(self.export_data)
        
        menu = self.menuBar()
        file_menu = menu.addMenu('&File')
        file_menu.addAction(open_action)
        file_menu.addAction(reset_map)
        file_menu.addAction(export_data)
        
        filters_menu = menu.addMenu('&Filters')
        filters_menu.addAction(filter_action)
        filters_menu.addAction(filter2_action)
        
        
        #export_actions
    
    #def create_menu(self):
        #add menu with actions from toolbar
    
    def file_editor_window(self):
        #creates the dialog window after button is clicked
        #self and parent connection ensures that the dialog opens above the 
        #main window
        self.dlg = dw.CustomDialog(self)
        self.dlg.FileDialog.clicked.connect(self.dlg.select_file_button_clicked)
        self.dlg.accepted.connect(self.dlg.assign_variables)
        self.dlg.accepted.connect(self.read_from_dialog)
        self.dlg.exec()
        
#    def dialog_accepted(self):
#        self.read_from_dialog()
       
    def read_from_dialog(self):
    #will probably have to change this when adding the ability to manually choose columns
        try:
            self.file_paths = self.dlg.file_paths
            raw_file = self.dlg.raw_file
#            if self.file_paths:
#                self.read_file()
#                print('Yay!')
            if raw_file is not None:
                self.df_list.append(raw_file)
                for index, value in enumerate(self.df_list):
                    print(f"Index: {index}, Value: {value}")
                self.read_file(raw_file)
                print('Yeahh!')
        except Exception as e:
            print(f':( {e}')
            import traceback
            traceback.print_exc()
        
        
    def read_file(self, raw_file):
        if self.file_paths:
            for file in self.file_paths:
                short_name = os.path.basename(file)
                if self.select_file.findText(short_name) == -1:
                    self.select_file.addItem(short_name, userData=file)
                self.select_file.setPlaceholderText(short_name)
                self.excel_reader(df=self.df_list[-1])
    #make excel reader optional? for people who don't want their data cleaned or already did it
    
    def assign_v_values(self):
        #self.vmin = self.set_vmin.text()
        #self.vmax = self.set_vmax.text()
        valid = True
        vmin_entry = self.set_vmin.text()
        if vmin_entry.strip() == '':
            self.vmin = None
            self.statusBar().showMessage('Minimum/Maximum Scale Value(s) Not Entered')
            valid = False
        try:
            self.vmin = float(vmin_entry)
            #self.statusBar().showMessage('Field Scale Changed')
        except ValueError:
            #self.statusBar().showMessage('Invalid field value entered (must be a number)')
            valid = True
        
        vmax_entry = self.set_vmax.text()
        if vmax_entry.strip() == '':
            self.vmax = None
            self.statusBar().showMessage('Minimum/Maximum Scale Value(s) Not Entered')
            valid = False
        try:
            self.vmax = float(vmax_entry)
            #self.statusBar().showMessage('Field Scale Changed')
            #self.statusBar().showMessage(f'Continuation Height={self.Hm')
            
        except ValueError:
            #self.statusBar().showMessage('Invalid field value entered (must be a number)')
            valid = True
        
        return valid
        
    #def change continuation height
    def assign_continuation_height(self):
        H_entry = self.set_continuation_height.text()
        if H_entry.strip() == '':
            self.H = 0
            self.statusBar().showMessage('Continuation Height Not Entered')
            return False
        try:
            self.H = float(H_entry)
            self.statusBar().showMessage(f'Continuation Height={self.H}m')
            return True
        except ValueError:
            self.statusBar().showMessage('Invalid continuation height entered (must be a number)')
            return False
        
    def select_display_file(self, index):
        file_entry = self.select_file.itemData(index, Qt.ItemDataRole.UserRole)
        current_index = self.select_file.currentIndex()
        print(f'current index: {current_index}')
        try:
            self.excel_reader(df=self.df_list[current_index])
        except ValueError:
            self.statusBar().showMessage('File not selected')
            return False
            
    def excel_reader(self, df):#, file_path):
        bx = self.dlg.BX
        by = self.dlg.BY
        bz = self.dlg.BZ
        Lat = self.dlg.Lat
        Lon = self.dlg.Lon
        LocTime = self.dlg.LocTime
        MagTime = self.dlg.MagTime
        mag_columns = [f'{bx}', f'{by}', f'{bz}', f'{MagTime}']
        rename_mag_columns = {f'{bx}': 'X (µT)', f'{by}': 'Y (µT)', f'{bz}': 'Z (µT)', f'{MagTime}': 'Mag_Time (s)'}
        gps_columns = [f'{Lat}', f'{Lon}', f'{LocTime}']
        rename_gps_columns = {f'{Lat}': 'Latitude (°)', f'{Lon}': 'Longitude (°)', f'{LocTime}': 'Loc_Time (s)'}
        #self.df = self.dlg.raw_file
        self.df = df
#        print(self.df)
        
        self.magdf = self.df[mag_columns]
        self.magdf = self.magdf.rename(columns=rename_mag_columns)
        self.gpsdf = self.df[gps_columns]
        self.gpsdf = self.gpsdf.rename(columns=rename_gps_columns)
#        print(self.magdf)
        self.magdf.to_csv('magdf.csv')
#        print(self.gpsdf)
        self.gpsdf.to_csv('gpsdf.csv')
        
        excelreader = er.ExcelReader(self.magdf, self.gpsdf)
        self.df = excelreader.input_sheets()
        self.df = excelreader.interpolate()
        #self.df = excelreader.alignTime()
        self.statusBar().showMessage(f'Successfully Loaded {self.file_paths}')
        self.plot_data(self.df)
        
    def plot_data(self, df, vmin=None, vmax=None, contour=None):
        #clears any previous figures from the canvas widget
        self.figure.clear()
        #replots the blank matplotlib figure and axes
        self.axes = self.figure.add_subplot()
        #calls mapmaker class to plot the data
        mapper = mm.MapMaker(df)
        #runs data through showMap function
        #creates a colorbar
        #fig.colorbar(cax, ax=self.axes, label='Total Magnetic Field [uT]')
        #refreshes the canvas
        mapper.showMap(df, ax=self.axes, contour=contour)
        self.canvas.draw()
        self.current_df = df
        
    def scale_changed(self, df, contour=None):
        #checks if v values were assigned
        if not self.assign_v_values():
            return
        if self.toggle_map_type.isChecked():
            contour=True
        #refreshs the graph after clearing
        self.figure.clear()
        #replot the figure widget
        self.axes = self.figure.add_subplot()
        mapper = mm.MapMaker(self.current_df)
        self.assign_v_values()
       # if (vmin, vmax) is None:
        mapper.showMap(self.current_df, ax=self.axes, vmin=self.vmin, vmax=self.vmax, contour=contour)
       # else:
       #     mapper.showMap(df, ax=self.axes, vmin=vmin, vmax=vmax)
        self.canvas.draw()
        
    def filtered_scale_changed(self, df, contour=None):
        #checks if v values were assigned
        if not self.assign_v_values():
            return
        #refreshs the graph after clearing
        self.figure.clear()
        #replot the figure widget
        self.axes = self.figure.add_subplot()
        mapper = mm.MapMaker(df)
        self.assign_v_values()
       # if (vmin, vmax) is None:
        mapper.showMap(df, ax=self.axes, vmin=self.vmin, vmax=self.vmax, contour=contour)
        self.statusBar().showMessage(f'Continuation Height={self.H}m')
       # else:
       #     mapper.showMap(df, ax=self.axes, vmin=vmin, vmax=vmax)
        self.canvas.draw()
        self.current_df = df
        
    def map_type_changed(self):
        if self.toggle_map_type.isChecked():
            self.plot_data(self.current_df, contour=True)
        else:
            self.plot_data(self.current_df, contour=None)
        
    
    def clear_data(self, df):
        #clear previous plots
        self.axes.clear()
        self.figure.clear()
        self.canvas.draw()
        
    def upward_continuation(self, df):
        #calls the magnetic filtering class
        filters = mf.MapFilter(self.df)
        #reads the continuation height assigned by the user
        self.assign_continuation_height()
        if self.H == 0:
            self.scale_changed(self.df)
            #self.plot_data(self.df)
        else:
            #runs data through upward continuation filter
            df = filters.upward_continuation(H=self.H)
            self.filtered_scale_changed(df)
           
        
    def downward_continuation(self, df):
        #calls the magnetic filtering class
        filters = mf.MapFilter(self.df)
        #reads the continuation height assigned by the user
        self.assign_continuation_height()
        if self.H == 0:
            self.scale_changed(self.df)
            #self.plot_data(self.df)
        else:
            #runs data through downward continuation filter
            df = filters.downward_continuation(H=self.H)
            self.filtered_scale_changed(df)
            #self.plot_data(df)
           # self.plot_data(df)
        
    def reset_map(self):
        self.figure.clear()
        if self.select_file.currentIndex()!= -1:
            self.select_display_file(self.select_file.currentIndex())
        else:
            self.plot_data(self.current_df)
        self.canvas.draw()
        self.statusBar().showMessage('Map Successfully Reset')
        
    def export_data(self):
       current_df = pd.DataFrame(self.current_df)
       if self.select_file.currentIndex()!= -1:
           filepath = Path(self.select_file.itemData(self.select_file.currentIndex(), Qt.ItemDataRole.UserRole))
           new_filepath = filepath.with_suffix('.csv')
           current_df.to_csv(new_filepath, index=False)
           self.statusBar().showMessage(f'Dataset Successfully Exported {new_filepath}')
       else:
           filepath = Path(self.file_paths[-1])
           new_filepath = filepath.with_suffix('.csv')                
           current_df.to_csv(new_filepath, index=False)
           self.statusBar().showMessage(f'Dataset Successfully Exported {new_filepath}')
       
        
    #def sampling frequency
    #   add ability to set sampling frequency and adjust the filters class so it's not static at d=1
    
    #def rewind action
    #   allows users to go back one step
#%% Executing app
if __name__ == '__main__':
    catchErrors() # prevent crash of the app
    app = QApplication(sys.argv)   
    window = MainWindow()
    window.show()
    sys.exit(app.exec())