SmartMagMapper

Requirements

The application has been tested on Windows 64-bit with Python 3.11.9. The required Python packages and their versions are listed in requirements.txt. Other Python versions have not yet been validated.

How to run the application

Keep all files together. Open Command Prompt in this folder and run these commands in order:

py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe GUI.py

The first command creates a separate Python environment. The second installs the required packages and needs internet access. These two steps are normally needed only once on each computer.

To open the application again, run:

.venv\Scripts\python.exe GUI.py

Import your survey data through the application. Survey files are not included in this folder.

Interface

The interface uses PyQt6 with a custom light theme. Matplotlib displays scientific plots, and Folium with Qt WebEngine displays geographic maps. Web-map backgrounds require internet access.

Source files

GUI.py starts the application. The other Python files provide filtering, mapping, analysis, tables, project storage and supporting functions. Keep these files together.
