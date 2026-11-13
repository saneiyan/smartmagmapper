"""Units and display names for the magnetic field and its components.

Magnetic values are kept exactly as recorded, in the unit chosen when the survey is imported. The data columns are
unit-free (BT, X, Y, Z) and the unit is stored with the survey; everything people see (dropdowns, axes, colour bars,
table headers, exported column names) shows that unit. The Filter Lab keeps its internal signal names
('Total magnitude', 'X', ...) for projects and filter settings.
"""
import math
import re

# Magnetic field units offered on import: name -> size in tesla
MAG_UNITS = {'nT': 1e-9, 'µT': 1e-6, 'mT': 1e-3, 'T': 1.0, 'G': 1e-4, 'mG': 1e-7}
UNIT_NAMES = {'nT': 'nanotesla', 'µT': 'microtesla', 'mT': 'millitesla', 'T': 'tesla', 'G': 'gauss', 'mG': 'milligauss'}
DEFAULT_UNIT = 'µT'

# Data columns that hold magnetic field values (the column names carry no unit)
FIELD_COLUMNS = ['BT', 'X', 'Y', 'Z']
COMPONENTS = ['X', 'Y', 'Z']
# Other magnetic-valued columns that get the unit in exports
UNIT_COLUMNS = FIELD_COLUMNS + ['Analysis_Field', 'Background_BT', 'Residual_BT']

_display_unit = DEFAULT_UNIT


def set_display_unit(unit):
    """Unit used for labels on screen: the active survey's unit (unknown units fall back to the default)."""
    global _display_unit
    _display_unit = unit if unit in MAG_UNITS else DEFAULT_UNIT


def display_unit():
    return _display_unit


def unit_factor(from_unit, to_unit):
    """Multiply values in from_unit by this to express them in to_unit (e.g. nT -> µT is 0.001)."""
    return MAG_UNITS[from_unit] / MAG_UNITS[to_unit]


_UNIT_WORDS = {'nt': 'nT', 'nanotesla': 'nT', 'ut': 'µT', 'microtesla': 'µT', 'mt': 'mT', 'millitesla': 'mT',
               't': 'T', 'tesla': 'T', 'g': 'G', 'gauss': 'G', 'mg': 'mG', 'milligauss': 'mG'}


def detect_unit(*names):
    """Unit written in brackets in a column header, e.g. 'X (nT)' or 'Magnetometer_X [uT]'; None if absent."""
    for name in names:
        for token in re.findall(r'[\(\[]\s*([A-Za-zµμ]+)\s*[\)\]]', str(name)):
            unit = _UNIT_WORDS.get(token.replace('µ', 'u').replace('μ', 'u').lower())
            if unit is not None:
                return unit
    return None


def total_field_label(unit=None):
    return f'Total Magnetic Field (BT) ({unit or _display_unit})'


def field_label(column, unit=None, short=False):
    """Label for a data column; columns that are not magnetic field values are shown as they are."""
    unit = unit or _display_unit
    column = str(column)
    if column == 'BT':
        return f'BT ({unit})' if short else total_field_label(unit)
    if column in COMPONENTS:
        return f'{column} ({unit})'
    return column


def signal_label(signal, unit=None):
    """Label for a Filter Lab signal name such as 'Total magnitude' or 'X'."""
    if signal == 'Total magnitude':
        return total_field_label(unit)
    if signal in COMPONENTS:
        return f'{signal} ({unit or _display_unit})'
    return str(signal)


def difference_label(unit=None):
    return f'Difference ({unit or _display_unit})'


def export_name(column, unit):
    """Column name for exported files: magnetic columns get their unit, e.g. 'X' -> 'X (nT)'."""
    return f'{column} ({unit})' if column in UNIT_COLUMNS else column


def with_units(frame, unit):
    """Copy of frame for export, with the unit added to the names of magnetic-valued columns."""
    return frame.rename(columns={column: export_name(column, unit) for column in frame.columns if column in UNIT_COLUMNS})


def format_value(value, digits=4):
    """Readable number in any unit: fixed decimals for ordinary sizes, scientific notation for very small or large."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(value) or value == 0:
        return f'{value:g}'
    if 1e-3 <= abs(value) < 1e7:
        return f'{value:.{digits}f}'.rstrip('0').rstrip('.') if digits else f'{value:.0f}'
    return f'{value:.{digits}e}'


def nice_range(low, high):
    """Round a data range outward to a tidy step (about 1/100 of the range) in any unit; returns (low, high, step)."""
    span = abs(high - low) or abs(high) or 1.0
    step = 10 ** math.floor(math.log10(span / 100))
    return math.floor(low / step) * step, math.ceil(high / step) * step, step


def step_decimals(step):
    """Decimal places needed to show values rounded to `step`."""
    return max(0, -math.floor(math.log10(step))) if step > 0 else 0
