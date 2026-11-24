# SmartMagMapper

SmartMagMapper is a desktop application for processing and interpreting magnetic survey data, such as smartphone magnetometer surveys. It synchronizes magnetometer and GPS records, cleans the survey, applies time-series and spatial filters, maps the magnetic field, and detects, clusters and explains magnetic anomalies with GeoXAI.

## What Is Included

This repository contains the application source code.

The code is split into two packages:

- `GUI.py` - the main window and the application launcher (run this file). It builds the window and its tabs; its behaviour comes from these modules in `ui/`: `survey_actions.py` (import and cleaning actions), `analysis_tab.py` (Anomaly Analysis tab), `location_tab.py` (Location Estimate tab) and `exports.py` (File > Export Data).
- `ui/` - the rest of the user interface (PyQt6):
  - `data_workspace.py` - the Data & Cleaning tab (cleaning settings, cleaning maps, data tables, signal plots).
  - `filter_workspace.py`, `filter_comparison.py`, `vmd_panel.py` - the Filter Lab tab.
  - `dialogs.py` - the import and export dialogs; `project_tools.py` - project files and the File/Edit/View/Tools menus.
  - `theme.py`, `table_model.py`, `busy.py`, `confirm.py` - styling, tables and shared pop-ups.
- `processing/` - data processing with no PyQt6 dependency, usable from scripts:
  - `data_analysis_pipeline.py` - survey import, synchronization, cleaning, suggested cleaning settings and anomaly analysis.
  - `scientific_filters.py` - Filter Lab filters (time/path-series filters, VMD, continuation and reduction to pole).
  - `geoxai_interpreter.py` - explanation layer for anomaly candidates; `survey_session.py`, `project_io.py` - survey state and project files.
  - `map_maker.py` - maps and GeoTIFF export; `web_map.py` - web maps (folium); `comparison_spectrum.py` - filter comparison spectra.
  - `labels.py`, `coordinates.py` - magnetic units and display names; coordinate format conversion.
- `requirements.txt` - Python packages needed to run the app.

For example, a script can run the processing without the interface:

```python
from processing import data_analysis_pipeline as dap
mag, gps = dap.read_survey_file('survey.xlsx')
cleaned, audit = dap.clean_survey(mag, gps, dap.AnalysisParams())
```

Every function and class has a NumPy-style docstring describing its parameters and return values, e.g. `help(dap.clean_survey)`.

Survey data files are not included in this repository. Each user should load survey files from their own computer using the app.

## Install

Use Python 3.10 or newer (tested with Python 3.11 on Windows 64-bit).

Open a terminal in the project folder and run:

```powershell
python -m pip install -r requirements.txt
```

## Run The App

```powershell
python GUI.py
```

## Load A Survey

1. Open the app.
2. Choose `File > Import Data...` (or start with `File > New Project` / `File > Open Project...`).
3. Select the survey file (Excel or CSV) and assign the magnetic, coordinate and time columns.
4. Review the cleaning, filters, anomaly analysis and location estimate in the main tabs.

Survey files need magnetometer data (X/Y/Z components or total field) and GPS positions with timestamps. Excel workbooks may keep them on separate `Magnetometer` and `Location` sheets.

### Reduction to pole field direction

Reduction to pole (Filter Lab) needs the inclination and declination of the Earth's field at the survey. Choose the survey date and click `Estimate from IGRF` to fill them in from the IGRF model (via `ppigrf`, dates 1900-2029) at the survey's centre, or type known values. The direction used, and whether it came from IGRF, is recorded in the processing record, the exports and the GeoTIFF metadata.

### Units and coordinate formats

The Import Data dialog asks for:

