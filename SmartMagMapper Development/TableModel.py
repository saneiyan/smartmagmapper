from PyQt6 import QtCore
from PyQt6.QtCore import Qt
import numbers,math
DISPLAY_PRECISION = None

class TableModel(QtCore.QAbstractTableModel):
    def __init__(self, df, row_labels=None):
        super().__init__()
        self.df = df
        self.row_labels = row_labels
        if row_labels is not None and len(row_labels)!=len(df):raise ValueError("Record labels must match table rows")
        
    def data(self, index, role):
        if role == Qt.ItemDataRole.DisplayRole:
            value = self.df.iloc[index.row(), index.column()]
            if DISPLAY_PRECISION is not None and isinstance(value,numbers.Real) and not isinstance(value,numbers.Integral) and math.isfinite(value):return f'{value:.{DISPLAY_PRECISION}f}'
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
                return str(self.row_labels[section] if self.row_labels is not None else self.df.index[section])
