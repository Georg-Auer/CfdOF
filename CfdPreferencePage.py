# ***************************************************************************
# *                                                                         *
# *   Copyright (c) 2013-2015 - Juergen Riegel <FreeCAD@juergen-riegel.net> *
# *   Copyright (c) 2016 - Qingfeng Xia <qingfeng.xia()eng.ox.ac.uk>        *
# *   Copyright (c) 2017-2018 Oliver Oxtoby (CSIR) <ooxtoby@csir.co.za>     *
# *   Copyright (c) 2017 Johan Heyns (CSIR) <jheyns@csir.co.za>             *
# *   Copyright (c) 2017 Alfred Bogaers (CSIR) <abogaers@csir.co.za>        *
# *   Copyright (c) 2019-2021 Oliver Oxtoby <oliveroxtoby@gmail.com>        *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

import os
import os.path
import platform
import sys
if sys.version_info >= (3,):  # Python 3
    import urllib.request as urlrequest
    import urllib.parse as urlparse
else:
    import urllib as urlrequest
    import urlparse
import ssl
import ctypes

import FreeCAD
import CfdTools
import tempfile
from contextlib import closing

if FreeCAD.GuiUp:
    import FreeCADGui
    from PySide import QtCore
    from PySide import QtGui
    from PySide.QtCore import Qt, QObject, QThread
    from PySide.QtGui import QApplication

OPENFOAM_URL = \
    "https://sourceforge.net/projects/openfoam/files/v2012/OpenCFD-OpenFOAM-v2012-DP-mingw-crosscompiled-WindowsInstaller.exe/download"
OPENFOAM_FILE_EXT = ".exe"
PARAVIEW_URL = \
    "https://www.paraview.org/paraview-downloads/download.php?submit=Download&version=v5.5&type=binary&os=Windows&downloadFile=ParaView-5.5.2-Qt5-Windows-64bit.exe"
PARAVIEW_FILE_EXT = ".exe"
CFMESH_URL = \
    "https://sourceforge.net/projects/cfmesh-cfdof/files/cfmesh-cfdof.zip/download"
CFMESH_URL_MINGW = \
    "https://sourceforge.net/projects/cfmesh-cfdof/files/cfmesh-cfdof-binaries-{}.zip/download"
CFMESH_FILE_BASE = "cfmesh-cfdof"
CFMESH_FILE_EXT = ".zip"
HISA_URL = \
    "https://sourceforge.net/projects/hisa/files/hisa-master.zip/download"
HISA_URL_MINGW = \
    "https://sourceforge.net/projects/hisa/files/hisa-master-binaries-{}.zip/download"
HISA_FILE_BASE = "hisa-master"
HISA_FILE_EXT = ".zip"


# Tasks for the worker thread
DOWNLOAD_OPENFOAM = 1
DOWNLOAD_PARAVIEW = 2
DOWNLOAD_CFMESH = 3
DOWNLOAD_HISA = 4


