"""Portable survey projects: JSON, CSV and numeric arrays; no executable serialization."""
from pathlib import Path
from copy import deepcopy
import io,json,os,shutil,zipfile,tempfile,uuid
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from processing import data_analysis_pipeline as dap
from processing.survey_session import SurveySession
from processing.scientific_filters import FilterResult

FORMAT='SmartMagMapper project'
VERSION=1

def _json(value):
    """json.dumps fallback for NumPy values.

    Parameters
    ----------
    value : object
        Value json cannot serialise by itself.

    Returns
    -------
    object
        Python scalar for NumPy scalars, list for arrays.

    Raises
    ------
    TypeError
        For any other type.
    """
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,np.ndarray):return value.tolist()
    raise TypeError(type(value).__name__)

def _csv(z,name,frame):
    """Write a data frame into the project archive as CSV with round-trip float precision.

    Parameters
    ----------
    z : zipfile.ZipFile
        Open project archive.
    name : str
        Member name inside the archive.
    frame : pandas.DataFrame
        Data to write.
    """
    z.writestr(name,frame.to_csv(index=False,float_format='%.17g'))
def _exact_read_options():
    """read_csv options that read '%.17g' floats back bit-for-bit (project checks need exact values).

    pandas < 3.1 needs float_precision='round_trip'; from pandas 3.1 the default parser is exact and that
    option is deprecated. The installed pandas is tested once instead of relying on its version number.

    Returns
    -------
    dict
        Keyword arguments for pandas.read_csv.
    """
    rng=np.random.default_rng(0)
    sample=np.concatenate([rng.normal(50,5,1000),rng.uniform(-1e7,1e7,500),rng.standard_normal(500)*1e-9])
    text=pd.DataFrame({'v':sample}).to_csv(index=False,float_format='%.17g')
    if np.array_equal(pd.read_csv(io.StringIO(text))['v'].to_numpy(),sample):return {}
    return {'float_precision':'round_trip'}

_READ_OPTIONS=_exact_read_options()
def _read(z,name):
    """Read a CSV member of the project archive with exact float parsing.

    Parameters
    ----------
    z : zipfile.ZipFile
        Open project archive.
    name : str
        Member name inside the archive.

    Returns
    -------
    pandas.DataFrame
        The table.
    """
    return pd.read_csv(io.BytesIO(z.read(name)),**_READ_OPTIONS)

def write_project(path,sessions,active,settings,metadata,comparisons=None,backup=True):
    """Save surveys, settings and stored filter comparisons as a .smmproj project (a zip of JSON, CSV and arrays).

    The file is written to a temporary file and moved into place, so an interrupted save never damages the
    previous project. With `backup`, the previous file is kept as .bak1 (older ones as .bak2 and .bak3).

    Parameters
    ----------
    path : str or pathlib.Path
        Project file to write.
    sessions : list of survey_session.SurveySession
        Surveys in the project.
    active : int or None
        Index of the active survey.
    settings : dict
        Window settings to restore (analysis settings, view choices, colour scales...).
    metadata : dict
        Project id, title, author and notes.
    comparisons : dict, optional
        Stored filter results for comparison: name -> {'result': FilterResult, 'frame': DataFrame}.
    backup : bool, optional
        Keep up to three previous versions of an existing file.

    Returns
    -------
    dict
        The manifest written as project.json.
    """
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    manifest={'format':FORMAT,'version':VERSION,'saved_utc':datetime.now(timezone.utc).isoformat(),'active':active,'settings':settings,'metadata':metadata,'surveys':[],'comparisons':[]}
    handle=tempfile.NamedTemporaryFile(prefix='smm-',suffix='.tmp',dir=path.parent,delete=False);temporary=Path(handle.name);handle.close()
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as z:
            for i,session in enumerate(sessions):
                prefix=f'surveys/{i}/'
                for label,frame in [('mag',session.magnetometer),('gps',session.location),('cleaned',session.cleaned),('working',session.working)]:_csv(z,prefix+label+'.csv',frame)
                manifest['surveys'].append({'source':session.path,'cleaning_key':session.cleaning_key,'filters':session.filters,'history':session.filter_history,'audit':session.audit,
                                           'field_unit':session.field_unit,'coordinates':session.coordinates})
            for index,(name,item) in enumerate((comparisons or {}).items()):
                result=item['result'];prefix=f'comparisons/{index}/';arrays={}
                for key in ['before','after','axis','modes','mode_axis','mode_signal']:
                    value=getattr(result,key)
                    if value is not None:arrays[key]=value
                for i,grid in enumerate(result.grids or ()):arrays[f'grid_{i}']=grid
                buffer=io.BytesIO();np.savez_compressed(buffer,**arrays);z.writestr(prefix+'arrays.npz',buffer.getvalue())
                if result.metrics is not None:_csv(z,prefix+'metrics.csv',result.metrics)
                manifest['comparisons'].append({'name':name,'axis_label':result.axis_label,'settings':result.settings,'notes':result.notes,'selected':result.selected,'metrics':result.metrics is not None})
            z.writestr('project.json',json.dumps(manifest,indent=2,default=_json))
        if backup and path.exists():
            for number in [2,1]:
                previous=Path(str(path)+f'.bak{number}')
                if previous.exists():shutil.copy2(previous,Path(str(path)+f'.bak{number+1}'))
            shutil.copy2(path,Path(str(path)+'.bak1'))
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()
    return manifest

