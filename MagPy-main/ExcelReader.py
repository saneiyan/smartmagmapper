import pandas as pd
import numpy as np
import openpyxl
import utm

class ExcelReader:
    def __init__(self, magdf, gpsdf):
        #initialize the ER with the Excel Sheet file path
#        self.file_path = file_path
#        self.sheets = self.get_sheet_names()
        self.magdf = magdf
        self.gpsdf = gpsdf

#    def get_sheet_names(self):
#        '''reads sheets names within Excel sheet'''
#        xls = pd.ExcelFile(self.file_path)
#        return(xls.sheet_names)

    def input_sheets(self):
        '''Merges separate Excel Sheets and cleans dataset'''
#        magdf = pd.read_excel(self.file_path, sheet_name = 'Magnetometer')
        #renaming columns from dataset to be uniform
#        rename_columns = {'Time (s)': 'Mag_Time (s)', 'Magnetic field x (µT)': 'X (µT)',
#                          'Magnetic field y (µT)': 'Y (µT)', 'Magnetic field z (µT)': 'Z (µT)'}
#        self.magdf = magdf.rename(columns=rename_columns)
#        if 'Time (s)' in self.magdf.columns:
#            self.magdf = self.magdf.rename(columns={'Time (s)': 'Mag_Time (s)'})
#        columns_to_keep = ['Mag_Time (s)', 'X (µT)', 'Y (µT)', 'Z (µT)']
#        self.magdf = self.magdf[columns_to_keep]
        #calculating total magnetic field vector from individual directions
        self.magdf['BT'] = np.sqrt(self.magdf['X (µT)']**2 + self.magdf['Y (µT)']**2 + self.magdf['Z (µT)']**2)
        #calculating the time difference of adjacent points throughout the dataset
        self.magdf['Diff'] = self.magdf['Mag_Time (s)'].diff()
        #calculating the mean difference between all datapoints, the sampling frequency
        self.average_sampling_frequency =  self.magdf['Diff'].mean()
        #maximum trustworthy difference in time between two adjacent data points
        magnetic_max_value = self.average_sampling_frequency * 1.2
        #minimum trustworthy difference in time between two adjacent data points
        magnetic_min_value = self.average_sampling_frequency * 0.8
        #removing datapoints that are outside of the maximum and minimum variables
        self.magdf = self.magdf.drop(self.magdf[self.magdf.Diff > magnetic_max_value].index)
        self.magdf = self.magdf.drop(self.magdf[self.magdf.Diff < magnetic_min_value].index)
        self.magdf = self.magdf.dropna().reset_index()


        #cleaning datapoints from Location sheet