class CfdPreferencePage:
    def __init__(self):
        ui_path = os.path.join(os.path.dirname(__file__), "CfdPreferencePage.ui")
        self.form = FreeCADGui.PySideUic.loadUi(ui_path)

        self.form.tb_choose_foam_dir.clicked.connect(self.chooseFoamDir)
        self.form.le_foam_dir.textChanged.connect(self.foamDirChanged)
        self.form.tb_choose_paraview_path.clicked.connect(self.chooseParaviewPath)
        self.form.le_paraview_path.textChanged.connect(self.paraviewPathChanged)
        self.form.tb_choose_gmsh_path.clicked.connect(self.chooseGmshPath)
        self.form.le_gmsh_path.textChanged.connect(self.gmshPathChanged)
        self.form.pb_run_dependency_checker.clicked.connect(self.runDependencyChecker)
        self.form.pb_download_install_openfoam.clicked.connect(self.downloadInstallOpenFoam)
        self.form.tb_pick_openfoam_file.clicked.connect(self.pickOpenFoamFile)
        self.form.pb_download_install_paraview.clicked.connect(self.downloadInstallParaview)
        self.form.tb_pick_paraview_file.clicked.connect(self.pickParaviewFile)
        self.form.pb_download_install_cfMesh.clicked.connect(self.downloadInstallCfMesh)
        self.form.tb_pick_cfmesh_file.clicked.connect(self.pickCfMeshFile)
        self.form.pb_download_install_hisa.clicked.connect(self.downloadInstallHisa)
        self.form.tb_pick_hisa_file.clicked.connect(self.pickHisaFile)

        self.form.le_openfoam_url.setText(OPENFOAM_URL)
        self.form.le_paraview_url.setText(PARAVIEW_URL)

        self.form.tb_choose_output_dir.clicked.connect(self.chooseOutputDir)
        self.form.le_output_dir.textChanged.connect(self.outputDirChanged)

        self.thread = None
        self.install_process = None

        self.console_message = ""

        self.foam_dir = ""
        self.initial_foam_dir = ""

        self.paraview_path = ""
        self.initial_paraview_path = ""

        self.gmsh_path = ""
        self.initial_gmsh_path = ""

        self.output_dir = ""

        self.form.gb_openfoam.setVisible(platform.system() == 'Windows')
        self.form.gb_paraview.setVisible(platform.system() == 'Windows')

        self.setDownloadURLs()

    def __del__(self):
        if self.thread and self.thread.isRunning():
            FreeCAD.Console.PrintMessage("Terminating a pending install task")
            self.thread.terminate()
        if self.install_process and self.install_process.state() == QtCore.QProcess.Running:
            FreeCAD.Console.PrintMessage("Terminating a pending install task")
            self.install_process.terminate()
        QApplication.restoreOverrideCursor()

    def saveSettings(self):
        CfdTools.setFoamDir(self.foam_dir)
        CfdTools.setParaviewPath(self.paraview_path)
        CfdTools.setGmshPath(self.gmsh_path)
        prefs = CfdTools.getPreferencesLocation()
        FreeCAD.ParamGet(prefs).SetString("DefaultOutputPath", self.output_dir)

    def loadSettings(self):
        # Don't set the autodetected location, since the user might want to allow that to vary according
        # to WM_PROJECT_DIR setting
        prefs = CfdTools.getPreferencesLocation()
        self.foam_dir = FreeCAD.ParamGet(prefs).GetString("InstallationPath", "")
        self.initial_foam_dir = str(self.foam_dir)
        self.form.le_foam_dir.setText(self.foam_dir)

        self.paraview_path = CfdTools.getParaviewPath()
        self.initial_paraview_path = str(self.paraview_path)
        self.form.le_paraview_path.setText(self.paraview_path)

        self.gmsh_path = CfdTools.getGmshPath()
        self.initial_gmsh_path = str(self.gmsh_path)
        self.form.le_gmsh_path.setText(self.gmsh_path)

        self.output_dir = CfdTools.getDefaultOutputPath()
        self.form.le_output_dir.setText(self.output_dir)

    def consoleMessage(self, message="", color="#000000"):
        message = message.replace('\n', '<br>')
        self.console_message = self.console_message + \
            '<font color="{0}">{1}</font><br>'.format(color, message)
        self.form.textEdit_Output.setText(self.console_message)
        self.form.textEdit_Output.moveCursor(QtGui.QTextCursor.End)

    def foamDirChanged(self, text):
        self.foam_dir = text
        if self.foam_dir and os.access(self.foam_dir, os.R_OK):
            self.setDownloadURLs()

    def testGetRuntime(self, disable_exception=True):
        """ Set the foam dir temporarily and see if we can detect the runtime """
        prefs = CfdTools.getPreferencesLocation()
        prev_foam_dir = FreeCAD.ParamGet(prefs).GetString("InstallationPath", "")
        CfdTools.setFoamDir(self.foam_dir)
        try:
            runtime = CfdTools.getFoamRuntime()
        except IOError as e:
            runtime = None
            if not disable_exception:
                raise
        CfdTools.setFoamDir(prev_foam_dir)
        return runtime

    def setDownloadURLs(self):
        if self.testGetRuntime() == "MinGW":
            foam_ver = os.path.split(CfdTools.getFoamDir())[-1]
            self.form.le_cfmesh_url.setText(CFMESH_URL_MINGW.format(foam_ver))
            self.form.le_hisa_url.setText(HISA_URL_MINGW.format(foam_ver))
        else:
            self.form.le_cfmesh_url.setText(CFMESH_URL)
            self.form.le_hisa_url.setText(HISA_URL)

    def paraviewPathChanged(self, text):
        self.paraview_path = text

    def gmshPathChanged(self, text):
        self.gmsh_path = text

    def chooseFoamDir(self):
        d = QtGui.QFileDialog().getExistingDirectory(None, 'Choose OpenFOAM directory', self.foam_dir)
        if d and os.access(d, os.R_OK):
            self.foam_dir = d
        self.form.le_foam_dir.setText(self.foam_dir)

    def chooseParaviewPath(self):
        p, filter = QtGui.QFileDialog().getOpenFileName(None, 'Choose ParaView executable', self.paraview_path,
                                                        filter="*.exe"  if platform.system() == 'Windows' else None)
        if p and os.access(p, os.R_OK):
            self.paraview_path = p
        self.form.le_paraview_path.setText(self.paraview_path)

    def chooseGmshPath(self):
        p, filter = QtGui.QFileDialog().getOpenFileName(None, 'Choose gmsh executable', self.gmsh_path,
                                                        filter="*.exe"  if platform.system() == 'Windows' else None)
        if p and os.access(p, os.R_OK):
            self.gmsh_path = p
        self.form.le_gmsh_path.setText(self.gmsh_path)

    def outputDirChanged(self, text):
        self.output_dir = text

    def chooseOutputDir(self):
        d = QtGui.QFileDialog().getExistingDirectory(None, 'Choose output directory', self.output_dir)
        if d and os.access(d, os.W_OK):
            self.output_dir = os.path.abspath(d)
        self.form.le_output_dir.setText(self.output_dir)

    def runDependencyChecker(self):
        # Temporarily apply the foam dir selection and paraview path selection
        CfdTools.setFoamDir(self.foam_dir)
        CfdTools.setParaviewPath(self.paraview_path)
        CfdTools.setGmshPath(self.gmsh_path)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.consoleMessage("Checking dependencies...")
        msg = CfdTools.checkCfdDependencies()
        if not msg:
            self.consoleMessage("No missing dependencies detected")
        else:
            self.consoleMessage(msg)
        CfdTools.setFoamDir(self.initial_foam_dir)
        CfdTools.setParaviewPath(self.initial_paraview_path)
        CfdTools.setGmshPath(self.initial_gmsh_path)
        QApplication.restoreOverrideCursor()

    def showAdministratorWarningMessage(self):
        if platform.system() == "Windows":
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            if not is_admin:
                button = QtGui.QMessageBox.question(
                    None,
                    "CfdOF Workbench",
                    "Before installing this software, it is advised to run FreeCAD in administrator mode (hold down "
                    " the 'Shift' key, right-click on the FreeCAD launcher, and choose 'Run as administrator').\n\n"
                    "If this is not possible, please make sure OpenFOAM is installed in a location to which you have "
                    "full read/write access rights.\n\n"
                    "You are not currently running as administrator - do you wish to continue anyway?")
                return button == QtGui.QMessageBox.StandardButton.Yes
        return True

    def downloadInstallOpenFoam(self):
        if not self.showAdministratorWarningMessage():
            return
        if self.createThread():
            self.thread.task = DOWNLOAD_OPENFOAM
            self.thread.openfoam_url = self.form.le_openfoam_url.text()
            self.thread.start()

    def pickOpenFoamFile(self):
        f, filter = QtGui.QFileDialog().getOpenFileName(title='Choose OpenFOAM install file', filter="*.exe")
        if f and os.access(f, os.R_OK):
            self.form.le_openfoam_url.setText(urlparse.urljoin('file:', urlrequest.pathname2url(f)))

    def downloadInstallParaview(self):
        if self.createThread():
            self.thread.task = DOWNLOAD_PARAVIEW
            self.thread.paraview_url = self.form.le_paraview_url.text()
            self.thread.start()

    def pickParaviewFile(self):
        f, filter = QtGui.QFileDialog().getOpenFileName(title='Choose ParaView install file', filter="*.exe")
        if f and os.access(f, os.R_OK):
            self.form.le_paraview_url.setText(urlparse.urljoin('file:', urlrequest.pathname2url(f)))

    def downloadInstallCfMesh(self):
        if not self.showAdministratorWarningMessage():
            return

        runtime = self.testGetRuntime(False)
        if runtime == "MinGW" and self.form.le_cfmesh_url.text() == CFMESH_URL:
            # Openfoam might have just been installed and the URL would not have had a chance to update
            self.setDownloadURLs()

        if self.createThread():
            self.thread.task = DOWNLOAD_CFMESH
            # We are forced to apply the foam dir selection - reset when the task finishes
            CfdTools.setFoamDir(self.foam_dir)
            self.thread.cfmesh_url = self.form.le_cfmesh_url.text()
            self.thread.start()

    def pickCfMeshFile(self):
        f, filter = QtGui.QFileDialog().getOpenFileName(title='Choose cfMesh archive', filter="*.zip")
        if f and os.access(f, os.R_OK):
            self.form.le_cfmesh_url.setText(urlparse.urljoin('file:', urlrequest.pathname2url(f)))

    def downloadInstallHisa(self):
        if not self.showAdministratorWarningMessage():
            return

        runtime = self.testGetRuntime(False)
        if runtime == "MinGW" and self.form.le_hisa_url.text() == HISA_URL:
            # Openfoam might have just been installed and the URL would not have had a chance to update
            self.setDownloadURLs()

        if self.createThread():
            self.thread.task = DOWNLOAD_HISA
            # We are forced to apply the foam dir selection - reset when the task finishes
            CfdTools.setFoamDir(self.foam_dir)
            self.thread.hisa_url = self.form.le_hisa_url.text()
            self.thread.start()

    def pickHisaFile(self):
        f, filter = QtGui.QFileDialog().getOpenFileName(title='Choose HiSA archive', filter="*.zip")
        if f and os.access(f, os.R_OK):
            self.form.le_hisa_url.setText(urlparse.urljoin('file:', urlrequest.pathname2url(f)))

    def createThread(self):
        if self.thread and self.thread.isRunning():
            self.consoleMessage("Busy - please wait...", '#FF0000')
            return False
        else:
            self.thread = CfdPreferencePageThread()
            self.thread.signals.error.connect(self.threadError)
            self.thread.signals.finished.connect(self.threadFinished)
            self.thread.signals.status.connect(self.threadStatus)
            self.thread.signals.downloadProgress.connect(self.downloadProgress)
            return True

    def threadStatus(self, msg):
        self.consoleMessage(msg)

    def threadError(self, msg):
        self.consoleMessage(msg, '#FF0000')

    def threadFinished(self, status):
        if self.thread.task == DOWNLOAD_CFMESH:
            if status:
                if CfdTools.getFoamRuntime() != "MinGW":
                    self.consoleMessage("Download completed")
                    user_dir = self.thread.user_dir
                    self.consoleMessage("Building cfMesh. Lengthy process - please wait...")
                    self.consoleMessage("Log file: {}/{}/log.Allwmake".format(user_dir, CFMESH_FILE_BASE))
                    if CfdTools.getFoamRuntime() == 'WindowsDocker':
                        # There seem to be issues when using multi processors to build in docker
                        self.install_process = CfdTools.startFoamApplication(
                            "export WM_NCOMPPROCS=1; ./Allwmake",
                            "$WM_PROJECT_USER_DIR/"+CFMESH_FILE_BASE,
                            'log.Allwmake', self.installFinished)
                    else:
                        self.install_process = CfdTools.startFoamApplication(
                            "export WM_NCOMPPROCS=`nproc`; ./Allwmake", "$WM_PROJECT_USER_DIR/"+CFMESH_FILE_BASE,
                            'log.Allwmake', self.installFinished)
                else:
                    self.consoleMessage("Install completed")
                # Reset foam dir for now in case the user presses 'Cancel'
                CfdTools.setFoamDir(self.initial_foam_dir)
            else:
                self.consoleMessage("Download unsuccessful")
        elif self.thread.task == DOWNLOAD_HISA:
            if status:
                if CfdTools.getFoamRuntime() != "MinGW":
                    self.consoleMessage("Download completed")
                    user_dir = self.thread.user_dir
                    self.consoleMessage("Building HiSA. Please wait...")
                    self.consoleMessage("Log file: {}/{}/log.Allwmake".format(user_dir, HISA_FILE_BASE))
                    if CfdTools.getFoamRuntime() == 'WindowsDocker':
                        # There seem to be issues when using multi processors to build in docker
                        self.install_process = CfdTools.startFoamApplication(
                            "export WM_NCOMPPROCS=1; ./Allwmake",
                            "$WM_PROJECT_USER_DIR/"+HISA_FILE_BASE,
                            'log.Allwmake', self.installFinished)
                    else:
                        self.install_process = CfdTools.startFoamApplication(
                            "export WM_NCOMPPROCS=`nproc`; ./Allwmake", "$WM_PROJECT_USER_DIR/"+HISA_FILE_BASE,
                            'log.Allwmake', self.installFinished)
                else:
                    self.consoleMessage("Install completed")
                # Reset foam dir for now in case the user presses 'Cancel'
                CfdTools.setFoamDir(self.initial_foam_dir)
            else:
                self.consoleMessage("Download unsuccessful")
        self.thread = None

    def installFinished(self, exit_code):
        if exit_code:
            self.consoleMessage("Install finished with error {}".format(exit_code))
        else:
            self.consoleMessage("Install completed")

    def downloadProgress(self, bytes_done, bytes_total):
        mb_done = float(bytes_done)/(1024*1024)
        msg = "Downloaded {:.2f} MB".format(mb_done)
        if bytes_total > 0:
            msg += " of {:.2f} MB".format(float(bytes_total)/(1024*1024))
        self.form.labelDownloadProgress.setText(msg)


