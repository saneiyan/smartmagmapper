from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
import PyQt6.QtCore as QtCore
import tempfile
from PyQt6.QtCore import QUrl
import folium
import numpy as np
import branca.colormap as cm

#Leaflet maps are always drawn north-up, so a fixed arrow is accurate at any zoom
NORTH_ARROW_HTML = '''
<div style="position: fixed; top: 90px; left: 12px; z-index: 1000;
            background: rgba(255, 255, 255, 0.85); border-radius: 4px;
            padding: 4px 6px; box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4);
            font: bold 14px sans-serif; text-align: center; pointer-events: none;">
    <svg width="20" height="28" viewBox="0 0 20 28">
        <polygon points="10,0 20,28 10,21" fill="black"/>
        <polygon points="10,0 0,28 10,21" fill="white" stroke="black" stroke-width="1"/>
    </svg>
    <div>N</div>
</div>
'''

#white boxes behind the value scale and distance scale bar so their text reads over satellite imagery,
#matching the north arrow (!important because Leaflet's own CSS loads after this)
CONTROL_BACKGROUND_CSS = '''
<style>
    .legend.leaflet-control {
        background: rgba(255, 255, 255, 0.85) !important;
        border-radius: 4px;
        padding: 4px 6px;
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4);
    }
    .leaflet-control-scale-line {
        background: rgba(255, 255, 255, 0.85) !important;
    }
</style>
'''

class MapWidget(QWebEngineView):
    def __init__(self, df, caption='BT (µT)', vmin=None, vmax=None):
        super().__init__()
        self.df = df
        self.caption = caption
        self.vmin = vmin
        self.vmax = vmax
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

        #loading data and assigning coordinate variables
        x = self.df['Longitude (°)']
        x_mean = x.mean()
        y = self.df['Latitude (°)']
        y_mean = y.mean()
        self.bt = self.df['BT']

        #loading the map onto the view
        self.load_map(latitude=y_mean, longitude=x_mean, x=x, y=y, bt=self.bt)

    def load_map(self, latitude, longitude, x, y, bt, zoom=18):
        '''Loads the map onto the QWebEngineView widget.

        Parameters:
        ----------
            latitude (float): The latitude of the center of the map.
            longitude (float): The longitude of the center of the map.
            x (array-like): The x-coordinates of the data points.
            y (array-like): The y-coordinates of the data points.
            zoom (int, optional): The zoom level of the map. Defaults to 18.

        '''
        colormap = self.color_map(bt)
        #create the map, control_scale adds the distance scale bar in the bottom left
        m = folium.Map(location=[latitude, longitude], zoom_start=zoom, prefer_canvas=True, tiles=None, control_scale=True)
        #adding satellite imagery tile
        folium.TileLayer(
            tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
            attr='Google',
            max_zoom=25,
            name='Google Satellite').add_to(m)
        #adding circle markers for each data point in the imported dataframe
        val = list(bt)
        data = list(zip(y, x, val))
        fg = folium.FeatureGroup(name='Points')
        for lat, lon, val in data:
            folium.CircleMarker([lat, lon], color='black', fill=True, fill_color=colormap(val), fill_opacity=1, radius=2, weight=1).add_to(fg)
        m.add_child(fg)
        #value scale legend in the top right
        colormap.caption = self.caption
        colormap.add_to(m)
        #north arrow below the zoom buttons
        m.get_root().html.add_child(folium.Element(NORTH_ARROW_HTML))
        m.get_root().header.add_child(folium.Element(CONTROL_BACKGROUND_CSS))
        #creating temporary html file to allow for >2MB datasets
        temp_map = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
        m.save(temp_map.name)
        #loading the temporary url
        self.url = QtCore.QUrl.fromLocalFile(temp_map.name)
        self.load(self.url)

    def color_map(self, bt):
        #use the regular map's scale when one was set, otherwise the same default range
        vmin = self.vmin if self.vmin is not None else np.nanpercentile(bt, 2)
        vmax = self.vmax if self.vmax is not None else np.nanpercentile(bt, 98)
        if vmin >= vmax:
            vmin, vmax = np.nanpercentile(bt, 2), np.nanpercentile(bt, 98)
        colormap = cm.LinearColormap(colors = ['blue', 'green', 'yellow'], vmin=vmin, vmax=vmax)
        return colormap