#        gpsdf = pd.read_excel(self.file_path, sheet_name = 'Location')
#        if 'Time (s)' in gpsdf.columns:
#            self.gpsdf = gpsdf.rename(columns={'Time (s)': 'Loc_Time (s)'})
#        columns_to_keep = ['Loc_Time (s)', 'Latitude (°)', 'Longitude (°)','Height (m)']
#        self.gpsdf = self.gpsdf[columns_to_keep]
        #calculating the time difference of adjacent points throughout the dataset
        self.gpsdf['Diff'] = self.gpsdf['Loc_Time (s)'].diff()
        #calculating the mean difference between all datapoints, the sampling frequency
        self.average_time_frequency = self.gpsdf['Diff'].mean()
        #maximum trustworthy difference in time between two adjacent data points
        time_max_value = self.average_time_frequency * 1.2
        #minimum trustworthy difference in time between two adjacent data points
        time_min_value = self.average_time_frequency * 0.8
        #removing datapoints that are outside of the maximum and minimum variables
        self.gpsdf = self.gpsdf.drop(self.gpsdf[self.gpsdf.Diff > time_max_value].index)
        self.gpsdf = self.gpsdf.drop(self.gpsdf[self.gpsdf.Diff < time_min_value].index)
        self.gpsdf = self.gpsdf.dropna().reset_index()
        self.gpsdf = self.gpsdf.drop('Diff', axis=1)


    @staticmethod
    def findNearest(array, value):
        '''finding closest value in an array

        Parameters
        ----------
        array : n1array
            1D numpy array
        value : float
            any float to find the closest to in the array

        Returns
        --------
        array[idx] : float
            Closest value in the array to the input value
        idx : int
            row number of the closest value in the array to the input value
        '''
        array = np.asarray(array)
        idx = (np.abs(array - value)).argmin()
        return array[idx],idx

    @staticmethod
    def findFr(arr):
        '''determining the sample rate

        Parameters
        ----------
        arr : n1array
            1D numpy array.

        Returns
        -------
        fr : float
            sampling rate (Hz) of the dataset.

        '''
        fr = 1/(np.abs(arr[1]-arr[0]))
        return fr

    def interpolate(self):
        gt = self.gpsdf["Loc_Time (s)"].to_numpy()
        glat = self.gpsdf["Latitude (°)"].to_numpy()
        glon = self.gpsdf["Longitude (°)"].to_numpy()
        mt = self.magdf["Mag_Time (s)"].to_numpy()

        # index of first gps time >= mag_time
        idx = np.searchsorted(gt, mt, side="left")
        valid = (idx > 0) & (idx < len(gt))   # must have a lower and upper GPS fix

        lo = (idx - 1).clip(0, len(gt)-1)
        up = (idx).clip(0, len(gt)-1)

        t0 = gt[lo]; t1 = gt[up]
        dt = t1 - t0
        frac = np.zeros_like(mt, dtype=float)
        mask_nonzero = valid & (dt != 0)
        frac[mask_nonzero] = (mt[mask_nonzero] - t0[mask_nonzero]) / dt[mask_nonzero]
        frac = np.clip(frac, 0.0, 1.0)

        lat_i = np.full_like(mt, np.nan, dtype=float)
        lon_i = np.full_like(mt, np.nan, dtype=float)
        lat_i[valid] = glat[lo[valid]] * (1-frac[valid]) + glat[up[valid]] * frac[valid]
        lon_i[valid] = glon[lo[valid]] * (1-frac[valid]) + glon[up[valid]] * frac[valid]

        self.magdf["Latitude (°)"] = lat_i
        self.magdf["Longitude (°)"] = lon_i
        self.magdf["frac_in_interval"] = frac
        self.magdf["gps_lo_idx"] = lo
        self.magdf["gps_up_idx"] = up

        n_total = len(self.magdf)
        n_interp = int(np.sum(~np.isnan(lat_i)))
        n_out = n_total - n_interp
        print(f"Total MAG rows: {n_total}  interpolated: {n_interp}  out-of-range (no bracket): {n_out}")
        #mag[["Time (s)","Latitude_interp","Longitude_interp","frac_in_interval"]].head(12)
        columns_to_keep = ['Mag_Time (s)', 'X (µT)', 'Y (µT)', 'Z (µT)', 'BT', 'Latitude (°)', 'Longitude (°)']
        self.df = pd.DataFrame(self.magdf[columns_to_keep]).dropna()
        return self.df

    def convertUTM(self):
        self.df['utm_coords'] = self.df.apply(lambda row: utm.from_latlon(row['Latitude (°)'], row['Longitude (°)']), axis=1)
        # Extract the components into separate columns
        self.df['easting'] = self.df['utm_coords'].apply(lambda coord: coord[0])
        self.df['northing'] = self.df['utm_coords'].apply(lambda coord: coord[1])
        #anna_df['zone_number'] = anna_df['utm_coords'].apply(lambda coord: coord[2])
        #anna_df['zone_letter'] = anna_df['utm_coords'].apply(lambda coord: coord[3])

        # Drop the temporary 'utm_coords' column if no longer needed
        self.df = self.df.drop('utm_coords', axis=1)
        return self.df

    def distance(self):
        self.df['Easting_dist'] = self.df['easting'].diff()**2
        self.df['Northing_dist'] = self.df['northing'].diff()**2
        self.df['distance'] = np.sqrt(self.df['Easting_dist']+self.df['Northing_dist'])
        self.df['Distance (m)'] = self.df['distance'].cumsum()

        self.df = self.df.drop(['Easting_dist', 'Northing_dist', 'distance'], axis=1)
        return self.df

    def alignTime(self):
        '''aligns the offset dataframes of similar sampling rates by
        matching to nearest time'''
        #will update with Shoog's method when meeting together next Thursday
        #y = ((y2-y1)/(x2-x1)) * (x-x1) + y1
        gpstar = self.gpsdf['Loc_Time (s)'].values
        magtar = self.magdf['Mag_Time (s)'].values

        self.st, self.rowst = self.findNearest(magtar, gpstar[0])
        self.magdf = self.magdf.iloc[self.rowst:].reset_index()

        self.df = pd.concat([self.gpsdf, self.magdf], axis=1).dropna()
        #columns_to_keep =
        return self.df

    def alignTimeSearch(self):
        #only called on to align two arrays with widely varying sampling rates
        return
