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
    QgsProcessingException,
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
    Synchronize local media/upload data to remote FTP
    via LFTP
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.
    INPUT_SYNC_DATE = 'INPUT_SYNC_DAT'
    LOCAL_QGIS_PROJECT_FOLDER = 'LOCAL_QGIS_PROJECT_FOLDER'
    FTP_HOST = 'FTP_HOST'
    FTP_LOGIN = 'FTP_LOGIN'
    FTP_REMOTE_DIR = 'FTP_REMOTE_DIR'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    ftphost = 'ftp-valabre.lizmap.com'


    def name(self):
        return 'synchronize_media_subfolder_to_ftp'

    def displayName(self):
        return self.tr('Synchronize local media subfolder to central FTP server')

    def group(self):
        return self.tr('Synchronization')

    def groupId(self):
        return 'lizsync_sync'

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
            QgsProcessingParameterString(
                self.LOCAL_QGIS_PROJECT_FOLDER,
                self.tr('Local QGIS project folder'),
                defaultValue=local_qgis_project_folder,
                optional=False
            )
        )
        ftp_host = QgsExpressionContextUtils.globalScope().variable('lizsync_ftp_host')
        self.addParameter(
            QgsProcessingParameterString(
                self.FTP_HOST,
                self.tr('FTP Server host'),
                defaultValue=ftp_host,
                optional=False
            )
        )
        ftp_login = QgsExpressionContextUtils.globalScope().variable('lizsync_ftp_login')
        self.addParameter(
            QgsProcessingParameterString(
                self.FTP_LOGIN,
                self.tr('FTP Server login'),
                defaultValue=ftp_login,
                optional=False
            )
        )
        ftp_remote_dir = QgsExpressionContextUtils.globalScope().variable('lizsync_ftp_remote_dir')
        self.addParameter(
            QgsProcessingParameterString(
                self.FTP_REMOTE_DIR,
                self.tr('FTP Server remote directory'),
                defaultValue=ftp_remote_dir,
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

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """

        # Check internet
        feedback.pushInfo(self.tr('Check internet connection'))
        if not check_internet():
            feedback.pushInfo(self.tr('No internet connection'))
            raise Exception(self.tr('No internet connection'))

        # Parameters
        ftphost = parameters[self.FTP_HOST]
        ftplogin = parameters[self.FTP_LOGIN]
        ftpport = 21
        ftppass = ''
        remotedir = parameters[self.FTP_REMOTE_DIR]
        localdir = parameters[self.LOCAL_QGIS_PROJECT_FOLDER]

        # Check FTP password
        try:
            auth = netrc.netrc().authenticators(ftphost)
            if auth is not None:
                ftpuser, account, ftppass = auth
        except (netrc.NetrcParseError, IOError):
            raise Exception(self.tr('Could not retrieve password from ~/.netrc file'))
        if not ftppass:
            raise Exception(self.tr('Could not retrieve password from ~/.netrc file or is empty'))

        msg = ''

        # Check localdir
        feedback.pushInfo(self.tr('CHECK LOCAL PROJECT DIRECTORY'))
        if not localdir or not os.path.isdir(localdir):
            m = self.tr('QGIS project local directory not found')
            feedback.pushInfo(m)
            raise Exception(m)
        else:
            m = self.tr('QGIS project local directory ok')

        # Check if remotedir exists
        feedback.pushInfo(self.tr('CHECK REMOTE DIRECTORY') + ' %s' % remotedir )
        ftp = FTP()
        ftp.connect(ftphost, 21)
        ftp.login(ftplogin, ftppass)
        try:
            ftp.cwd(remotedir)
            #do the code for successfull cd
            self.tr('Remote directory exists in the central server')
        except Exception:
            ftp.close()
            m = self.tr('Remote directory does not exist')
            feedback.pushInfo(m)
            raise Exception(m)

        # Check if media/upload exists locally
        feedback.pushInfo(self.tr('START FTP DIRECTORY SYNCHRONIZATION FROM SERVER') + ' %s' % remotedir )
        localdir = localdir + '/media/upload'
        remotedir = remotedir + '/media/upload'
        feedback.pushInfo(self.tr('Local directory') + ' %s' % localdir)
        feedback.pushInfo(self.tr('Remote directory') + ' %s' % remotedir)
        if os.path.isdir(localdir):
            # Run FTP sync
            ftp_sync(ftphost, ftpport, ftpuser, localdir, remotedir, '', parameters, context, feedback)
            msg = self.tr("Synchronization successfull")
        else:
            m = self.tr('Local directory does not exists. No synchronization needed.')
            feedback.pushInfo(m)
            msg = m

        status = 1
        msg = 'Synchro'
        out = {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }
        return out
