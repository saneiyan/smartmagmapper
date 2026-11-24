"""Survey maps: outline clipping, contour maps, inverse-distance gridding and georeferenced GeoTIFF export.

No PyQt; usable from scripts. showMap draws a quick map in longitude/latitude; saveMap writes a GeoTIFF.
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.path as mpath
import matplotlib.tri as mtri
from scipy.interpolate import griddata
from scipy.spatial import Delaunay
from scipy.spatial import ConvexHull
from processing import labels

# Optional packages: concave-hull and pykrige are not in requirements.txt; without them the outline falls back to
# the convex hull and kriging is not offered. rasterio (in requirements.txt) is needed for GeoTIFF export.
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
    """Map drawing and GeoTIFF export for survey data.

    Parameters
    ----------
    fp : pandas.DataFrame, str or None
        Default survey data for saveMap (a data frame or a CSV path); None when the data are always passed in.
    """
    def __init__(self, fp):
        """Keep the default survey data (see the class description)."""
        self.fp = fp

    def clipConvexHull(self, xdata, ydata, x, y, z):
        """Set interpolated values outside the convex hull of the measurements to NaN.

        Parameters
        ----------
        xdata, ydata : array_like
            Positions of the measurements.
        x, y : array_like
            Positions of the interpolated points.
        z : array_like
            Interpolated values.

        Returns
        -------
        numpy.ndarray
            Copy of `z` with NaN outside the convex hull.
        """
        knownPoints = np.unique(np.array([xdata, ydata], dtype=float).T, axis=0)
        hull = Delaunay(knownPoints[ConvexHull(knownPoints).vertices])
        znew = np.array(z, dtype=float, copy=True)
        # test every interpolation point at once (much faster than one at a time for raster grids)
        znew[hull.find_simplex(np.c_[x, y]) < 0] = np.nan
        return znew


    def clipConcaveHull(self, xdata, ydata, x, y, z):
        """Set interpolated values outside the concave hull (outline) of the measurements to NaN.

        Falls back to the convex hull when the optional concave-hull package is not installed.

        Parameters
        ----------
        xdata, ydata : array_like
            Positions of the measurements.
        x, y : array_like
            Positions of the interpolated points.
        z : array_like
            Interpolated values.

        Returns
        -------
        numpy.ndarray
            Copy of `z` with NaN outside the hull.
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
        """Filled contour map (matplotlib tricontourf) masked to the concave hull of the data.

        Without the concave-hull package the unmasked tricontourf is drawn.

        Parameters
        ----------
        x, y : array_like
            Positions.
        z : array_like
            Values.
        ax : matplotlib.axes.Axes, optional
            Axes to draw on; a new figure is created when not given.
        **kwargs
            Passed to tricontourf (levels, cmap, extend...).

        Returns
        -------
        matplotlib.contour.TriContourSet
            The contour set (for a colour bar).
        """
        if ax is None:
            _, ax = plt.subplots()

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
        """Inverse distance weighting interpolation.

        Parameters
        ----------
        xnew, ynew : array_like
            Positions to interpolate to.
        xknown, yknown, zknown : numpy.ndarray
            Measurement positions and values.
        n : float, optional
            Distance power (2 is the common choice).

        Returns
        -------
        numpy.ndarray
            Interpolated values; a point on a measurement takes that measurement.
        """
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


    def showMap(self, df, contour=False, ax=None, vmin=None, vmax=None, pts=False, cmap='viridis',
                xlab='Longitude (°)', ylab='Latitude (°)', levels=None, cbar_label=None):
        """Map of the total field (BT) in longitude/latitude, as points or filled contours.

        Parameters
        ----------
        df : pandas.DataFrame
            Survey with 'Longitude (°)', 'Latitude (°)' and 'BT'.
        contour : bool, optional
            Draw filled contours (clipped to the survey outline) instead of points.
        ax : matplotlib.axes.Axes, optional
            Axes to draw on; a new figure is created when not given.
        vmin, vmax : float, optional
            Colour limits; the 2nd and 98th percentiles when not given.
        pts : bool, optional
            With contours, also mark the measurement positions.
        cmap : str, optional
            Matplotlib colour map name.
        xlab, ylab : str, optional
            Axis labels.
        levels : array_like, optional
            Contour levels; 8 levels from vmin to vmax when not given.
        cbar_label : str, optional
            Colour bar label; defaults to the total-field label in the display unit.

        Returns
        -------
        matplotlib.figure.Figure or None
            The new figure when `ax` was not given, otherwise None.
        """
        x = df['Longitude (°)'].values
        y = df['Latitude (°)'].values
        val = df['BT'].values
        inan = ~np.isnan(val)
        val = val[inan]
        x = x[inan]
        y = y[inan]
        created = ax is None
        if created:
            fig, ax = plt.subplots()
        else:
            fig = ax.figure
        if vmin is None:
            vmin = np.nanpercentile(val, 2)
        if vmax is None:
            vmax = np.nanpercentile(val, 98)
        if contour is True:
            if levels is None or len(levels) == 0:
                #evenly spaced levels in any unit (rounding to whole units repeated levels for small ranges)
                levels = np.linspace(vmin, vmax, 8)
            cax = self.tricontourf_clipped(x, y, val, ax=ax, levels=levels, extend='both', cmap=cmap)
            if pts is True:
                ax.plot(x, y, 'k+')
        else:
            cax = ax.scatter(x, y, s=15, c=val, vmin=vmin, vmax=vmax, cmap=cmap)
        ax.set_xlabel(xlab)
        ax.set_ylabel(ylab)
        if len(x) > 0:
            ax.set_xlim([np.nanmin(x), np.nanmax(x)])
            ax.set_ylim([np.nanmin(y), np.nanmax(y)])
        ax.get_xaxis().get_major_formatter().set_useOffset(False)
        ax.get_yaxis().get_major_formatter().set_useOffset(False)
        ax.get_xaxis().get_major_formatter().set_scientific(False)
        ax.get_yaxis().get_major_formatter().set_scientific(False)
        fig.colorbar(cax, ax=ax, label=cbar_label or labels.total_field_label())
        if created:
            return fig

    def saveMap(self, fname, df=None, value_column='BT', cell_size=None, method='linear',
                projection='utm', output='values', cmap='viridis', vmin=None, vmax=None,
                nlevel=256, nx=100, ny=100, units='µT', description=None, tags=None):
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
        description : str, optional
            What the values are, e.g. 'Total Magnetic Field (BT) (nT) → High-pass'. Written as the band description and
            a 'description' tag; defaults to value_column.
        tags : dict, optional
            Extra metadata tags written to the file, e.g. the dataset name and the processing history.

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
        description = description or value_column
        extra = {key: str(value) for key, value in (tags or {}).items()}
        if output == 'values':
            with rasterio.open(fname, 'w', count=1, dtype='float32', nodata=np.nan, **profile) as dst:
                dst.write(z.astype('float32'), 1)
                dst.set_band_description(1, description)
                dst.update_tags(1, field=value_column, units=units, interpolation=method)
                dst.update_tags(description=description, **extra)
        elif output == 'rgba':
            lo = np.nanmin(z) if vmin is None else vmin
            hi = np.nanmax(z) if vmax is None else vmax
            rgba = plt.get_cmap(cmap, nlevel)(plt.Normalize(vmin=lo, vmax=hi)(z))
            rgba = (255 * rgba).astype('uint8')
            rgba[..., 3] = np.where(np.isfinite(z), 255, 0)
            with rasterio.open(fname, 'w', count=4, dtype='uint8', **profile) as dst:
                #red, green, blue, alpha
                for band in range(4):
                    dst.write(rgba[:, :, band], band + 1)
                dst.update_tags(field=value_column, units=units, interpolation=method, color_min=str(lo), color_max=str(hi), colormap=cmap,
                                description=description, **extra)
        else:
            raise ValueError("output must be 'values' or 'rgba'.")
        return {'width': ncols, 'height': nrows, 'crs': crs, 'cell_size_x': xres, 'cell_size_y': yres}
