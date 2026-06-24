from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
import PyQt6.QtCore as QtCore
import tempfile
from PyQt6.QtCore import QUrl
import folium
import numpy as np
import branca.colormap as cm

class MapWidget(QWebEngineView):
    def __init__(self, df):
        super().__init__()
        self.df = df
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
        #create the map
        m = folium.Map(location=[latitude, longitude], zoom_start=zoom, prefer_canvas=True, tiles=None)
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
        #creating temporary html file to allow for >2MB datasets
        temp_map = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
        m.save(temp_map.name)
        #loading the temporary url
        self.url = QtCore.QUrl.fromLocalFile(temp_map.name)
        self.load(self.url)

    def color_map(self, bt):
        vmin = np.nanpercentile(bt, 2)
        vmax = np.nanpercentile(bt, 98)
        colormap = cm.LinearColormap(colors = ['blue', 'green', 'yellow'], vmin=vmin, vmax=vmax)
        return colormap
