""" splashScreen

"""
from PyQt6.QtWidgets import QSplashScreen, QApplication, QProgressBar
from PyQt6.QtGui import QPixmap, QMovie
from PyQt6.QtCore import Qt
from zipfile import ZipFile, ZipInfo
from subprocess import Popen
import os
import sys
import shutil
import platform
# Qt6 note: AA_EnableHighDpiScaling / AA_UseHighDpiPixmaps no longer exist --
# high-DPI scaling is always on in Qt6, so the PySide6 setAttribute lines were dropped.

OS = platform.system()

frozen = 'not'
if getattr(sys, 'frozen', False):
        # we are running in a bundle
        frozen = 'ever so'
        bundle_dir = sys._MEIPASS
else:
        # we are running in a normal Python environment
        bundle_dir = os.path.dirname(os.path.abspath(__file__))
print( 'we are',frozen,'frozen')
print( 'bundle dir is', bundle_dir )


""" PERMISSION ISSUE WITH ZIPFILE MODULE
https://stackoverflow.com/questions/39296101/python-zipfile-removes-execute-permissions-from-binaries
by default zipfile does not umpack any binary bit to say executable or not
Below is a way to do it
"""

class MySplashScreen(QSplashScreen):
    def __init__(self, animation, flags):
        # run event dispatching in another thread
        QSplashScreen.__init__(self, QPixmap(), flags)
        self.movie = QMovie(animation)
        self.movie.frameChanged.connect(self.onNextFrame)
        self.movie.start()

    def onNextFrame(self):
        pixmap = self.movie.currentPixmap()
        self.setPixmap(pixmap)
        self.setMask(pixmap.mask())


class MyZipFile(ZipFile):
    def extract(self, member, path=None, pwd=None):
        if not isinstance(member, ZipInfo):
            member = self.getinfo(member)

        if path is None:
            path = os.getcwd()

        ret_val = self._extract_member(member, path, pwd)
        attr = member.external_attr >> 16
        if OS != 'Windows':
            os.chmod(ret_val, attr) # IMPORTANT this line needs to be commented otherwise we got the _MEIxxxxx issue
        # changing the permission of somes files makes them unremovable by the splascreen bootloader when the program finished
        # this leads to accumulation of _MEIxxxxx temporary files in C:\Users\User\AppData\Local\Temp\
        # this issue is windows specific, on Linux, the temporary folder in /tmp is removed even when we uncomment this line
        return ret_val


if __name__ == "__main__":

    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    splash_pix = QPixmap(os.path.join(bundle_dir, 'imgs/logo_s.png'))
    splash = QSplashScreen(splash_pix, Qt.WindowType.WindowStaysOnTopHint)
    splash.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    splash.setEnabled(False)
    # adding progress bar
    progressBar = QProgressBar(splash)
    progressBar.setGeometry(100, splash_pix.height() - 50, splash_pix.width() - 200, 20)

    splash.show()
    splash.showMessage("Unzipping files", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
    app.processEvents()

    zf = MyZipFile(os.path.join(bundle_dir, 'ui.zip'),'r')
    extractDir = os.path.join(bundle_dir, 'ui')
    if os.path.exists(extractDir):
#        print('overwritting pyR2 dir')
        shutil.rmtree(extractDir)
    os.mkdir(extractDir)
    uncompress_size = sum((file.file_size for file in zf.infolist()))
    extracted_size = 0

    for file in zf.infolist():
        extracted_size += file.file_size
        percentage = extracted_size * 100/uncompress_size
        progressBar.setValue(int(percentage))
        if percentage > 50 and percentage < 70:
            splash.showMessage("Copying temp files", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
        if percentage >= 70 and percentage < 80:
            splash.showMessage("Checking files", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
        if percentage >= 80 and percentage < 90:
            splash.showMessage("Loading libraries", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
        if percentage >= 90 and percentage < 98:
            splash.showMessage("Loading App", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
        if percentage >= 98:
            splash.showMessage("Almost there!", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, Qt.GlobalColor.white)
        app.processEvents()
        zf.extract(file, extractDir)
    zf.close()
    print('finished unzipping')

    splash.hide()
    splash.close()
    appDir = os.path.join(bundle_dir, 'ui', 'ui') # zip always putting a double dir ... don't know why
    print('Main app will be run in appDir = ', appDir)
    os.chdir(appDir)
#    os.system(['python3', 'ui.py']) # this work fine
    if OS == 'Linux':
        os.system(os.path.join(appDir, 'SmartMagMapper'))
    else:
        p = Popen(os.path.join(appDir, 'SmartMagMapper'), shell=True, stdout=None, stdin=None) # this works now as well !
        p.communicate() # block and wait for the main program to finish
    # this last one doesn't work on linux WHEN COMPILED and I don't know why
    sys.exit(0) # send the SIGTERM signal -> works

#  need to comment the following lines as the exit signal is given by the main app
#    sys.exit()
#    sys.exit(app.exec())

""" NOTE
This approach increase significantly the size of the package.
Another approach would be to load all modules in this script and just unzip the
sources and run `python ui.py`.
"""
