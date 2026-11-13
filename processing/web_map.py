"""Folium web maps of survey data (no PyQt: usable from scripts). The on-screen widget is ui.web_map_widget."""
import tempfile
from processing import labels
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

# Satellite imagery shared by every web map in the app (Data & Cleaning and Location Estimate).
GOOGLE_SATELLITE = dict(tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google',
                        max_zoom=25, name='Google Satellite')


def add_satellite_layer(m, **options):
    '''Add the Google satellite imagery layer to a folium map (options such as show=True pass through).'''
    folium.TileLayer(**GOOGLE_SATELLITE, **options).add_to(m)


def build_map(df, value_column='BT', caption=None, vmin=None, vmax=None, colors=None,
              excluded=None, excluded_name='Excluded Positions', layer_name='Points', zoom=18):
    '''Builds the satellite web map and saves it to a temporary html file.

    Parameters:
    ----------
        df (DataFrame): Survey points with 'Latitude (°)', 'Longitude (°)' and value_column.
        value_column (str, optional): Column used to colour the points. Defaults to 'BT'.
        caption (str, optional): Colour scale caption (default: the column's label in the current unit).
        vmin, vmax (float, optional): Colour scale limits, 2nd/98th percentile when not given.
        colors (list, optional): Colour ramp; defaults to blue, green, yellow.
        excluded (DataFrame, optional): Points drawn as red outlined markers on their own layer.

    Returns:
    -------
        str: Path of the saved html file.
    '''
    x = df['Longitude (°)']
    y = df['Latitude (°)']
    bt = df[value_column]
    colormap = color_map(bt, vmin, vmax, colors)
    #create the map, control_scale adds the distance scale bar in the bottom left
    m = folium.Map(location=[y.mean(), x.mean()], zoom_start=zoom, prefer_canvas=True, tiles=None, control_scale=True)
    #adding satellite imagery tile
    add_satellite_layer(m)
    #adding circle markers for each data point in the imported dataframe
    fg = folium.FeatureGroup(name=layer_name)
    for lat, lon, val in zip(y, x, bt):
        if np.isnan(val):
            continue
        folium.CircleMarker([lat, lon], color='black', fill=True, fill_color=colormap(val), fill_opacity=1, radius=2, weight=1).add_to(fg)
    m.add_child(fg)
    #optional layer of rejected points (e.g. positions removed during cleaning)
    if excluded is not None and len(excluded):
        ex = folium.FeatureGroup(name=excluded_name)
        for lat, lon in zip(excluded['Latitude (°)'], excluded['Longitude (°)']):
            folium.CircleMarker([lat, lon], radius=5, color='#b91c1c', weight=2, fill=False).add_to(ex)
        m.add_child(ex)
        folium.LayerControl(collapsed=False).add_to(m)
    #value scale legend in the top right
    colormap.caption = caption or labels.field_label(value_column, short=True)
    colormap.add_to(m)
    #north arrow below the zoom buttons
    m.get_root().html.add_child(folium.Element(NORTH_ARROW_HTML))
    m.get_root().header.add_child(folium.Element(CONTROL_BACKGROUND_CSS))
    #creating temporary html file to allow for >2MB datasets
    temp_map = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
    temp_map.close()
    m.save(temp_map.name)
    return temp_map.name

def color_map(bt, vmin=None, vmax=None, colors=None):
    #use the regular map's scale when one was set, otherwise the same default range
    lo = vmin if vmin is not None else np.nanpercentile(bt, 2)
    hi = vmax if vmax is not None else np.nanpercentile(bt, 98)
    if lo >= hi:
        lo, hi = np.nanpercentile(bt, 2), np.nanpercentile(bt, 98)
    return cm.LinearColormap(colors=colors or ['blue', 'green', 'yellow'], vmin=lo, vmax=hi)
