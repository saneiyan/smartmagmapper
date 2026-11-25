"""Read-only Qt table model for showing pandas data frames in the data tables.

DISPLAY_PRECISION (set from Tools > Settings) is the number of decimals shown; None shows values as they are.
Display rounding never changes the data or exports.
"""
from PyQt6 import QtCore
from PyQt6.QtCore import Qt
import numbers,math
from processing.labels import field_label
DISPLAY_PRECISION = None

class TableModel(QtCore.QAbstractTableModel):
    """Read-only Qt table model over a pandas DataFrame.

    Parameters
    ----------
    df : pandas.DataFrame
        Data to show.
    row_labels : sequence, optional
        Row header labels (e.g. synchronized record numbers); defaults to the frame's index.

    Raises
    ------
    ValueError
        If `row_labels` does not have one label per row.
    """
    def __init__(self, df, row_labels=None):
        """Keep the data frame and the optional row labels (see the class description)."""
        super().__init__()
        self.df = df
        self.row_labels = row_labels
        if row_labels is not None and len(row_labels)!=len(df):raise ValueError("Record labels must match table rows")
        
    def data(self, index, role):
        """Cell text (DisplayRole, rounded to DISPLAY_PRECISION) or raw value (EditRole, used for sorting).

        Parameters
        ----------
        index : QModelIndex
            Cell.
        role : Qt.ItemDataRole
            Requested role.

        Returns
        -------
        object
            Text, value, or None for other roles.
        """
        if role == Qt.ItemDataRole.DisplayRole:
            value = self.df.iloc[index.row(), index.column()]
            if DISPLAY_PRECISION is not None and isinstance(value,numbers.Real) and not isinstance(value,numbers.Integral) and math.isfinite(value):
                # very small or very large values (e.g. tesla) in scientific notation so they do not show as 0.0000
                if value != 0 and not 10**-DISPLAY_PRECISION <= abs(value) < 1e9:return f'{value:.{DISPLAY_PRECISION}e}'
                return f'{value:.{DISPLAY_PRECISION}f}'
            return str(value)
        if role == Qt.ItemDataRole.EditRole:
            value = self.df.iloc[index.row(), index.column()]
            if hasattr(value, 'item'):
                return value.item()
            return value
    
    def rowCount(self, index):
        """Number of rows.

        Parameters
        ----------
        index : QModelIndex
            Parent index (unused; the table is flat).

        Returns
        -------
        int
            Number of rows in the data frame.
        """
        return self.df.shape[0]
    
    def columnCount(self, index):
        """Number of columns.

        Parameters
        ----------
        index : QModelIndex
            Parent index (unused; the table is flat).

        Returns
        -------
        int
            Number of columns in the data frame.
        """
        return self.df.shape[1]
    
    def headerData(self, section, orientation, role):
        """Column names (magnetic columns with their unit) and row numbers counted from 1.

        Parameters
        ----------
        section : int
            Column or row number.
        orientation : Qt.Orientation
            Horizontal for column headers, vertical for row headers.
        role : Qt.ItemDataRole
            Only DisplayRole is answered.

        Returns
        -------
        str or None
            Header text.
        """
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                # display name with units for the total field (the data keeps its column name)
                return field_label(self.df.columns[section], short=True)
            
            if orientation == Qt.Orientation.Vertical:
                label = self.row_labels[section] if self.row_labels is not None else self.df.index[section]
                # Rows are numbered from 1 on screen; the data keep their 0-based index.
                if isinstance(label, numbers.Integral):
                    label = label + 1
                return str(label)
