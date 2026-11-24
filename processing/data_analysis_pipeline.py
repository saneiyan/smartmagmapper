"""Survey import, synchronization, cleaning and automated anomaly analysis (no PyQt; usable from scripts).

Typical use::

    from processing import data_analysis_pipeline as dap
    mag, gps = dap.read_survey_file('survey.xlsx')
    cleaned, audit = dap.clean_survey(mag, gps, dap.AnalysisParams())

Magnetic values are used in whatever unit they were recorded in; every step is scale-invariant, so nT, µT, mT,
T, G and mG surveys give the same anomalies and candidate locations.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pyproj import Transformer
from sklearn.cluster import DBSCAN
from processing import labels

try:
    from vmdpy import VMD
except Exception:
    VMD = None


def utm_epsg(lat: float, lon: float) -> int:
    """EPSG code of the WGS 84 UTM zone containing a position.

    Parameters
    ----------
    lat, lon : float
        Position in decimal degrees.

    Returns
    -------
    int
        For example 32618 for zone 18N (326xx north, 327xx south).
    """
    zone = min(max(int((float(lon) + 180.0) // 6.0) + 1, 1), 60)
    return (32600 if float(lat) >= 0 else 32700) + zone


def utm_zone_label(epsg: int) -> str:
    """Readable UTM zone name for an EPSG code from utm_epsg.

    Parameters
    ----------
    epsg : int
        WGS 84 UTM EPSG code, e.g. 32618.

    Returns
    -------
    str
        For example '18N'.
    """
    return f"{epsg % 100}{'N' if epsg < 32700 else 'S'}"


@lru_cache(maxsize=None)
def _utm_transformers(epsg: int) -> tuple[Transformer, Transformer]:
    """Cached coordinate transformers between WGS 84 and a UTM zone.

    Parameters
    ----------
    epsg : int
        WGS 84 UTM EPSG code.

    Returns
    -------
    to_utm : pyproj.Transformer
        (longitude, latitude) -> (easting, northing).
    to_wgs84 : pyproj.Transformer
        (easting, northing) -> (longitude, latitude).
    """
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    to_wgs84 = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    return to_utm, to_wgs84


def survey_epsg(df: pd.DataFrame) -> int:
    """UTM zone chosen for a survey by clean_survey, stored so every step uses the same zone.

    Parameters
    ----------
    df : pandas.DataFrame
        Cleaned survey with a 'UTM_EPSG' column.

    Returns
    -------
    int
        EPSG code of the survey's UTM zone.
    """
    return int(df["UTM_EPSG"].iloc[0])


@dataclass
class AnalysisParams:
    #optional coordinates of a known reference location (e.g. a known target), used only for display and offsets, never for candidate selection
    """Settings for cleaning and automated anomaly analysis.

    Attributes
    ----------
    reference_lat, reference_lon : float or None
        Optional known reference location (e.g. a known target) in decimal degrees. Used only for display and
        offsets, never for choosing the candidate.
    startup_samples : int
        Synchronized samples removed at the start of the survey.
    spatial_mad_multiplier : float
        Positions farther than median radius + multiplier x radial MAD from the survey centre are rejected.
    spatial_fallback_percentile : float
        Radial percentile limit used instead when the radial MAD is zero.
    window_length_m : float
        Length of the anomaly-score windows along the survey path, in metres.
    step_ratio : float
        Window step as a fraction of the window length.
    gamma : float
        Score threshold = median + gamma x MAD of the window scores.
    dbscan_eps_m : float
        DBSCAN neighbourhood radius for grouping hit windows, in metres.
    dbscan_min_samples : int
        DBSCAN minimum number of hit windows per cluster.
    vmd_modes : int
        Number of VMD modes.
    vmd_alpha : float
        VMD bandwidth penalty.
    max_selected_modes : int
        Maximum number of modes kept for scoring.
    support_fraction : float
        A cluster needs at least this fraction of the largest cluster's windows to be eligible as the candidate.
    min_support_points : int
        Minimum number of windows for an eligible cluster.
    """
    reference_lat: float | None = None
    reference_lon: float | None = None
    startup_samples: int = 10
    spatial_mad_multiplier: float = 6.0
    spatial_fallback_percentile: float = 95.0
    window_length_m: float = 5.0
    step_ratio: float = 0.25
    gamma: float = 2.0
    dbscan_eps_m: float = 4.0
    dbscan_min_samples: int = 5
    vmd_modes: int = 10
    vmd_alpha: float = 2000.0
    max_selected_modes: int = 2
    support_fraction: float = 0.30
    min_support_points: int = 5

    @property
    def reference_known(self) -> bool:
        """True when both reference coordinates were entered."""
        return self.reference_lat is not None and self.reference_lon is not None


def reference_utm(params: AnalysisParams, epsg: int) -> tuple[float, float] | None:
    """Reference location in the survey's UTM zone.

    Parameters
    ----------
    params : AnalysisParams
        Settings holding the optional reference latitude and longitude.
    epsg : int
        The survey's UTM EPSG code.

    Returns
    -------
    tuple of float or None
        (easting, northing) in metres, or None if no reference was entered.
    """
    if not params.reference_known:
        return None
    east, north = _utm_transformers(epsg)[0].transform(params.reference_lon, params.reference_lat)
    return float(east), float(north)


def add_reference_distance(df: pd.DataFrame, params: AnalysisParams) -> pd.DataFrame:
    """Add each point's distance to the entered reference location.

    Parameters
    ----------
    df : pandas.DataFrame
        Cleaned survey with Easting/Northing columns.
    params : AnalysisParams
        Settings holding the optional reference location.

    Returns
    -------
    pandas.DataFrame
        Copy with a 'Distance_to_Reference_m' column, or `df` itself when no reference was entered.
    """
    reference = reference_utm(params, survey_epsg(df))
    if reference is None:
        return df
    out = df.copy()
    out["Distance_to_Reference_m"] = np.hypot(
        out["Easting (m)"].to_numpy(dtype=float) - reference[0],
        out["Northing (m)"].to_numpy(dtype=float) - reference[1],
    )
    return out


def _flat_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Copy of a data frame with string column names (MultiIndex headers joined with '_').

    Parameters
    ----------
    df : pandas.DataFrame
        Table read from a survey file.

    Returns
    -------
    pandas.DataFrame
        Copy with flat, string column names.
    """
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = ["_".join(str(part) for part in col if str(part) != "nan").strip("_") for col in out.columns]
    else:
        out.columns = [str(col) for col in out.columns]
    return out


