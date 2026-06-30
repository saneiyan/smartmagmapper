# OrphaMag Studio

OrphaMag Studio is a Windows desktop application for reviewing smartphone magnetometer surveys and estimating candidate orphan-well locations. It is built from the MagPy application and adds the OrphaMag workflow for cleaning survey data, calculating anomaly scores, clustering candidate windows, and explaining the selected result with GeoXAI.

## What Is Included

This repository contains the application source code and launch files.

Important files:

- `GUI.py` - main desktop application.
- `OrphanWellPipeline.py` - orphan-well processing workflow.
- `GeoXAIInterpreter.py` - explanation layer for candidate estimates.
- `DialogWindow.py`, `ExcelReader.py`, `MapFilter.py`, `MapMaker.py`, `PlotData.py`, `TableModel.py`, `WebMap.py` - original MagPy support modules.
- `requirements.txt` - Python packages needed to run the app.
- `Start_Orphan_Well_App.bat` - optional Windows double-click launcher.

Survey data files are not included in this repository. Each user should load survey files from their own computer using the app.

## Install

Use Python 3.10 or newer on Windows.

Open PowerShell in the project folder and run:

```powershell
pip install -r requirements.txt
```

If `pip` points to a different Python installation, use:

```powershell
python -m pip install -r requirements.txt
```

## Run The App

From PowerShell:

```powershell
python GUI.py
```

On Windows, you can also double-click:

```text
Start_Orphan_Well_App.bat
```

The `.bat` file only starts the app. It is not the app itself and it does not contain data.

## Load A Survey

1. Open the app.
2. Go to the `OrphaMag` tab.
3. Click the top toolbar button `Import Data`.
4. Select the survey workbook from your computer.
5. Review the maps, plots, scores, clusters, candidate estimate, and GeoXAI explanation.

The OrphaMag workflow expects survey workbooks that include smartphone location and magnetometer data. The original Butkowsky survey workbooks used `Location` and `Magnetometer` sheets.

## OrphaMag Workflow

The app performs these main steps:

1. Reads the survey workbook.
2. Synchronizes location and magnetometer records.
3. Converts latitude and longitude to UTM coordinates.
4. Removes startup samples and spatial outliers.
5. Calculates total magnetic field.
6. Applies VMD-based mode selection.
7. Computes anomaly scores over moving windows.
8. Uses DBSCAN to cluster high-score windows.
9. Selects a candidate orphan-well estimate.
10. Generates GeoXAI interpretation for the result.

## Main Tabs

- `Map` - geographic map view of the survey and candidate area.
- `Engineering Map` - UTM engineering view for points, clusters, and candidate estimate.
- `Total Field` - magnetic total-field trace.
- `VMD Modes` - selected VMD mode energy and decomposition view.
- `Scores` - anomaly score, threshold, and hit windows.
- `GeoXAI` - explanation of the candidate estimate and confidence factors.

## Parameters

The left control panel lets users adjust:

- Reference well latitude and longitude.
- Known-reference or unknown-location mode.
- Startup samples removed.
- Spatial MAD filter.
- Score window length.
- Window step ratio.
- Threshold gamma.
- DBSCAN epsilon distance.
- DBSCAN minimum samples.

After changing parameters, click `Update Results`.

## Known-Reference And Unknown-Location Modes

Use known-reference mode when the expected well coordinate is available. The app reports the candidate offset from that reference.

Use unknown-location mode when the well coordinate is not known. The app will still rank candidate clusters and provide a GeoXAI explanation based on the magnetic and spatial evidence.

## Sharing Notes

For collaborators:

1. Clone or download this repository.
2. Install packages using `pip install -r requirements.txt`.
3. Run `python GUI.py`.
4. Import a survey workbook from local storage.

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

If maps or web views do not display, make sure `PyQt6-WebEngine`, `folium`, and `branca` installed correctly.

If the app opens but no results appear, import a valid survey workbook from the `OrphaMag` tab.
