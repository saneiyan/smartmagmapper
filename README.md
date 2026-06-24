# OrphaMag Studio

This folder contains OrphaMag Studio, a MagPy-based desktop application with an added orphan-well localization workflow.

Run the app from this folder, or double-click `Start_Orphan_Well_App.bat`:

```powershell
python GUI.py
```

Run directly with the selected Butkowsky test survey:

```powershell
python GUI.py "C:\Users\nimri\OneDrive\Desktop\Retreived OW\Orphan Well Data\Butkowsky 1A Surveys 10_09_25\McKee_Seth.xls"
```

Main files:

- `GUI.py` - PyQt6 desktop interface, existing MagPy tabs, and the new OrphaMag tab.
- `OrphanWellPipeline.py` - executable methodology for survey ingest, cleaning, VMD scoring, DBSCAN clustering, candidate selection, and point labeling.
- `GeoXAIInterpreter.py` - candidate explanation layer for known-reference and unknown-location workflows.
- `ExcelReader.py`, `MapMaker.py`, `MapFilter.py`, `PlotData.py`, `WebMap.py` - original MagPy import, map, filtering, plotting, and web map helpers.

The OrphaMag tab keeps the existing data labels and adds:

- Direct import for smartphone survey workbooks with `Location` and `Magnetometer` sheets.
- Cleaning with time interpolation, UTM 18N conversion, startup removal, spatial MAD filtering, total field, walked distance, and well-distance fields.
- VMD mode selection and anomaly score calculation.
- Dynamic controls for reference well coordinate, score window length, step ratio, threshold gamma, DBSCAN eps, and DBSCAN minimum samples.
- A tabbed dashboard with a satellite/street map, engineering UTM map, score trace, total-field trace, and VMD mode chart.
- A GeoXAI tab that explains the selected candidate using support, peak magnetic response, compactness, threshold separation, and shape coherence.
- Unknown-location mode for surveys where the true orphan-well coordinate is not known.
- Candidate centroid, uncertainty radius, cluster support count, reference well offset, and labeled point table.

The selected test dataset is:

`C:\Users\nimri\OneDrive\Desktop\Retreived OW\Orphan Well Data\Butkowsky 1A Surveys 10_09_25\McKee_Seth.xls`

The test run produced 3,348 cleaned samples, 432 threshold hits, 3 clusters, and a selected candidate near the Butkowsky 1A reference well.
