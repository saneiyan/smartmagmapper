"""One survey, shared preprocessing, and independently preserved field versions."""
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
from copy import deepcopy
import numpy as np
import pandas as pd
from processing import data_analysis_pipeline as dap


@dataclass
class SurveySession:
    """One imported survey: its raw streams, the cleaned baseline and the current (filtered) field.

    The raw magnetometer and GPS streams are never modified. `cleaned` is reproducible from them and the cleaning
    settings; `working` starts as a copy of `cleaned` and holds stored filter results, with undo/redo history.

    Attributes
    ----------
    path : str
        Absolute path of the source file.
    magnetometer, location : pandas.DataFrame
        Raw magnetometer and GPS streams as imported.
    cleaned : pandas.DataFrame
        Synchronized and cleaned survey (see data_analysis_pipeline.clean_survey).
    working : pandas.DataFrame
        Current field: `cleaned` with any stored filter result in its BT column.
    audit : dict
        Cleaning report from clean_survey.
    filters : list of str
        Names of the filters applied to `working`, in order.
    filter_history : list of dict
        Each applied filter with its parameters.
    cleaning_key : tuple or None
        (startup samples, MAD multiplier, fallback percentile) used for `cleaned`.
    revision : int
        Incremented on every change, so stale previews can be detected.
    mode_cache : dict
        Cached VMD decompositions (see modes_for).
    undo_states, redo_states : list
        Saved (working, filters, filter_history) states for Edit > Undo / Redo.
    suggested_cleaning : dict or None
        Data-based cleaning suggestion, computed on first use.
    field_unit : str
        Unit of the magnetic values as recorded (see labels.MAG_UNITS); values are never converted.
    coordinates : dict
        How the coordinates were recorded: {'format': ..., 'epsg': ..., 'columns': ...}.
    """
    path: str
    magnetometer: pd.DataFrame
    location: pd.DataFrame
    cleaned: pd.DataFrame = field(default_factory=pd.DataFrame)
    working: pd.DataFrame = field(default_factory=pd.DataFrame)
    audit: dict = field(default_factory=dict)
    filters: list = field(default_factory=list)
    filter_history: list = field(default_factory=list)
    cleaning_key: tuple | None = None
    revision: int = 0
    mode_cache: dict = field(default_factory=dict)
    undo_states: list = field(default_factory=list, repr=False)
    redo_states: list = field(default_factory=list, repr=False)
    # Data-based cleaning suggestion (see dap.suggest_cleaning_settings); computed on first use.
    suggested_cleaning: dict | None = field(default=None, repr=False)
    # Unit of the magnetic values as recorded (see processing.labels.MAG_UNITS); values are never converted.
    field_unit: str = 'µT'
    # How the coordinates were recorded: {'format': ..., 'epsg': ...} (see processing.coordinates.FORMATS).
    coordinates: dict = field(default_factory=lambda: {'format': 'decimal_degrees'})

    def __post_init__(self):
        """Store the absolute source path and private copies of the raw streams."""
        self.path = str(Path(self.path).resolve())
        self.magnetometer = self.magnetometer.copy(deep=True)
        self.location = self.location.copy(deep=True)

    def ensure_cleaned(self, params):
        """Clean the survey with the given settings unless it is already cleaned with them.

        Re-cleaning resets the current field, the filter history, the undo/redo states and the VMD cache.

        Parameters
        ----------
        params : data_analysis_pipeline.AnalysisParams
            Analysis settings; only the cleaning settings are used here.

        Returns
        -------
        bool
            True if the survey was (re)cleaned, False if it was already up to date.
        """
        key = (int(params.startup_samples), float(params.spatial_mad_multiplier), float(params.spatial_fallback_percentile))
        if self.cleaning_key == key and not self.cleaned.empty:
            return False
        # Commit only after successful preprocessing; the raw streams stay intact.
        cleaned, audit = dap.clean_survey(self.magnetometer, self.location, params)
        self.cleaned = cleaned.copy(deep=True)
        self.working = cleaned.copy(deep=True)
        self.audit = dict(audit)
        self.cleaning_key = key
        self.filters = []
        self.filter_history = []
        self.mode_cache.clear()
        self.undo_states.clear();self.redo_states.clear()
        self.revision += 1
        return True

    def set_working(self, frame, filters, parameters=None, replace_history=False):
        """Make a filter result the current field.

        Parameters
        ----------
        frame : pandas.DataFrame
            New current field; must have the same rows, in the same order, as `cleaned`.
        filters : list of str
            Names of all filters applied to the new field, in order.
        parameters : dict, optional
            Settings of the filter just applied, kept in the history.
        replace_history : bool, optional
            Start a new history (the filter ran on the cleaned data rather than on the previous result).

        Raises
        ------
        ValueError
            If the rows differ from the cleaned survey or the BT values are not all finite.
        """
        if len(frame) != len(self.cleaned) or not frame.index.equals(self.cleaned.index):
            raise ValueError('A map filter must preserve the shared survey rows and order.')
        if not np.isfinite(frame['BT'].to_numpy(dtype=float)).all():
            raise ValueError('The filter produced non-finite magnetic values; the previous field is retained.')
        self.remember_field()
        self.working = frame.copy(deep=True)
        self.filters = list(filters)
        if replace_history:self.filter_history=[]
        self.filter_history.append({'filter': self.filters[-1] if self.filters else 'Custom field', 'parameters': dict(parameters or {})})
        self.revision += 1

    def reset_field(self):
        """Restore the current field to the cleaned baseline (the previous field can be restored with undo)."""
        if self.filters:self.remember_field()
        self.working = self.cleaned.copy(deep=True)
        self.filters = []
        self.filter_history = []
        self.mode_cache.clear()
        self.revision += 1

    def field_state(self):
        """Snapshot of the current field for undo/redo.

        Returns
        -------
        tuple
            (copy of working, list of filters, copy of filter_history).
        """
        return (self.working.copy(deep=True),list(self.filters),deepcopy(self.filter_history))

    def remember_field(self):
        """Push the current field onto the undo stack (at most 20 states) and clear the redo stack."""
        self.undo_states.append(self.field_state())
        self.undo_states=self.undo_states[-20:]
        self.redo_states.clear()

    def restore_field(self,state):
        """Restore a snapshot made by field_state.

        Parameters
        ----------
        state : tuple
            (working, filters, filter_history) as returned by field_state.
        """
        frame,filters,history=state
        self.working=frame.copy(deep=True);self.filters=list(filters);self.filter_history=deepcopy(history)
        self.revision+=1

    def undo_field(self):
        """Go back to the previous current field.

        Returns
        -------
        bool
            False if there is nothing to undo.
        """
        if not self.undo_states:return False
        self.redo_states.append(self.field_state());self.restore_field(self.undo_states.pop());return True

    def redo_field(self):
        """Reapply the field that was last undone.

        Returns
        -------
        bool
            False if there is nothing to redo.
        """
        if not self.redo_states:return False
        self.undo_states.append(self.field_state());self.restore_field(self.redo_states.pop());return True

    def modes_for(self, frame, params):
        """VMD decomposition of a frame's Analysis_Field, cached by its values and the VMD settings.

        Parameters
        ----------
        frame : pandas.DataFrame
            Survey with 'Time (s)' and 'Analysis_Field' columns.
        params : data_analysis_pipeline.AnalysisParams
            VMD settings (number of modes, alpha, maximum selected modes).

        Returns
        -------
        tuple
            (modes, metrics, selected modes) as returned by data_analysis_pipeline.run_vmd_modes.
        """
        field_values = frame['Analysis_Field'].to_numpy(dtype=float)
        time_values = frame['Time (s)'].to_numpy(dtype=float)
        digest = hashlib.sha256(field_values.tobytes() + time_values.tobytes()).hexdigest()
        key = (digest, params.vmd_modes, params.vmd_alpha, params.max_selected_modes)
        if key not in self.mode_cache:
            if len(self.mode_cache) >= 4:
                self.mode_cache.pop(next(iter(self.mode_cache)))
            result = dap.run_vmd_modes(frame, params, field_column='Analysis_Field')
            self.mode_cache[key] = result
        return self.mode_cache[key]
