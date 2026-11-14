"""Short XAI definitions shown through Qt information popups."""
from PyQt6.QtWidgets import QMessageBox


FEATURE_HELP = {
    'local_overview': (
        'Reading a local SHAP explanation',
        'Explains one selected analysis window. Teal bars show features '
        'that raise the model output for selected-neighborhood membership; '
        'orange bars show features that lower it. Contributions are relative '
        'to the model base value. The base value plus all signed '
        'contributions equals the output for this window.',
    ),
    'overview': (
        'Reading the global SHAP chart',
        "Shows which features most influence the model's selected-neighborhood "
        'classification across the survey. Longer bars mean greater average '
        'influence. The bars show the strength of influence, rather than '
        'whether it increased or decreased a prediction.',
    ),
    'e_m': (
        'Projected easting',
        "The east-west coordinate of an analysis window's center, measured "
        "in meters in the survey's projected coordinate system.",
    ),
    'n_m': (
        'Projected northing',
        "The north-south coordinate of an analysis window's center, measured "
        "in meters in the survey's projected coordinate system.",
    ),
    'score': (
        'Combined anomaly score',
        'Combines the normalized responses of the retained VMD modes within '
        'each analysis window. It is the sum of those mode contributions '
        'and is used to identify unusual signal responses.',
    ),
    'threshold_margin': (
        'Score above/below threshold',
        "The difference between a window's anomaly score and the cutoff used "
        'to identify an anomaly. Positive means the score is above the '
        'cutoff; negative means below it; zero means equal to it. '
        'For example, a score of 8 and a cutoff of 5 give a difference of 3.',
    ),
    'contrib_mode1': (
        'First retained-mode contribution',
        'The normalized response of the first VMD mode retained for analysis. '
        "It compares that mode's root-mean-square signal amplitude in a "
        'window with its typical response across the survey.',
    ),
    'contrib_mode2': (
        'Second retained-mode contribution',
        'The normalized response of the second VMD mode retained for '
        'analysis, calculated in the same way as the first contribution. '
        'It is zero when only one mode is retained.',
    ),
    'nearest_centroid_distance_m': (
        'Nearest-centroid distance',
        'The straight-line distance, in meters, from an analysis '
        "window's center position to the nearest detected cluster center.",
    ),
    'nearest_centroid_radius_m': (
        'Nearest-cluster spatial spread',
        "Describes how tightly the nearest cluster's supporting window "
        'positions are concentrated around its center. It is their '
        'score-weighted root-mean-square distance from that center, '
        'in meters. Smaller values indicate a tighter cluster.',
    ),
    'nearest_centroid_peak_score': (
        'Nearest-cluster peak score',
        'The highest combined anomaly score among the windows assigned '
        'to the nearest detected cluster.',
    ),
    'cluster_support': (
        'Supporting anomaly windows',
        'The number of windows with scores above the anomaly threshold '
        'that are assigned to each cluster. Teal highlights the '
        'selected cluster.',
    ),
    'cluster_spread': (
        'Spatial spread around cluster center',
        "Shows how tightly each cluster's supporting window positions are "
        'concentrated around its center, in meters. The chart uses their '
        'score-weighted root-mean-square distance. Smaller values indicate '
        'a tighter cluster; teal highlights the selected cluster.',
    ),
    'threshold_multiplier': (
        'Anomaly threshold multiplier',
        'Controls the anomaly cutoff relative to the median score and '
        'its median absolute deviation. Higher values usually raise the '
        'cutoff, making detection more selective. This is a user setting; '
        'score above/below threshold is a calculated difference '
        'for each window.',
    ),
    'neighborhoods': (
        'Neighborhood categories',
        'Selected neighborhood: windows assigned to the selected '
        'candidate cluster.\n\n'
        'Secondary neighborhood: windows assigned to other '
        'detected clusters.\n\n'
        'Background: windows not assigned to a detected cluster.',
    ),
    'windows': (
        'What is an analysis window?',
        'The app takes a short sequence of signal values from each '
        'retained VMD mode and calculates one root-mean-square (RMS) '
        'response for that sequence. The normalized mode responses '
        'are combined into one anomaly score, placed at the '
        "window's center position on the map. The window then moves "
        'forward and the calculation repeats. For example, a nine-sample '
        'window moving two samples at a time covers samples 1–9, '
        'then 3–11.',
    ),
}


def show_feature_help(owner, key='overview'):
    """Show a definition without changing analysis settings."""
    title, definition = FEATURE_HELP.get(
        key,
        FEATURE_HELP['overview'],
    )

    box = QMessageBox(
        QMessageBox.Icon.Information,
        title,
        title,
        QMessageBox.StandardButton.Ok,
        owner,
    )
    box.setInformativeText(definition)
    box.exec()


def show_picked_feature(owner, event):
    """Open a definition when its chart bar or label is clicked."""
    key = getattr(event.artist, '_xai_feature_key', None)

    if key in FEATURE_HELP:
        show_feature_help(owner, key)