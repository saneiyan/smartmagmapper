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
UNIT_COLUMNS = FIELD_COLUMNS + ['Analysis_Field']

_display_unit = DEFAULT_UNIT


def set_display_unit(unit):
    """Set the magnetic unit used for labels on screen (the active survey's unit).

    Parameters
    ----------
    unit : str
        One of the keys of MAG_UNITS, e.g. 'nT'. Unknown units fall back to DEFAULT_UNIT.
    """
    global _display_unit
    _display_unit = unit if unit in MAG_UNITS else DEFAULT_UNIT


def display_unit():
    """Magnetic unit currently used for on-screen labels.

    Returns
    -------
    str
        Unit symbol, e.g. 'µT'.
    """
    return _display_unit


def unit_factor(from_unit, to_unit):
    """Conversion factor between two magnetic units.

    Parameters
    ----------
    from_unit, to_unit : str
        Keys of MAG_UNITS.

    Returns
    -------
    float
        Multiply values in `from_unit` by this to express them in `to_unit` (e.g. nT -> µT is 0.001).
    """
    return MAG_UNITS[from_unit] / MAG_UNITS[to_unit]


_UNIT_WORDS = {'nt': 'nT', 'nanotesla': 'nT', 'ut': 'µT', 'microtesla': 'µT', 'mt': 'mT', 'millitesla': 'mT',
               't': 'T', 'tesla': 'T', 'g': 'G', 'gauss': 'G', 'mg': 'mG', 'milligauss': 'mG'}


def detect_unit(*names):
    """Find a magnetic unit written in brackets in column headers.

    Parameters
    ----------
    *names : str
        Column headers to search, e.g. 'X (nT)' or 'Magnetometer_X [uT]'. The first recognised unit wins.

    Returns
    -------
    str or None
        Unit symbol (a key of MAG_UNITS), or None if no header names a unit.
    """
    for name in names:
        for token in re.findall(r'[\(\[]\s*([A-Za-zµμ]+)\s*[\)\]]', str(name)):
            unit = _UNIT_WORDS.get(token.replace('µ', 'u').replace('μ', 'u').lower())
            if unit is not None:
                return unit
    return None


def total_field_label(unit=None):
    """Display name of the total magnetic field.

    Parameters
    ----------
    unit : str, optional
        Unit to show; defaults to the display unit.

    Returns
    -------
    str
        For example 'Total Magnetic Field (BT) (nT)'.
    """
    return f'Total Magnetic Field (BT) ({unit or _display_unit})'


def field_label(column, unit=None, short=False):
    """Display name of a data column, with the unit for magnetic field columns.

    Parameters
    ----------
    column : str
        Data column name, e.g. 'BT', 'X' or 'Easting (m)'.
    unit : str, optional
        Unit to show; defaults to the display unit.
    short : bool, optional
        Use 'BT (unit)' instead of the long total-field name (for table headers and legends).

    Returns
    -------
    str
        The label; columns that are not magnetic field values are returned unchanged.
    """
    unit = unit or _display_unit
    column = str(column)
    if column == 'BT':
        return f'BT ({unit})' if short else total_field_label(unit)
    if column in COMPONENTS:
        return f'{column} ({unit})'
    return column


def signal_label(signal, unit=None):
    """Display name of a Filter Lab signal.

    Parameters
    ----------
    signal : str
        Internal signal name: 'Total magnitude', 'X', 'Y', 'Z' or 'Current result'.
    unit : str, optional
        Unit to show; defaults to the display unit.

    Returns
    -------
    str
        For example 'Total Magnetic Field (BT) (nT)' or 'X (nT)'.
    """
    if signal == 'Total magnitude':
        return total_field_label(unit)
    if signal in COMPONENTS:
        return f'{signal} ({unit or _display_unit})'
    return str(signal)


def difference_label(unit=None):
    """Axis label for after-minus-before differences.

    Parameters
    ----------
    unit : str, optional
        Unit to show; defaults to the display unit.

    Returns
    -------
    str
        For example 'Difference (nT)'.
    """
    return f'Difference ({unit or _display_unit})'


def export_name(column, unit):
    """Column name used in exported files.

    Parameters
    ----------
    column : str
        Data column name.
    unit : str
        The survey's magnetic unit.

    Returns
    -------
    str
        Magnetic columns get their unit, e.g. 'X' -> 'X (nT)'; other columns are unchanged.
    """
    return f'{column} ({unit})' if column in UNIT_COLUMNS else column


def with_units(frame, unit):
    """Copy of a data frame for export, with units added to magnetic column names.

    Parameters
    ----------
    frame : pandas.DataFrame
        Survey data with unit-free columns (BT, X, Y, Z, Analysis_Field).
    unit : str
        The survey's magnetic unit.

    Returns
    -------
    pandas.DataFrame
        Renamed copy, e.g. with 'BT (nT)' instead of 'BT'.
    """
    return frame.rename(columns={column: export_name(column, unit) for column in frame.columns if column in UNIT_COLUMNS})


def format_value(value, digits=4):
    """Readable number in any unit.

    Parameters
    ----------
    value : float
        Number to format (other values are returned with str()).
    digits : int, optional
        Decimal places (fixed notation) or significant decimals (scientific notation).

    Returns
    -------
    str
        Fixed decimals with trailing zeros removed for ordinary sizes; scientific notation below 1e-3 or from 1e7.
    """
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
    """Round a data range outward to a tidy step of about 1/100 of the range.

    Parameters
    ----------
    low, high : float
        Data minimum and maximum, in any unit.

    Returns
    -------
    low : float
        Rounded-down minimum.
    high : float
        Rounded-up maximum.
    step : float
        The power of ten used for rounding.
    """
    span = abs(high - low) or abs(high) or 1.0
    step = 10 ** math.floor(math.log10(span / 100))
    return math.floor(low / step) * step, math.ceil(high / step) * step, step


def step_decimals(step):
    """Decimal places needed to show values rounded to a step.

    Parameters
    ----------
    step : float
        Rounding step, e.g. 0.01.

    Returns
    -------
    int
        Number of decimals (0 for steps of 1 or more).
    """
    return max(0, -math.floor(math.log10(step))) if step > 0 else 0
