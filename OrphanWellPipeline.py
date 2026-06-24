from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pyproj import Transformer
from sklearn.cluster import DBSCAN

try:
    from vmdpy import VMD
except Exception:  # pragma: no cover - fallback keeps the GUI importable.
    VMD = None


WELL_LAT = 42.142823
WELL_LON = -75.824952
WGS84_TO_UTM18 = Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)
UTM18_TO_WGS84 = Transformer.from_crs("EPSG:32618", "EPSG:4326", always_xy=True)


@dataclass
class OrphanWellParams:
    well_lat: float = WELL_LAT
    well_lon: float = WELL_LON
    startup_samples: int = 10
    spatial_mad_multiplier: float = 6.0
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


def well_utm(params: OrphanWellParams) -> tuple[float, float]:
    east, north = WGS84_TO_UTM18.transform(params.well_lon, params.well_lat)
    return float(east), float(north)


def _flat_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = ["_".join(str(part) for part in col if str(part) != "nan").strip("_") for col in out.columns]
    else:
        out.columns = [str(col) for col in out.columns]
    return out


def _norm(text: Any) -> str:
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
    normalized = {_norm(col): col for col in df.columns}
    for alias in aliases:
        key = _norm(alias)
        if key in normalized:
            return normalized[key]
    for col in df.columns:
        key = _norm(col)
        if any(_norm(alias) in key or key in _norm(alias) for alias in aliases):
            return col
    if required:
        raise ValueError(f"Missing required column. Tried aliases: {aliases}")
    return None


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def _standardize_magnetometer(df: pd.DataFrame) -> pd.DataFrame:
    df = _flat_columns(df)
    time_col = _find_column(df, ["Mag_Time (s)", "Magnetometer_Time (s)", "Time (s)", "time"])
    x_col = _find_column(df, ["X (uT)", "X (µT)", "Magnetic field x (uT)", "Magnetometer_X (uT)", "BX"])
    y_col = _find_column(df, ["Y (uT)", "Y (µT)", "Magnetic field y (uT)", "Magnetometer_Y (uT)", "BY"])
    z_col = _find_column(df, ["Z (uT)", "Z (µT)", "Magnetic field z (uT)", "Magnetometer_Z (uT)", "BZ"])
    out = df[[time_col, x_col, y_col, z_col]].copy()
    out.columns = ["Mag_Time (s)", "X (uT)", "Y (uT)", "Z (uT)"]
    return _coerce_numeric(out).dropna(subset=["Mag_Time (s)", "X (uT)", "Y (uT)", "Z (uT)"])


def _standardize_location(df: pd.DataFrame) -> pd.DataFrame:
    df = _flat_columns(df)
    time_col = _find_column(df, ["Loc_Time (s)", "Location_Time (s)", "GPS Time", "Time (s)", "time"])
    lat_col = _find_column(df, ["Latitude (degree)", "Latitude (°)", "Location_Latitude (°)", "latitude", "lat"])
    lon_col = _find_column(df, ["Longitude (degree)", "Longitude (°)", "Location_Longitude (°)", "longitude", "lon"])
    out = df[[time_col, lat_col, lon_col]].copy()
    out.columns = ["Loc_Time (s)", "Latitude (deg)", "Longitude (deg)"]
    return _coerce_numeric(out).dropna(subset=["Loc_Time (s)", "Latitude (deg)", "Longitude (deg)"])


def _find_standard_sheet(sheets: dict[str, pd.DataFrame], kind: str) -> pd.DataFrame | None:
    for name, df in sheets.items():
        lower_name = str(name).lower()
        cols = " ".join(str(col).lower() for col in df.columns)
        if kind == "mag" and ("magnet" in lower_name or ("x" in cols and "z" in cols and "µt" in cols)):
            return df
        if kind == "loc" and ("location" in lower_name or ("latitude" in cols and "longitude" in cols)):
            return df
    return None


