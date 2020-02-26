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
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFile,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber
)

import os, subprocess
from pathlib import Path
import processing
from datetime import date, datetime
from ftplib import FTP
import netrc
import re
from .tools import *
from platform import system as psys
from ...qgis_plugin_tools.tools.i18n import tr

class GetProjectsAndFilesFromCentralFtp(QgsProcessingAlgorithm):
    """
    Synchronize local data from remote FTP
    via LFTP
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.
    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    CENTRAL_FTP_HOST = 'CENTRAL_FTP_HOST'
    CENTRAL_FTP_PORT = 'CENTRAL_FTP_PORT'
    CENTRAL_FTP_LOGIN = 'CENTRAL_FTP_LOGIN'
    CENTRAL_FTP_REMOTE_DIR = 'CENTRAL_FTP_REMOTE_DIR'
    LOCAL_QGIS_PROJECT_FOLDER = 'LOCAL_QGIS_PROJECT_FOLDER'

    CONNECTION_NAME_CLONE = 'CONNECTION_NAME_CLONE'
    CLONE_QGIS_PROJECT_FOLDER = 'CLONE_QGIS_PROJECT_FOLDER'

    FTP_EXCLUDE_REMOTE_SUBDIRS = 'FTP_EXCLUDE_REMOTE_SUBDIRS'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'get_projects_and_files_from_central_ftp'

    def displayName(self):
        return tr('Get projects and files from the central FTP server')

    def group(self):
        return tr('03 Synchronize data and files')

    def groupId(self):
        return 'lizsync_sync'

    def shortHelpString(self):
        short_help = tr(
            ' Get QGIS projects and files from the give FTP server and remote directory'
            ' and adapt QGIS projects for the local clone database'
            ' by replacing PostgreSQL connection data with the local PostgreSQL server data.'
            ' An internet connection is needed to use this algorithm'
        )
        return short_help

    def createInstance(self):
        return GetProjectsAndFilesFromCentralFtp()

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # LizSync config file from ini
        ls = lizsyncConfig()

        # Central connexion info
        connection_name_central = ls.variable('postgresql:central/name')
        db_param_a = QgsProcessingParameterString(
            self.CONNECTION_NAME_CENTRAL,
            tr('PostgreSQL connection to the central database'),
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
        connection_name_clone = ls.variable('postgresql:clone/name')
        db_param_b = QgsProcessingParameterString(
            self.CONNECTION_NAME_CLONE,
            tr('PostgreSQL connection to the local database'),
            defaultValue=connection_name_clone,
            optional=False
        )
        db_param_b.setMetadata({
            'widget_wrapper': {
                'class': 'processing.gui.wrappers_postgis.ConnectionWidgetWrapper'
            }
        })
        self.addParameter(db_param_b)

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

        self.addParameter(
            QgsProcessingParameterString(
                self.FTP_EXCLUDE_REMOTE_SUBDIRS,
                tr('List of sub-directory to exclude from synchro, separated by commas.'),
                defaultValue='data',
                optional=True
            )
        )

        clone_qgis_project_folder = ls.variable('clone/qgis_project_folder')
        self.addParameter(
            QgsProcessingParameterFile(
                self.CLONE_QGIS_PROJECT_FOLDER,
                tr('Clone QGIS project folder'),
                defaultValue=clone_qgis_project_folder,
                behavior=QgsProcessingParameterFile.Folder,
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

        return super(GetProjectsAndFilesFromCentralFtp, self).checkParameterValues(parameters, context)

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        output = {
            self.OUTPUT_STATUS: 0,
            self.OUTPUT_STRING: ''
        }
        # Check internet
        feedback.pushInfo(tr('CHECK INTERNET CONNECTION'))
        if not check_internet():
            m = tr('No internet connection')
            return returnError(output, m, feedback)

        # Parameters
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        connection_name_clone = parameters[self.CONNECTION_NAME_CLONE]
        ftphost = parameters[self.CENTRAL_FTP_HOST]
        ftplogin = parameters[self.CENTRAL_FTP_LOGIN]
        ftpport = parameters[self.CENTRAL_FTP_PORT]
        ftppass = ''
        ftpdir = parameters[self.CENTRAL_FTP_REMOTE_DIR]
        localdir = parameters[self.CLONE_QGIS_PROJECT_FOLDER]

        # Check FTP password
        try:
            auth = netrc.netrc().authenticators(ftphost)
            if auth is not None:
                ftplogin, account, ftppass = auth
        except (netrc.NetrcParseError, IOError):
            m = tr('Could not retrieve password from ~/.netrc file')
            return returnError(output, m, feedback)
        if not ftppass:
            m = tr('Could not retrieve password from ~/.netrc file or is empty')
            return returnError(output, m, feedback)

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

        # Remove existing QGIS project files with subprocess to avoid a nasty bug
        # in Userland context
        if os.path.isdir('/storage/internal/geopoppy') and psys().lower().startswith('linux'):
            cmd = [
                'rm',
                '-v',
                '{}/*.qgs'.format(
                    os.path.abspath(localdir)
                )
            ]
            feedback.pushInfo(tr('USELAND CONTEXT: Remove old QGIS project files to avoid bug'))
            feedback.pushInfo(" ".join(cmd))
            myenv = { **os.environ }
            run_command(cmd, myenv, feedback)

        import time
        time.sleep(1)

        # Run FTP sync
        feedback.pushInfo(tr('Local directory') + ' %s' % localdir)
        feedback.pushInfo(tr('FTP directory') + ' %s' % ftpdir)
        excludedirs = parameters[self.FTP_EXCLUDE_REMOTE_SUBDIRS].strip()
        direction = 'from' # we get data FROM FTP
        print("LOCAL DIR = %s" % localdir)
        print("FTP   DIR = %s" % ftpdir)

        ok, msg = ftp_sync(ftphost, ftpport, ftplogin, localdir, ftpdir, direction, excludedirs, feedback)
        if not ok:
            m = msg
            return returnError(output, m, feedback)

        # Adapt QGIS project to Geopoppy
        # Mainly change database connection parameters (central -> clone)
        feedback.pushInfo(tr('ADAPT QGIS PROJECTS FOR OFFLINE USE'))
        ok, msg = setQgisProjectOffline(localdir, connection_name_central, connection_name_clone, feedback)
        if not ok:
            m = msg
            return returnError(output, m, feedback)

        status = 1
        msg = tr("QGIS projects and file successfully synchronized from the central FTP server")
        output = {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }
        return output

