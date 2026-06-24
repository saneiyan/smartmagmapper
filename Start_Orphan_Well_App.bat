@echo off
setlocal
set "APP_DIR=%~dp0"
set "DATA_FILE=%APP_DIR%..\..\Butkowsky 1A Surveys 10_09_25\McKee_Seth.xls"
if not exist "%DATA_FILE%" set "DATA_FILE=%APP_DIR%..\..\Orphan Well Data\Butkowsky 1A Surveys 10_09_25\McKee_Seth.xls"
if not exist "%DATA_FILE%" set "DATA_FILE=C:\Users\nimri\OneDrive\Desktop\Retreived OW\Orphan Well Data\Butkowsky 1A Surveys 10_09_25\McKee_Seth.xls"

pushd "%APP_DIR%"
where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
    start "OrphaMag Studio" pythonw.exe "%APP_DIR%GUI.py" "%DATA_FILE%"
) else (
    start "OrphaMag Studio" python.exe "%APP_DIR%GUI.py" "%DATA_FILE%"
)
popd
