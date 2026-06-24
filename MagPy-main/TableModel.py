from PyQt6 import QtCore
from PyQt6.QtCore import Qt

class TableModel(QtCore.QAbstractTableModel):
    def __init__(self, df):
        super().__init__()
        self.df = df
        
    def data(self, index, role):
        if role == Qt.ItemDataRole.DisplayRole:
            value = self.df.iloc[index.row(), index.column()]
            return str(value)
        if role == Qt.ItemDataRole.EditRole:
            value = self.df.iloc[index.row(), index.column()]
            if hasattr(value, 'item'):
                return value.item()
            return value
    
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