def _norm(text: Any) -> str:
    """Normalise a column name for matching: lower case, no spaces, brackets, underscores or degree signs.

    Parameters
    ----------
    text : object
        Column name or alias.

    Returns
    -------
    str
        Normalised text ('µ' becomes 'u', 'deg' becomes 'degree').
    """
    return (
        str(text)
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
        .replace("[", "")
        .replace("]", "")
        .replace("deg", "degree")
        .replace("degrees", "degree")
        .replace("Â", "")
        .replace("µ", "u")
        .replace("μ", "u")
        .replace("°", "")
    )


def _find_column(df: pd.DataFrame, aliases: list[str], required: bool = True) -> str | None:
    """Find the column matching one of several aliases.

    Exact (normalised) matches are tried first, then partial matches; names shorter than three characters
    only match exactly, so 'X' never matches 'Max'.

    Parameters
    ----------
    df : pandas.DataFrame
        Table to search.
    aliases : list of str
        Accepted names, most specific first.
    required : bool, optional
        Raise if nothing matches.

    Returns
    -------
    str or None
        The matching column name, or None when not found and not required.

    Raises
    ------
    ValueError
        If `required` and no column matches.
    """
    normalized = {_norm(col): col for col in df.columns}
    for alias in aliases:
        key = _norm(alias)
        if key in normalized:
            return normalized[key]
    fuzzy = [_norm(alias) for alias in aliases if len(_norm(alias)) >= 3]
    for col in df.columns:
        key = _norm(col)
        if len(key) >= 3 and any(alias in key or key in alias for alias in fuzzy):
            return col
    if required:
        raise ValueError(f"Missing required column. Tried aliases: {aliases}")
    return None


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Copy of a data frame with every column converted to numbers (unreadable values become NaN).

    Parameters
    ----------
    df : pandas.DataFrame
        Table to convert.

    Returns
    -------
    pandas.DataFrame
        Numeric copy.
    """
    out = df.copy()
    for col in out.columns:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


_UNIT_TAGS = ["uT", "µT", "nT", "mT", "T", "G", "mG"]


def _standardize_magnetometer(df: pd.DataFrame) -> pd.DataFrame:
    """Magnetometer stream with unit-free columns Mag_Time (s) and X, Y, Z (or BT for scalar data).

    Values are kept as recorded. The unit written in the source headers (e.g. 'X (nT)'), if any, is put in
    out.attrs['field_unit'] (None when the headers give no unit).

    Parameters
    ----------
    df : pandas.DataFrame
        Raw magnetometer table.

    Returns
    -------
    pandas.DataFrame
        Standardised stream without non-finite rows.

    Raises
    ------
    ValueError
        If no time column or magnetic field column can be found.
    """
    df = _flat_columns(df)
    time_col = _find_column(df, ["Mag_Time (s)", "Magnetometer_Time (s)", "Time (s)", "time"])
    components = [
        _find_column(df, [axis] + [f"{axis} ({unit})" for unit in _UNIT_TAGS]
                     + [f"Magnetic field {axis.lower()} (uT)", f"Magnetometer_{axis} (uT)", f"B{axis}"], required=False)
        for axis in "XYZ"
    ]
    if all(col is not None for col in components):
        source = components
        out = df[[time_col] + components].copy()
        out.columns = ["Mag_Time (s)", "X", "Y", "Z"]
    else:
        scalar = _find_column(df, ["BT"] + [f"BT ({unit})" for unit in _UNIT_TAGS]
                              + ["Total_Field_uT", "Total magnetic field (uT)", "Magnetic field (uT)", "B (uT)"])
        source = [scalar]
        out = df[[time_col, scalar]].copy()
        out.columns = ["Mag_Time (s)", "BT"]
    out = _coerce_numeric(out).replace([np.inf, -np.inf], np.nan).dropna()
    out.attrs["field_unit"] = labels.detect_unit(*source) or ("µT" if any("Total_Field_uT" == s for s in source) else None)
    return out


def _standardize_location(df: pd.DataFrame) -> pd.DataFrame:
    """GPS stream with columns Loc_Time (s), Latitude (°) and Longitude (°).

    Parameters
    ----------
    df : pandas.DataFrame
        Raw GPS table (coordinates in decimal degrees).

    Returns
    -------
    pandas.DataFrame
        Standardised stream without rows missing a time or coordinate.

    Raises
    ------
    ValueError
        If the time, latitude or longitude column cannot be found.
    """
    df = _flat_columns(df)
    time_col = _find_column(df, ["Loc_Time (s)", "Location_Time (s)", "GPS Time", "Time (s)", "time"])
    lat_col = _find_column(df, ["Latitude (degree)", "Latitude (°)", "Location_Latitude (°)", "latitude", "lat"])
    lon_col = _find_column(df, ["Longitude (degree)", "Longitude (°)", "Location_Longitude (°)", "longitude", "lon"])
    out = df[[time_col, lat_col, lon_col]].copy()
    out.columns = ["Loc_Time (s)", "Latitude (°)", "Longitude (°)"]
    return _coerce_numeric(out).dropna(subset=["Loc_Time (s)", "Latitude (°)", "Longitude (°)"])


def _find_standard_sheet(sheets: dict[str, pd.DataFrame], kind: str) -> pd.DataFrame | None:
    """Find the magnetometer or GPS sheet of an Excel workbook by its name or headers.

    Parameters
    ----------
    sheets : dict of str to pandas.DataFrame
        Workbook sheets.
    kind : {'mag', 'loc'}
        Which sheet to look for.

    Returns
    -------
    pandas.DataFrame or None
        The sheet, or None if none matches.
    """
    for name, df in sheets.items():
        lower_name = str(name).lower()
        cols = " ".join(str(col).lower() for col in df.columns)
        if kind == "mag" and ("magnet" in lower_name or ("x" in cols and "z" in cols and "µt" in cols)):
            return df
        if kind == "loc" and ("location" in lower_name or ("latitude" in cols and "longitude" in cols)):
            return df
    return None


def read_survey_file(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read a survey file into standardised magnetometer and GPS streams.

    Excel workbooks may hold the streams on separate sheets (e.g. 'Magnetometer' and 'Location') or on one;
    CSV and text files hold both in one table. Coordinates must be in decimal degrees (the Import Data dialog
    converts other formats).

    Parameters
    ----------
    path : str or pathlib.Path
        .xls, .xlsx, .xlsm, .csv or .txt file.

    Returns
    -------
    mag : pandas.DataFrame
        Magnetometer stream (see _standardize_magnetometer); mag.attrs['field_unit'] holds a unit found in the headers.
    gps : pandas.DataFrame
        GPS stream (see _standardize_location).

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        For unsupported file types or missing columns.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix in {".xls", ".xlsx", ".xlsm"}:
        sheets = pd.read_excel(path, sheet_name=None)
        mag_sheet = _find_standard_sheet(sheets, "mag")
        loc_sheet = _find_standard_sheet(sheets, "loc")
        if mag_sheet is not None and loc_sheet is not None:
            return _standardize_magnetometer(mag_sheet), _standardize_location(loc_sheet)
        first = next(iter(sheets.values()))
        return _standardize_magnetometer(first), _standardize_location(first)
    if suffix in {".csv", ".txt"}:
        df = pd.read_csv(path, sep=None, engine="python")
        return _standardize_magnetometer(df), _standardize_location(df)
    raise ValueError(f"Unsupported survey file type: {path.suffix}")


def clean_survey(magdf: pd.DataFrame, gpsdf: pd.DataFrame, params: AnalysisParams, *, synchronized_only=False) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Synchronize the magnetometer with GPS positions, project to UTM and remove unreliable samples.

    Positions are linearly interpolated in time onto the magnetometer samples. The whole survey is projected
    into the UTM zone of its median position. Cleaning then removes the first `startup_samples` samples and
    positions farther from the survey centre than median radius + `spatial_mad_multiplier` x radial MAD (a
    radial percentile when the MAD is zero). For vector data BT is computed from X, Y and Z.

    Parameters
    ----------
    magdf, gpsdf : pandas.DataFrame
        Magnetometer and GPS streams (raw or standardised).
    params : AnalysisParams
        Cleaning settings.
    synchronized_only : bool, optional
        Only synchronize and project (no startup or position removal), e.g. to show the data before cleaning.

    Returns
    -------
    cleaned : pandas.DataFrame
        Survey with Time (s), BT (and X, Y, Z), Latitude (°), Longitude (°), Easting (m), Northing (m),
        UTM_EPSG and Distance (m) along the path.
    audit : dict
        Row counts before and after each step, the position limit in metres and the rule used.

    Raises
    ------
    ValueError
        If a stream is empty, coordinates are outside the UTM range, no magnetometer sample falls within the GPS
        time range, or fewer than 8 samples remain.
    """
    mag = _standardize_magnetometer(magdf)
    gps = _standardize_location(gpsdf).replace([np.inf, -np.inf], np.nan).dropna()
    if mag.empty or gps.empty:
        raise ValueError("The survey needs valid magnetic and location records.")
    if not gps["Latitude (°)"].between(-80, 84).all() or not gps["Longitude (°)"].between(-180, 180).all():
        raise ValueError("UTM analysis requires latitude between -80 and 84 and longitude between -180 and 180 degrees.")

    mag = mag.sort_values("Mag_Time (s)").drop_duplicates("Mag_Time (s)").reset_index(drop=True)
    gps = gps.sort_values("Loc_Time (s)").drop_duplicates("Loc_Time (s)").reset_index(drop=True)
    # BT is the single total-field column (vector surveys compute it; scalar surveys already have it).
    if all(col in mag.columns for col in ["X", "Y", "Z"]):
        mag["BT"] = np.sqrt(mag["X"] ** 2 + mag["Y"] ** 2 + mag["Z"] ** 2)

    gt = gps["Loc_Time (s)"].to_numpy(dtype=float)
    mt = mag["Mag_Time (s)"].to_numpy(dtype=float)
    lat = gps["Latitude (°)"].to_numpy(dtype=float)
    lon = gps["Longitude (°)"].to_numpy(dtype=float)
    valid = (mt >= np.nanmin(gt)) & (mt <= np.nanmax(gt))
    mag["Latitude (°)"] = np.nan
    mag["Longitude (°)"] = np.nan
    mag.loc[valid, "Latitude (°)"] = np.interp(mt[valid], gt, lat)
    mag.loc[valid, "Longitude (°)"] = np.interp(mt[valid], gt, lon)

    # Synchronized samples are on the magnetometer clock; from here on that is the survey's "Time (s)".
    interpolated = (mag.dropna(subset=["Latitude (°)", "Longitude (°)"]).reset_index(drop=True)
                    .rename(columns={"Mag_Time (s)": "Time (s)"}))
    before_startup = len(interpolated)
    startup = 0 if synchronized_only else max(0, int(params.startup_samples))
    if startup:
        interpolated = interpolated.iloc[startup:].reset_index(drop=True)

    if interpolated.empty:
        raise ValueError("No magnetometer samples fall within the GPS time range, so no positions could be assigned.")

    #one UTM zone for the whole survey, from its median position, so distances stay consistent
    point_lon = interpolated["Longitude (°)"].to_numpy(dtype=float)
    point_lat = interpolated["Latitude (°)"].to_numpy(dtype=float)
    epsg = utm_epsg(np.nanmedian(point_lat), np.nanmedian(point_lon))
    east, north = _utm_transformers(epsg)[0].transform(point_lon, point_lat)
    interpolated["Easting (m)"] = east
    interpolated["Northing (m)"] = north
    interpolated["UTM_EPSG"] = epsg

    med_e = float(np.nanmedian(east))
    med_n = float(np.nanmedian(north))
    radial = np.sqrt((east - med_e) ** 2 + (north - med_n) ** 2)
    med_r = float(np.nanmedian(radial))
    mad_r = robust_mad(radial)
    if mad_r > 0:
        limit = med_r + float(params.spatial_mad_multiplier) * mad_r
    else:
        limit = float(np.nanpercentile(radial, params.spatial_fallback_percentile))
    keep = np.ones(len(radial), dtype=bool) if synchronized_only else radial <= limit
    cleaned = interpolated.loc[keep].reset_index(drop=True)
    if len(cleaned) < 8:
        raise ValueError("Fewer than 8 samples remain after synchronization and cleaning. Check timestamps and startup removal.")

    cleaned["Distance (m)"] = np.sqrt(
        cleaned["Easting (m)"].diff().fillna(0) ** 2 + cleaned["Northing (m)"].diff().fillna(0) ** 2
    ).cumsum()

    audit = {
        "raw_mag_rows": int(len(magdf)),
        "raw_location_rows": int(len(gpsdf)),
        "interpolated_rows": int(before_startup),
        "startup_removed": int(min(startup, before_startup)),
        "spatial_removed": int((~keep).sum()),
        "cleaned_rows": int(len(cleaned)),
        "spatial_limit_m": float(limit),
        "spatial_rule": "MAD" if mad_r > 0 else "percentile fallback",
        "fallback_percentile": float(params.spatial_fallback_percentile),
    }
    return cleaned, audit


