import numpy as np
import pandas as pd
from scipy.fft import ifft2, fft2, fftfreq
from scipy.interpolate import griddata
import ppigrf
import datetime as dt
import harmonica as hm
import xarray as xr

class MapFilter:
    def __init__(self, df):
        self.df = df

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
        upwardcontinuation = pd.DataFrame(np.real(ifft2(ucdata)), columns=['BT'])
        df = pd.concat([upwardcontinuation, self.df[['Longitude (°)', 'Latitude (°)']]], axis=1)
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
        downwardcontinuation = pd.DataFrame(np.real(ifft2(dcdata)), columns=['BT'])
        df = pd.concat([downwardcontinuation, self.df[['Longitude (°)', 'Latitude (°)']]], axis=1)
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

    # #def first_vertical_derivative(self):

    # #def total_horizontal_derivative(self):
