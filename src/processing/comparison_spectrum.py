"""Comparable temporal Welch power densities on a shared uniform time grid."""
import numpy as np
import pandas as pd
from scipy.signal import welch


def comparison_spectra(time, signals, unit='µT'):
    """Welch power spectral densities of several signals on one shared, uniform time grid.

    Duplicate times are averaged and every signal is linearly interpolated to the same uniform grid, so the
    spectra are directly comparable.

    Parameters
    ----------
    time : array_like
        Sample times in seconds, shared by all signals.
    signals : dict of str to array_like
        Signal name -> values at `time`.
    unit : str, optional
        Magnetic unit of the values, recorded in the metadata as the density unit (unit^2/Hz).

    Returns
    -------
    frequency : numpy.ndarray
        Frequencies in Hz.
    densities : dict of str to numpy.ndarray
        Power spectral density of each signal.
    metadata : dict
        Method, sampling rate, segment length, window and other settings, for exports.

    Raises
    ------
    ValueError
        If the signals and times differ in length or are not finite, if there are fewer than 16 distinct times,
        or if a time gap exceeds five median sampling intervals.
    """
    time = np.asarray(time, dtype=float)
    values = {name: np.asarray(y, dtype=float) for name, y in signals.items()}
    if not values or any(y.shape != time.shape for y in values.values()):
        raise ValueError('Spectrum signals must share the same survey times.')
    if not np.isfinite(time).all() or any(not np.isfinite(y).all() for y in values.values()):
        raise ValueError('Finite survey times and field values are required.')
    grouped = pd.DataFrame({'time': time, **values}).groupby('time', sort=True).mean()
    unique = grouped.index.to_numpy()
    if len(unique) < 16:
        raise ValueError('Spectra require at least 16 distinct sample times.')
    step = float(np.median(np.diff(unique)))
    if np.max(np.diff(unique)) > 5 * step:
        raise ValueError('A time gap exceeds five median intervals. Segment the survey before comparing spectra.')
    count = int(np.clip(round((unique[-1]-unique[0])/step)+1, 16, 30000))
    uniform = np.linspace(unique[0], unique[-1], count)
    fs = 1 / (uniform[1]-uniform[0])
    segment = min(256, count)
    output = {}
    for name in values:
        y = np.interp(uniform, unique, grouped[name].to_numpy())
        frequency, density = welch(y, fs=fs, window='hann', nperseg=segment,
                                   noverlap=segment//2, detrend='constant', scaling='density')
        output[name] = density
    metadata = dict(method='Welch power spectral density', coordinate='Time',
                    frequency_unit='Hz', density_unit=f'{unit}^2/Hz', sampling_rate_hz=float(fs),
                    uniform_samples=count, segment_samples=segment, overlap_samples=segment//2,
                    window='Hann', detrend='constant per segment',
                    resampling='duplicate times averaged; linear interpolation to common uniform grid',
                    interpretation='Temporal spectrum along the recorded survey, including for path/grid filters; not a 2D spatial spectrum.')
    return frequency, output, metadata
