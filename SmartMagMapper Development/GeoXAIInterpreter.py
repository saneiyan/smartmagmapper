from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class GeoXAIReport:
    narrative: str
    cluster_scores: pd.DataFrame
    contributions: pd.DataFrame


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(out):
        return default
    return out


def _normalize_positive(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    vmax = values.max(skipna=True)
    if not np.isfinite(vmax) or vmax <= 0:
        return pd.Series(np.zeros(len(values)), index=series.index, dtype=float)
    return (values.fillna(0.0) / float(vmax)).clip(0.0, 1.0)


def _compactness_score(radius: pd.Series) -> pd.Series:
    values = pd.to_numeric(radius, errors="coerce").replace([np.inf, -np.inf], np.nan)
    valid = values.dropna()
    if valid.empty:
        return pd.Series(np.zeros(len(values)), index=radius.index, dtype=float)
    scale = max(float(valid.median()), 1.0)
    return (1.0 / (1.0 + values.fillna(scale) / scale)).clip(0.0, 1.0)


def _shape_score(elongation: pd.Series) -> pd.Series:
    values = pd.to_numeric(elongation, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(1.0)
    values = values.clip(lower=1.0)
    return (1.0 / values).clip(0.0, 1.0)


def score_clusters(score_points: pd.DataFrame, clusters: pd.DataFrame) -> pd.DataFrame:
    if clusters is None or clusters.empty:
        return pd.DataFrame()

    out = clusters.copy().reset_index(drop=True)
    out["support_score"] = _normalize_positive(out["n_points"])
    out["peak_score_norm"] = _normalize_positive(out["peak_score"])
    out["compactness_score"] = _compactness_score(out["uncertainty_radius_m"])
    out["shape_score"] = _shape_score(out.get("elongation_ratio", pd.Series(np.ones(len(out)))))

    margins = []
    if score_points is not None and not score_points.empty and "threshold_margin" in score_points.columns:
        for _, row in out.iterrows():
            group = score_points[score_points["cluster_label"] == int(row["cluster_label"])]
            margins.append(float(group["threshold_margin"].median()) if not group.empty else 0.0)
    else:
        margins = [0.0] * len(out)
    out["median_threshold_margin"] = margins
    out["threshold_separation_score"] = _normalize_positive(out["median_threshold_margin"])

    out["geo_xai_confidence"] = (
        0.30 * out["support_score"]
        + 0.25 * out["peak_score_norm"]
        + 0.25 * out["compactness_score"]
        + 0.10 * out["shape_score"]
        + 0.10 * out["threshold_separation_score"]
    ).clip(0.0, 1.0)
    out = out.sort_values("geo_xai_confidence", ascending=False).reset_index(drop=True)
    out["geo_xai_rank"] = np.arange(1, len(out) + 1)
    return out


def selected_contributions(cluster_scores: pd.DataFrame) -> pd.DataFrame:
    if cluster_scores is None or cluster_scores.empty:
        return pd.DataFrame(columns=["factor", "score", "weight", "weighted_score"])
    selected = cluster_scores[cluster_scores["selected_by_support_compactness"].astype(bool)]
    row = selected.iloc[0] if not selected.empty else cluster_scores.iloc[0]
    rows = [
        ("Cluster support", _safe_float(row.get("support_score")), 0.30),
        ("Magnetic peak strength", _safe_float(row.get("peak_score_norm")), 0.25),
        ("Spatial compactness", _safe_float(row.get("compactness_score")), 0.25),
        ("Threshold separation", _safe_float(row.get("threshold_separation_score")), 0.10),
        ("Shape coherence", _safe_float(row.get("shape_score")), 0.10),
    ]
    out = pd.DataFrame(rows, columns=["factor", "score", "weight"])
    out["weighted_score"] = out["score"] * out["weight"]
    return out


def explain_candidate(
    clean_df: pd.DataFrame,
    score_points: pd.DataFrame,
    clusters: pd.DataFrame,
    summary: dict[str, Any],
    reference_known: bool = False,
) -> GeoXAIReport:
    cluster_scores = score_clusters(score_points, clusters)
    contributions = selected_contributions(cluster_scores)

    if clusters is None or clusters.empty or "candidate_latitude" not in summary:
        mode = "Known-reference mode" if reference_known else "Unknown-location mode"
        narrative = (
            f"Explainable AI (XAI) — {mode}\n\n"
            "No explainable candidate was available because the current parameters did not produce a selected "
            "cluster. Lower the threshold gamma, increase DBSCAN eps, or reduce DBSCAN minimum samples and rerun."
        )
        return GeoXAIReport(narrative=narrative, cluster_scores=cluster_scores, contributions=contributions)

    selected = cluster_scores[cluster_scores["selected_by_support_compactness"].astype(bool)]
    row = selected.iloc[0] if not selected.empty else cluster_scores.iloc[0]
    candidate_label = int(row["cluster_label"])
    confidence = 100.0 * _safe_float(row.get("geo_xai_confidence"))
    support = int(row["n_points"])
    radius = _safe_float(row["uncertainty_radius_m"])
    peak = _safe_float(row["peak_score"])
    margin = _safe_float(row.get("median_threshold_margin"))
    lat = _safe_float(row["centroid_latitude"])
    lon = _safe_float(row["centroid_longitude"])

    if reference_known:
        reference_text = (
            "The entered reference well is used only as validation/context here; it does not affect which "
            "candidate is selected. "
            f"The selected candidate is {summary.get('candidate_distance_to_well_m', 0.0):.2f} m from that point."
        )
        mode = "Known-reference interpretation"
    else:
        reference_text = (
            "The candidate well location is estimated from the magnetic anomaly evidence, "
            "cluster support and compactness. Any entered coordinate is treated as a map/search context, "
            "not ground truth."
        )
        mode = "Unknown-location GeoXAI interpretation"

    support_threshold = int(row.get("support_threshold_points", 0))
    eligibility = (
        f"It passes the support gate of {support_threshold} windows."
        if bool(row.get("eligible_for_compactness", False))
        else f"It does not pass the support gate of {support_threshold} windows, so review it cautiously."
    )
    narrative = (
        f"Explainable AI (XAI) — {mode}\n\n"
        f"Selected candidate: C{candidate_label} at lat {lat:.6f}, lon {lon:.6f}.\n"
        f"XAI evidence score: {confidence:.1f}/100. A rule-based, weighted evidence summary; not a trained AI classifier or a calibrated probability of a well.\n"
        "Weights: support 30%, peak response 25%, compactness 25%, shape coherence 10%, threshold separation 10%. Scores are relative to the current survey clusters.\n\n"
        "Selection and explanation are separate: the pipeline applies a support gate then selects a compact cluster. The XAI score describes the evidence; it does not select the location.\n\n"
        f"Why this candidate was selected:\n"
        f"- Support: {support} anomaly-score windows are assigned to this cluster. {eligibility}\n"
        f"- Peak response: the cluster reaches a score of {peak:.2f}, indicating a strong localized magnetic response.\n"
        f"- Compactness: the weighted RMS cluster spread is {radius:.2f} m; smaller compact clusters are preferred. Spread is not a confidence interval.\n"
        f"- Threshold separation: the median score margin above threshold is {margin:.2f}.\n"
        f"- Spatial logic: the candidate selection does not need the true well coordinate; it uses the score-window "
        f"geometry and DBSCAN cluster shape.\n\n"
        f"{reference_text}\n\n"
        f"Recommended field use: navigate to the candidate centroid, sweep a radius of about {max(radius, 3.0):.1f} m, "
        "and confirm with repeated passes or another sensor before treating it as a final well location."
    )
    return GeoXAIReport(narrative=narrative, cluster_scores=cluster_scores, contributions=contributions)
