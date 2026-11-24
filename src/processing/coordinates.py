"""Convert survey coordinates to decimal degrees (WGS 84), which the maps, UTM projection and IGRF model need.

Formats (the `fmt` names are stored with each survey):
    'decimal_degrees'  45.123456 / -75.654321
    'degrees_minutes'  45°07.407'N, 45 07.407 N, -75 39.15, or NMEA style 4507.407 / 07539.150
    'dms'              45°07'24.4"N, 45 7 24.4 N, -75 39 9, or packed 450724.4
    'projected'        easting / northing in metres in a projected CRS given by its EPSG code (e.g. 32618 = UTM 18N)
"""
import re
import numpy as np
import pandas as pd
from pyproj import CRS, Transformer

FORMATS = {
    'decimal_degrees': 'Decimal degrees',
    'degrees_minutes': 'Degrees + decimal minutes',
    'dms': 'Degrees-minutes-seconds',
    'projected': 'Projected metres (UTM / EPSG)',
}
DEFAULT_FORMAT = 'decimal_degrees'

_NUMBER = re.compile(r'[-+]?\d+(?:\.\d+)?')


def _parse_angle(value, minutes_parts):
    """One angle written as degrees with minutes (minutes_parts=2) or minutes and seconds (3)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    text = str(value).strip()
    if not text:
        return np.nan
    upper = text.upper()
    negative = text.startswith('-') or bool(re.search(r'[SW]', upper))
    numbers = [abs(float(n)) for n in _NUMBER.findall(text)]
    if not numbers:
        raise ValueError(f'Cannot read the coordinate "{text}".')
    if len(numbers) == 1:
        # packed without separators: NMEA dddmm.mmmm or dddmmss.s
        packed = numbers[0]
        if minutes_parts == 2:
            degrees = int(packed // 100)
            numbers = [degrees, packed - degrees * 100]
        else:
            degrees = int(packed // 10000)
            minutes = int((packed - degrees * 10000) // 100)
            numbers = [degrees, minutes, packed - degrees * 10000 - minutes * 100]
    if len(numbers) > minutes_parts:
        raise ValueError(f'The coordinate "{text}" has more parts than expected for this format.')
    degrees = numbers[0]
    minutes = numbers[1] if len(numbers) > 1 else 0.0
    seconds = numbers[2] if len(numbers) > 2 else 0.0
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f'The coordinate "{text}" has minutes or seconds of 60 or more; check the coordinate format.')
    angle = degrees + minutes / 60 + seconds / 3600
    return -angle if negative else angle


def angles_to_decimal_degrees(values, fmt):
    """Series of latitudes or longitudes in fmt -> decimal degrees."""
    series = pd.Series(values)
    if fmt == 'decimal_degrees':
        return pd.to_numeric(series, errors='coerce').to_numpy(dtype=float)
    parts = {'degrees_minutes': 2, 'dms': 3}.get(fmt)
    if parts is None:
        raise ValueError(f'Unknown angle format: {fmt}')
    return np.array([_parse_angle(v, parts) for v in series], dtype=float)


def to_decimal_degrees(first, second, fmt, epsg=None):
    """Two coordinate columns -> (latitude, longitude) in decimal degrees.

    For angle formats, first/second are latitude/longitude; for 'projected' they are easting/northing in metres.
    """
    if fmt == 'projected':
        if not epsg:
            raise ValueError('Enter the EPSG code of the projected coordinates (e.g. 32618 for UTM zone 18N).')
        try:
            source = CRS.from_epsg(int(epsg))
        except Exception as exc:
            raise ValueError(f'EPSG:{epsg} is not a coordinate reference system pyproj recognises.') from exc
        if not source.is_projected:
            raise ValueError(f'EPSG:{epsg} ({source.name}) is not a projected system in metres.')
        east = pd.to_numeric(pd.Series(first), errors='coerce').to_numpy(dtype=float)
        north = pd.to_numeric(pd.Series(second), errors='coerce').to_numpy(dtype=float)
        lon, lat = Transformer.from_crs(source, 'EPSG:4326', always_xy=True).transform(east, north)
        lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    else:
        lat, lon = angles_to_decimal_degrees(first, fmt), angles_to_decimal_degrees(second, fmt)
    valid = np.isfinite(lat) & np.isfinite(lon)
    if not valid.any():
        raise ValueError('No coordinates could be read in the chosen format.')
    if (np.abs(lat[valid]) > 90).any() or (np.abs(lon[valid]) > 180).any():
        raise ValueError('Some converted coordinates are outside ±90° latitude / ±180° longitude; '
                         'check the coordinate format, the column order and (for projected data) the EPSG code.')
    return lat, lon
