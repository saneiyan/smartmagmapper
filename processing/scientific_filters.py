"""Explicit signal/domain filters with recoverable inputs and metric spatial grids."""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from scipy import signal as sp
from scipy.interpolate import griddata, RegularGridInterpolator
from scipy.ndimage import distance_transform_edt
import harmonica as hm
import xarray as xr
from processing.labels import signal_label
from processing import data_analysis_pipeline as dap

SAVITZKY_POLYORDER = 2

SERIES_FILTERS = ['VMD', 'Savitzky–Golay', 'Moving average', 'Low-pass', 'High-pass', 'Band-pass', 'Linear detrend']
SPATIAL_FILTERS = ['Upward continuation', 'Regularized downward continuation', 'Reduction to pole']


class FilterSettingError(ValueError):
    """A filter setting is outside the range this survey supports; `setting` names the parameter."""
    def __init__(self, message, setting=None):
        super().__init__(message)
        self.setting = setting


@dataclass
class FilterResult:
    before: np.ndarray
    after: np.ndarray
    axis: np.ndarray
    axis_label: str
    settings: dict
    notes: list = field(default_factory=list)
    modes: np.ndarray | None = None
    metrics: pd.DataFrame | None = None
    selected: list = field(default_factory=list)
    mode_axis: np.ndarray | None = None
    mode_signal: np.ndarray | None = None
    grids: tuple | None = None

    def select_modes(self, selected):
        if self.modes is None:
            raise ValueError('There is no decomposition to reconstruct.')
        selected = sorted(set(int(x) for x in selected))
        if not selected or any(x < 1 or x > len(self.modes) for x in selected):
            raise ValueError('Keep at least one valid mode.')
        self.selected = selected
        reconstructed = self.modes[np.array(selected)-1].sum(axis=0) + np.median(self.mode_signal)
        self.after = np.interp(self.axis, self.mode_axis, reconstructed)
        self.settings['selected_modes'] = selected


def field_values(frame, field):
    if field == 'Total magnitude':
        return frame['BT'].to_numpy(dtype=float)
    key = field if field in ('X', 'Y', 'Z') else None
    if key is None or key not in frame:
        raise ValueError(f'{signal_label(field)} is not available in this survey.')
    return frame[key].to_numpy(dtype=float)