- **Magnetic field unit**: nT, µT (default), mT, T, G or mG. It is suggested from the column headers when they include a unit, e.g. `X (nT)`. Values are never converted. The unit is stored with the survey in the project, and every label, axis, colour bar, table header, exported CSV column (`BT (nT)`, ...) and GeoTIFF shows it. Internally the field columns are unit-free: `BT`, `X`, `Y`, `Z`. Projects saved before units were added open as µT.
- **Coordinate format**: decimal degrees (default); degrees + decimal minutes (`45°07.407'N`, `45 07.407`, NMEA `4507.407`); degrees-minutes-seconds (`45°07'24.4"N`, `45 7 24.4`); or projected metres with an EPSG code (e.g. `32618` for UTM 18N). Coordinates are converted to decimal degrees (WGS 84) for processing. The original columns are kept in the raw GPS data, and the format is saved with the project.

## Processing Workflow

1. Reads the survey and standardizes column names.
2. Synchronizes magnetometer samples with GPS positions (linear interpolation in time).
3. Converts latitude and longitude to one UTM zone for the whole survey.
4. Removes startup samples and spatial outliers (median radius + MAD rule). Both settings are suggested from the survey itself: startup samples end where the sampling interval, distance travelled and change in magnetic field per sample become steady (catching GPS settling and magnetometer warm-up; later magnetic anomalies are never removed), and the MAD multiplier keeps every position reached by a normal step while rejecting GPS jumps.
5. Calculates the total magnetic field (BT).
6. Optionally filters the field (Filter Lab).
7. Decomposes the field with VMD and selects anomaly-bearing modes.
8. Computes anomaly scores over moving windows and clusters high-score windows with DBSCAN.
9. Selects a candidate anomaly location and explains it with GeoXAI.

## Main Tabs

- `Data & Cleaning` - cleaning settings, cleaning maps (scatter, contour or web map; before or after cleaning), data tables and signal plots.
- `Filter Lab` - preview, compare and apply filters (band-pass, high-pass, low-pass, moving average, Savitzky-Golay, linear detrend, VMD, upward/downward continuation, reduction to pole).
- `Automated Anomaly Analysis` - finds anomalies automatically from the survey itself (no training data): VMD splits the signal into bands, robust statistics score each section of the track, DBSCAN groups high-scoring sections into candidates, and GeoXAI explains the result. Shows the magnetic field, VMD modes, anomaly scores and the GeoXAI explanation.
- `Location Estimate` - location map and web map of the candidate anomaly, with exportable results.

`File > Export Data...` lets you choose what to export: cleaned, synchronized and filtered data tables (CSV), the cleaning maps and open signal plots (PNG or PDF), and a georeferenced raster of a field (GeoTIFF, in the survey's UTM zone or WGS 84). GeoTIFF export needs the `rasterio` package.

## Analysis Parameters

The Automated Anomaly Analysis settings panel lets users adjust:

- Analysis input (cleaned total field or the current filtered field).
- Optional reference latitude and longitude.
- Score window length and window step ratio.
- Threshold gamma.
- DBSCAN epsilon distance and minimum samples.

Cleaning settings (startup samples, spatial MAD multiplier, percentile fallback) are in the Data & Cleaning tab. Startup samples and the MAD multiplier are filled in automatically from each survey when it is imported; adjust them if needed and click `Update Cleaning Settings` to apply. `Restore suggested settings` returns to the survey's suggested values.

## Known-Reference And Unknown-Location Modes

Enter a reference latitude and longitude when the location of a known target is available. The app reports the candidate's offset from that reference.

Leave the reference blank when no location is known. The app still ranks candidate clusters and provides a GeoXAI explanation based on the magnetic and spatial evidence.

## Sharing Notes

For collaborators:

1. Clone or download this repository.
2. Install packages using `python -m pip install -r requirements.txt`.
3. Run `python GUI.py`.
4. Import a survey file from local storage.

Do not upload private field survey files unless the project owner approves sharing those data.

## Troubleshooting

If the app does not open, confirm Python is installed:

```powershell
python --version
```

If a package is missing, reinstall dependencies:

```powershell
python -m pip install -r requirements.txt
```

If maps or web views do not display, make sure `PyQt6-WebEngine`, `folium`, and `branca` installed correctly. Web-map backgrounds require internet access.

If the app opens but no results appear, import a valid survey file with `File > Import Data...`.
