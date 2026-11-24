conda activate smartmagmapper && ^
pyinstaller -y ui-dir.spec && ^
cd dist && ^
7z a -aoa -r gui.zip gui && ^
cd .. && ^
move /y dist\gui.zip gui.zip && ^
pyinstaller -y splashScreen-exe.spec
conda deactivate