def _uniform_series(frame, values, domain):
    key = 'Time (s)' if domain == 'Time' else 'Distance (m)'
    x = frame[key].to_numpy(dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(values).all():
        raise ValueError('Finite magnetic values and coordinates are required.')
    if np.any(np.diff(x) < 0):
        raise ValueError('The processing axis must be ordered.')
    # Repeated path-distance positions are averaged, not treated as extra samples.
    groups = pd.DataFrame({'axis': x, 'value': values}).groupby('axis', sort=True).value.mean()
    unique, samples = groups.index.to_numpy(), groups.to_numpy()
    if len(unique) < 16 or unique[-1] <= unique[0]:
        raise ValueError('At least 16 distinct time or path-distance positions are required.')
    step = np.median(np.diff(unique))
    count = int(np.clip(round((unique[-1]-unique[0])/step)+1, 16, 30000))
    uniform = np.linspace(unique[0], unique[-1], count)
    notes = [f'Uniform processing grid: {count} samples, spacing {uniform[1]-uniform[0]:.6g} ' + ('s.' if domain == 'Time' else 'm.'),
             'Results are interpolated back to the original survey positions.']
    if np.max(np.diff(unique)) > 5 * step:
        raise ValueError('A gap exceeds five median sampling intervals. Segment the survey before filtering.')
    if domain != 'Time':
        notes.append('Path distance is along the recorded walk, not a two-dimensional grid.')
    return x, uniform, np.interp(uniform, unique, samples), notes


def run_filter(frame, field='Total magnitude', domain='Time', method='VMD', **params):
    if method == 'VMD' and domain != 'Time':
        raise ValueError("This application's VMD workflow is time-based; choose Time.")
    before = field_values(frame, field)
    if domain == 'Spatial grid':
        if field != 'Total magnitude':
            raise ValueError('Spatial transformations require the total magnetic field; individual device components are not supported.')
        return _spatial(frame, before, method, params, field)
    if method not in SERIES_FILTERS:
        raise ValueError('Choose a time/path-series filter for this domain.')
    axis, uniform, values, notes = _uniform_series(frame, before, domain)
    if field in ('X','Y','Z'):
        notes.append('Phone components are device axes. No orientation correction is applied; phone rotation can change the component values.')
    dx = uniform[1]-uniform[0]
    settings = dict(params, field=field, domain=domain, method=method, spacing=float(dx))
    result = FilterResult(before.copy(), before.copy(), axis, 'Time (s)' if domain == 'Time' else 'Path distance (m)', settings, notes)
    if method == 'VMD':
        if dap.VMD is None:
            raise ValueError('Install vmdpy to run a genuine VMD decomposition.')
        k = int(params.get('k_modes', 10))
        if not 2 <= k <= 20 or len(values) < k*4:
            raise FilterSettingError(f'Number of modes is {k}, but VMD needs 2–20 modes and at least four samples per mode. '
                                     f'This series has {len(values)} samples, so use at most {min(20, len(values)//4)} modes.', 'k_modes')
        work = pd.DataFrame({'Time (s)': uniform, 'Easting (m)': uniform,
                             'Northing (m)': np.zeros(len(uniform)), 'Signal': values})
        alpha = float(params.get('alpha', 2000))
        if alpha <= 0:
            raise FilterSettingError(f'Penalty α is {alpha:g}, but it must be greater than 0.', 'alpha')
        config = dap.AnalysisParams(vmd_modes=k, vmd_alpha=alpha)
        result.modes, result.metrics, result.selected = dap.run_vmd_modes(work, config, field_column='Signal')
        result.mode_axis, result.mode_signal = uniform, values
        result.select_modes(result.selected)
        result.notes.append('Automatic recommendations use rate, variance ratio, spectral flatness, and ranking. Excluded modes remain available.')
        return result
    if method in ('Moving average', 'Savitzky–Golay'):
        window = int(params.get('window', 11))
        if window < 3 or window % 2 == 0 or window > len(values):
            largest = len(values) if len(values) % 2 else len(values)-1
            nearest = f' The nearest valid windows are {window-1} and {window+1}.' if window % 2 == 0 and 3 <= window < largest else ''
            raise FilterSettingError(f'Window (samples) is {window}, but {method} needs an odd window from 3 to {largest} '
                                     f'(the processing series has {len(values)} samples).' + nearest, 'window')
        if method == 'Moving average':
            out = np.convolve(np.pad(values, (window//2, window//2), mode='edge'), np.ones(window)/window, mode='valid')
        else:
            settings['polyorder'] = SAVITZKY_POLYORDER
            notes.append('Savitzky-Golay uses a fixed quadratic polynomial (degree 2). Coefficients are fitted locally in each window.')
            out = sp.savgol_filter(values, window, polyorder=SAVITZKY_POLYORDER)
    elif method == 'Linear detrend':
        out = sp.detrend(values)
    else:
        low, high = float(params.get('low', .05)), float(params.get('high', .5))
        nyquist = .5/dx
        unit = 'Hz' if domain == 'Time' else 'cycles/m'
        def check_cutoff(value, label, setting):
            if not 0 < value < nyquist:
                raise FilterSettingError(f'{label} cutoff is {value:g} {unit}, but it must be above 0 and below the Nyquist limit '
                                         f'of {nyquist:.4g} {unit} for this survey\'s sampling. Choose a value between 0 and {nyquist:.4g}.', setting)
        cutoff = high if method == 'Low-pass' else low
        if method == 'Band-pass':
            check_cutoff(low, 'Lower / high-pass', 'low');check_cutoff(high, 'Upper / low-pass', 'high')
            if low >= high:
                raise FilterSettingError(f'Lower cutoff ({low:g} {unit}) must be less than the upper cutoff ({high:g} {unit}).', 'low')
            cutoff = [low, high]
        else:
            check_cutoff(cutoff, 'Upper / low-pass' if method == 'Low-pass' else 'Lower / high-pass', 'high' if method == 'Low-pass' else 'low')
        sos = sp.butter(4, cutoff, btype={'Low-pass':'lowpass','High-pass':'highpass','Band-pass':'bandpass'}[method], fs=1/dx, output='sos')
        try:
            out = sp.sosfiltfilt(sos, values)
        except ValueError as exc:
            raise ValueError('The series is too short for this forward/backward filter.') from exc
        notes.append('Fourth-order Butterworth, forward/backward filtering; frequency units are ' + ('Hz.' if domain == 'Time' else 'cycles/m.'))
    result.after = np.interp(axis, uniform, out)
    return result


def _spatial(frame, values, method, params, field):
    if method not in SPATIAL_FILTERS:
        raise ValueError('Choose a spatial-grid transform.')
    e = frame['Easting (m)'].to_numpy(dtype=float)
    n = frame['Northing (m)'].to_numpy(dtype=float)
    xy = np.column_stack((e,n))
    if not np.isfinite(xy).all() or not np.isfinite(values).all():
        raise ValueError('Finite projected positions and field values are required.')
    if len(np.unique(xy,axis=0)) < 16 or np.linalg.matrix_rank(xy-xy.mean(axis=0)) < 2:
        raise ValueError('Spatial filtering needs two-dimensional survey coverage, not a single line.')
    cell = float(params.get('cell_size', 2.0))
    if cell <= 0:
        raise FilterSettingError('Grid spacing must be a positive number of metres.', 'cell_size')
    nx, ny = int(np.ceil(np.ptp(e)/cell))+1, int(np.ceil(np.ptp(n)/cell))+1
    if min(nx,ny)<4 or max(nx,ny)>512:
        smallest, largest = max(np.ptp(e), np.ptp(n))/511*1.01, min(np.ptp(e), np.ptp(n))/3*.99
        advice = (f'For this survey choose a spacing between {smallest:.3g} and {largest:.3g} m.' if smallest < largest
                  else 'No single spacing fits this survey\'s extent; the survey is too elongated for a spatial grid.')
        raise FilterSettingError(f'Grid spacing of {cell:g} m gives {nx} × {ny} cells, but each direction needs 4–512 cells. ' + advice, 'cell_size')
    gx, gy = np.linspace(e.min(),e.max(),nx), np.linspace(n.min(),n.max(),ny)
    xx, yy = np.meshgrid(gx,gy)
    grid = griddata(xy, values, (xx,yy), method='linear')
    missing = ~np.isfinite(grid)
    if missing.all():
        raise ValueError('The survey cannot support a spatial grid.')
    grid = grid[tuple(distance_transform_edt(missing, return_distances=False, return_indices=True))]
    dx,dy = gx[1]-gx[0],gy[1]-gy[0]
    pad = max(4,min(64,max(nx,ny)//4))
    baseline = float(np.median(values))
    padded = np.pad(grid-baseline,pad,mode='reflect')
    if method == 'Reduction to pole':
        inc, dec = float(params.get('inclination',60)),float(params.get('declination',0))
        if abs(inc)<15:
            raise FilterSettingError(f'Field inclination is {inc:g}°, but reduction to pole is unstable near the magnetic equator; '
                                     'use an inclination of at least 15° or at most −15°.', 'inclination')
        data = xr.DataArray(padded, dims=('northing','easting'), coords={
            'northing':gy[0]+np.arange(-pad,ny+pad)*dy,
            'easting':gx[0]+np.arange(-pad,nx+pad)*dx})
        filtered = hm.reduction_to_pole(data,inclination=inc,declination=dec).values
        offset = 0.0
    else:
        height = float(params.get('height',5))
        if height < 0:
            raise FilterSettingError(f'Continuation height is {height:g} m, but it must be zero or more metres.', 'height')
        ky = 2*np.pi*np.fft.fftfreq(padded.shape[0],d=dy)[:,None]
        kx = 2*np.pi*np.fft.fftfreq(padded.shape[1],d=dx)[None,:]
        exponent = height*np.hypot(kx,ky)
        if method == 'Upward continuation':
            kernel = np.exp(-exponent)
        else:
            gain = float(params.get('max_gain',10))
            if gain<1 or gain>100:
                raise FilterSettingError(f'Inverse gain cap is {gain:g}, but it must be between 1 and 100.', 'max_gain')
            # Bounded approximation; not an unconstrained inverse continuation.
            kernel = np.exp(np.minimum(exponent,np.log(gain)))
        filtered = np.fft.ifft2(np.fft.fft2(padded)*kernel).real
        offset = baseline
    after_grid = filtered[pad:pad+ny,pad:pad+nx]+offset
    after = RegularGridInterpolator((gy,gx),after_grid)((np.column_stack((n,e))))
    settings = dict(params,field=field,domain='Spatial grid',method=method,grid_dx_m=dx,grid_dy_m=dy)
    notes = ['Metric UTM grid; linear interpolation, nearest fill outside the convex hull, and reflection padding.',
             'Gridding and boundaries influence the result; map interpretation requires adequate survey coverage.']
    if method == 'Reduction to pole':
        notes.append('Median background removed. Enter field direction for the survey; magnetization is assumed parallel to the inducing field.')
    elif method == 'Regularized downward continuation':
        notes.append('Gain-capped inverse continuation is a stabilized approximation and can still amplify noise.')
    axis = frame['Time (s)'].to_numpy(dtype=float)
    return FilterResult(values.copy(),after,axis,'Time (s)',settings,notes,grids=(gx,gy,grid,after_grid))
