"""Folium web maps of survey data (no PyQt: usable from scripts). The on-screen widget is ui.web_map_widget."""
import json
import re
import tempfile
import urllib.request
from pathlib import Path
from matplotlib import colormaps as _mpl_colormaps
from matplotlib.colors import to_hex as _to_hex
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

# Base imagery shared by every web map in the app (Data & Cleaning and Location Estimate).
GOOGLE_SATELLITE = dict(tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google',
                        max_zoom=25, name='Google Hybrid')


def add_satellite_layer(m, **options):
    '''Add the Google satellite imagery layer to a folium map (options such as show=True pass through).'''
    folium.TileLayer(**GOOGLE_SATELLITE, **options).add_to(m)


# Esri World Imagery Wayback: archived releases of the satellite/aerial mosaic, each served as
# ordinary tiles, so a past date is just another base layer in the map's layer control.
WAYBACK_CONFIG_URL = 'https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json'
WAYBACK_TILES = ('https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/'
                 '1.0.0/default028mm/MapServer/tile/{release}/{z}/{y}/{x}')
_wayback_cache = None


def wayback_releases():
    """[(release_number, 'YYYY-MM-DD'), ...] newest first; [] when the config cannot be
    fetched (e.g. offline), in which case maps simply keep the Google layer only.
    The list is fetched once and cached for the rest of the session."""
    global _wayback_cache
    if _wayback_cache is not None:
        return _wayback_cache
    releases = []
    try:
        with urllib.request.urlopen(WAYBACK_CONFIG_URL, timeout=10) as response:
            config = json.load(response)
        for number, info in config.items():
            match = re.search(r'(\d{4}-\d{2}-\d{2})', info.get('itemTitle', ''))
            if match:
                releases.append((int(number), match.group(1)))
        releases.sort(key=lambda item: item[1], reverse=True)
    except Exception:
        releases = []
    _wayback_cache = releases
    return releases


def add_wayback_layers(m, releases=None):
    """Add one Wayback base layer per year (the newest release of each), named by date and
    hidden until picked in the layer control; Google stays the default view."""
    picks, seen_years = [], set()
    for number, date in (releases if releases is not None else wayback_releases()):
        if date[:4] not in seen_years:
            seen_years.add(date[:4])
            picks.append((number, date))
    for number, date in picks:
        folium.TileLayer(tiles=WAYBACK_TILES.replace('{release}', str(number)), attr='Esri World Imagery Wayback',
                         max_zoom=25, name=f'Imagery {date}', show=False).add_to(m)


