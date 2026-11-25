# -*- mode: python -*-
# this file is used by pyinstaller to generate a zip file that would 
# then be uncompressed by the splashScreen.spec

block_cipher = None


a = Analysis(['GUI.py'],
             pathex=[],
             binaries=[],
             datas=[('./imgs/*','./imgs'),
                    ('./processing/models/neighborhood_rf.joblib', './processing/models'),
                    ('./processing/models/neighborhood_rf.json', './processing/models')],
             hiddenimports=['numpy.core._dtype_ctypes', 'PySide.QtXml', 'scipy.special._cdflib', 'scipy._lib.array_api_compat.numpy.fft', 'scipy.special._special_ufuncs'],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          exclude_binaries=True,
          name='SmartMagMapper',
          debug=False,
          strip=False,
          upx=True,
          console=False,
          icon='./imgs/app_icon.ico')
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               name='gui')