def read_survey_file(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
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
    if suffix == ".csv":
        df = pd.read_csv(path)
        return _standardize_magnetometer(df), _standardize_location(df)
    raise ValueError(f"Unsupported survey file type: {path.suffix}")


def clean_survey(magdf: pd.DataFrame, gpsdf: pd.DataFrame, params: OrphanWellParams) -> tuple[pd.DataFrame, dict[str, Any]]:
    mag = _standardize_magnetometer(magdf) if "Mag_Time (s)" not in magdf.columns else _coerce_numeric(magdf)
    gps = _standardize_location(gpsdf) if "Loc_Time (s)" not in gpsdf.columns else _coerce_numeric(gpsdf)

    mag = mag.sort_values("Mag_Time (s)").drop_duplicates("Mag_Time (s)").reset_index(drop=True)
    gps = gps.sort_values("Loc_Time (s)").drop_duplicates("Loc_Time (s)").reset_index(drop=True)
    mag["Total_Field_uT"] = np.sqrt(mag["X (uT)"] ** 2 + mag["Y (uT)"] ** 2 + mag["Z (uT)"] ** 2)

    gt = gps["Loc_Time (s)"].to_numpy(dtype=float)
    mt = mag["Mag_Time (s)"].to_numpy(dtype=float)
    lat = gps["Latitude (deg)"].to_numpy(dtype=float)
    lon = gps["Longitude (deg)"].to_numpy(dtype=float)
    valid = (mt >= np.nanmin(gt)) & (mt <= np.nanmax(gt))
    mag["Latitude (deg)"] = np.nan
    mag["Longitude (deg)"] = np.nan
    mag.loc[valid, "Latitude (deg)"] = np.interp(mt[valid], gt, lat)
    mag.loc[valid, "Longitude (deg)"] = np.interp(mt[valid], gt, lon)

    interpolated = mag.dropna(subset=["Latitude (deg)", "Longitude (deg)"]).reset_index(drop=True)
    before_startup = len(interpolated)
    startup = max(0, int(params.startup_samples))
    if startup:
        interpolated = interpolated.iloc[startup:].reset_index(drop=True)

    east, north = WGS84_TO_UTM18.transform(
        interpolated["Longitude (deg)"].to_numpy(dtype=float),
        interpolated["Latitude (deg)"].to_numpy(dtype=float),
    )
    interpolated["Easting (m)"] = east
    interpolated["Northing (m)"] = north

    med_e = float(np.nanmedian(east))
    med_n = float(np.nanmedian(north))
    radial = np.sqrt((east - med_e) ** 2 + (north - med_n) ** 2)
    med_r = float(np.nanmedian(radial))
    mad_r = robust_mad(radial)
    if mad_r > 0:
        limit = med_r + float(params.spatial_mad_multiplier) * mad_r
    else:
        limit = float(np.nanpercentile(radial, 95))
    keep = radial <= limit
    cleaned = interpolated.loc[keep].reset_index(drop=True)

    cleaned = update_well_columns(cleaned, params)
    cleaned["Time (s)"] = cleaned["Mag_Time (s)"]
    cleaned["BT"] = cleaned["Total_Field_uT"]
    cleaned["Latitude (°)"] = cleaned["Latitude (deg)"]
    cleaned["Longitude (°)"] = cleaned["Longitude (deg)"]
    cleaned["easting"] = cleaned["Easting (m)"]
    cleaned["northing"] = cleaned["Northing (m)"]
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
    }
    return cleaned, audit


def load_and_clean(path: str | Path, params: OrphanWellParams) -> tuple[pd.DataFrame, dict[str, Any]]:
    magdf, gpsdf = read_survey_file(path)
    return clean_survey(magdf, gpsdf, params)


def update_well_columns(df: pd.DataFrame, params: OrphanWellParams) -> pd.DataFrame:
    out = df.copy()
    well_e, well_n = well_utm(params)
    out["Well_Easting_m"] = well_e
    out["Well_Northing_m"] = well_n
    out["Delta_E_m"] = out["Easting (m)"].to_numpy(dtype=float) - well_e
    out["Delta_N_m"] = out["Northing (m)"].to_numpy(dtype=float) - well_n
    out["Distance_to_Well_m"] = np.sqrt(out["Delta_E_m"] ** 2 + out["Delta_N_m"] ** 2)
    return out


