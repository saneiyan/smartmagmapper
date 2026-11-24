"""Load the bundled neighborhood forest and summarize its actual SHAP values."""
from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

from processing.xai_features import FEATURE_NAMES, FEATURE_LABELS, FEATURE_SCHEMA

MODEL_DIR = Path(__file__).resolve().parent/'models'
_SUMMARY_CACHE = OrderedDict()


@lru_cache(maxsize=2)
def _load_bundle(model_path: str, modified_ns: int, metadata_modified_ns: int):
    """Load the application's trusted model and check schema and versions."""
    import joblib
    import sklearn
    path = Path(model_path)
    metadata = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    if hashlib.sha256(path.read_bytes()).hexdigest() != metadata['model_sha256']:
        raise ValueError('The model file does not match its metadata. Restore the matching model files.')
    if metadata['versions']['scikit_learn'] != sklearn.__version__:
        raise ValueError(f"This saved model requires scikit-learn {metadata['versions']['scikit_learn']}; installed: {sklearn.__version__}.")
    bundle = joblib.load(path)
    model = bundle['model']
    if metadata['feature_schema'] != FEATURE_SCHEMA or metadata['feature_names'] != list(FEATURE_NAMES):
        raise ValueError('Saved model and feature definitions do not match.')
    if list(model.feature_names_in_) != list(FEATURE_NAMES) or metadata['target_class'] not in model.classes_:
        raise ValueError('Saved model has an incompatible feature or class definition.')
    return model, metadata


def global_neighborhood_explanation(features: pd.DataFrame, coordinate_epsg: int) -> tuple[pd.DataFrame, dict]:
    """Calculate class-specific global SHAP for the current survey's windows.

    Parameters
    ----------
    features : pandas.DataFrame
        Nine validated features from ``build_neighborhood_features``.
    coordinate_epsg : int
        Projected coordinate reference system of the current survey.

    Returns
    -------
    pandas.DataFrame
        Full feature names, symbols and mean absolute SHAP contributions to
        the selected-neighborhood class, with no invented factor weights.
    dict
        Model provenance, sample scope and interpretation limits for exports.

    Notes
    -----
    The trained forest is loaded, never retrained here. Up to 2000 current-survey
    windows are sampled reproducibly. This reference model is site-specific;
    other CRSs and positions outside its training bounds are refused. Being
    inside those bounds does not establish generalization performance.
    """
    path = MODEL_DIR/'neighborhood_rf.joblib'
    meta_path = path.with_suffix('.json')
    if not path.exists() or not meta_path.exists():
        raise ValueError('The verified neighborhood model and metadata have not been installed.')
    model, metadata = _load_bundle(str(path), path.stat().st_mtime_ns, meta_path.stat().st_mtime_ns)
    if int(coordinate_epsg) != metadata['coordinate_epsg']:
        raise ValueError('This reference model was trained in a different projected CRS. A compatible validated model is required.')
    X = features.loc[:, list(FEATURE_NAMES)].astype(float)
    if X.empty or not np.isfinite(X.to_numpy()).all():
        raise ValueError('No complete finite explanation features are available.')
    for col, (lower, upper) in metadata['coordinate_bounds'].items():
        if ((X[col] < lower) | (X[col] > upper)).any():
            raise ValueError('Survey positions are outside this reference model\'s training extent. Cross-site application has not been validated.')
    digest = hashlib.sha256(X.to_numpy().tobytes()+metadata['model_sha256'].encode()).hexdigest()
    if digest in _SUMMARY_CACHE:
        table, scope = _SUMMARY_CACHE[digest]
        return table.copy(deep=True), dict(scope)
    import shap
    sample = X.sample(min(2000, len(X)), random_state=42)
    explainer = shap.TreeExplainer(model, feature_perturbation='tree_path_dependent', model_output='raw')
    values = explainer.shap_values(sample)
    cube = np.stack(values, axis=2) if isinstance(values, list) else np.asarray(values)
    if cube.shape != (len(sample), len(FEATURE_NAMES), len(model.classes_)):
        raise ValueError(f'Unsupported SHAP output shape: {cube.shape}')
    np.testing.assert_allclose(np.asarray(explainer.expected_value)[None,:]+cube.sum(axis=1),
                               model.predict_proba(sample), rtol=1e-5, atol=1e-6)
    class_index = list(model.classes_).index(metadata['target_class'])
    importance = np.abs(cube[:,:,class_index]).mean(axis=0)
    table = pd.DataFrame({'feature':FEATURE_NAMES,
        'label':[FEATURE_LABELS[f][1] for f in FEATURE_NAMES],
        'symbol':[FEATURE_LABELS[f][0] for f in FEATURE_NAMES],
        'mean_abs_shap':importance})
    scope = {'status':'available', 'model_id':metadata['model_id'],
        'model_sha256':metadata['model_sha256'],'feature_schema':FEATURE_SCHEMA,
        'target_class':metadata['target_class'],'aggregation':'mean absolute SHAP',
        'feature_perturbation':'tree_path_dependent',
        'target_expected_value':float(np.asarray(explainer.expected_value)[class_index]),
        'output_units':'Random-forest class-probability units',
        'scope':'Current survey scored windows; all window classes included.',
        'total_windows':len(X),'explained_windows':len(sample),'sample_seed':42,
        'coordinate_epsg':int(coordinate_epsg),'model_training_surveys':metadata['surveys'],
        'shap_version':shap.__version__,
        'interpretation':'Importance for the neighborhood classifier; not centroid attribution or probability of a well.',
        'validation_limit':metadata['split'],
        'reference_run':'New corrected-feature training run; not a reproduction of published metrics.'}
    _SUMMARY_CACHE[digest] = (table.copy(deep=True), dict(scope))
    while len(_SUMMARY_CACHE) > 4:
        _SUMMARY_CACHE.popitem(last=False)
    return table, scope


