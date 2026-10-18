import pandas as pd
import numpy as np

import os
import warnings
from datetime import time, datetime

import matplotlib.pyplot as plt
import matplotlib.path as mpath
import matplotlib.tri as mtri
from scipy.stats import linregress
from scipy.spatial.distance import cdist
from scipy.interpolate import (griddata, NearestNDInterpolator,
    splrep, splev, make_smoothing_spline)
from scipy.spatial import Delaunay
from scipy.spatial import ConvexHull

class MapMaker:
    def __init__(self, fp):
        self.fp = fp

    def clipConvexHull(self, xdata, ydata, x, y, z):
        """Set to nan data outside the convex hull of xdata, ydata

        Parameters
        ----------
            xdata, ydata (arrays) : x and y position of the data collected
            x, y (arrays) : x and y position of the computed interpolation points
            z (arrays) : value of the interpolation

        Returns
        -------
            znew (array) : a copy of z with nan when outside convexHull
        """
        knownPoints = np.array([xdata, ydata]).T
        newPoints = np.array([x,y]).T
        _, idx = np.unique(xdata+ydata, return_index=1)
        q = ConvexHull(knownPoints[idx,:])
        hull = Delaunay(q.points[q.vertices, :])
    #    qq = q.points[q.vertices,:]

        znew = np.copy(z)
        for i in range(0, len(z)):
            if hull.find_simplex(newPoints[i,:]) < 0:
                znew[i] = np.nan
        return znew


    def clipConcaveHull(self, xdata, ydata, x, y, z):
        """Clip according to concave hull.

        Parameters
        ----------
        xdata : array_like
            X positions collected.
        ydata : array_like
            Y positions collected.
        x : array_like
            X positions of interpolated points
        y : array_like
            Y positions of interpolated points
        z : array_like
            Z values of interpolated points

        Returns
        -------
        znew : array_like
            Z values with NaN outside of the concave hull
        """
        try:
            from concave_hull import concave_hull_indexes
        except ImportError as e:
            print('concave-hull not installed, will use convexhull instead. Install it with `pip install concave-hull`')
            znew = self.clipConvexHull(xdata, ydata, x, y, z)
            return znew

        # estimate threshold
        threshold = np.max([(np.min(xdata) - np.max(xdata))/10,
                            (np.min(ydata) - np.max(ydata))/10])

        # building concave hull
        points = np.c_[xdata, ydata]
        idxes = concave_hull_indexes(points, length_threshold=threshold)

        # creating path of outside segments
        segs = []
        for f, t in zip(idxes[:-1], idxes[1:]):  # noqa
            seg = points[[f, t]]
            segs.append(seg[0, :])
        path = mpath.Path(segs)

        # set to NaN point outside concave hull
        ie = ~path.contains_points(np.c_[x, y])
        znew = np.copy(z)
        znew[ie] = np.nan

        return znew

    def tricontourf_clipped(self, x, y, z, ax=None, **kwargs):
        """Adaption of matplotlib tricontourf with mask inside concave hull.
        Note the additional 'ax' argument to specify the axis.

        Parameters
        ----------
        x : array_like
            X values.
        y : array_like
            Y values.
        z : array_like
            Z values.
        ax : maplotlib.axes.Axes
            Matplotlib axes.
        kwargs : optional
            Additional keyword arguments passed to tricontourf.

        Returns
        -------
        cax :
            Output of matplotlib tricontourf.
        """
        if ax is None:
            fig, ax = plt.subplots()
        else:
            fig = ax.figure

        try:
            from concave_hull import concave_hull_indexes
        except ImportError as e:
            print('concave-hull not installed, will use normal tricontourf instead. Install it with `pip install concave-hull`')
            cax = ax.tricontourf(x, y, z, **kwargs)
            return cax

        # make a triangulation
        triang = mtri.Triangulation(x, y)


        # compute triangles centroids
        centroid = np.mean([triang.x[triang.triangles], triang.y[triang.triangles]], axis=-1).T

        # compute concave hull
        threshold = np.max([(np.min(x) - np.max(x))/10,
                            (np.min(y) - np.max(y))/10])
        points = np.c_[x, y]
        idxes = concave_hull_indexes(points, length_threshold=threshold)

        # compute edges of the hull
        segs = []
        for f, t in zip(idxes[:-1], idxes[1:]):  # noqa
            seg = points[[f, t]]
            segs.append(seg[0, :])

        # create path and check if centroids are inside the concave hull
        path = mpath.Path(segs)
        ie = path.contains_points(centroid)
        triang.set_mask(~ie)

        # call tricontourf
        cax = ax.tricontourf(triang, z, **kwargs)

        return cax


    def idw(xnew, ynew, xknown, yknown, zknown, n=1):
        '''Inverse Distance Weighting'''
        znew = np.zeros(len(xnew))
        for i,(x,y) in enumerate(zip(xnew, ynew)):
    #        dist = pdist(x, y, xknown, yknown)
            dist = np.sqrt((x-xknown)**2+(y-yknown)**2)
            # if we consider all the points (might be not good)
            w = (1/dist)**n # exponent to be chosen
            znew[i] = np.sum(zknown*w)/np.sum(w)
        return znew


    def convertFromCoord(df, targetProjection=None):
        """Convert coordinates string (NMEA or DMS) to selected CRS projection.

        Parameters
        ----------
        df : pandas.DataFrame
            Dataframe with a 'latitude' and 'longitude' columns that contains NMEA
            string.
        targetProjection : str, optional
            Target CRS, in EPSG number: e.g. `targetProjection='EPSG:3395'`
            for the British Grid. If None, only WGS84 decimal degree will be returned.
        """
        import pyproj

        def NMEA(arg):
            """ Convert NMEA string to WGS84 (GPS) decimal degree.
            """
            try:
                letter = arg[-1]
                if (letter == 'W') | (letter == 'S'):
                    sign = -1
                else:
                    sign = 1
                arg = arg[:-1]
                x = arg.index('.')
                a = float(arg[:x-2]) # degree
                b = float(arg[x-2:]) # minutes
                return (a + b/60)*sign
            except Exception as e:
                print('ERROR in NMEA string conversion, will set NaN instead')
                return np.nan

        def DMS(arg):
            """Convert convert degrees, minutes, seconds to decimal degrees
            """
            letter = arg[-1]
            if (letter == 'W') | (letter == 'S'):
                sign = -1
            else:
                sign = 1
            #extract degrees from string
            deg_idx = arg.find('°')
            deg = int(arg[:deg_idx])
            #extract minutes from string
            min_idx = arg.find("'")
            mins = int(arg[(deg_idx+1):min_idx])
            #extract seconds from string
            sec_idx = arg.find('"')
            secs = float(arg[(min_idx+1):sec_idx])
            DD = deg + (mins/60) + (secs/3600) # decimal degree calculation
            return sign*DD # return with sign

        def gps2gps(x):
            return float(x)

        check = df['latitude'].values[0]
        if not isinstance(check, float):
            if check.find('°') !=-1 and check.find("'") != -1:
                print("Coordinates appear to be given as Degrees, minutes, seconds ... adjusting conversion scheme")
                gps2deg = np.vectorize(DMS)
            elif any([a in check for a in ['N','S','W','E']]):
                print('Coordinates converted from NMEA string')
                gps2deg = np.vectorize(NMEA)
            else:  # assume in decimal degree
                gps2deg = np.vectorize(gps2gps)
        else:
            gps2deg = np.vectorize(gps2gps)

        df['lat'] = gps2deg(df['latitude'].values)
        df['lon'] = gps2deg(df['longitude'].values)

        # in case some values were not well converted, drop the NaN rows
        df = df[df['lat'].notnull() & df['lon'].notnull()].reset_index(drop=True)

        if targetProjection is not None:
            try:
                transformer = pyproj.Transformer.from_crs('EPSG:4326', targetProjection, always_xy=True)
                df['x'], df['y'] = transformer.transform(
                    df['lon'].values, df['lat'].values)
                # wgs84 = pyproj.Proj("EPSG:4326") # LatLon with WGS84 datum used by GPS units and Google Earth
                # targetCRS = pyproj.Proj(targetProjection) # target EPSG
                # df['x'], df['y'] = pyproj.transform(wgs84, targetCRS,
                #                   df['lat'].values, df['lon'].values)
            except Exception as e:
                raise ValueError('You may need to upgrade pyproj (pip install -U pyproj) to have Transformer')
        else:  # set decimal degree as x,y if no projection given
            df['x'] = df['lon']
            df['y'] = df['lat']

        return df

    def showMap(self, df, contour=False, ax=None, vmin=None, vmax=None, cax=None,
                    pts=False, cmap='viridis', xlab='x', ylab='y', levels=[],
                    cbar_label='Total Magnetic Field [uT]'):
            """ Display a map of the measurements.

            Parameters
            ----------
            df : pandas.DataFrame
                DataFrame containing x, y (converted coordinates), and bt (total magnetic field)
            contour : bool, optional
                If `True` filled contour will be plotted using `tricontourf`.
            ax : Matplotlib.Axes, optional
                If specified, the graph will be plotted against the axis.
            vmin : float, optional
                Minimum of the colorscale.
            vmax : float, optional
                Maximum of the colorscale.
            pts : bool, optional
                If `True` the measurements location will be plotted on the graph.
            xlab : str, optional
                X label.
            ylab : str, optional
                Y label.
            levels list of float, optional
                If `contour == True`, levels are the contour intervals.
            """
            #self.df = pd.read_excel(self.fp)
            #links to ExcelReader Class without overriding the df
            self.df = df
            x = self.df['Longitude (°)'].values
            y = self.df['Latitude (°)'].values
            val = self.df['BT'].values
            inan = ~np.isnan(val)
            val = val[inan]
            x = x[inan]
            y = y[inan]
            if ax is None:
                fig, ax = plt.subplots()
            else:
                fig = ax.figure
            if vmin is None:
                vmin = np.nanpercentile(val, 2)
            if vmax is None:
                vmax = np.nanpercentile(val, 98)
 #           ax.set_title(coil)
            if contour is True:
                if len(levels) == 0:
                    #not rounded to whole µT, which repeated levels and failed for ranges under ~7 µT
                    levels = np.linspace(vmin, vmax, 8)
                # cax = ax.tricontourf(x, y, val, levels=levels, extend='both', cmap=cmap)
                cax = self.tricontourf_clipped(x, y, val, ax=ax, levels=levels, extend='both', cmap=cmap)
                if pts is True:
                    ax.plot(x, y, 'k+')
            else:
                cax = ax.scatter(x, y, s=15, c=val, vmin=vmin, vmax=vmax, cmap=cmap)
            ax.set_xlabel('Longitude (°)')
            ax.set_ylabel('Latitude (°)')
            if len(x) > 0:
                ax.set_xlim([np.nanmin(x), np.nanmax(x)])
                ax.set_ylim([np.nanmin(y), np.nanmax(y)])
            ax.get_xaxis().get_major_formatter().set_useOffset(False) # prevent exponent notation
            ax.get_yaxis().get_major_formatter().set_useOffset(False)
            ax.get_xaxis().get_major_formatter().set_scientific(False)
            ax.get_yaxis().get_major_formatter().set_scientific(False)
            fig.colorbar(cax, ax=ax, label=cbar_label)
            if ax is None:
                return fig

    def meshMap(self, ax=None, vmax=None,vmin=None, xmesh=None, ymesh=None, val=None, levels=None):
        if ax is None:
            fig, ax = plt.subplots()
        else:
            fig = ax.figure
        if vmin is None:
            vmin = np.nanpercentile(val, 2)
        if vmax is None:
            vmax = np.nanpercentile(val, 98)
        levels = np.linspace(vmin, vmax, 14)
        #plt.figure(figsize=(10, 6))
        contour_plot = ax.contourf(xmesh, ymesh, val, cmap='viridis')
        fig.colorbar(contour_plot, ax=ax, label='BT (µT)')
        plt.xlabel('Easting')
        plt.ylabel('Northing')
        plt.title('Original BT')
        return fig

    def saveMap(self, fname, nx=100, ny=100, method='linear',
                xmin=None, xmax=None, ymin=None, ymax=None, cmap='viridis',
                vmin=None, vmax=None, nlevel=14, targetProjection='EPSG:4326'):
        """Save a georeferenced raster TIFF file.

        Parameters
        ----------
        df : pandas.DataFrame
            DataFrame containing x, y (coordinates), and bt (total magnetic field)
        fname : str
            Path of where to save the .tiff file.
        nx : int, optional
            Number of points in x direction.
        ny : int, optional
            Number of points in y direction.
        method : str, optional
            Interpolation method (nearest, cubic or linear see
            `scipy.interpolate.griddata`) or IDW (default).
        xmin : float, optional
            Mininum X value.
        xmax : float, optional
            Maximum X value.
        ymin : float, optional
            Minimium Y value.
        ymax : float, optional
            Maximum Y value
        cmap : str, optional
            If `color == True`, name of the colormap. Default is viridis.
        vmin : float, optional
            Minimum value for colomap.
        vmax : float, optional
            Maximum value for colormap.
        nlevel : int, optional
            Number of level in the colormap. Default 7.
        targetProjection : str, optional
            Target CRS, in EPSG number: e.g. `targetProjection='EPSG:4326'` Default DMS
        """

        try:
            import rasterio
            from rasterio.transform import from_origin
        except:
            raise ImportError('rasterio is needed to save georeferenced .tif file. Install it with "pip install rasterio"')

        self.df = pd.read_csv(self.fp)
        xknown = self.df['Longitude (°)'].values
        yknown = self.df['Latitude (°)'].values
        if xmin is None:
            xmin = np.min(xknown)
        if xmax is None:
            xmax = np.max(xknown)
        if ymin is None:
            ymin = np.min(yknown)
        if ymax is None:
            ymax = np.max(yknown)
        X, Y = np.meshgrid(np.linspace(xmin, xmax, nx),
                           np.linspace(ymin, ymax, ny))
        x, y = X.flatten(), Y.flatten()

        # compute convex hull
        inside = np.ones(nx*ny)
        # inside2 = clipConvexHull(xknown, yknown, x, y, inside)
        inside2 = self.clipConcaveHull(xknown, yknown, x, y, inside)

        ie = np.isnan(inside2).reshape(X.shape)

        values = self.df['BT'].values
        if method == 'idw':
            z = self.idw(x, y, xknown, yknown, values)
            z = z.reshape(X.shape)
        elif method == 'kriging':
            from pykrige.ok import OrdinaryKriging
            gridx = np.linspace(xmin, xmax, nx)
            gridy = np.linspace(ymin, ymax, ny)
            OK = OrdinaryKriging(xknown, yknown, values, variogram_model='linear',
                                verbose=True, enable_plotting=False, nlags=25)
            z, ss = OK.execute('grid', gridx, gridy)
        else:
            z = griddata(np.c_[xknown, yknown], values, (X, Y), method=method)
        z[ie] = np.nan
        Z = np.flipud(z.T)
        Z = np.fliplr(np.flipud(Z.T))

        # distance between corners
        dist0 = np.abs(xmax - xmin)
        dist1 = np.abs(ymax - ymin)
        yscale = dist1/Z.shape[0]
        xscale = dist0/Z.shape[1]

        # compute affine transform
        tOffsetScaling = from_origin(xmin - xscale/2, ymax - yscale/2, xscale, yscale)
        tt = tOffsetScaling

        if vmin is None:
            vmin = np.nanpercentile(Z.flatten(), 2)
        if vmax is None:
            vmax = np.nanpercentile(Z.flatten(), 98)
        norm = plt.Normalize(vmin=vmin, vmax=vmax)
        Z = plt.get_cmap(cmap, nlevel)(norm(Z))
        Z = 255*Z
        Z = Z.astype('uint8')
        for i in range(4):
            Z[np.fliplr(ie.T).T, i] = 0

        with rasterio.open(fname, 'w',
                    driver='GTiff',
                    height=Z.shape[0],
                    width=Z.shape[1], count=4, dtype=Z.dtype,
                    crs=targetProjection, transform=tt) as dst:
            for i in range(4):  # RGB + mask
                dst.write(Z[:,:,i], i+1)