def read_project(path):
    """Open a .smmproj project and check it against its raw data.

    Each survey is re-cleaned from its raw streams with its saved cleaning settings and must match the archived
    cleaned data; the current field may only differ from it in BT. Projects saved by earlier versions (no unit or
    coordinate format, duplicate columns) are brought up to date.

    Parameters
    ----------
    path : str or pathlib.Path
        Project file (.smmproj or a .bak backup).

    Returns
    -------
    manifest : dict
        Contents of project.json (settings, metadata, active survey...).
    sessions : list of survey_session.SurveySession
        The surveys.
    comparisons : dict
        Stored filter results for comparison: name -> {'result': FilterResult, 'frame': DataFrame}.

    Raises
    ------
    ValueError
        If the archive is too large, of an unsupported format or version, or fails a consistency check.
    """
    with zipfile.ZipFile(path) as z:
        members=z.infolist()
        if len(members)>2000 or sum(i.file_size for i in members)>1024**3:raise ValueError('Project archive exceeds the supported size.')
        manifest=json.loads(z.read('project.json'))
        if manifest.get('format')!=FORMAT or manifest.get('version')!=VERSION:raise ValueError('Unsupported project format or version.')
        metadata=manifest.get('metadata',{})
        uuid.UUID(metadata.get('id',''))
        if any(not isinstance(metadata.get(key,''),str) for key in ['title','author','notes']):raise ValueError('Invalid project metadata.')
        surveys=manifest.get('surveys',[])
        if len(surveys)>100:raise ValueError('Too many surveys in this project.')
        sessions=[]
        for i,entry in enumerate(surveys):
            prefix=f'surveys/{i}/';mag=_read(z,prefix+'mag.csv');gps=_read(z,prefix+'gps.csv')
            key=entry['cleaning_key']
            if len(key)!=3:raise ValueError('Invalid cleaning settings.')
            params=dap.AnalysisParams(startup_samples=int(key[0]),spatial_mad_multiplier=float(key[1]),spatial_fallback_percentile=float(key[2]))
            # older projects have no unit or coordinate entry: their values are in µT and decimal degrees
            session=SurveySession(entry['source'],mag,gps,field_unit=entry.get('field_unit','µT'),
                                  coordinates=entry.get('coordinates') or {'format':'decimal_degrees'})
            session.ensure_cleaned(params)
            # Projects saved by earlier versions carry duplicate columns; drop them and match today's column order.
            archived=dap.drop_legacy_aliases(_read(z,prefix+'cleaned.csv'));working=dap.drop_legacy_aliases(_read(z,prefix+'working.csv'))
            if set(archived.columns)==set(session.cleaned.columns):archived=archived.reindex(columns=list(session.cleaned.columns))
            working=working.reindex(columns=[c for c in archived.columns if c in working]+[c for c in working.columns if c not in archived.columns])
            columns=['Time (s)','Easting (m)','Northing (m)','BT']
            if len(archived)!=len(session.cleaned) or not np.allclose(archived[columns],session.cleaned[columns],rtol=1e-10,atol=1e-8):raise ValueError('The archived baseline does not match its raw data and cleaning settings.')
            if len(working)!=len(archived) or not np.array_equal(working['Time (s)'],archived['Time (s)']) or not np.isfinite(working['BT']).all():raise ValueError('Invalid current-field data in project.')
            for column in archived:
                if column=='BT':continue
                if column not in working or not working[column].equals(archived[column]):raise ValueError('A saved filter changed the source survey columns.')
            session.cleaned=archived;session.working=working;session.filters=list(entry['filters']);session.filter_history=deepcopy(entry['history']);session.revision+=1
            sessions.append(session)
        active=manifest.get('active')
        if active is not None and (not isinstance(active,int) or not 0<=active<len(sessions)):raise ValueError('Invalid active survey index.')
        comparisons={}
        for i,entry in enumerate(manifest.get('comparisons',[])):
            if active is None:raise ValueError('Saved comparisons require an active survey.')
            prefix=f'comparisons/{i}/'
            with np.load(io.BytesIO(z.read(prefix+'arrays.npz')),allow_pickle=False) as data:
                arrays={key:data[key].copy() for key in data.files}
            count=len(sessions[active].cleaned)
            if any(len(arrays[key])!=count or not np.isfinite(arrays[key]).all() for key in ['before','after','axis']):raise ValueError('Invalid comparison arrays.')
            result=FilterResult(arrays['before'],arrays['after'],arrays['axis'],entry['axis_label'],entry['settings'],entry['notes'],selected=entry['selected'])
            for key in ['modes','mode_axis','mode_signal']:setattr(result,key,arrays.get(key))
            if result.modes is not None:
                if result.modes.ndim!=2 or result.mode_axis is None or result.mode_signal is None or result.modes.shape[1]!=len(result.mode_axis) or len(result.mode_signal)!=len(result.mode_axis):raise ValueError('Invalid saved VMD decomposition.')
            result.metrics=_read(z,prefix+'metrics.csv') if entry['metrics'] else None
            grids=[arrays[key] for key in sorted(arrays) if key.startswith('grid_')];result.grids=tuple(grids) if grids else None
            comparisons[entry['name']]={'result':result,'frame':sessions[active].cleaned.copy(deep=True)}
    return manifest,sessions,comparisons
