"""One survey, shared preprocessing, and independently preserved field versions."""
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
from copy import deepcopy
import numpy as np
import pandas as pd
import OrphanWellPipeline as ow


@dataclass
class SurveySession:
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

    def __post_init__(self):
        self.path = str(Path(self.path).resolve())
        self.magnetometer = self.magnetometer.copy(deep=True)
        self.location = self.location.copy(deep=True)

    def ensure_cleaned(self, params):
        key = (int(params.startup_samples), float(params.spatial_mad_multiplier), float(params.spatial_fallback_percentile))
        if self.cleaning_key == key and not self.cleaned.empty:
            return False
        # Commit only after successful preprocessing; the raw streams stay intact.
        cleaned, audit = ow.clean_survey(self.magnetometer, self.location, params)
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
        if self.filters:self.remember_field()
        self.working = self.cleaned.copy(deep=True)
        self.filters = []
        self.filter_history = []
        self.mode_cache.clear()
        self.revision += 1

    def field_state(self):
        return (self.working.copy(deep=True),list(self.filters),deepcopy(self.filter_history))

    def remember_field(self):
        self.undo_states.append(self.field_state())
        self.undo_states=self.undo_states[-20:]
        self.redo_states.clear()

    def restore_field(self,state):
        frame,filters,history=state
        self.working=frame.copy(deep=True);self.filters=list(filters);self.filter_history=deepcopy(history)
        self.revision+=1

    def undo_field(self):
        if not self.undo_states:return False
        self.redo_states.append(self.field_state());self.restore_field(self.undo_states.pop());return True

    def redo_field(self):
        if not self.redo_states:return False
        self.undo_states.append(self.field_state());self.restore_field(self.redo_states.pop());return True

    def modes_for(self, frame, params):
        field_values = frame['Analysis_Field_uT'].to_numpy(dtype=float)
        time_values = frame['Time (s)'].to_numpy(dtype=float)
        digest = hashlib.sha256(field_values.tobytes() + time_values.tobytes()).hexdigest()
        key = (digest, params.vmd_modes, params.vmd_alpha, params.max_selected_modes)
        if key not in self.mode_cache:
            if len(self.mode_cache) >= 4:
                self.mode_cache.pop(next(iter(self.mode_cache)))
            result = ow.run_vmd_modes(frame, params, field_column='Analysis_Field_uT')
            self.mode_cache[key] = result
        return self.mode_cache[key]
