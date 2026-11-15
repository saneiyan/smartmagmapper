conda activate smartmagmapper && ^
pyinstaller -y ui-dir.spec && ^
cd dist && ^
7z a -aoa -r ui.zip ui && ^
cd .. && ^
move /y dist\ui.zip ui.zip && ^
pyinstaller -y splashScreen-exe.spec
conda deactivate
