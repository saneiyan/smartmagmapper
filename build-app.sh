conda activate pyside_installer
pyinstaller -y ui-osx.spec
mv ./dist/SmartMagMapper.app ./SmartMagMapper_dmg/SmartMagMapper.app
hdiutil create ./dist/SmartMagMapper.dmg -srcfolder SmartMagMapper_dmg -ov
mv ./SmartMagMapper_dmg/SmartMagMapper.app ./dist/SmartMagMapper.app
conda deactivate