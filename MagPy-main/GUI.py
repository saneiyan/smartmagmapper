from PyQt6.QtCore import QSize, Qt, QTimer, QSortFilterProxyModel, QUrl
from PyQt6.QtGui import QAction, QIcon, QKeySequence, QFont
from PyQt6.QtWidgets import (QApplication, QCheckBox, QLabel, QMainWindow,
                             QStatusBar, QToolBar, QWidget, QPushButton,
                             QVBoxLayout, QHBoxLayout, QFileDialog, QTableWidget,
                             QTableWidgetItem, QLineEdit, QMessageBox,
                             QRadioButton, QComboBox, QTabWidget, QTableView,
                             QHeaderView, QStackedLayout)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import ExcelReader as er
import MapFilter as mf
import MapMaker as mm
import DialogWindow as dw
import PlotData as plot
import WebMap as wm
import TableModel
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
        #set function to 'bold' labels
        bold = QFont()
        bold.setBold(True)
        #set tabs
        self.tabs = QTabWidget()
        #self.tabs.setTabPosition(QTabWidget.TabPosition.North)
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
        self.change_label = QLabel('Edit Map Scale')
        self.change_label.setFont(bold)
        self.vmax_label = QLabel('Maximum BT (µT):')
        #self.vmax_label.setFont(bold)
        self.set_vmax = QLineEdit()
        self.set_vmax.setPlaceholderText('Max BT (µT) (e.g. "50")')
        self.set_vmax.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.vmin_label = QLabel('Minimum BT (µT):')
        #self.vmin_label.setFont(bold)
        self.set_vmin = QLineEdit()
        self.set_vmin.setPlaceholderText('Min BT (µT) (e.g. "35")')
        self.set_vmin.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.date = QLabel('Survey Date')
        self.date.setFont(bold)
        self.year_label = QLabel('Year:')
        self.year = QLineEdit()
        self.year.setPlaceholderText('Year')
        self.year.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.month_label = QLabel('Month:')
        self.month = QLineEdit()
        self.month.setPlaceholderText('Month')
        self.month.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.day_label = QLabel('Day:')
        self.day = QLineEdit()
        self.day.setPlaceholderText('Day')
        self.day.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.continuation_label = QLabel('Continuation Height (UC/DC Filters):')
        self.continuation_label.setFont(bold)
        self.set_continuation_height = QLineEdit()
        self.set_continuation_height.setPlaceholderText('Height (meters) (e.g. "5")')
        self.set_continuation_height.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.select_file = QComboBox()
        self.select_file.setPlaceholderText('Select File to Display')
        self.select_file.currentIndexChanged.connect(self.select_display_file)
        #self.select_file.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.toggle_map_type = QCheckBox('Contour Map')
        self.toggle_map_type.stateChanged.connect(self.map_type_changed)

        self.load_web_map = QCheckBox('Web Map')
        self.load_web_map.stateChanged.connect(self.web_map)

        self.data = QTableView()
        # self.proxyModel = QSortFilterProxyModel()
        # self.proxyModel.setSourceModel(self.data.model())
        # self.data.setSortingEnabled(True)
        # self.data.setModel(self.proxyModel)

        self.plot = Figure()
        self.plot_axes = self.plot.add_subplot()
        self.chart = FigureCanvas(self.plot)

        #creating the map layout
        main_layout = QVBoxLayout()
        self.map_layout = QVBoxLayout()
        button_layout = QHBoxLayout()
        button_layout_2 = QHBoxLayout()
        #assigning a widget to the layout
        button_layout.addWidget(self.change_label)
        button_layout.addWidget(self.vmin_label)
        button_layout.addWidget(self.set_vmin)
        button_layout.addWidget(self.vmax_label)
        button_layout.addWidget(self.set_vmax)
        button_layout.addWidget(self.continuation_label)
        button_layout.addWidget(self.set_continuation_height)
        main_layout.addLayout(button_layout)
        button_layout_2.addWidget(self.date)
        button_layout_2.addWidget(self.year_label)
        button_layout_2.addWidget(self.year)
        button_layout_2.addWidget(self.month_label)
        button_layout_2.addWidget(self.month)
        button_layout_2.addWidget(self.day_label)
        button_layout_2.addWidget(self.day)
        button_layout_2.addWidget(self.toggle_map_type)
        button_layout_2.addWidget(self.load_web_map)
        button_layout_2.addWidget(self.select_file)
        main_layout.addLayout(button_layout_2)
        self.map_layout.addWidget(self.canvas)

        # #creating the plot layout
         # self.plot_layout = QVBoxLayout()
         # self.plot_layout.addWidget(self.chart)

        #creating the data table layour
        #table_layout = QVBoxLayout()
        #table_layout.addWidget(self.data)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.tabs.addTab(self.data, 'Data Table')
        map_widget = QWidget()
        map_widget.setLayout(self.map_layout)
        self.tabs.addTab(map_widget,'Map')
        #table_widget = QWidget()
        #table_widget.setLayout(table_layout)
        self.plot_tabs = QTabWidget()
        self.plot_widget = QWidget()
        #creating the plot layout
        self.plot_layout = QVBoxLayout()
        self.plot_layout.addWidget(self.plot_tabs)
        #plot_layout.addWidget(self.chart)
        self.plot_widget.setLayout(self.plot_layout)
        self.tabs.addTab(self.plot_widget, 'Time-Series Data')
        main_layout.addWidget(self.tabs)
        self.setCentralWidget(central_widget)
        #self.setCentralWidget(central_widget)
        #sets a fixed window size
        self.setFixedSize(1300, 850)


    def create_toolbar(self):
        #creates the toolbar
        self.toolbar = QToolBar('Main Toolbar')
        #sets the toolbar to the main window
        self.addToolBar(self.toolbar)
        #creates action for opening files
        open_action = QAction('Import Data', self)
        open_action.setStatusTip('Import Excel Data')
        open_action.triggered.connect(self.file_editor_window)
        self.toolbar.addAction(open_action)

        #export cleaned dataset
        export_data = QAction('Export Data', self)
        export_data.triggered.connect(self.export_dialog)
        self.toolbar.addAction(export_data)

        #filter_actions
        filter_action = QAction('Upward Continuation', self)
        #filter_action.setStatusTip('Filter Applied to Data')
        filter_action.triggered.connect(self.upward_continuation)
        #self.toolbar.addAction(filter_action)

        filter2_action = QAction('Downward Continuation', self)
        filter2_action.triggered.connect(self.downward_continuation)
        #toolbar.addAction(filter2_action)

        rtp_action = QAction('Reduction to Pole', self)
        rtp_action.triggered.connect(self.reduction_to_pole)

        #reset_canvas_actions
        reset_canvas_action = QAction('Clear Figure', self)
        #filter_action.setStatusTip('Filter Applied to Data')
        reset_canvas_action.triggered.connect(self.clear_data)
        #self.toolbar.addAction(reset_canvas_action)

        #reset map action
        reset_map = QAction('Reset Map', self)
        reset_map.triggered.connect(self.reset_map)
        self.toolbar.addAction(reset_map)

        #set v values action
        set_value_action = QAction('Change Map Scale', self)
        set_value_action.triggered.connect(self.scale_changed)
        self.toolbar.addAction(set_value_action)

        #change the data visualized in the plot
        plot_data = QAction('Change Plot', self)
        plot_data.triggered.connect(self.plot_changed)
        #self.toolbar.addAction(plot_data)

        self.menu = self.menuBar()
        self.file_menu = self.menu.addMenu('&File')
        self.file_menu.addAction(open_action)
        self.file_menu.addAction(reset_map)
        self.file_menu.addAction(export_data)

        self.edit_menu = self.menu.addMenu('&Plot')

        self.filters_menu = self.menu.addMenu('&Apply Filters')
        self.filters_menu.addAction(filter_action)
        self.filters_menu.addAction(filter2_action)
        self.filters_menu.addAction(rtp_action)
        self.toolbar.addAction(self.filters_menu.menuAction())

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
                self.short_name = os.path.basename(file)
                if self.select_file.findText(self.short_name) == -1:
                    self.select_file.addItem(self.short_name, userData=file)
                self.select_file.setPlaceholderText(self.short_name)
                self.excel_reader(df=self.df_list[-1])
    #make excel reader optional? for people who don't want their data cleaned or already did it

    def assign_v_values(self):
        #self.vmin = self.set_vmin.text()
        #self.vmax = self.set_vmax.text()
        valid = True
        vmin_entry = self.set_vmin.text()
        if vmin_entry.strip() == '':
            self.vmin = None
            self.statusBar().showMessage('Minimum/Maximum Scale Value(s) Not Entered (fill min/max scale fields). Try again.')
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
            self.statusBar().showMessage('Minimum/Maximum Scale Value(s) Not Entered (fill min/max scale fields). Try again.')
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
            self.statusBar().showMessage('Continuation Height Not Entered (fill continuation height field). Try again.')
            return False
        try:
            self.H = float(H_entry)
            self.statusBar().showMessage(f'Continuation Height={self.H}m')
            return True
        except ValueError:
            self.statusBar().showMessage('Invalid continuation height entered (must be a number). Try again.')
            return False

    def extract_survey_date(self):
        self.date_year = self.year.text()
        self.date_month = self.month.text()
        self.date_day = self.day.text()
        if self.date_year.strip() == '' or self.date_month.strip() == '' or self.date_day.strip() == '':
            self.statusBar().showMessage('Survey date not entered (fill year, month, day fields). Try again.')
            return False
        try:
            self.date_year = int(self.date_year)
            self.date_month = int(self.date_month)
            self.date_day = int(self.date_day)
            return True
        except ValueError:
            self.statusBar().showMessage('Invalid survey date entered. Try again.')
            return False

    def select_display_file(self, index):
        file_entry = self.select_file.itemData(index, Qt.ItemDataRole.UserRole)
        current_index = self.select_file.currentIndex()
        print(f'current index: {current_index}')
        try:
            self.excel_reader(df=self.df_list[current_index])

        except ValueError:
            self.statusBar().showMessage('File not selected. Try again.')
            return False

    def excel_reader(self, df):#, file_path):
        self.plot_tabs.clear()
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
#        self.magdf.to_csv('magdf.csv')
#        print(self.gpsdf)
#        self.gpsdf.to_csv('gpsdf.csv')

        excelreader = er.ExcelReader(self.magdf, self.gpsdf)
        self.df = excelreader.input_sheets()
        self.df = excelreader.interpolate()
        #self.df = excelreader.alignTime()
        self.df = excelreader.convertUTM()
        self.df = excelreader.distance()
        self.statusBar().showMessage(f'Successfully Loaded {self.file_paths}')
        self.plot_data(self.df)
        self.plot_table(self.df)
        self.new_plot(df=self.df, name='BT', column=self.df['BT'])
        self.add_menu(columns=self.df.columns)

    def add_menu(self, columns):
        if hasattr(self, 'select_data') and self.select_data:
            self.edit_menu.removeAction(self.select_data.menuAction())
            self.select_data.deleteLater()
        self.select_data = self.edit_menu.addMenu('&Select data')
        for column in columns:
            add_column = QAction(column, self)
            self.select_data.addAction(add_column)
            add_column.triggered.connect(lambda _, col=column: self.plot_changed(val=col))

    def plot_data(self, df, vmin=None, vmax=None, contour=None):
        #clears any previous figures from the canvas widget
        self.figure.clear()
        #replots the blank matplotlib figure and axes
        self.axes = self.figure.add_subplot()
        #calls mapmaker class to plot the data
        mapper = mm.MapMaker(df)
        #runs data through showMap function
        mapper.showMap(df, ax=self.axes, contour=contour, vmin=vmin, vmax=vmax)
        #refreshes the canvas
        self.canvas.draw()
        self.current_df = df

    def plot_mesh(self, rtp, vmin=None, vmax=None, xmesh=None, ymesh=None):
        self.figure.clear()
        self.axes = self.figure.add_subplot()
        mapper = mm.MapMaker(self.current_df)
        mapper.meshMap(ax=self.axes, xmesh=xmesh, ymesh=ymesh, val=rtp)
        self.canvas.draw()
        #self.current_df = df