def build_map(df, value_column='BT', caption=None, vmin=None, vmax=None, colors=None,
              excluded=None, excluded_name='Excluded Positions', layer_name='Points', zoom=18,
              historical=True):
    '''Builds the satellite web map and saves it to a temporary html file.

    Parameters:
    ----------
        df (DataFrame): Survey points with 'Latitude (°)', 'Longitude (°)' and value_column.
        value_column (str, optional): Column used to colour the points. Defaults to 'BT'.
        caption (str, optional): Colour scale caption (default: the column's label in the current unit).
        vmin, vmax (float, optional): Colour scale limits, 2nd/98th percentile when not given.
        colors (list, optional): Colour ramp; defaults to blue, green, yellow.
        excluded (DataFrame, optional): Points drawn as red outlined markers on their own layer.
        historical (bool, optional): Add Esri Wayback imagery (one release per year) as extra base layers. Defaults to True.

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
    #historical imagery (Esri Wayback, one release per year) as switchable base layers
    if historical:
        add_wayback_layers(m)
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
    #value scale legend in the top right, added BEFORE the layer control:
    #controls in the same corner stack in the order they are added, so the
    #colour scale sits at the top, above the layer selection
    colormap.caption = caption or labels.field_label(value_column, short=True)
    colormap.add_to(m)
    #layer control: base layers (Google / Wayback dates) are radio choices, overlays are checkboxes
    folium.LayerControl(collapsed=False).add_to(m)
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


def _color_ramp(name, count=16):
    """Hex colours sampled along a matplotlib colormap (same ramp the Qt theme's
    color_list produces, kept here so processing stays PyQt-free)."""
    return [_to_hex(_mpl_colormaps[name](value)) for value in np.linspace(0, 1, count)]


def build_analysis_map(clean_df, score_points, clusters, summary, reference_point=None,
                       colors_name='RdYlBu_r'):
    """Builds the Location Estimate web map (survey track, score windows, clusters and the
    selected candidate over Google Hybrid + Wayback historical base layers) and saves it to
    the fixed temp html the app has always used.

    Parameters:
    ----------
        clean_df (DataFrame): Survey points with 'Latitude (°)' / 'Longitude (°)'.
        score_points (DataFrame or None): Anomaly-score windows (latitude, longitude, score, is_hit).
        clusters (DataFrame or None): Cluster rows (centroid, support, peak score, radius, selection).
        summary (dict): Analysis summary; candidate_latitude/longitude centre the map when present.
        reference_point (tuple or None): (lat, lon) of the reference location marker.
        colors_name (str, optional): Matplotlib colormap for the score ramp. Defaults to 'RdYlBu_r'.

    Returns:
    -------
        str: Path of the saved html file.
    """
    if 'candidate_latitude' in summary:
        center_lat = float(summary['candidate_latitude'])
        center_lon = float(summary['candidate_longitude'])
    elif score_points is not None and not score_points.empty:
        center_lat = float(score_points['latitude'].mean())
        center_lon = float(score_points['longitude'].mean())
    else:
        center_lat = float(clean_df['Latitude (°)'].mean())
        center_lon = float(clean_df['Longitude (°)'].mean())

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=19,
        control_scale=True,
        prefer_canvas=True,
        tiles=None,
    )
    # Same Google hybrid imagery as the Data & Cleaning web map, plus historical releases.
    add_satellite_layer(m, show=True)
    add_wayback_layers(m)

    route = clean_df[['Latitude (°)', 'Longitude (°)']].dropna()
    if len(route) > 900:
        route = route.iloc[::max(1, int(np.ceil(len(route) / 900)))]
    route_points = route.values.tolist()
    if route_points:
        folium.PolyLine(
            route_points,
            color='#38BDF8',
            weight=3,
            opacity=0.75,
            tooltip='survey track',
        ).add_to(m)

    if score_points is not None and not score_points.empty:
        score_values = score_points['score'].to_numpy(dtype=float)
        vmin = float(np.nanpercentile(score_values, 5))
        vmax = float(np.nanpercentile(score_values, 98))
        if not np.isfinite(vmin) or not np.isfinite(vmax) or vmin == vmax:
            vmin, vmax = float(np.nanmin(score_values)), float(np.nanmax(score_values) + 1.0)
        colormap = cm.LinearColormap(
            colors=_color_ramp(colors_name),
            vmin=vmin,
            vmax=vmax,
            caption='Anomaly score',
        )
        point_layer = folium.FeatureGroup(name='score windows', show=True)
        display_points = score_points.copy()
        if len(display_points) > 1200:
            display_points = display_points.iloc[::max(1, int(np.ceil(len(display_points) / 1200)))]
        for _, row in display_points.iterrows():
            is_hit = bool(row.get('is_hit', False))
            folium.CircleMarker(
                location=[float(row['latitude']), float(row['longitude'])],
                radius=4 if is_hit else 2,
                color='#111827' if is_hit else '#475569',
                weight=1.0 if is_hit else 0.4,
                fill=True,
                fill_color=colormap(float(row['score'])),
                fill_opacity=0.88 if is_hit else 0.48,
                tooltip=f"Score {float(row['score']):.2f}",
            ).add_to(point_layer)
        point_layer.add_to(m)
        colormap.add_to(m)

    if reference_point is not None:
        folium.Marker(
            list(reference_point),
            tooltip='Reference location',
            popup=f'Reference location<br>{reference_point[0]:.6f}, {reference_point[1]:.6f}',
            icon=folium.Icon(color='red', icon='flag'),
        ).add_to(m)

    if clusters is not None and not clusters.empty:
        cluster_layer = folium.FeatureGroup(name='clusters and candidate', show=True)
        for _, row in clusters.iterrows():
            selected = bool(row.get('selected_by_support_compactness', False))
            color = '#111827' if selected else '#F97316'
            label = f"C{int(row['cluster_label'])}"
            popup = (
                f"<b>{'Selected candidate' if selected else 'Cluster'} {label}</b><br>"
                f"Support: {int(row['n_points'])} windows<br>"
                f"Peak score: {float(row['peak_score']):.2f}<br>"
                f"Radius: {float(row['uncertainty_radius_m']):.2f} m"
            )
            if reference_point is not None:
                popup += f"<br>Offset to reference location: {float(row['dist_to_reference_m']):.2f} m"
            folium.CircleMarker(
                [float(row['centroid_latitude']), float(row['centroid_longitude'])],
                radius=9 if selected else 6,
                color='white',
                weight=2,
                fill=True,
                fill_color=color,
                fill_opacity=0.96,
                tooltip=label,
                popup=folium.Popup(popup, max_width=280),
            ).add_to(cluster_layer)
            folium.Marker(
                [float(row['centroid_latitude']), float(row['centroid_longitude'])],
                icon=folium.DivIcon(
                    html=(
                        "<div style='font-size:12px;font-weight:700;color:white;"
                        "text-shadow:0 1px 3px #000;'>"
                        f"{label}</div>"
                    )
                ),
            ).add_to(cluster_layer)
            if selected:
                folium.Circle(
                    [float(row['centroid_latitude']), float(row['centroid_longitude'])],
                    radius=float(row['uncertainty_radius_m']),
                    color='#111827',
                    weight=2,
                    fill=True,
                    fill_color='#111827',
                    fill_opacity=0.12,
                    tooltip='candidate uncertainty radius',
                ).add_to(cluster_layer)
        cluster_layer.add_to(m)

    bounds = []
    if route_points:
        bounds.extend(route_points)
    if score_points is not None and not score_points.empty:
        bounds.extend(score_points[['latitude', 'longitude']].dropna().values.tolist())
    if reference_point is not None:
        bounds.append(list(reference_point))
    if len(bounds) > 1:
        m.fit_bounds(bounds, padding=(28, 28))
    folium.LayerControl(collapsed=False).add_to(m)
    #north arrow and control backgrounds, matching build_map
    m.get_root().html.add_child(folium.Element(NORTH_ARROW_HTML))
    m.get_root().header.add_child(folium.Element(CONTROL_BACKGROUND_CSS))

    map_path = Path(tempfile.gettempdir()) / 'smartmagmapper_anomaly_cluster_map.html'
    m.save(str(map_path))
    return str(map_path)