class CfdPreferencePageSignals(QObject):
    error = QtCore.Signal(str)  # Signal in PySide, pyqtSignal in PyQt
    finished = QtCore.Signal(bool)
    status = QtCore.Signal(str)
    downloadProgress = QtCore.Signal(int, int)


class CfdPreferencePageThread(QThread):
    """ Worker thread to complete tasks in preference page """
    def __init__(self):
        super(CfdPreferencePageThread, self).__init__()
        self.signals = CfdPreferencePageSignals()
        self.user_dir = None
        self.task = None
        self.openfoam_url = None
        self.paraview_url = None
        self.cfmesh_url = None
        self.hisa_url = None

    def run(self):
        try:
            if self.task == DOWNLOAD_OPENFOAM:
                self.downloadOpenFoam()
            elif self.task == DOWNLOAD_PARAVIEW:
                self.downloadParaview()
            elif self.task == DOWNLOAD_CFMESH:
                self.downloadCfMesh()
            elif self.task == DOWNLOAD_HISA:
                self.downloadHisa()
        except Exception as e:
            self.signals.error.emit(str(e))
            self.signals.finished.emit(False)
            raise
        self.signals.finished.emit(True)

    def downloadFile(self, url, **kwargs):
        block_size = kwargs.get('block_size', 10*1024)
        context = kwargs.get('context', None)
        reporthook = kwargs.get('reporthook', None)
        suffix = kwargs.get('suffix', '')
        with closing(urlrequest.urlopen(url, context=context)) as response:  # For Python < 3.3 backward compatibility
            download_len = int(response.info().get('Content-Length', 0))
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
                i = 0
                while True:
                    data = response.read(block_size)
                    if not data:
                        break
                    tmp_file.write(data)
                    i += 1
                    if reporthook:
                        reporthook(i, block_size, download_len)
                filename = tmp_file.name
                return filename, response.info()

    def download(self, url, suffix, name):
        self.signals.status.emit("Downloading {}, please wait...".format(name))
        try:
            if hasattr(ssl, 'create_default_context'):
                context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            else:
                context = None
            # Download
            (filename, header) = self.downloadFile(
                url, suffix=suffix, reporthook=self.downloadStatus, context=context)
        except Exception as ex:
            raise Exception("Error downloading {}: {}".format(name, str(ex)))

        self.signals.status.emit("{} downloaded to {}".format(name, filename))
        return filename

    def downloadOpenFoam(self):
        filename = self.download(self.openfoam_url, OPENFOAM_FILE_EXT, "OpenFOAM")
        if QtCore.QProcess().startDetached(filename):
            self.signals.status.emit("OpenFOAM installer launched - please complete the installation")
        else:
            raise Exception("Failed to launch OpenFOAM installer")

    def downloadParaview(self):
        filename = self.download(self.paraview_url, PARAVIEW_FILE_EXT, "ParaView")
        if QtCore.QProcess().startDetached(filename):
            self.signals.status.emit("ParaView installer launched - please complete the installation")
        else:
            raise Exception("Failed to launch ParaView installer")

    def downloadCfMesh(self):
        filename = self.download(self.cfmesh_url, CFMESH_FILE_EXT, "cfMesh")

        if CfdTools.getFoamRuntime() == "MinGW":
            self.user_dir = None
            self.signals.status.emit("Installing cfMesh...")
            CfdTools.runFoamCommand(
                '{{ mkdir -p "$FOAM_APPBIN" && cd "$FOAM_APPBIN" && unzip -o "{}"; }}'.
                    format(CfdTools.translatePath(filename)))
        else:
            self.user_dir = CfdTools.runFoamCommand("echo $WM_PROJECT_USER_DIR")[0].rstrip().split('\n')[-1]
            # We can't reverse-translate the path for docker since it sits inside the container. Just report it as such.
            if CfdTools.getFoamRuntime() != 'WindowsDocker':
                self.user_dir = CfdTools.reverseTranslatePath(self.user_dir)

            self.signals.status.emit("Extracting cfMesh...")
            if CfdTools.getFoamRuntime() == 'WindowsDocker':
                from zipfile import ZipFile
                with ZipFile(filename, 'r') as zip:
                    with tempfile.TemporaryDirectory() as tempdir:
                        zip.extractall(path=tempdir)
                        CfdTools.runFoamCommand(
                            '{{ mkdir -p "$WM_PROJECT_USER_DIR" && cp -r "{}" "$WM_PROJECT_USER_DIR/"; }}'
                                .format(CfdTools.translatePath(os.path.join(tempdir, CFMESH_FILE_BASE))))
            else:
                CfdTools.runFoamCommand(
                    '{{ mkdir -p "$WM_PROJECT_USER_DIR" && cd "$WM_PROJECT_USER_DIR" && ( rm -r {}; unzip -o "{}"; ); }}'.
                    format(CFMESH_FILE_BASE, CfdTools.translatePath(filename)))

    def downloadHisa(self):
        filename = self.download(self.hisa_url, HISA_FILE_EXT, "HiSA")

        if CfdTools.getFoamRuntime() == "MinGW":
            self.user_dir = None
            self.signals.status.emit("Installing HiSA...")
            CfdTools.runFoamCommand(
                '{{ mkdir -p "$FOAM_APPBIN" && cd "$FOAM_APPBIN" && unzip -o "{}"; }}'.
                    format(CfdTools.translatePath(filename)))
        else:
            self.user_dir = CfdTools.runFoamCommand("echo $WM_PROJECT_USER_DIR")[0].rstrip().split('\n')[-1]
            # We can't reverse-translate the path for docker since it sits inside the container. Just report it as such.
            if CfdTools.getFoamRuntime() != 'WindowsDocker':
                self.user_dir = CfdTools.reverseTranslatePath(self.user_dir)

            self.signals.status.emit("Extracting HiSA...")
            if CfdTools.getFoamRuntime() == 'WindowsDocker':
                from zipfile import ZipFile
                with ZipFile(filename, 'r') as zip:
                    with tempfile.TemporaryDirectory() as tempdir:
                        zip.extractall(path=tempdir)
                        CfdTools.runFoamCommand(
                            '{{ mkdir -p "$WM_PROJECT_USER_DIR" && cp -r "{}" "$WM_PROJECT_USER_DIR/"; }}'
                                .format(CfdTools.translatePath(os.path.join(tempdir, HISA_FILE_BASE))))
            else:
                CfdTools.runFoamCommand(
                    '{{ mkdir -p "$WM_PROJECT_USER_DIR" && cd "$WM_PROJECT_USER_DIR" && ( rm -r {}; unzip -o "{}"; );  }}'.
                    format(HISA_FILE_BASE, CfdTools.translatePath(filename)))

    def downloadStatus(self, blocks, block_size, total_size):
        self.signals.downloadProgress.emit(blocks*block_size, total_size)
