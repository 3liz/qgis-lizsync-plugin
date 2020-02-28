# -*- coding: utf-8 -*-
"""
/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

__author__ = '3liz'
__date__ = '2018-12-19'
__copyright__ = '(C) 2018 by 3liz'

from PyQt5.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingUtils,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFile,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber,
    QgsProcessingParameterDefinition
)

import os, subprocess
from pathlib import Path
import processing
from datetime import date, datetime
from ftplib import FTP
from .tools import *
import netrc
from ...qgis_plugin_tools.tools.i18n import tr

class SynchronizeMediaSubfolderToFtp(QgsProcessingAlgorithm):
    """
    Synchronize clone media/upload data to remote FTP
    via LFTP
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.
    INPUT_SYNC_DATE = 'INPUT_SYNC_DAT'
    LOCAL_QGIS_PROJECT_FOLDER = 'LOCAL_QGIS_PROJECT_FOLDER'
    CENTRAL_FTP_HOST = 'CENTRAL_FTP_HOST'
    CENTRAL_FTP_PORT = 'CENTRAL_FTP_PORT'
    CENTRAL_FTP_LOGIN = 'CENTRAL_FTP_LOGIN'
    CENTRAL_FTP_REMOTE_DIR = 'CENTRAL_FTP_REMOTE_DIR'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    ftphost = 'ftp-valabre.lizmap.com'


    def name(self):
        return 'synchronize_media_subfolder_to_ftp'

    def displayName(self):
        return tr('Synchronize the clone media subfolder to the central FTP server')

    def group(self):
        return tr('03 Synchronize data and files')

    def groupId(self):
        return 'lizsync_sync'

    def shortHelpString(self):
        short_help = tr(
            ' Send media files, such as new images, stored in the clone QGIS "media/upload/" folder,'
            ' TO the central FTP server remote directory "media/upload/"'
            '\n'
            '\n'
            ' These media files can for example have been added by using Lizmap editing form.'
            '\n'
            '\n'
            ' Every file existing in the clone "media/upload/" folder but not in the central server "media/upload/" folder will be sent.'
        )
        return short_help

    def createInstance(self):
        return SynchronizeMediaSubfolderToFtp()

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # LizSync config file from ini
        ls = lizsyncConfig()

        # INPUTS
        p = QgsProcessingParameterString(
            self.INPUT_SYNC_DATE, 'Synchronization time',
            defaultValue=datetime.now().isoformat(),
            optional=False
        )
        p.setFlags(QgsProcessingParameterDefinition.FlagHidden)
        self.addParameter(p)

        local_qgis_project_folder = ls.variable('local/qgis_project_folder')
        self.addParameter(
            QgsProcessingParameterFile(
                self.LOCAL_QGIS_PROJECT_FOLDER,
                tr('Local QGIS project folder'),
                defaultValue=local_qgis_project_folder,
                behavior=QgsProcessingParameterFile.Folder,
                optional=False
            )
        )
        central_ftp_host = ls.variable('ftp:central/host')
        self.addParameter(
            QgsProcessingParameterString(
                self.CENTRAL_FTP_HOST,
                tr('Central FTP Server host'),
                defaultValue=central_ftp_host,
                optional=False
            )
        )
        central_ftp_port = ls.variable('ftp:central/port')
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CENTRAL_FTP_PORT,
                tr('Central FTP Server port'),
                defaultValue=central_ftp_port,
                optional=False
            )
        )
        central_ftp_login = ls.variable('ftp:central/user')
        self.addParameter(
            QgsProcessingParameterString(
                self.CENTRAL_FTP_LOGIN,
                tr('Central FTP Server login'),
                defaultValue=central_ftp_login,
                optional=False
            )
        )
        central_ftp_remote_dir = ls.variable('ftp:central/remote_directory')
        self.addParameter(
            QgsProcessingParameterString(
                self.CENTRAL_FTP_REMOTE_DIR,
                tr('Central FTP Server remote directory'),
                defaultValue=central_ftp_remote_dir,
                optional=False
            )
        )

        # OUTPUTS
        # Add output for message
        self.addOutput(
            QgsProcessingOutputNumber(
                self.OUTPUT_STATUS, tr('Output status')
            )
        )
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING, tr('Output message')
            )
        )

    def checkParameterValues(self, parameters, context):

        # Check FTP binary
        status, msg = checkFtpBinary()
        if not status:
            return status, msg

        return super(SynchronizeMediaSubfolderToFtp, self).checkParameterValues(parameters, context)

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        status = 0
        msg = ''
        output = {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }

        # Check internet
        feedback.pushInfo(tr('Check internet connection'))
        if not check_internet():
            m = tr('No internet connection')
            return returnError(output, m, feedback)

        # Parameters
        ftphost = parameters[self.CENTRAL_FTP_HOST]
        ftplogin = parameters[self.CENTRAL_FTP_LOGIN]
        ftpport = parameters[self.CENTRAL_FTP_PORT]
        ftpdir = parameters[self.CENTRAL_FTP_REMOTE_DIR]
        localdir = parameters[self.LOCAL_QGIS_PROJECT_FOLDER]

        # Check FTP password
        # Get FTP password
        # First check if it is given in ini file
        ls = lizsyncConfig()
        ftppass = ls.variable('ftp:central/password')
        # If not given, search for it in ~/.netrc
        if not ftppass:
            try:
                auth = netrc.netrc().authenticators(ftphost)
                if auth is not None:
                    ftpuser, account, ftppass = auth
            except (netrc.NetrcParseError, IOError):
                m = tr('Could not retrieve password from ~/.netrc file')
                return returnError(output, m, feedback)
            if not ftppass:
                m =tr('Could not retrieve password from ~/.netrc file or is empty')
                return returnError(output, m, feedback)
            else:
                # Use None to force to use netrc file
                # only for linux (lftp). we need to use password for winscp
                if psys().lower().startswith('linux'):
                    ftppass = None

        msg = ''

        # Check localdir
        feedback.pushInfo(tr('CHECK LOCAL PROJECT DIRECTORY'))
        if not localdir or not os.path.isdir(localdir):
            m = tr('QGIS project local directory not found')
            return returnError(output, m, feedback)
        else:
            m = tr('QGIS project local directory ok')

        # Check if ftpdir exists
        feedback.pushInfo(tr('CHECK REMOTE DIRECTORY') + ' %s' % ftpdir )
        ftp = FTP()
        ftp.connect(ftphost, ftpport)
        ftp.login(ftplogin, ftppass)
        try:
            ftp.cwd(ftpdir)
            #do the code for successfull cd
            tr('Remote directory exists in the central server')
        except Exception:
            ftp.close()
            m = tr('Remote directory does not exist')
            return returnError(output, m, feedback)

        # Check if media/upload exists locally
        feedback.pushInfo(tr('START FTP DIRECTORY SYNCHRONIZATION TO SERVER') + ' %s' % ftpdir )
        localdir = localdir + '/media/upload'
        ftpdir = ftpdir + '/media/upload'
        feedback.pushInfo(tr('Local directory') + ' %s' % localdir)
        feedback.pushInfo(tr('FTP remote directory') + ' %s' % ftpdir)
        if os.path.isdir(localdir):
            # Run FTP sync
            direction = 'to'
            ok, msg = ftp_sync(ftphost, ftpport, ftplogin, ftppass, localdir, ftpdir, direction, '', feedback)
            if not ok:
                m = msg
                return returnError(output, m, feedback)
        else:
            m = tr('Local directory does not exists. No synchronization needed.')
            feedback.pushInfo(m)
            msg = m

        status = 1
        msg = tr('Media upload subfolder sucessfully synchronized to the central server')
        output = {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }
        return output