def robust_mad(values: np.ndarray | pd.Series) -> float:
    arr = np.asarray(values, dtype=float)
    med = np.nanmedian(arr)
    return float(np.nanmedian(np.abs(arr - med)))


def dominant_rate(values: np.ndarray, dt: float) -> float:
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
    arr = np.asarray(values, dtype=float) - np.nanmean(values)
    power = np.abs(np.fft.rfft(arr)) ** 2 + 1e-12
    return float(np.exp(np.mean(np.log(power))) / np.mean(power))


def median_speed_and_dt(df: pd.DataFrame) -> tuple[float, float]:
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


def run_vmd_modes(df: pd.DataFrame, params: OrphanWellParams) -> tuple[np.ndarray, pd.DataFrame, list[int]]:
    ordered = df.sort_values("Time (s)").reset_index(drop=True)
    signal = ordered["Total_Field_uT"].to_numpy(dtype=float)
    signal = signal - np.nanmedian(signal)
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
    modes, original_order = sort_modes_by_rate(modes, dt_med)
    metrics = mode_metrics(modes, signal, dt_med)
    selected_modes = select_modes(metrics, max_modes=int(params.max_selected_modes))
    metrics["selected"] = metrics["mode"].isin(selected_modes)
    metrics["original_vmd_order_zero_based"] = original_order
    return modes, metrics, selected_modes


def _fallback_modes(signal: np.ndarray, k_modes: int) -> np.ndarray:
    modes = []
    residual = np.asarray(signal, dtype=float)
    for window in np.linspace(5, 101, max(1, k_modes)).astype(int):
        window = int(max(3, window + (window % 2 == 0)))
        kernel = np.ones(window) / window
        smooth = np.convolve(residual, kernel, mode="same")
        modes.append(residual - smooth)
        residual = smooth
    return np.asarray(modes, dtype=float)


def sort_modes_by_rate(modes: np.ndarray, dt: float) -> tuple[np.ndarray, list[int]]:
    rates = [dominant_rate(mode, dt) for mode in modes]
    order = np.argsort(rates)
    return modes[order], [int(i) for i in order]


def mode_metrics(modes: np.ndarray, raw: np.ndarray, dt: float) -> pd.DataFrame:
    raw_var = float(np.nanvar(raw)) or 1.0
    rows = []
    for i, mode in enumerate(modes, start=1):
        rows.append(
            {
                "mode": i,
                "energy_ratio": float(np.nanvar(mode) / raw_var),
                "dominant_rate_hz": dominant_rate(mode, dt),
                "spectral_flatness": spectral_flatness(mode),
            }
        )
    metrics = pd.DataFrame(rows)
    er = metrics["energy_ratio"].to_numpy(dtype=float)
    fr = metrics["dominant_rate_hz"].to_numpy(dtype=float)
    sf = metrics["spectral_flatness"].to_numpy(dtype=float)
    metrics["noise_like"] = (sf > np.nanpercentile(sf, 80)) & (er < np.nanmedian(er))
    metrics["trend_like"] = fr <= max(0.001, np.nanpercentile(fr, 10))
    metrics["extreme_high_rate"] = fr >= np.nanpercentile(fr, 95)
    return metrics


def select_modes(metrics: pd.DataFrame, max_modes: int = 2) -> list[int]:
    candidates = metrics[
        (~metrics["noise_like"]) & (~metrics["trend_like"]) & (~metrics["extreme_high_rate"])
    ].copy()
    candidates = candidates[candidates["energy_ratio"] >= max(0.035, float(metrics["energy_ratio"].median()))]
    if candidates.empty:
        candidates = metrics[~metrics["trend_like"]].copy()
    if candidates.empty:
        candidates = metrics.copy()
    candidates["rank_score"] = candidates["energy_ratio"] * (1.0 - candidates["spectral_flatness"].clip(0, 0.95))
    selected = candidates.sort_values("rank_score", ascending=False).head(max_modes)["mode"].astype(int).tolist()
    return sorted(selected)


