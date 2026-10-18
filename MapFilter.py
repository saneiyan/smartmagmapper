import numpy as np
import pandas as pd
from scipy.fft import ifft2, fft2, fftfreq
from scipy.interpolate import griddata
from scipy.ndimage import distance_transform_edt
import ppigrf
import datetime as dt
import harmonica as hm
import xarray as xr

try:
    from vmdpy import VMD
except Exception:  # pragma: no cover - keeps the app importable if vmdpy is missing.
    VMD = None

class MapFilter:
    def __init__(self, df):
        self.df = df

    @staticmethod
    def _dominant_rate(values, dt_seconds=1.0):
        arr = np.asarray(values, dtype=float) - np.nanmean(values)
        if len(arr) < 3:
            return 0.0
        freqs = np.fft.rfftfreq(len(arr), max(float(dt_seconds), 1e-6))
        power = np.abs(np.fft.rfft(arr)) ** 2
        if len(freqs) <= 1:
            return 0.0
        idx = 1 + int(np.argmax(power[1:]))
        return float(freqs[idx])

    @staticmethod
    def _spectral_flatness(values):
        arr = np.asarray(values, dtype=float) - np.nanmean(values)
        power = np.abs(np.fft.rfft(arr)) ** 2 + 1e-12
        return float(np.exp(np.mean(np.log(power))) / np.mean(power))

    @staticmethod
    def _median_sample_interval(df):
        for col in ("Mag_Time (s)", "Time (s)", "Loc_Time (s)"):
            if col in df.columns:
                time = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
                dt_values = np.diff(time[np.isfinite(time)])
                dt_values = dt_values[dt_values > 0]
                if len(dt_values):
                    return float(np.nanmedian(dt_values))
        return 1.0

    def variational_mode_decomposition(self, k_modes=10, alpha=2000.0, max_modes=2):
        """Applies a VMD anomaly-component reconstruction to the BT column.

        The filter decomposes the median-centered total field, ranks modes by
        energy, spectral flatness, and dominant rate, then reconstructs BT from
        the selected non-trend and non-noise modes plus the original baseline.
        """
        if VMD is None:
            raise ImportError("The vmdpy package is required for the VMD filter.")
        if "BT" not in self.df.columns:
            raise ValueError("The VMD filter requires a BT column.")

        out = self.df.copy()
        signal = pd.to_numeric(out["BT"], errors="coerce")
        if signal.notna().sum() < max(int(k_modes) * 4, 20):
            raise ValueError("Not enough valid BT samples for VMD filtering.")

        filled = signal.interpolate(limit_direction="both").fillna(signal.median()).to_numpy(dtype=float)
        baseline = float(np.nanmedian(filled))
        centered = filled - baseline

        modes, _, _ = VMD(
            centered,
            alpha=float(alpha),
            tau=0.0,
            K=int(k_modes),
            DC=0,
            init=1,
            tol=1e-7,
        )
        modes = np.asarray(modes, dtype=float)

        dt_seconds = self._median_sample_interval(out)
        rates = [self._dominant_rate(mode, dt_seconds) for mode in modes]
        order = np.argsort(rates)
        modes = modes[order]

        raw_var = float(np.nanvar(centered)) or 1.0
        rows = []
        for i, mode in enumerate(modes, start=1):
            rows.append(
                {
                    "mode": i,
                    "energy_ratio": float(np.nanvar(mode) / raw_var),
                    "dominant_rate_hz": self._dominant_rate(mode, dt_seconds),
                    "spectral_flatness": self._spectral_flatness(mode),
                    "original_vmd_order_zero_based": int(order[i - 1]),
                }
            )
        metrics = pd.DataFrame(rows)
        er = metrics["energy_ratio"].to_numpy(dtype=float)
        fr = metrics["dominant_rate_hz"].to_numpy(dtype=float)
        sf = metrics["spectral_flatness"].to_numpy(dtype=float)
        metrics["noise_like"] = (sf > np.nanpercentile(sf, 80)) & (er < np.nanmedian(er))
        metrics["trend_like"] = fr <= max(0.001, np.nanpercentile(fr, 10))
        metrics["extreme_high_rate"] = fr >= np.nanpercentile(fr, 95)

        candidates = metrics[
            (~metrics["noise_like"]) & (~metrics["trend_like"]) & (~metrics["extreme_high_rate"])
        ].copy()
        candidates = candidates[candidates["energy_ratio"] >= max(0.035, float(metrics["energy_ratio"].median()))]
        if candidates.empty:
            candidates = metrics[~metrics["trend_like"]].copy()
        if candidates.empty:
            candidates = metrics.copy()
        candidates["rank_score"] = candidates["energy_ratio"] * (
            1.0 - candidates["spectral_flatness"].clip(0, 0.95)
        )
        selected_modes = sorted(
            candidates.sort_values("rank_score", ascending=False).head(int(max_modes))["mode"].astype(int).tolist()
        )
        metrics["selected"] = metrics["mode"].isin(selected_modes)

        selected_idx = [mode - 1 for mode in selected_modes]
        reconstructed = modes[selected_idx].sum(axis=0) + baseline
        if "BT_Original" not in out.columns:
            out["BT_Original"] = signal
        out["VMD_Filtered_BT"] = reconstructed
        out["BT"] = reconstructed
        return out, selected_modes, metrics

    def upward_continuation(self, H):
        '''Applies the Upward Continuation filter to FFT time-domain data.


        Parameters
        ----------
        H : float
            Height of upward continuation.

        Returns
        -------
        dfuc : TYPE
            Dataset with transformed BT to upward continued simulated data..

        '''
        self.H = H
        #self.df = pd.read_csv(self.fp)
        #self.df = df
        input_array = self.df[['BT']].to_numpy()
        n = len(self.df)
        #FFT to time-domain magnetic data to transform into frequency domain
        forward = fft2(input_array)

        #sampling frequencies of time domain FFT array
        fx = abs(fftfreq(n,d=1.0)).reshape(n, 1)

        #upward continuation configuration
        upward_config = np.exp(-self.H*fx)

        #applying the upward continuation filter
        ucdata = upward_config * forward

        #inverse FFT to transform data back to original domain
        upwardcontinuation = np.real(ifft2(ucdata)).ravel()
        #keep every original column so the result can be exported and plotted over time
        df = self.df.copy()
        df['Upward_BT'] = upwardcontinuation
        df['BT'] = upwardcontinuation
        return df

    def downward_continuation(self, H):
        '''Applies the Downward Continuation filter to FFT time-domain data.


        Parameters
        ----------
        H : float
            Height of downward continuation.

        Returns
        -------
        dfdc : pandas.DataFrame
            Dataset with transformed BT to downward continued simulated data.

        '''
        self.H = H
        #self.df = pd.read_csv(self.fp)
        input_array = self.df[['BT']].to_numpy()
        n = len(self.df)
        #FFT to time-domain magnetic data to transform into frequency domain
        forward = fft2(input_array)

        #sampling frequencies of time domain FFT array
        fx = abs(fftfreq(n,d=1.0)).reshape(n, 1)

        #downward continuation configuration
        downward_config = np.exp(self.H*fx)

        #applying the downward continuation filter
        dcdata = downward_config * forward

        #inverse FFT to transform data back to original domain
        downwardcontinuation = np.real(ifft2(dcdata)).ravel()
        #keep every original column so the result can be exported and plotted over time
        df = self.df.copy()
        df['Downward_BT'] = downwardcontinuation
        df['BT'] = downwardcontinuation
        return df

    def reduction_to_pole(self, year, month, day):
        map_lat = self.df['Latitude (°)'].values
        map_lon = self.df['Longitude (°)'].values
        map_lat_mean = map_lat.mean()
        map_lon_mean = map_lon.mean()
        bt = self.df['BT'].values

        #date of the survey
        time = dt.date(year=year, month=month, day=day)
        #converting to pandas timestamp
        date = pd.Timestamp(time)
        #interpolating the magnetic field data onto a regular grid
        ncols = 500
        nrows = 500
        lon_grid = np.linspace(map_lon.min(), map_lon.max(), ncols)
        lat_grid = np.linspace(map_lat.min(), map_lat.max(), nrows)
        lon_mesh, lat_mesh = np.meshgrid(lon_grid, lat_grid)

        #Interpolate BT onto the mesh grid
        interpolate_bt = griddata(points=(map_lon, map_lat), values=bt, xi=(lon_mesh, lat_mesh), method='linear')
        nan_mask = np.isnan(interpolate_bt)

        #filling the NaN values with the mean BT value for filtering
        fill_value = np.nanmean(bt)
        interpolate_bt = np.nan_to_num(interpolate_bt, nan=fill_value)
        interpolate_bt = xr.DataArray(interpolate_bt,
            coords={'latitude': lat_grid, 'longitude': lon_grid},
            dims=['latitude', 'longitude'])
        #calculating the IGRF at the survey site (Easting, Northing, Upward)
        Be, Bn, Bu = ppigrf.igrf(lon=map_lon_mean, lat=map_lat_mean, h=0, date=date)
        #converting the IGRF components to intensity, inclination, and declination
        intensity, inclination, declination = hm.magnetic_vec_to_angles(Be[0], Bn[0], Bu[0])
        #reduction to pole transformation
        rtp = hm.reduction_to_pole(interpolate_bt, inclination, declination)
        #masking the NaN values in the RTP data
        rtp = rtp.where(~nan_mask, np.nan)
        return rtp, lon_mesh, lat_mesh

    def _with_residual(self, background):
        '''Copy of the data with BT replaced by BT minus the given background (µT).'''
        out = self.df.copy()
        out['Background_BT'] = background
        out['Residual_BT'] = out['BT'].to_numpy(dtype=float) - background
        out['BT'] = out['Residual_BT']
        return out

    def residual_trend(self, outlier_mad=3.0, iterations=3):
        '''Removes a planar background trend fitted to the survey itself, leaving local anomalies.

        Strong anomalies are left out of the fit (beyond outlier_mad robust standard
        deviations) so they don't tilt the background.

        Returns
        -------
        df : pandas.DataFrame
            Copy of the dataset with BT replaced by the residual, plus Background_BT and Residual_BT.
        '''
        lat = self.df['Latitude (°)'].to_numpy(dtype=float)
        lon = self.df['Longitude (°)'].to_numpy(dtype=float)
        bt = self.df['BT'].to_numpy(dtype=float)
        #local east/north offsets in metres, accurate enough for fitting a plane
        lat0, lon0 = np.nanmean(lat), np.nanmean(lon)
        x = (lon - lon0) * 111320.0 * np.cos(np.radians(lat0))
        y = (lat - lat0) * 110540.0
        design = np.column_stack([np.ones_like(x), x, y])
        fit_mask = np.isfinite(bt) & np.isfinite(x) & np.isfinite(y)
        if fit_mask.sum() < 3:
            raise ValueError('Not enough valid points to fit a background trend.')
        valid = fit_mask.copy()
        for _ in range(iterations):
            coef, *_ = np.linalg.lstsq(design[fit_mask], bt[fit_mask], rcond=None)
            resid = bt - design @ coef
            center = np.nanmedian(resid[valid])
            mad = 1.4826 * np.nanmedian(np.abs(resid[valid] - center))
            if not mad > 0:
                break
            new_mask = valid & (np.abs(resid - center) <= outlier_mad * mad)
            if new_mask.sum() < 3 or np.array_equal(new_mask, fit_mask):
                break
            fit_mask = new_mask
        return self._with_residual(design @ coef)

    def residual_igrf(self, year, month, day):
        '''Removes the IGRF model Earth field for each point's location on the survey date.

        Returns
        -------
        df : pandas.DataFrame
            Copy of the dataset with BT replaced by the residual, plus Background_BT and Residual_BT.
        '''
        date = pd.Timestamp(dt.date(year=year, month=month, day=day))
        lat = self.df['Latitude (°)'].to_numpy(dtype=float)
        lon = self.df['Longitude (°)'].to_numpy(dtype=float)
        Be, Bn, Bu = ppigrf.igrf(lon=lon, lat=lat, h=0, date=date)
        #IGRF is in nT, BT is in µT
        background = np.sqrt(Be ** 2 + Bn ** 2 + Bu ** 2).ravel() / 1000.0
        return self._with_residual(background)

    def reduction_to_pole_points(self, year, month, day):
        '''Applies reduction to pole and samples the gridded result back at the
        survey points, so the output matches the other filters.

        Returns
        -------
        df : pandas.DataFrame
            Copy of the input dataset with BT replaced by the RTP values.
        '''
        rtp, _lon_mesh, _lat_mesh = self.reduction_to_pole(year=year, month=month, day=day)
        #survey points on the edge of the area sit next to masked grid cells,
        #so fill masked cells from the closest valid cell before sampling
        grid = rtp.values
        masked = np.isnan(grid)
        if masked.any() and not masked.all():
            nearest_idx = distance_transform_edt(masked, return_distances=False, return_indices=True)
            rtp = rtp.copy(data=grid[tuple(nearest_idx)])
        points_lon = xr.DataArray(self.df['Longitude (°)'].values, dims='points')
        points_lat = xr.DataArray(self.df['Latitude (°)'].values, dims='points')
        rtp_values = rtp.interp(longitude=points_lon, latitude=points_lat).values
        out = self.df.copy()
        out['RTP_BT'] = rtp_values
        out['BT'] = rtp_values
        return out

    # #def first_vertical_derivative(self):

    # #def total_horizontal_derivative(self):
