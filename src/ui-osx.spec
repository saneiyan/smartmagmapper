# -*- mode: python -*-

block_cipher = None


a = Analysis(['GUI.py'],
             pathex=[],
             binaries=[],
             datas=[('./imgs/*','./imgs'),
                    ('./processing/models/neighborhood_rf.joblib', './processing/models'),
                    ('./processing/models/neighborhood_rf.json', './processing/models')],
             hiddenimports=['numpy.core._dtype_ctypes', 'PySide.QtXml', 'scipy.special._cdflib'],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          [],
          exclude_binaries=True,
          name='gui',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=False )
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               name='gui')
app = BUNDLE(coll,
             name='SmartMagMapper.app',
             icon='./imgs/app_icon.icns',
             bundle_identifier=None,
             info_plist={'NSHighResolutionCapable': 'True'})
