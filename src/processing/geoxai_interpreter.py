"""GeoXAI: explanation of the anomaly analysis's candidate location.

Combines a plain-language narrative and cluster evidence with explanations from a saved Random Forest model:
global (mean absolute SHAP contribution of each neighbourhood feature over all score windows) and local (SHAP
contributions for one chosen score window). See processing.xai_features and processing.xai_model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from processing.xai_features import (
    build_neighborhood_features,
    neighborhood_labels,
)
from processing.xai_model import (
    global_neighborhood_explanation,
    local_neighborhood_explanation,
)

@dataclass
class GeoXAIReport:
    """Explanation of a candidate location.

    Attributes
    ----------
    narrative : str
        Plain-language explanation shown in the Explainable AI (XAI) view.
    cluster_scores : pandas.DataFrame
        Cluster evidence (support, spread...) used by the evidence chart.
    contributions : pandas.DataFrame
        Global feature contributions of the saved model.
    metadata : dict
        Model, feature and explanation details ('status' is 'available' when the saved-model explanation ran).
    features : pandas.DataFrame
        Feature table, one row per score window.
    local_contributions : pandas.DataFrame
        Feature contributions for the window shown in the local view (empty for the global view).
    local_metadata : dict
        Details of the local explanation (window identity, model output...).
    display_narrative : str
        Narrative for the view currently shown (exported instead of `narrative` when set).
    """
    narrative: str
    cluster_scores: pd.DataFrame
    contributions: pd.DataFrame
    metadata: dict[str, Any] = field(default_factory=dict)
    features: pd.DataFrame = field(default_factory=pd.DataFrame)
    local_contributions: pd.DataFrame = field(default_factory=pd.DataFrame)
    local_metadata: dict[str, Any] = field(default_factory=dict)
    display_narrative: str = ''

def explain_window(
    features: pd.DataFrame,
    score_points: pd.DataFrame,
    coordinate_epsg: int,
    window_position: int,
) -> tuple[pd.DataFrame, dict]:
    """Explain a scored window and retain its recorded spatial/time identity.

    Parameters
    ----------
    features : pandas.DataFrame
        Feature table for this survey in scored-window order.
    score_points : pandas.DataFrame
        Actual scored windows from the same analysis, in identical row order.
    coordinate_epsg : int
        Survey projected coordinate reference system.
    window_position : int
        Zero-based position of the window to explain.

    Returns
    -------
    pandas.DataFrame
        Signed local SHAP contributions and the actual feature values.
    dict
        Window identity, model output and explanation provenance.
    """
    if (
        len(features) != len(score_points)
        or not features.index.equals(score_points.index)
    ):
        raise ValueError(
            'Explanation features and scored windows must have '
            'identical rows and order.'
        )

    identity = ['e_m', 'n_m', 'score', 'threshold_margin']

    if not np.allclose(
        features[identity].to_numpy(),
        score_points[identity].to_numpy(),
    ):
        raise ValueError(
            'Explanation features do not match these scored-window positions.'
        )

    table, metadata = local_neighborhood_explanation(
        features,
        coordinate_epsg,
        window_position,
    )

    point = score_points.iloc[window_position]

    for col in (
        'sample_index',
        't_center_s',
        'e_m',
        'n_m',
        'cluster_label',
        'latitude',
        'longitude',
    ):
        if col in point and pd.notna(point[col]):
            metadata[col] = (
                int(point[col])
                if col in ('sample_index', 'cluster_label')
                else float(point[col])
            )

    if 'pipeline_neighborhood' in features:
        metadata['pipeline_neighborhood'] = str(
            features['pipeline_neighborhood'].iloc[window_position]
        )

    return table, metadata

def explain_candidate(
    clean_df: pd.DataFrame,
    score_points: pd.DataFrame,
    clusters: pd.DataFrame,
    summary: dict[str, Any],
    reference_known: bool,
) -> GeoXAIReport:
    """Report candidate-selection evidence and global SHAP separately.

    The existing pipeline supplies the selected candidate and its measured
    properties. This function does not modify its inputs, select a different
    cluster, or recalculate the candidate coordinates.
    """
    evidence = (
        pd.DataFrame()
        if clusters is None
        else clusters.copy(deep=True)
    )
    empty = pd.DataFrame(columns=['factor', 'value', 'unit'])

    status = (
        'Candidate-selection evidence. Cluster support and spatial spread '
        'below come directly from the location pipeline. They are separate '
        'from the Random Forest neighborhood-classification explanation.'
    )

    if evidence.empty:
        return GeoXAIReport(
            status + '\n\nNo clusters were produced by the current analysis.',
            evidence,
            empty,
        )

    selected = evidence.loc[
        evidence['selected_by_support_compactness'].astype(bool)
    ]

    if len(selected) != 1:
        return GeoXAIReport(
            status + '\n\nNo unique selected cluster is available.',
            evidence,
            empty,
        )

    row = selected.iloc[0]
    label = int(row['cluster_label'])
    support = int(row['n_points'])
    spread = float(row['uncertainty_radius_m'])
    peak = float(row['peak_score'])
    gate = int(row['support_threshold_points'])

    eligible = evidence.loc[
        evidence['eligible_for_compactness'].astype(bool)
    ]

    if eligible.empty:
        decision = (
            'No cluster passed the support gate; the pipeline compared '
            'all clusters as its fallback.'
        )
    else:
        decision = (
            f'{len(eligible)} cluster(s) passed the support gate '
            f'of {gate} scored windows.'
        )

    margin = np.nan

    if (
        score_points is not None
        and not score_points.empty
        and 'threshold_margin' in score_points
    ):
        group = score_points.loc[
            score_points['cluster_label'] == label
        ]
        if not group.empty:
            margin = float(group['threshold_margin'].median())

    evidence['median_threshold_margin'] = [
        float(
            score_points.loc[
                score_points['cluster_label'] == lab,
                'threshold_margin',
            ].median()
        )
        if (
            score_points is not None
            and not score_points.empty
            and 'threshold_margin' in score_points
        )
        else np.nan
        for lab in evidence['cluster_label']
    ]

    narrative = (
        status
        + f'\n\nSelected cluster: C{label}\n'
        f'Projected centroid: X (easting) = '
        f'{row["centroid_e_m"]:.3f} m; '
        f'Y (northing) = {row["centroid_n_m"]:.3f} m.\n'
        f'Latitude = {row["centroid_latitude"]:.7f}; '
        f'longitude = {row["centroid_longitude"]:.7f}.\n\n'
        f'Selection: {decision} The pipeline selects the smallest '
        f'score-weighted RMS spatial spread among the compared clusters, '
        f'using the largest peak anomaly score to resolve spread ties.\n'
        f'Centroid: the mean of cluster-window positions weighted by '
        f'max(anomaly score, 0); equal weights are used only if their '
        f'sum is zero.\n'
        f'Measured support: {support} scored windows. '
        f'Weighted RMS spatial spread: {spread:.3f} m. '
        f'Peak anomaly score: {peak:.3f}. '
        f'Median threshold margin: {margin:.3f}.\n'
        'Spatial spread describes cluster dispersion, not a calibrated '
        'location-uncertainty radius. Peak and threshold margin are '
        'reported measurements, not additional weighted selection criteria.'
    )

    if reference_known:
        narrative += (
            '\nThe entered reference coordinate is comparison context '
            'and is not used for candidate selection.'
        )

    features = pd.DataFrame()
    importance = pd.DataFrame()
    metadata = {
        'status': 'unavailable',
        'target_class': 'selected neighborhood',
    }

    try:
        raw_modes = summary.get('selected_modes', '')

        modes = (
            [int(v) for v in raw_modes.split(';') if v.strip()]
            if isinstance(raw_modes, str)
            else [int(v) for v in raw_modes]
        )

        features = build_neighborhood_features(
            score_points,
            clusters,
            modes,
        )

        if (
            clean_df is None
            or clean_df.empty
            or 'UTM_EPSG' not in clean_df
        ):
            raise ValueError(
                'The survey projected CRS is required '
                'for this reference model.'
            )

        epsg_values = clean_df['UTM_EPSG'].dropna().unique()

        if len(epsg_values) != 1:
            raise ValueError(
                'The survey must use one verified projected CRS.'
            )

        importance, metadata = global_neighborhood_explanation(
            features,
            int(epsg_values[0]),
        )

        features['pipeline_neighborhood'] = neighborhood_labels(
            score_points,
            clusters,
        ).to_numpy()

        explanation = (
            'Global SHAP | Target class: selected neighborhood\n'
            f'Explained windows: {metadata["explained_windows"]} '
            f'of {metadata["total_windows"]} in the current survey. '
            'Bars show average absolute feature contributions to '
            'neighborhood classification. They indicate influence, '
            'not fixed weights or the probability of a well.\n'
            'Reference-site model; current-survey explanations are '
            'not independent detection validation. Model provenance '
            'and explanation scope are included in the numerical exports.'
        )

    except (
        ImportError,
        ValueError,
        OSError,
        KeyError,
        AssertionError,
    ) as exc:
        metadata['reason'] = str(exc)
        explanation = (
            'Global SHAP unavailable: '
            + str(exc)
            + ' Candidate-selection results are retained.'
        )

    narrative = explanation + '\n\n' + narrative

    return GeoXAIReport(
        narrative,
        evidence,
        importance,
        metadata,
        features,
    )