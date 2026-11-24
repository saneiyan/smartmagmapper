"""Qt widget that shows a survey web map (the map itself is built by processing.web_map)."""
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
import PyQt6.QtCore as QtCore
from processing.web_map import build_map


class MapWidget(QWebEngineView):
    def __init__(self, df, caption=None, vmin=None, vmax=None):
        super().__init__()
        self.df = df
        self.caption = caption
        self.vmin = vmin
        self.vmax = vmax
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        self.bt = self.df['BT']
        #loading the map onto the view
        self.url = QtCore.QUrl.fromLocalFile(build_map(df, caption=caption, vmin=vmin, vmax=vmax))
        self.load(self.url)
