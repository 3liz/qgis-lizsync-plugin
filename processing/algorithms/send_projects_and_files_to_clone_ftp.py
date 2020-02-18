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
    QgsExpressionContextUtils
)

import os, subprocess
from pathlib import Path
import processing
from datetime import date, datetime
from ftplib import FTP
import netrc
import re
from .tools import *

class SendProjectsAndFilesToCloneFtp(QgsProcessingAlgorithm):
    """
    Synchronize local data from remote FTP
    via LFTP
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    LOCAL_QGIS_PROJECT_FOLDER = 'LOCAL_QGIS_PROJECT_FOLDER'

    CONNECTION_NAME_CLONE = 'CONNECTION_NAME_CLONE'
    CLONE_FTP_HOST = 'CLONE_FTP_HOST'
    CLONE_FTP_PORT = 'CLONE_FTP_PORT'
    CLONE_FTP_LOGIN = 'CLONE_FTP_LOGIN'
    CLONE_FTP_REMOTE_DIR = 'CLONE_FTP_REMOTE_DIR'
    CLONE_QGIS_PROJECT_FOLDER = 'CLONE_QGIS_PROJECT_FOLDER'

    FTP_EXCLUDE_REMOTE_SUBDIRS = 'FTP_EXCLUDE_REMOTE_SUBDIRS'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'send_projects_and_files_to_clone_ftp'

    def displayName(self):
        return self.tr('Send local QGIS projects and files to the clone FTP server')

    def group(self):
        return self.tr('03 Synchronize data and files')

    def groupId(self):
        return 'lizsync_sync'

    def shortHelpString(self):
        short_help = self.tr(
            ' Send QGIS projects and files to the clone FTP server remote directory.'
            '<br>'
            '<br>'
            ' This script can be used by the geomatician in charge of the deployment of data'
            ' to one or several clone(s).'
            '<br>'
            '<br>'
            ' It synchronizes the files from the given local QGIS project folder'
            ' to the clone remote folder by using the given FTP connexion.'
            ' This means all the files from the clone folder will be overwritten'
            ' by the files from the local QGIS project folder.'
            '<br>'
            '<br>'
            ' Beware ! This script does not adapt projects for the clone database'
            ' (no modification of the PostgreSQL connexion data inside the QGIS project files) !'
        )
        return short_help

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return SendProjectsAndFilesToCloneFtp()

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # INPUTS
        connection_name_central = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_central')
        db_param_a = QgsProcessingParameterString(
            self.CONNECTION_NAME_CENTRAL,
            self.tr('PostgreSQL connection to the central database'),
            defaultValue=connection_name_central,
            optional=False
        )
        db_param_a.setMetadata({
            'widget_wrapper': {
                'class': 'processing.gui.wrappers_postgis.ConnectionWidgetWrapper'
            }
        })
        self.addParameter(db_param_a)

        # Clone database connection parameters
        connection_name_clone = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_clone')
        db_param_b = QgsProcessingParameterString(
            self.CONNECTION_NAME_CLONE,
            self.tr('PostgreSQL connection to the local database'),
            defaultValue=connection_name_clone,
            optional=False
        )
        db_param_b.setMetadata({
            'widget_wrapper': {
                'class': 'processing.gui.wrappers_postgis.ConnectionWidgetWrapper'
            }
        })
        self.addParameter(db_param_b)

        local_qgis_project_folder = QgsExpressionContextUtils.globalScope().variable('lizsync_local_qgis_project_folder')
        self.addParameter(
            QgsProcessingParameterFile(
                self.LOCAL_QGIS_PROJECT_FOLDER,
                self.tr('Local desktop QGIS project folder'),
                defaultValue=local_qgis_project_folder,
                behavior=QgsProcessingParameterFile.Folder,
                optional=False
            )
        )

        clone_ftp_host = QgsExpressionContextUtils.globalScope().variable('lizsync_clone_ftp_host')
        self.addParameter(
            QgsProcessingParameterString(
                self.CLONE_FTP_HOST,
                self.tr('Clone FTP Server host'),
                defaultValue=clone_ftp_host,
                optional=False
            )
        )
        clone_ftp_port = QgsExpressionContextUtils.globalScope().variable('lizsync_clone_ftp_port')
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CLONE_FTP_PORT,
                self.tr('Clone FTP Server port'),
                defaultValue=clone_ftp_port,
                optional=False
            )
        )
        clone_ftp_login = QgsExpressionContextUtils.globalScope().variable('lizsync_clone_ftp_login')
        self.addParameter(
            QgsProcessingParameterString(
                self.CLONE_FTP_LOGIN,
                self.tr('Clone FTP Server login'),
                defaultValue=clone_ftp_login,
                optional=False
            )
        )
        clone_ftp_remote_dir = QgsExpressionContextUtils.globalScope().variable('lizsync_clone_ftp_remote_dir')
        self.addParameter(
            QgsProcessingParameterString(
                self.CLONE_FTP_REMOTE_DIR,
                self.tr('Clone FTP Server remote directory'),
                defaultValue=clone_ftp_remote_dir,
                optional=False
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.FTP_EXCLUDE_REMOTE_SUBDIRS,
                self.tr('List of sub-directory to exclude from synchro, separated by commas.'),
                defaultValue='data',
                optional=True
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

        return super(SendProjectsAndFilesToCloneFtp, self).checkParameterValues(parameters, context)

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """

        # Check internet
        feedback.pushInfo(self.tr('CHECK INTERNET CONNECTION'))
        if not check_internet():
            m = self.tr('No internet connection')
            feedback.pushInfo(m)
            raise Exception(m)

        # Parameters
        ftphost = parameters[self.CLONE_FTP_HOST]
        ftpport = parameters[self.CLONE_FTP_PORT]
        ftplogin = parameters[self.CLONE_FTP_LOGIN]
        ftppass = ''
        localdir = parameters[self.LOCAL_QGIS_PROJECT_FOLDER]
        ftpdir = parameters[self.CLONE_FTP_REMOTE_DIR]

        # Check FTP password
        try:
            auth = netrc.netrc().authenticators(ftphost)
            if auth is not None:
                ftplogin, account, ftppass = auth
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
            feedback.pushInfo(m)
            raise Exception(m)

        # Run FTP sync
        feedback.pushInfo(self.tr('Local directory') + ' %s' % localdir)
        feedback.pushInfo(self.tr('FTP directory') + ' %s' % ftpdir)
        direction = 'to' # we send data TO FTP
        excludedirs = parameters[self.FTP_EXCLUDE_REMOTE_SUBDIRS].strip()
        ftp_sync(ftphost, ftpport, ftplogin, localdir, ftpdir, direction, excludedirs, feedback)


        status = 1
        msg = self.tr("Synchronization successfull")
        out = {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }
        return out

