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
    QgsProcessingParameterDefinition,
    QgsExpressionContextUtils
)

import os, subprocess
from pathlib import Path
import processing
from datetime import date, datetime
from ftplib import FTP
from .tools import *
import netrc

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
        return self.tr('Synchronize the clone media subfolder to the central FTP server')

    def group(self):
        return self.tr('03 Synchronize data and files')

    def groupId(self):
        return 'lizsync_sync'

    def shortHelpString(self):
        short_help = self.tr(
            ' Send media files, such as new images, stored in the clone QGIS "media/upload/" folder,'
            ' TO the central FTP server remote directory "media/upload/"'
            '<br>'
            '<br>'
            ' These media files can for example have been added by using Lizmap editing form.'
            '<br>'
            '<br>'
            ' Every file existing in the clone "media/upload/" folder but not in the central server "media/upload/" folder will be sent.'
        )
        return short_help

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return SynchronizeMediaSubfolderToFtp()

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # INPUTS
        p = QgsProcessingParameterString(
            self.INPUT_SYNC_DATE, 'Synchronization time',
            defaultValue=datetime.now().isoformat(),
            optional=False
        )
        p.setFlags(QgsProcessingParameterDefinition.FlagHidden)
        self.addParameter(p)

        local_qgis_project_folder = QgsExpressionContextUtils.globalScope().variable('lizsync_local_qgis_project_folder')
        self.addParameter(
            QgsProcessingParameterFile(
                self.LOCAL_QGIS_PROJECT_FOLDER,
                self.tr('Local QGIS project folder'),
                defaultValue=local_qgis_project_folder,
                behavior=QgsProcessingParameterFile.Folder,
                optional=False
            )
        )
        central_ftp_host = QgsExpressionContextUtils.globalScope().variable('lizsync_central_ftp_host')
        self.addParameter(
            QgsProcessingParameterString(
                self.CENTRAL_FTP_HOST,
                self.tr('Central FTP Server host'),
                defaultValue=central_ftp_host,
                optional=False
            )
        )
        central_ftp_port = QgsExpressionContextUtils.globalScope().variable('lizsync_central_ftp_port')
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CENTRAL_FTP_PORT,
                self.tr('Central FTP Server port'),
                defaultValue=central_ftp_port,
                optional=False
            )
        )
        central_ftp_login = QgsExpressionContextUtils.globalScope().variable('lizsync_central_ftp_login')
        self.addParameter(
            QgsProcessingParameterString(
                self.CENTRAL_FTP_LOGIN,
                self.tr('Central FTP Server login'),
                defaultValue=central_ftp_login,
                optional=False
            )
        )
        central_ftp_remote_dir = QgsExpressionContextUtils.globalScope().variable('lizsync_central_ftp_remote_dir')
        self.addParameter(
            QgsProcessingParameterString(
                self.CENTRAL_FTP_REMOTE_DIR,
                self.tr('Central FTP Server remote directory'),
                defaultValue=central_ftp_remote_dir,
                optional=False
            )
        )

        # OUTPUTS
        # Add output for message
        self.addOutput(
            QgsProcessingOutputNumber(
                self.OUTPUT_STATUS, self.tr('Output status')
            )
        )
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING, self.tr('Output message')
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
        feedback.pushInfo(self.tr('Check internet connection'))
        if not check_internet():
            m = self.tr('No internet connection')
            return returnError(output, m, feedback)

        # Parameters
        ftphost = parameters[self.CENTRAL_FTP_HOST]
        ftplogin = parameters[self.CENTRAL_FTP_LOGIN]
        ftpport = parameters[self.CENTRAL_FTP_PORT]
        ftppass = ''
        ftpdir = parameters[self.CENTRAL_FTP_REMOTE_DIR]
        localdir = parameters[self.LOCAL_QGIS_PROJECT_FOLDER]

        # Check FTP password
        try:
            auth = netrc.netrc().authenticators(ftphost)
            if auth is not None:
                ftpuser, account, ftppass = auth
        except (netrc.NetrcParseError, IOError):
            m = self.tr('Could not retrieve password from ~/.netrc file')
            return returnError(output, m, feedback)
        if not ftppass:
            m =self.tr('Could not retrieve password from ~/.netrc file or is empty')
            return returnError(output, m, feedback)

        msg = ''

        # Check localdir
        feedback.pushInfo(self.tr('CHECK LOCAL PROJECT DIRECTORY'))
        if not localdir or not os.path.isdir(localdir):
            m = self.tr('QGIS project local directory not found')
            return returnError(output, m, feedback)
        else:
            m = self.tr('QGIS project local directory ok')

        # Check if ftpdir exists
        feedback.pushInfo(self.tr('CHECK REMOTE DIRECTORY') + ' %s' % ftpdir )
        ftp = FTP()
        ftp.connect(ftphost, ftpport)
        ftp.login(ftplogin, ftppass)
        try:
            ftp.cwd(ftpdir)
            #do the code for successfull cd
            self.tr('Remote directory exists in the central server')
        except Exception:
            ftp.close()
            m = self.tr('Remote directory does not exist')
            return returnError(output, m, feedback)

        # Check if media/upload exists locally
        feedback.pushInfo(self.tr('START FTP DIRECTORY SYNCHRONIZATION TO SERVER') + ' %s' % ftpdir )
        localdir = localdir + '/media/upload'
        ftpdir = ftpdir + '/media/upload'
        feedback.pushInfo(self.tr('Local directory') + ' %s' % localdir)
        feedback.pushInfo(self.tr('FTP remote directory') + ' %s' % ftpdir)
        if os.path.isdir(localdir):
            # Run FTP sync
            direction = 'to'
            ok, msg = ftp_sync(ftphost, ftpport, ftpuser, localdir, ftpdir, direction, '', feedback)
            if not ok:
                m = msg
                return returnError(output, m, feedback)
        else:
            m = self.tr('Local directory does not exists. No synchronization needed.')
            feedback.pushInfo(m)
            msg = m

        status = 1
        msg = self.tr('Media upload subfolder sucessfully synchronized to the central server')
        output = {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }
        return output
