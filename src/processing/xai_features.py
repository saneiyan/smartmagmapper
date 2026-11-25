"""Shared scored-window inputs for research neighborhood classification.

This module constructs features only. It does not select modes, train a model,
change clustering, calculate SHAP values, or estimate a source coordinate.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree


FEATURE_NAMES = (
    'e_m', 'n_m', 'score', 'threshold_margin',
    'contrib_mode1', 'contrib_mode2',
    'nearest_centroid_distance_m', 'nearest_centroid_radius_m',
    'nearest_centroid_peak_score',
)

CLASS_NAMES = (
    'background',
    'secondary neighborhood',
    'selected neighborhood',
)

FEATURE_SCHEMA = 'neighborhood_features_v1'

FEATURE_LABELS = {
    'e_m': (
        'E_j', 'Projected easting', r'$E_j$'
    ),
    'n_m': (
        'N_j', 'Projected northing', r'$N_j$'
    ),
    'score': (
        'S_j', 'Combined anomaly score', r'$S_j$'
    ),
    'threshold_margin': (
        'Delta_j^thr',
        'Threshold margin',
        r'$\Delta_j^{\mathrm{thr}}$',
    ),
    'contrib_mode1': (
        'z_1,j',
        'First retained-mode contribution',
        r'$z_{1,j}$',
    ),
    'contrib_mode2': (
        'z_2,j',
        'Second retained-mode contribution',
        r'$z_{2,j}$',
    ),
    'nearest_centroid_distance_m': (
        'delta_j^near',
        'Nearest-centroid distance',
        r'$\delta_j^{\mathrm{near}}$',
    ),
    'nearest_centroid_radius_m': (
        'r_j^near',
        'Nearest-cluster spatial spread',
        r'$r_j^{\mathrm{near}}$',
    ),
    'nearest_centroid_peak_score': (
        'S_j^near',
        'Nearest-cluster peak score',
        r'$S_j^{\mathrm{near}}$',
    ),
}


def build_neighborhood_features(
    score_points: pd.DataFrame,
    clusters: pd.DataFrame,
    selected_modes: Sequence[int],
) -> pd.DataFrame:
    """Construct the nine RF features for one survey's scored windows.

    Parameters
    ----------
    score_points : pandas.DataFrame
        Window positions in projected meters, anomaly scores, thresholds and
        ``z_mode_N`` columns produced by the existing analysis pipeline.
    clusters : pandas.DataFrame
        Detected clusters from the same survey, with projected centroid,
        weighted RMS spatial spread and peak anomaly score columns.
    selected_modes : sequence of int
        One or two one-based mode IDs in the pipeline's retained order.
        These IDs are read from the analysis result, never chosen here.

    Returns
    -------
    pandas.DataFrame
        Nine ordered features with exactly the input row order and index.
        If only one mode was retained, its absent second contribution is zero.
        Actual missing measurements are rejected rather than filled with zero.

    Raises
    ------
    ValueError
        If inputs are incomplete, contain mixed surveys, have no clusters, or
        do not match the recorded mode selection and combined anomaly score.

    Notes
    -----
    Nearest-cluster features refer to the nearest detected centroid, which need
    not be the window's assigned cluster. All spatial inputs must use the same
    projected coordinate reference system in meters. The zero second-mode
    convention and strict missing-value handling are explicit integration
    choices; this schema is not a claim of reproducing earlier model metrics.
    """
    modes = list(selected_modes)

    if (
        not 1 <= len(modes) <= 2
        or len(set(modes)) != len(modes)
        or any(
            isinstance(m, (bool, np.bool_))
            or not isinstance(m, (int, np.integer))
            or m < 1
            for m in modes
        )
    ):
        raise ValueError(
            'Pass the one or two retained positive integer mode IDs '
            'from the analysis result.'
        )

    for name, frame in [
        ('score points', score_points),
        ('clusters', clusters),
    ]:
        if frame is None or frame.empty:
            raise ValueError(
                f'No {name}: neighborhood-model features are unavailable.'
            )

        for survey_col in ('Survey_ID', 'survey_id'):
            if survey_col in frame and (
                frame[survey_col].isna().any()
                or frame[survey_col].nunique() != 1
            ):
                raise ValueError(
                    'Build explanation features one survey at a time.'
                )

    for survey_col in ('Survey_ID', 'survey_id'):
        if survey_col in score_points and survey_col in clusters:
            if (
                score_points[survey_col].iloc[0]
                != clusters[survey_col].iloc[0]
            ):
                raise ValueError(
                    'Scored windows and clusters belong to different surveys.'
                )

    point_cols = [
        'e_m',
        'n_m',
        'score',
        'threshold_margin',
    ] + [f'z_mode_{m}' for m in modes]

    cluster_cols = [
        'centroid_e_m',
        'centroid_n_m',
        'uncertainty_radius_m',
        'peak_score',
    ]

    for name, frame, cols in [
        ('score points', score_points, point_cols),
        ('clusters', clusters, cluster_cols),
    ]:
        missing = [c for c in cols if c not in frame]

        if missing:
            raise ValueError(f'Missing {name} columns: {missing}')

        if not np.isfinite(frame[cols].to_numpy(dtype=float)).all():
            raise ValueError(
                f'Non-finite {name} values; '
                'explanation features were not generated.'
            )

    if (clusters['uncertainty_radius_m'] < 0).any():
        raise ValueError('Cluster spatial spread cannot be negative.')

    values = [
        score_points[f'z_mode_{m}'].to_numpy(dtype=float)
        for m in modes
    ]

    if not np.allclose(
        np.sum(values, axis=0),
        score_points['score'].to_numpy(dtype=float),
        rtol=1e-8,
        atol=1e-9,
    ):
        raise ValueError(
            'Combined scores do not match the contributions '
            'of the supplied retained modes.'
        )

    out = score_points[
        ['e_m', 'n_m', 'score', 'threshold_margin']
    ].astype(float).copy()

    out['contrib_mode1'] = values[0]
    out['contrib_mode2'] = values[1] if len(values) == 2 else 0.0

    centroids = clusters[
        ['centroid_e_m', 'centroid_n_m']
    ].to_numpy(dtype=float)

    distance, nearest = cKDTree(centroids).query(
        out[['e_m', 'n_m']].to_numpy(dtype=float)
    )

    out['nearest_centroid_distance_m'] = distance

    out['nearest_centroid_radius_m'] = clusters[
        'uncertainty_radius_m'
    ].to_numpy(dtype=float)[nearest]

    out['nearest_centroid_peak_score'] = clusters[
        'peak_score'
    ].to_numpy(dtype=float)[nearest]

    out = out.loc[:, list(FEATURE_NAMES)]

    out.attrs.update(
        feature_schema=FEATURE_SCHEMA,
        selected_modes=[int(m) for m in modes],
        single_mode_policy='absent second contribution is zero',
        spatial_units='meters',
    )

    return out


def neighborhood_labels(
    score_points: pd.DataFrame,
    clusters: pd.DataFrame,
) -> pd.Series:
    """Return pipeline-derived class labels for one survey without changing it.

    Parameters
    ----------
    score_points : pandas.DataFrame
        Scored windows with DBSCAN ``cluster_label``; -1 denotes unassigned.
    clusters : pandas.DataFrame
        Detected cluster IDs and ``selected_by_support_compactness`` flags.

    Returns
    -------
    pandas.Series
        Background, secondary-neighborhood or selected-neighborhood labels in
        the original window order. These are pipeline labels, not well truth.
    """
    if 'cluster_label' not in score_points:
        raise ValueError('Scored windows must contain cluster_label.')

    if clusters is None or clusters.empty:
        raise ValueError(
            'No detected clusters; the neighborhood classifier is unavailable.'
        )

    if clusters['cluster_label'].duplicated().any():
        raise ValueError('Cluster IDs must be unique within one survey.')

    chosen = clusters.loc[
        clusters['selected_by_support_compactness'].eq(True),
        'cluster_label',
    ]

    if len(chosen) != 1:
        raise ValueError(
            'Exactly one selected candidate cluster is required.'
        )

    ids = score_points['cluster_label']

    if (
        ids.isna().any()
        or not ids.loc[ids >= 0].isin(clusters['cluster_label']).all()
    ):
        raise ValueError(
            'Window cluster IDs do not match the detected clusters.'
        )

    labels = pd.Series(
        'background',
        index=score_points.index,
        name='label',
    )

    labels.loc[ids >= 0] = 'secondary neighborhood'
    labels.loc[ids == chosen.iloc[0]] = 'selected neighborhood'

    return labels