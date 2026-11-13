import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.path as mpath
import matplotlib.tri as mtri
from scipy.interpolate import griddata
from scipy.spatial import Delaunay
from scipy.spatial import ConvexHull
import pyproj
from processing import labels

# Optional packages (not in requirements.txt):
# falling back or explaining what to install when a feature needs one.
try:
    from concave_hull import concave_hull_indexes
except ImportError:
    concave_hull_indexes = None
try:
    import rasterio
    from rasterio.transform import from_origin
except Exception:
    rasterio = from_origin = None
try:
    from pykrige.ok import OrdinaryKriging
except ImportError:
    OrdinaryKriging = None

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
        knownPoints = np.unique(np.array([xdata, ydata], dtype=float).T, axis=0)
        hull = Delaunay(knownPoints[ConvexHull(knownPoints).vertices])
        znew = np.array(z, dtype=float, copy=True)
        # test every interpolation point at once (much faster than one at a time for raster grids)
        znew[hull.find_simplex(np.c_[x, y]) < 0] = np.nan
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
        if concave_hull_indexes is None:
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

        if concave_hull_indexes is None:
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


    @staticmethod
    def idw(xnew, ynew, xknown, yknown, zknown, n=1):
        '''Inverse Distance Weighting (n is the distance power; 2 is the common choice).'''
        znew = np.zeros(len(xnew))
        for i,(x,y) in enumerate(zip(xnew, ynew)):
            dist = np.sqrt((x-xknown)**2+(y-yknown)**2)
            exact = dist == 0
            if exact.any():  # a grid node on a measurement takes that measurement
                znew[i] = np.mean(zknown[exact])
                continue
            w = (1/dist)**n
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
                    cbar_label=None):
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
            fig.colorbar(cax, ax=ax, label=cbar_label or labels.total_field_label())
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
        fig.colorbar(contour_plot, ax=ax, label=labels.total_field_label())
        plt.xlabel('Easting')
        plt.ylabel('Northing')
        plt.title('Original BT')
        return fig

    def saveMap(self, fname, df=None, value_column='BT', cell_size=None, method='linear',
                projection='utm', output='values', cmap='viridis', vmin=None, vmax=None,
                nlevel=256, nx=100, ny=100, units='µT'):
        """Save a georeferenced raster (GeoTIFF) of a survey field on a north-up grid.

        Parameters
        ----------
        fname : str
            Path of the .tif file to write.
        df : pandas.DataFrame, optional
            Survey data. Defaults to the data given to MapMaker (or read from its file path).
        value_column : str, optional
            Column to rasterize, e.g. 'BT' or 'X'.
        units : str, optional
            Unit of the values (written to the GeoTIFF metadata), e.g. 'nT' or 'µT'.
        cell_size : float, optional
            Raster cell size in metres. If None, the grid is nx by ny cells.
        method : str, optional
            'linear', 'cubic' or 'nearest' (scipy griddata), 'idw' or 'kriging' (needs pykrige).
        projection : str, optional
            'utm' writes metric Easting/Northing in the survey's UTM zone (square cells);
            'wgs84' writes longitude/latitude (EPSG:4326).
        output : str, optional
            'values' writes one 32-bit float band of field values (NaN outside the survey), for GIS analysis;
            'rgba' writes a coloured image using cmap and vmin/vmax, transparent outside the survey.
        cmap, vmin, vmax, nlevel : optional
            Colour map, colour limits (default: data range) and number of colours for output='rgba'.
        nx, ny : int, optional
            Grid size when cell_size is None.

        Returns
        -------
        dict
            Raster width, height, CRS and cell size.
        """
        if rasterio is None:
            raise ImportError('rasterio is needed to save georeferenced .tif file. Install it with "pip install rasterio"')
        data = df if df is not None else (self.fp if isinstance(self.fp, pd.DataFrame) else pd.read_csv(self.fp))
        data = data.dropna(subset=[value_column])
        values = data[value_column].to_numpy(dtype=float)
        if projection == 'utm':
            if not {'Easting (m)', 'Northing (m)', 'UTM_EPSG'} <= set(data.columns):
                raise ValueError('UTM output needs Easting (m), Northing (m) and UTM_EPSG columns.')
            xknown = data['Easting (m)'].to_numpy(dtype=float)
            yknown = data['Northing (m)'].to_numpy(dtype=float)
            crs = f"EPSG:{int(data['UTM_EPSG'].iloc[0])}"
        elif projection == 'wgs84':
            xknown = data['Longitude (°)'].to_numpy(dtype=float)
            yknown = data['Latitude (°)'].to_numpy(dtype=float)
            crs = 'EPSG:4326'
        else:
            raise ValueError("projection must be 'utm' or 'wgs84'.")
        if len(np.unique(np.c_[xknown, yknown], axis=0)) < 3:
            raise ValueError('At least three distinct survey positions are needed for a raster.')
        xmin, xmax, ymin, ymax = xknown.min(), xknown.max(), yknown.min(), yknown.max()

        # cell size in the output units (metres for UTM, degrees for WGS 84)
        if cell_size is None:
            xres, yres = (xmax - xmin) / max(nx - 1, 1), (ymax - ymin) / max(ny - 1, 1)
        elif projection == 'utm':
            xres = yres = float(cell_size)
        else:
            yres = float(cell_size) / 111_132.0
            xres = float(cell_size) / (111_320.0 * np.cos(np.radians(np.mean(yknown))))
        if xres <= 0 or yres <= 0:
            raise ValueError('The survey extent and cell size must be positive.')
        ncols = int(np.floor((xmax - xmin) / xres)) + 1
        nrows = int(np.floor((ymax - ymin) / yres)) + 1
        if ncols * nrows > 25_000_000:
            raise ValueError(f'A {ncols} x {nrows} raster is too large; choose a larger cell size.')

        # cell centres, north-up: row 0 is the northern edge
        gx = xmin + xres * np.arange(ncols)
        gy = ymax - yres * np.arange(nrows)
        X, Y = np.meshgrid(gx, gy)
        if method == 'idw':
            z = self.idw(X.ravel(), Y.ravel(), xknown, yknown, values, n=2).reshape(X.shape)
        elif method == 'kriging':
            if OrdinaryKriging is None:
                raise ImportError('pykrige is needed for kriging interpolation. Install it with "pip install pykrige"')
            OK = OrdinaryKriging(xknown, yknown, values, variogram_model='linear',
                                 verbose=False, enable_plotting=False, nlags=25)
            z, _ = OK.execute('grid', gx, gy[::-1])
            z = np.flipud(np.asarray(z, dtype=float))
        elif method in ('linear', 'cubic', 'nearest'):
            z = griddata(np.c_[xknown, yknown], values, (X, Y), method=method)
        else:
            raise ValueError(f'Unknown interpolation method: {method}')
        z = np.asarray(z, dtype=float)
        # leave cells outside the surveyed area empty
        outside = np.isnan(self.clipConcaveHull(xknown, yknown, X.ravel(), Y.ravel(), np.ones(X.size))).reshape(X.shape)
        z[outside] = np.nan

        # top-left corner of the top-left cell
        transform = from_origin(gx[0] - xres / 2, gy[0] + yres / 2, xres, yres)
        profile = dict(driver='GTiff', height=nrows, width=ncols, crs=crs, transform=transform, compress='deflate')
        if output == 'values':
            with rasterio.open(fname, 'w', count=1, dtype='float32', nodata=np.nan, **profile) as dst:
                dst.write(z.astype('float32'), 1)
                dst.set_band_description(1, value_column)
                dst.update_tags(1, field=value_column, units=units, interpolation=method)
        elif output == 'rgba':
            lo = np.nanmin(z) if vmin is None else vmin
            hi = np.nanmax(z) if vmax is None else vmax
            rgba = plt.get_cmap(cmap, nlevel)(plt.Normalize(vmin=lo, vmax=hi)(z))
            rgba = (255 * rgba).astype('uint8')
            rgba[..., 3] = np.where(np.isfinite(z), 255, 0)
            with rasterio.open(fname, 'w', count=4, dtype='uint8', **profile) as dst:
                for band in range(4):  # red, green, blue, alpha
                    dst.write(rgba[:, :, band], band + 1)
                dst.update_tags(field=value_column, units=units, interpolation=method, color_min=str(lo), color_max=str(hi), colormap=cmap)
        else:
            raise ValueError("output must be 'values' or 'rgba'.")
        return {'width': ncols, 'height': nrows, 'crs': crs, 'cell_size_x': xres, 'cell_size_y': yres}