#
    def plot_table(self, df):
        #df = pd.to_numeric(df, errors='coerce')
        self.model = TableModel.TableModel(df)
        self.data.setModel(self.model)
        self.proxyModel = QSortFilterProxyModel()
        self.proxyModel.setSourceModel(self.data.model())
        self.proxyModel.setSortRole(Qt.ItemDataRole.EditRole)
        self.data.setSortingEnabled(True)
        self.data.setModel(self.proxyModel)
        #self.data.resizeColumnsToContents()
        header = self.data.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    def update_current_plot(self, ymin=None, ymax=None):
        idx = self.plot_tabs.currentIndex()
        current_plot = self.plot_tabs.widget(idx)
        if current_plot is not None:
            canvas = current_plot.layout().itemAt(0).widget()
            fig = canvas.figure
            ax = fig.axes[0]
            ax.clear()
            column = getattr(current_plot, 'column', None)
            df = getattr(current_plot, 'df', None)
            if column is not None and df is not None:
                self.plotter = plot.PlotData(df)
                self.plotter.plot(val=column, ax=ax, ymin=ymin, ymax=ymax)
            if ymin is not None and ymax is not None:
                ax.set_ylim(ymin, ymax)
            canvas.draw()

    def plot_changed(self, val=None, ymin=None, ymax=None):
        print(f'success! y axis: {val}')
        self.new_plot(name=val, df=self.current_df, column=self.current_df[val])

    def new_plot(self, df, name, ymin=None, ymax=None, column=None, ax=None):
        fig = Figure()
        #plot_layout = QStackedLayout()
        plot_axes = fig.add_subplot()
        self.plotter = plot.PlotData(df)
        self.plotter.plot(val=column, ax=plot_axes, ymin=ymin, ymax=ymax, color=None)
        plot_canvas = FigureCanvas(fig)
        plot_tabs = QWidget()
        plot_layout = QVBoxLayout()
        plot_layout.addWidget(plot_canvas)
        plot_tabs.setLayout(plot_layout)
        plot_tabs.column = column
        plot_tabs.df = df
        self.plot_layout.addWidget(plot_tabs)
        self.plot_tabs.addTab(plot_tabs, f'{name}')
        plot_canvas.draw()


    def web_map(self):
        if self.load_web_map.isChecked():
            self.canvas.hide()

            # Remove existing web map if it exists
            if hasattr(self, 'web_map_widget') and self.web_map_widget:
                self.map_layout.removeWidget(self.web_map_widget)
                self.web_map_widget.deleteLater()

            # Create new web map
            self.web_map_widget = wm.MapWidget(self.current_df)
            self.map_layout.addWidget(self.web_map_widget)
            self.web_map_widget.show()
        else:
            if hasattr(self, 'web_map_widget') and self.web_map_widget:
                self.web_map_widget.hide()
                self.map_layout.removeWidget(self.web_map_widget)
                self.web_map_widget.deleteLater()
                self.web_map_widget = None
            self.canvas.show()

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
        self.plot_data(df=self.current_df, vmin=self.vmin, vmax=self.vmax, contour=contour)
        self.update_current_plot(ymin=self.vmin, ymax=self.vmax)

    def filtered_scale_changed(self, df, contour=None):
        #checks if v values were assigned
        if not self.assign_v_values():
            return
        if self.toggle_map_type.isChecked():
            contour=True
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

    def reduction_to_pole(self, df):
        #calls the magnetic filtering class
        filters = mf.MapFilter(self.current_df)
        #extract survey date from the user input
        self.extract_survey_date()
        #runs data through reduction to pole filter
        rtp, easting_mesh, northing_mesh = filters.reduction_to_pole(year=self.date_year, month=self.date_month, day=self.date_day)
        self.plot_mesh(rtp=rtp, xmesh=easting_mesh, ymesh=northing_mesh)

    def reset_map(self):
        self.figure.clear()
        if self.select_file.currentIndex()!= -1:
            self.select_display_file(self.select_file.currentIndex())
        else:
            self.plot_data(self.current_df)
        self.canvas.draw()
        self.reset_chart()
        self.statusBar().showMessage('Data Successfully Reset')

    def reset_chart(self):
        self.plot.clear()
        if self.select_file.currentIndex()!= -1:
            self.select_display_file(self.select_file.currentIndex())
        else:
            self.update_current_plot()
        #self.plot.draw()

    def export_dialog(self):
        self.extdlg = dw.ExportDialog(self)
        self.extdlg.accepted.connect(self.extract_name)
        self.extdlg.exec()

    def extract_name(self):
        self.extdlg.extractname()
        self.export_name = self.extdlg.file_name
        self.export_data()

    def export_data(self):
       current_df = pd.DataFrame(self.current_df)
       self.plotter.save_plot()
       if self.select_file.currentIndex()!= -1:
           filepath = Path(self.select_file.itemData(self.select_file.currentIndex(), Qt.ItemDataRole.UserRole))
           new_filepath = filepath.with_suffix('.csv')
           #new_mappath = Path(self.export_name).with_suffix('.png')
           dir_name = os.path.dirname(filepath)
           new_mappath = os.path.join(dir_name, f"{self.export_name}.png")
           current_df.to_csv(new_filepath, index=False)
           self.canvas.print_figure(new_mappath)
           self.statusBar().showMessage(f'Dataset Successfully Exported {new_filepath}')
       else:
           filepath = Path(self.file_paths[-1])
           new_filepath = filepath.with_suffix('.csv')
           #new_mappath = Path(self.export_name).with_suffix('.png')
           dir_name = os.path.dirname(filepath)
           new_mappath = os.path.join(dir_name, f"{self.export_name}.png")
           current_df.to_csv(new_filepath, index=False)
           self.canvas.print_figure(new_mappath)
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