def local_neighborhood_explanation(features: pd.DataFrame, coordinate_epsg: int,
                                   window_position: int) -> tuple[pd.DataFrame, dict]:
    """Explain the selected-neighborhood output for one real scored window.

    Parameters
    ----------
    features : pandas.DataFrame
        Survey features constructed by ``build_neighborhood_features``.
    coordinate_epsg : int
        Survey projected CRS, checked against the saved reference model.
    window_position : int
        Zero-based row position in the scored-window feature table, not a
        cluster ID or an interpolated position at a candidate centroid.

    Returns
    -------
    pandas.DataFrame
        Nine actual feature values and signed SHAP contributions.
    dict
        Explained class, model base value, output and predicted category.
        Base value plus signed contributions equals the explained output.
    """
    if isinstance(window_position, (bool, np.bool_)) or not isinstance(window_position, (int,np.integer)):
        raise ValueError('Select an integer scored-window position.')
    if not 0 <= window_position < len(features):
        raise ValueError('Selected window is outside this survey.')
    path = MODEL_DIR/'neighborhood_rf.joblib'
    meta_path = path.with_suffix('.json')
    if not path.exists() or not meta_path.exists():
        raise ValueError('The verified neighborhood model and metadata have not been installed.')
    model, metadata = _load_bundle(str(path),path.stat().st_mtime_ns,meta_path.stat().st_mtime_ns)
    if int(coordinate_epsg) != metadata['coordinate_epsg']:
        raise ValueError('The selected window uses a different projected CRS from the reference model.')
    row = features.iloc[[window_position]].loc[:,list(FEATURE_NAMES)].astype(float)
    if not np.isfinite(row.to_numpy()).all():
        raise ValueError('Selected window has incomplete or non-finite features.')
    for col, (lower, upper) in metadata['coordinate_bounds'].items():
        if not lower <= float(row[col].iloc[0]) <= upper:
            raise ValueError('Selected window is outside the reference-model training extent.')
    import shap
    explainer = shap.TreeExplainer(model,feature_perturbation='tree_path_dependent',model_output='raw')
    values = explainer.shap_values(row)
    cube = np.stack(values,axis=2) if isinstance(values,list) else np.asarray(values)
    if cube.shape != (1,len(FEATURE_NAMES),len(model.classes_)):
        raise ValueError(f'Unsupported local SHAP shape: {cube.shape}')
    probabilities = model.predict_proba(row)[0]
    base = np.asarray(explainer.expected_value)
    np.testing.assert_allclose(base+cube[0].sum(axis=0),probabilities,rtol=1e-5,atol=1e-6)
    index = list(model.classes_).index(metadata['target_class'])
    table = pd.DataFrame({'feature':FEATURE_NAMES,
        'label':[FEATURE_LABELS[f][1] for f in FEATURE_NAMES],
        'symbol':[FEATURE_LABELS[f][0] for f in FEATURE_NAMES],
        'feature_value':row.iloc[0].to_numpy(), 'shap_value':cube[0,:,index]})
    scope = {'status':'available','scope':'One actual scored window',
        'window_position':int(window_position),'window_number':int(window_position)+1,
        'target_class':metadata['target_class'],'predicted_class':str(model.classes_[int(np.argmax(probabilities))]),
        'base_value':float(base[index]),'model_output':float(probabilities[index]),
        'sum_of_contributions':float(cube[0,:,index].sum()),
        'class_outputs':{str(name):float(value) for name,value in zip(model.classes_,probabilities)},
        'model_id':metadata['model_id'],'model_sha256':metadata['model_sha256'],
        'coordinate_epsg':int(coordinate_epsg),'feature_perturbation':'tree_path_dependent',
        'output_units':'Neighborhood-classifier probability units, not well probability',
        'shap_version':shap.__version__,'additivity_verified':True}
    return table, scope