def _typical_band(values: np.ndarray) -> tuple[float, float]:
    """Typical value and tolerance of a series of steps.

    Parameters
    ----------
    values : numpy.ndarray
        For example sampling intervals, step lengths or field changes.

    Returns
    -------
    median : float
        Median of the values.
    tolerance : float
        3 robust standard deviations, never tighter than 20 % of the median.
    """
    median = float(np.nanmedian(values))
    sigma = 1.4826 * robust_mad(values)
    return median, max(3.0 * sigma, 0.2 * abs(median))


def suggest_cleaning_settings(magdf: pd.DataFrame, gpsdf: pd.DataFrame, *, stable_steps: int = 10,
                              max_startup_fraction: float = 0.25) -> dict[str, Any]:
    """Suggest startup removal and the spatial MAD multiplier from how the survey was recorded.

    Startup: samples before the first run of `stable_steps` consecutive steps whose sampling interval, distance
    travelled and change in total field are all typical for the survey (e.g. standing still while GPS settles,
    positions jumping, irregular sampling, magnetometer warm-up spikes or offsets). Never more than
    `max_startup_fraction` of the survey. The magnetic check only flags field changes that are too large, and only
    affects where the startup ends: magnetic anomalies later in the survey are never removed, since they are the
    signal being surveyed.

    MAD multiplier: after startup removal, positions reached by an implausible jump (steps both into and out of the
    position far longer than typical) are treated as off-track; the multiplier is the smallest value (in 0.5 steps,
    plus 0.5 margin) whose radial limit keeps every on-track position. None when the radial MAD is zero
    (the percentile fallback then applies).

    Parameters
    ----------
    magdf, gpsdf : pandas.DataFrame
        Magnetometer and GPS streams.
    stable_steps : int, optional
        Number of consecutive typical steps that marks the end of the startup.
    max_startup_fraction : float, optional
        Largest fraction of the survey that may be suggested as startup.

    Returns
    -------
    dict
        'startup_samples', 'spatial_mad_multiplier' (or None), 'median_interval_s', 'median_step_m',
        'field_change_noise' (in the survey's unit), 'startup_reasons' (failed timing / movement / magnetic checks
        before the cut-off), 'stable_start_found' and 'off_track_samples'.
    """
    sync, _ = clean_survey(magdf, gpsdf, AnalysisParams(), synchronized_only=True)
    t = sync["Time (s)"].to_numpy(dtype=float)
    east = sync["Easting (m)"].to_numpy(dtype=float)
    north = sync["Northing (m)"].to_numpy(dtype=float)
    dt = np.diff(t)
    step = np.hypot(np.diff(east), np.diff(north))
    field_change = np.diff(sync["BT"].to_numpy(dtype=float))
    median_dt, tol_dt = _typical_band(dt)
    median_step, tol_step = _typical_band(step)
    # signed changes are symmetric around the trend, so 3 robust standard deviations means what it says
    median_change, tol_change = _typical_band(field_change)
    timing_ok = np.abs(dt - median_dt) <= tol_dt
    movement_ok = np.abs(step - median_step) <= tol_step if median_step > 0 else np.ones(len(step), dtype=bool)
    # only a change that is too large is abnormal (a steady field is fine)
    magnetic_ok = np.abs(field_change - median_change) <= tol_change if tol_change > 0 else np.ones(len(step), dtype=bool)
    normal = timing_ok & movement_ok & magnetic_ok

    # step i joins sample i to sample i+1; keep from the first sample that starts a stable run
    startup, stable_found = 0, False
    for start in range(0, max(1, int(len(t) * max_startup_fraction)) + 1):
        window = normal[start:start + stable_steps]
        if len(window) == stable_steps and window.all():
            startup, stable_found = start, True
            break

    kept_e, kept_n = east[startup:], north[startup:]
    radial = np.hypot(kept_e - np.nanmedian(kept_e), kept_n - np.nanmedian(kept_n))
    median_r, mad_r = float(np.nanmedian(radial)), robust_mad(radial)
    kept_step = np.hypot(np.diff(kept_e), np.diff(kept_n))
    jump = median_step + tol_step if median_step > 0 else np.inf
    step_in = np.r_[np.nan, kept_step]
    step_out = np.r_[kept_step, np.nan]
    off_track = (step_in > jump) & (step_out > jump)
    multiplier = None
    if mad_r > 0:
        needed = (float(np.nanmax(radial[~off_track])) - median_r) / mad_r
        multiplier = float(min(100.0, max(0.5, np.ceil(needed * 2) / 2 + 0.5)))
    return {
        "startup_samples": int(startup),
        "spatial_mad_multiplier": multiplier,
        "median_interval_s": median_dt,
        "median_step_m": median_step,
        "field_change_noise": 1.4826 * robust_mad(field_change),
        # how many steps before the startup cut-off failed each check (one step can fail several)
        "startup_reasons": {"timing": int((~timing_ok[:startup]).sum()), "movement": int((~movement_ok[:startup]).sum()),
                            "magnetic": int((~magnetic_ok[:startup]).sum())},
        "stable_start_found": stable_found,
        "off_track_samples": int(off_track.sum()),
    }