def window_count_for_length(length_m: float, speed_med: float, dt_med: float) -> int:
    count = int(round((float(length_m) / speed_med) / dt_med))
    return int(np.clip(count, 8, 800))


def sliding_rms(values: np.ndarray, window: int, step: int) -> tuple[np.ndarray, np.ndarray]:
    idxs: list[int] = []
    vals: list[float] = []
    for start in range(0, len(values) - window + 1, step):
        stop = start + window
        segment = values[start:stop]
        idxs.append(start + window // 2)
        vals.append(float(np.sqrt(np.mean(segment**2))))
    return np.asarray(idxs, dtype=int), np.asarray(vals, dtype=float)


def score_trace(modes: np.ndarray, selected_modes: list[int], window: int, step: int) -> tuple[np.ndarray, pd.DataFrame]:
    idx = None
    parts: dict[str, np.ndarray] = {}
    for mode_num in selected_modes:
        centers, rms = sliding_rms(modes[mode_num - 1], window, step)
        med = np.nanmedian(rms)
        mad = robust_mad(rms)
        z = (rms - med) / (mad + 1e-9)
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
    params: OrphanWellParams,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    ordered = update_well_columns(clean_df.sort_values("Time (s)").reset_index(drop=True), params)
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
            "latitude": base["Latitude (deg)"].to_numpy(dtype=float),
            "longitude": base["Longitude (deg)"].to_numpy(dtype=float),
            "distance_to_well_m": base["Distance_to_Well_m"].to_numpy(dtype=float),
            "score": scores,
            "threshold": threshold,
            "threshold_margin": scores - threshold,
            "is_hit": scores > threshold,
        }
    )
    for col in contrib.columns:
        if col != "score":
            score_points[col] = contrib[col].to_numpy(dtype=float)
    score_points, clusters = cluster_hits(score_points, params)
    summary = summarize_analysis(ordered, score_points, clusters, selected_modes, params, window, step, threshold)
    return score_points, clusters, summary


def cluster_hits(score_points: pd.DataFrame, params: OrphanWellParams) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = score_points.copy()
    out["cluster_label"] = -1
    out["cluster_rank"] = np.nan
    if out.empty or not out["is_hit"].any():
        return out, pd.DataFrame()
    hit_idx = out.index[out["is_hit"]].to_numpy()
    hit_xy = out.loc[hit_idx, ["e_m", "n_m"]].to_numpy(dtype=float)
    labels = DBSCAN(eps=float(params.dbscan_eps_m), min_samples=int(params.dbscan_min_samples)).fit_predict(hit_xy)
    out.loc[hit_idx, "cluster_label"] = labels

    well_e, well_n = well_utm(params)
    cluster_rows = []
    for label in sorted(set(labels)):
        if label < 0:
            continue
        idx = hit_idx[labels == label]
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
        lon, lat = UTM18_TO_WGS84.transform(centroid_e, centroid_n)
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
                "dist_to_well_m": float(math.hypot(centroid_e - well_e, centroid_n - well_n)),
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
    params: OrphanWellParams,
    window: int,
    step: int,
    threshold: float,
) -> dict[str, Any]:
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
            "candidate_distance_to_well_m": float(row["dist_to_well_m"]),
        }
    summary = {
        "n_samples": int(len(clean_df)),
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
    out = clean_df.copy()
    out["OW_Score"] = np.nan
    out["OW_Threshold"] = np.nan
    out["OW_Is_Hit"] = False
    out["OW_Cluster_Label"] = -1
    out["OW_Label"] = "background"
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
        out.at[idx, "OW_Score"] = float(row["score"])
        out.at[idx, "OW_Threshold"] = float(row["threshold"])
        out.at[idx, "OW_Is_Hit"] = bool(row["is_hit"])
        out.at[idx, "OW_Cluster_Label"] = label
        if bool(row["is_hit"]) and label in selected_labels:
            out.at[idx, "OW_Label"] = "selected candidate"
        elif bool(row["is_hit"]) and label >= 0:
            out.at[idx, "OW_Label"] = "secondary cluster"
        elif bool(row["is_hit"]):
            out.at[idx, "OW_Label"] = "unclustered hit"
    return out