# Duplicate columns written by earlier versions (alias -> the column it copied).
LEGACY_ALIASES = {"Total_Field_uT": "BT", "Filtered_Field_uT": "BT", "easting": "Easting (m)",
                  "northing": "Northing (m)", "Mag_Time (s)": "Time (s)"}


# Component columns named with a unit by earlier versions (values were in µT).
LEGACY_COMPONENT_NAMES = {"X (µT)": "X", "Y (µT)": "Y", "Z (µT)": "Z"}


def drop_legacy_aliases(frame: pd.DataFrame) -> pd.DataFrame:
    """Bring data saved by earlier versions up to date.

    Duplicate columns (LEGACY_ALIASES) are dropped and component columns named with a unit ('X (µT)') are renamed
    to the unit-free names ('X').

    Parameters
    ----------
    frame : pandas.DataFrame
        Survey table from an older project.

    Returns
    -------
    pandas.DataFrame
        Updated copy.
    """
    frame = frame.drop(columns=[alias for alias, kept in LEGACY_ALIASES.items() if alias in frame and kept in frame])
    return frame.rename(columns={old: new for old, new in LEGACY_COMPONENT_NAMES.items() if old in frame and new not in frame})


def load_and_clean(path: str | Path, params: AnalysisParams) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read and clean a survey file in one step (convenience for scripts).

    Parameters
    ----------
    path : str or pathlib.Path
        Survey file (see read_survey_file).
    params : AnalysisParams
        Cleaning settings.

    Returns
    -------
    tuple
        (cleaned, audit) as returned by clean_survey.
    """
    magdf, gpsdf = read_survey_file(path)
    return clean_survey(magdf, gpsdf, params)


def robust_mad(values: np.ndarray | pd.Series) -> float:
    """Median absolute deviation (unscaled), ignoring NaN.

    Parameters
    ----------
    values : array_like
        Values.

    Returns
    -------
    float
        median(|values - median(values)|).
    """
    arr = np.asarray(values, dtype=float)
    med = np.nanmedian(arr)
    return float(np.nanmedian(np.abs(arr - med)))


def dominant_rate(values: np.ndarray, dt: float) -> float:
    """Frequency of the strongest non-zero spectral peak.

    Parameters
    ----------
    values : numpy.ndarray
        Evenly sampled signal.
    dt : float
        Sample spacing (seconds for time series).

    Returns
    -------
    float
        Dominant frequency in cycles per unit of `dt` (Hz for seconds); 0 for fewer than three samples.
    """
    arr = np.asarray(values, dtype=float) - np.nanmean(values)
    if len(arr) < 3:
        return 0.0
    freqs = np.fft.rfftfreq(len(arr), max(dt, 1e-6))
    power = np.abs(np.fft.rfft(arr)) ** 2
    if len(freqs) <= 1:
        return 0.0
    idx = 1 + int(np.argmax(power[1:]))
    return float(freqs[idx])


def spectral_flatness(values: np.ndarray) -> float:
    """Spectral flatness (geometric / arithmetic mean of the power spectrum).

    Close to 1 for noise-like signals, close to 0 for signals dominated by a few frequencies. The log(0) guard
    is relative to the signal's own power, so the result does not depend on the magnetic unit.

    Parameters
    ----------
    values : numpy.ndarray
        Signal.

    Returns
    -------
    float
        Flatness between 0 and 1.
    """
    arr = np.asarray(values, dtype=float) - np.nanmean(values)
    power = np.abs(np.fft.rfft(arr)) ** 2
    # guard against log(0) relative to the signal's own power, so any unit (T ... nT) gives the same result
    power = power + max(float(np.nanmax(power)), np.finfo(float).tiny) * 1e-12
    return float(np.exp(np.mean(np.log(power))) / np.mean(power))


def median_speed_and_dt(df: pd.DataFrame) -> tuple[float, float]:
    """Typical walking speed and sampling interval of a survey.

    Parameters
    ----------
    df : pandas.DataFrame
        Survey with Time (s), Easting (m) and Northing (m).

    Returns
    -------
    speed : float
        Median speed in m/s (at least 0.01; 0.05 when it cannot be computed).
    dt : float
        Median sampling interval in seconds (at least 0.001; 1.0 when it cannot be computed).
    """
    ordered = df.sort_values("Time (s)")
    t = ordered["Time (s)"].to_numpy(dtype=float)
    e = ordered["Easting (m)"].to_numpy(dtype=float)
    n = ordered["Northing (m)"].to_numpy(dtype=float)
    dt = np.diff(t)
    good = dt > 0
    if not good.any():
        return 0.05, 1.0
    de = np.diff(e)[good]
    dn = np.diff(n)[good]
    dt_good = dt[good]
    speed = np.sqrt(de**2 + dn**2) / dt_good
    speed = speed[np.isfinite(speed) & (speed > 0)]
    speed_med = float(np.nanmedian(speed)) if len(speed) else 0.05
    dt_med = float(np.nanmedian(dt_good))
    return max(speed_med, 0.01), max(dt_med, 1e-3)


def run_vmd_modes(df: pd.DataFrame, params: AnalysisParams, field_column: str = "BT") -> tuple[np.ndarray, pd.DataFrame, list[int]]:
    """Decompose a survey's field into VMD modes and choose the anomaly-bearing ones.

    The signal is centred on its median and divided by its standard deviation before VMD (whose convergence test
    is absolute), then the modes are scaled back, so the decomposition is the same in any magnetic unit. Modes are
    sorted from slowest to fastest. Without vmdpy a moving-average band split is used instead.

    Parameters
    ----------
    df : pandas.DataFrame
        Survey with Time (s), Easting (m), Northing (m) and `field_column`.
    params : AnalysisParams
        VMD settings (vmd_modes, vmd_alpha, max_selected_modes).
    field_column : str, optional
        Column to decompose.

    Returns
    -------
    modes : numpy.ndarray
        Array of shape (n_modes, n_samples), in the field's unit, time-ordered.
    metrics : pandas.DataFrame
        Per-mode metrics (see mode_metrics) with 'selected' and 'original_vmd_order_zero_based' columns.
    selected_modes : list of int
        1-based numbers of the modes used for anomaly scoring.
    """
    ordered = df.sort_values("Time (s)").reset_index(drop=True)
    signal = ordered[field_column].to_numpy(dtype=float)
    signal = signal - np.nanmedian(signal)
    # VMD runs on the signal divided by its own spread and the modes are scaled back afterwards, so the
    # decomposition (whose convergence test is absolute) behaves the same in any unit (T ... nT).
    scale = float(np.nanstd(signal)) or 1.0
    signal = signal / scale
    _, dt_med = median_speed_and_dt(ordered)
    if VMD is not None and len(signal) >= params.vmd_modes * 4:
        modes, _, _ = VMD(
            signal.astype(float),
            alpha=float(params.vmd_alpha),
            tau=0.0,
            K=int(params.vmd_modes),
            DC=0,
            init=1,
            tol=1e-7,
        )
        modes = np.asarray(modes, dtype=float)
    else:
        modes = _fallback_modes(signal, int(params.vmd_modes))
    # vmdpy truncates odd-length input by one sample. Preserve the survey row axis.
    if modes.shape[1] < len(signal):
        modes = np.pad(modes, ((0, 0), (0, len(signal) - modes.shape[1])), mode="edge")
    modes = modes[:, :len(signal)]
    modes = modes * scale
    signal = signal * scale
    modes, original_order = sort_modes_by_rate(modes, dt_med)
    metrics = mode_metrics(modes, signal, dt_med)
    selected_modes = select_modes(metrics, max_modes=int(params.max_selected_modes))
    metrics["selected"] = metrics["mode"].isin(selected_modes)
    metrics["original_vmd_order_zero_based"] = original_order
    return modes, metrics, selected_modes


def _fallback_modes(signal: np.ndarray, k_modes: int) -> np.ndarray:
    """Band split used when vmdpy is not installed: successive moving-average residuals.

    Parameters
    ----------
    signal : numpy.ndarray
        Centred signal.
    k_modes : int
        Number of bands.

    Returns
    -------
    numpy.ndarray
        Array of shape (k_modes, n_samples).
    """
    modes = []
    residual = np.asarray(signal, dtype=float)
    for window in np.linspace(5, 101, max(1, k_modes)).astype(int):
        window = int(max(3, window + (window % 2 == 0)))
        kernel = np.ones(window) / window
        smooth = np.convolve(np.pad(residual, (window // 2, window // 2), mode="edge"), kernel, mode="valid")
        modes.append(residual - smooth)
        residual = smooth
    return np.asarray(modes, dtype=float)


def sort_modes_by_rate(modes: np.ndarray, dt: float) -> tuple[np.ndarray, list[int]]:
    """Sort modes from the lowest to the highest dominant frequency.

    Parameters
    ----------
    modes : numpy.ndarray
        Array of shape (n_modes, n_samples).
    dt : float
        Sampling interval in seconds.

    Returns
    -------
    sorted_modes : numpy.ndarray
        The modes in rate order.
    order : list of int
        Original (zero-based) index of each sorted mode.
    """
    rates = [dominant_rate(mode, dt) for mode in modes]
    order = np.argsort(rates)
    return modes[order], [int(i) for i in order]


def mode_metrics(modes: np.ndarray, raw: np.ndarray, dt: float) -> pd.DataFrame:
    """Describe each mode for automatic selection.

    Parameters
    ----------
    modes : numpy.ndarray
        Array of shape (n_modes, n_samples).
    raw : numpy.ndarray
        The decomposed signal.
    dt : float
        Sampling interval in seconds.

    Returns
    -------
    pandas.DataFrame
        One row per mode: 'mode' (1-based), 'variance_ratio' (mode variance / input variance), 'dominant_rate_hz',
        'spectral_flatness', and the flags 'noise_like', 'trend_like' and 'extreme_high_rate'.
    """
    raw_var = float(np.nanvar(raw)) or 1.0
    rows = []
    for i, mode in enumerate(modes, start=1):
        rows.append(
            {
                "mode": i,
                "variance_ratio": float(np.nanvar(mode) / raw_var),
                "dominant_rate_hz": dominant_rate(mode, dt),
                "spectral_flatness": spectral_flatness(mode),
            }
        )
    metrics = pd.DataFrame(rows)
    er = metrics["variance_ratio"].to_numpy(dtype=float)
    fr = metrics["dominant_rate_hz"].to_numpy(dtype=float)
    sf = metrics["spectral_flatness"].to_numpy(dtype=float)
    metrics["noise_like"] = (sf > np.nanpercentile(sf, 80)) & (er < np.nanmedian(er))
    metrics["trend_like"] = fr <= max(0.001, np.nanpercentile(fr, 10))
    metrics["extreme_high_rate"] = fr >= np.nanpercentile(fr, 95)
    return metrics


def select_modes(metrics: pd.DataFrame, max_modes: int = 2) -> list[int]:
    """Choose the modes most likely to carry anomalies.

    Modes flagged as noise-like, trend-like or extremely fast are skipped, as are modes with a small variance
    ratio; the rest are ranked by variance ratio x (1 - spectral flatness).

    Parameters
    ----------
    metrics : pandas.DataFrame
        Output of mode_metrics.
    max_modes : int, optional
        Number of modes to keep.

    Returns
    -------
    list of int
        Selected 1-based mode numbers, in ascending order.
    """
    candidates = metrics[
        (~metrics["noise_like"]) & (~metrics["trend_like"]) & (~metrics["extreme_high_rate"])
    ].copy()
    candidates = candidates[candidates["variance_ratio"] >= max(0.035, float(metrics["variance_ratio"].median()))]
    if candidates.empty:
        candidates = metrics[~metrics["trend_like"]].copy()
    if candidates.empty:
        candidates = metrics.copy()
    candidates["rank_score"] = candidates["variance_ratio"] * (1.0 - candidates["spectral_flatness"].clip(0, 0.95))
    selected = candidates.sort_values("rank_score", ascending=False).head(max_modes)["mode"].astype(int).tolist()
    return sorted(selected)


def window_count_for_length(length_m: float, speed_med: float, dt_med: float) -> int:
    """Number of samples in a score window of a given length along the path.

    Parameters
    ----------
    length_m : float
        Window length in metres.
    speed_med : float
        Typical speed in m/s.
    dt_med : float
        Typical sampling interval in seconds.

    Returns
    -------
    int
        Window length in samples, between 8 and 800.
    """
    count = int(round((float(length_m) / speed_med) / dt_med))
    return int(np.clip(count, 8, 800))


def sliding_rms(values: np.ndarray, window: int, step: int) -> tuple[np.ndarray, np.ndarray]:
    """Root-mean-square of a signal in sliding windows.

    Parameters
    ----------
    values : numpy.ndarray
        Signal.
    window : int
        Window length in samples.
    step : int
        Step between window starts, in samples.

    Returns
    -------
    centers : numpy.ndarray
        Index of each window's centre sample.
    rms : numpy.ndarray
        RMS of each window.
    """
    idxs: list[int] = []
    vals: list[float] = []
    for start in range(0, len(values) - window + 1, step):
        stop = start + window
        segment = values[start:stop]
        idxs.append(start + window // 2)
        vals.append(float(np.sqrt(np.mean(segment**2))))
    return np.asarray(idxs, dtype=int), np.asarray(vals, dtype=float)


def score_trace(modes: np.ndarray, selected_modes: list[int], window: int, step: int) -> tuple[np.ndarray, pd.DataFrame]:
    """Anomaly score of each window: the sum of robust z-scores of the selected modes' windowed RMS.

    Parameters
    ----------
    modes : numpy.ndarray
        Array of shape (n_modes, n_samples).
    selected_modes : list of int
        1-based numbers of the modes to score.
    window, step : int
        Window length and step in samples.

    Returns
    -------
    centers : numpy.ndarray
        Centre sample index of each window.
    contributions : pandas.DataFrame
        One 'z_mode_<n>' column per selected mode and their sum in 'score'.
    """
    idx = None
    parts: dict[str, np.ndarray] = {}
    for mode_num in selected_modes:
        centers, rms = sliding_rms(modes[mode_num - 1], window, step)
        med = np.nanmedian(rms)
        mad = robust_mad(rms)
        # relative guard instead of a fixed 1e-9, so the z-scores do not depend on the field unit
        z = (rms - med) / (mad if mad > 0 else max(float(np.nanmax(np.abs(rms))), np.finfo(float).tiny) * 1e-9)
        if idx is None:
            idx = centers
        parts[f"z_mode_{mode_num}"] = z[: len(idx)]
    contrib = pd.DataFrame(parts)
    contrib["score"] = contrib.sum(axis=1)
    return idx if idx is not None else np.array([], dtype=int), contrib


def analyze_with_cached_modes(
    clean_df: pd.DataFrame,
    modes: np.ndarray,
    selected_modes: list[int],
    params: AnalysisParams,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Score windows along the survey, find high-scoring windows and cluster them into candidates.

    Parameters
    ----------
    clean_df : pandas.DataFrame
        Cleaned survey (the analysis field must be the one decomposed into `modes`).
    modes : numpy.ndarray
        VMD modes from run_vmd_modes.
    selected_modes : list of int
        Modes used for scoring.
    params : AnalysisParams
        Window, threshold and clustering settings.

    Returns
    -------
    score_points : pandas.DataFrame
        One row per window: position, score, threshold, hit flag, mode contributions and cluster label.
    clusters : pandas.DataFrame
        One row per cluster (see cluster_hits).
    summary : dict
        Settings and results, including the selected candidate (see summarize_analysis).

    Raises
    ------
    ValueError
        If no window fits in the survey.
    """
    ordered = clean_df.sort_values("Time (s)").reset_index(drop=True)
    speed_med, dt_med = median_speed_and_dt(ordered)
    window = window_count_for_length(params.window_length_m, speed_med, dt_med)
    step = max(1, int(round(window * float(params.step_ratio))))
    centers, contrib = score_trace(modes, selected_modes, window, step)
    if len(centers) == 0:
        raise ValueError("No score windows could be evaluated. Try a shorter window length.")
    base = ordered.iloc[centers].copy()
    scores = contrib["score"].to_numpy(dtype=float)
    threshold = float(np.nanmedian(scores) + float(params.gamma) * robust_mad(scores))
    score_points = pd.DataFrame(
        {
            "sample_index": centers,
            "t_center_s": base["Time (s)"].to_numpy(dtype=float),
            "e_m": base["Easting (m)"].to_numpy(dtype=float),
            "n_m": base["Northing (m)"].to_numpy(dtype=float),
            "latitude": base["Latitude (°)"].to_numpy(dtype=float),
            "longitude": base["Longitude (°)"].to_numpy(dtype=float),
            "score": scores,
            "threshold": threshold,
            "threshold_margin": scores - threshold,
            "is_hit": scores > threshold,
        }
    )
    for col in contrib.columns:
        if col != "score":
            score_points[col] = contrib[col].to_numpy(dtype=float)
    score_points, clusters = cluster_hits(score_points, params, survey_epsg(ordered))
    summary = summarize_analysis(ordered, score_points, clusters, selected_modes, params, window, step, threshold)
    return score_points, clusters, summary


def cluster_hits(score_points: pd.DataFrame, params: AnalysisParams, epsg: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Group hit windows with DBSCAN and choose the candidate cluster.

    Among clusters with enough support (support_fraction of the largest cluster, at least min_support_points), the
    most compact one (smallest score-weighted RMS radius, then highest peak) is selected.

    Parameters
    ----------
    score_points : pandas.DataFrame
        Windows from analyze_with_cached_modes, with 'e_m', 'n_m', 'score' and 'is_hit'.
    params : AnalysisParams
        DBSCAN and support settings, and the optional reference location.
    epsg : int
        The survey's UTM EPSG code.

    Returns
    -------
    score_points : pandas.DataFrame
        Copy with 'cluster_label' (-1 = not clustered) and 'cluster_rank'.
    clusters : pandas.DataFrame
        One row per cluster: size, weighted centroid (UTM and WGS 84), peak score, uncertainty radius, elongation,
        orientation, distance to the reference, eligibility and 'selected_by_support_compactness'.
    """
    out = score_points.copy()
    out["cluster_label"] = -1
    out["cluster_rank"] = np.nan
    if out.empty or not out["is_hit"].any():
        return out, pd.DataFrame()
    hit_idx = out.index[out["is_hit"]].to_numpy()
    hit_xy = out.loc[hit_idx, ["e_m", "n_m"]].to_numpy(dtype=float)
    hit_labels = DBSCAN(eps=float(params.dbscan_eps_m), min_samples=int(params.dbscan_min_samples)).fit_predict(hit_xy)
    out.loc[hit_idx, "cluster_label"] = hit_labels

    reference = reference_utm(params, epsg)
    cluster_rows = []
    for label in sorted(set(hit_labels)):
        if label < 0:
            continue
        idx = hit_idx[hit_labels == label]
        group = out.loc[idx]
        weights = np.maximum(group["score"].to_numpy(dtype=float), 0.0)
        if weights.sum() <= 0:
            weights = np.ones(len(group))
        e = group["e_m"].to_numpy(dtype=float)
        n = group["n_m"].to_numpy(dtype=float)
        centroid_e = float(np.average(e, weights=weights))
        centroid_n = float(np.average(n, weights=weights))
        radius = float(np.sqrt(np.average((e - centroid_e) ** 2 + (n - centroid_n) ** 2, weights=weights)))
        peak = float(group["score"].max())
        if len(group) > 2:
            cov = np.cov(np.vstack([e, n]), aweights=weights, bias=True)
            vals, vecs = np.linalg.eigh(cov)
            vals = np.maximum(vals, 1e-9)
            elongation = float(np.sqrt(vals.max() / vals.min()))
            vec = vecs[:, int(np.argmax(vals))]
            orientation = float(np.degrees(np.arctan2(vec[1], vec[0])))
        else:
            elongation = math.nan
            orientation = math.nan
        lon, lat = _utm_transformers(epsg)[1].transform(centroid_e, centroid_n)
        cluster_rows.append(
            {
                "cluster_label": int(label),
                "n_points": int(len(group)),
                "centroid_e_m": centroid_e,
                "centroid_n_m": centroid_n,
                "centroid_latitude": float(lat),
                "centroid_longitude": float(lon),
                "peak_score": peak,
                "uncertainty_radius_m": radius,
                "elongation_ratio": elongation,
                "orientation_deg": orientation,
                "dist_to_reference_m": (
                    float(math.hypot(centroid_e - reference[0], centroid_n - reference[1])) if reference is not None else math.nan
                ),
            }
        )
    clusters = pd.DataFrame(cluster_rows)
    if clusters.empty:
        return out, clusters
    nmax = int(clusters["n_points"].max())
    support_threshold = max(int(params.min_support_points), int(math.ceil(float(params.support_fraction) * nmax)))
    clusters["support_threshold_points"] = support_threshold
    clusters["eligible_for_compactness"] = clusters["n_points"] >= support_threshold
    eligible = clusters[clusters["eligible_for_compactness"]]
    if eligible.empty:
        eligible = clusters
    selected_label = int(
        eligible.sort_values(["uncertainty_radius_m", "peak_score"], ascending=[True, False]).iloc[0]["cluster_label"]
    )
    clusters["selected_by_support_compactness"] = clusters["cluster_label"] == selected_label
    clusters["uncertainty_rank"] = clusters["uncertainty_radius_m"].rank(method="dense").astype(int) - 1
    for _, row in clusters.iterrows():
        out.loc[out["cluster_label"] == row["cluster_label"], "cluster_rank"] = int(row["uncertainty_rank"])
    return out, clusters


def summarize_analysis(
    clean_df: pd.DataFrame,
    score_points: pd.DataFrame,
    clusters: pd.DataFrame,
    selected_modes: list[int],
    params: AnalysisParams,
    window: int,
    step: int,
    threshold: float,
) -> dict[str, Any]:
    """Collect the analysis settings and results in one dictionary.

    Parameters
    ----------
    clean_df : pandas.DataFrame
        Analysed survey.
    score_points, clusters : pandas.DataFrame
        Results of cluster_hits.
    selected_modes : list of int
        Modes used for scoring.
    params : AnalysisParams
        Settings used.
    window, step : int
        Window length and step in samples.
    threshold : float
        Score threshold.

    Returns
    -------
    dict
        Sample count, UTM zone, settings, hit and cluster counts, and for a selected candidate its position,
        radius, support, peak score and (with a reference) its distance to the reference.
    """
    selected = clusters[clusters["selected_by_support_compactness"]] if not clusters.empty else pd.DataFrame()
    if selected.empty:
        candidate = {}
    else:
        row = selected.iloc[0]
        candidate = {
            "candidate_cluster_label": int(row["cluster_label"]),
            "candidate_easting_m": float(row["centroid_e_m"]),
            "candidate_northing_m": float(row["centroid_n_m"]),
            "candidate_latitude": float(row["centroid_latitude"]),
            "candidate_longitude": float(row["centroid_longitude"]),
            "candidate_radius_m": float(row["uncertainty_radius_m"]),
            "candidate_points": int(row["n_points"]),
            "candidate_peak_score": float(row["peak_score"]),
        }
        if params.reference_known:
            candidate["candidate_distance_to_reference_m"] = float(row["dist_to_reference_m"])
    summary = {
        "n_samples": int(len(clean_df)),
        "utm_zone": utm_zone_label(survey_epsg(clean_df)),
        "selected_modes": ";".join(str(mode) for mode in selected_modes),
        "window_samples": int(window),
        "step_samples": int(step),
        "window_length_m": float(params.window_length_m),
        "step_ratio": float(params.step_ratio),
        "gamma": float(params.gamma),
        "threshold": float(threshold),
        "n_hits": int(score_points["is_hit"].sum()) if not score_points.empty else 0,
        "n_clusters": int(len(clusters)),
        "dbscan_eps_m": float(params.dbscan_eps_m),
        "dbscan_min_samples": int(params.dbscan_min_samples),
    }
    summary.update(candidate)
    return summary


def annotate_clean_points(
    clean_df: pd.DataFrame,
    score_points: pd.DataFrame,
    clusters: pd.DataFrame,
) -> pd.DataFrame:
    """Add window scores and cluster labels to the survey samples at each window centre.

    Parameters
    ----------
    clean_df : pandas.DataFrame
        Analysed survey, in time order.
    score_points, clusters : pandas.DataFrame
        Results of cluster_hits.

    Returns
    -------
    pandas.DataFrame
        Copy with Anomaly_Score, Anomaly_Threshold, Anomaly_Is_Hit, Anomaly_Cluster_Label and Anomaly_Label
        ('background', 'selected candidate', 'secondary cluster' or 'unclustered hit').
    """
    out = clean_df.copy()
    out["Anomaly_Score"] = np.nan
    out["Anomaly_Threshold"] = np.nan
    out["Anomaly_Is_Hit"] = False
    out["Anomaly_Cluster_Label"] = -1
    out["Anomaly_Label"] = "background"
    if score_points.empty:
        return out
    selected_labels = set(
        clusters.loc[clusters["selected_by_support_compactness"], "cluster_label"].astype(int).tolist()
    ) if not clusters.empty else set()
    for _, row in score_points.iterrows():
        idx = int(row["sample_index"])
        if idx < 0 or idx >= len(out):
            continue
        label = int(row.get("cluster_label", -1))
        out.at[idx, "Anomaly_Score"] = float(row["score"])
        out.at[idx, "Anomaly_Threshold"] = float(row["threshold"])
        out.at[idx, "Anomaly_Is_Hit"] = bool(row["is_hit"])
        out.at[idx, "Anomaly_Cluster_Label"] = label
        if bool(row["is_hit"]) and label in selected_labels:
            out.at[idx, "Anomaly_Label"] = "selected candidate"
        elif bool(row["is_hit"]) and label >= 0:
            out.at[idx, "Anomaly_Label"] = "secondary cluster"
        elif bool(row["is_hit"]):
            out.at[idx, "Anomaly_Label"] = "unclustered hit"
    return out
