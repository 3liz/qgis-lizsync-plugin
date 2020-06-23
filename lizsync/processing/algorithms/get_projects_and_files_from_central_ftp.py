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

import os

from qgis.core import (
    QgsProcessingException,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFile,
    QgsProcessingParameterBoolean,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber
)

from ftplib import FTP
from .tools import (
    checkFtpBinary,
    check_ftp_connection,
    ftp_sync,
    get_ftp_password,
    lizsyncConfig,
    run_command,
    setQgisProjectOffline,
)
from platform import system as psys

from ...qgis_plugin_tools.tools.i18n import tr
from ...qgis_plugin_tools.tools.algorithm_processing import BaseProcessingAlgorithm


class GetProjectsAndFilesFromCentralFtp(BaseProcessingAlgorithm):
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
    CENTRAL_FTP_PASSWORD = 'CENTRAL_FTP_PASSWORD'
    CENTRAL_FTP_REMOTE_DIR = 'CENTRAL_FTP_REMOTE_DIR'
    REPLACE_DATASOURCE_IN_QGIS_PROJECT = 'REPLACE_DATASOURCE_IN_QGIS_PROJECT'
    CLONE_QGIS_PROJECT_FOLDER = 'CLONE_QGIS_PROJECT_FOLDER'

    FTP_EXCLUDE_REMOTE_SUBDIRS = 'FTP_EXCLUDE_REMOTE_SUBDIRS'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'get_projects_and_files_from_central_ftp'

    def displayName(self):
        return tr('Get projects and files from the central FTP server')

    def group(self):
        return tr('03 GeoPoppy file synchronization')

    def groupId(self):
        return 'lizsync_geopoppy_sync'

    def shortHelpString(self):
        short_help = tr(
            ' Get QGIS projects and files from the give FTP server and remote directory'
            ' and adapt QGIS projects for the local clone database'
            ' by replacing PostgreSQL connection data with the local PostgreSQL server data.'
            ' An internet connection is needed to use this algorithm'
        )
        return short_help

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

        # Central host connection parameters
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
        self.addParameter(
            QgsProcessingParameterString(
                self.CENTRAL_FTP_PASSWORD,
                tr('Central FTP Server password'),
                optional=True
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

        # Exlude some directories from sync
        excluded_directories = ls.variable('local/excluded_directories')
        if not excluded_directories:
            excluded_directories = 'data'
        self.addParameter(
            QgsProcessingParameterString(
                self.FTP_EXCLUDE_REMOTE_SUBDIRS,
                tr('List of sub-directory to exclude from synchro, separated by commas.'),
                defaultValue=excluded_directories,
                optional=True
            )
        )

        # Target folder
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

        # Adapt project for Geopoppy
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.REPLACE_DATASOURCE_IN_QGIS_PROJECT,
                tr('Adapt PostgreSQL connection parameters for GeoPoppy database ?'),
                defaultValue=True,
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

        # Parameters
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        ftphost = parameters[self.CENTRAL_FTP_HOST]
        ftplogin = parameters[self.CENTRAL_FTP_LOGIN]
        ftppassword = parameters[self.CENTRAL_FTP_PASSWORD].strip()
        ftpport = parameters[self.CENTRAL_FTP_PORT]
        ftpdir = parameters[self.CENTRAL_FTP_REMOTE_DIR]
        localdir = parameters[self.CLONE_QGIS_PROJECT_FOLDER]
        adapt_qgis_projects = self.parameterAsBool(
            parameters,
            self.REPLACE_DATASOURCE_IN_QGIS_PROJECT,
            context
        )
        # store parameters
        ls = lizsyncConfig()
        ls.setVariable('postgresql:central/name', connection_name_central)
        ls.setVariable('ftp:central/host', ftphost)
        ls.setVariable('ftp:central/port', ftpport)
        ls.setVariable('ftp:central/user', ftplogin)
        ls.setVariable('ftp:central/password', ftppassword)
        ls.setVariable('ftp:central/remote_directory', ftpdir)
        ls.setVariable('clone/qgis_project_folder', localdir)
        ls.save()

        # Check localdir
        feedback.pushInfo(tr('CHECK LOCAL PROJECT DIRECTORY'))
        if not localdir or not os.path.isdir(localdir):
            m = tr('QGIS project local directory not found')
            raise QgsProcessingException(m)
        else:
            m = tr('QGIS project local directory ok')
            feedback.pushInfo(m)

        # Check ftp
        if not ftppassword:
            ok, password, msg = get_ftp_password(ftphost, ftpport, ftplogin)
            if not ok:
                raise QgsProcessingException(msg)
        else:
            password = ftppassword
        ok, msg = check_ftp_connection(ftphost, ftpport, ftplogin, password)
        if not ok:
            raise QgsProcessingException(msg)

        # Check if ftpdir exists
        ok = True
        feedback.pushInfo(tr('CHECK REMOTE DIRECTORY') + ' %s' % ftpdir)
        ftp = FTP()
        ftp.connect(ftphost, ftpport)
        ftp.login(ftplogin, password)
        try:
            ftp.cwd(ftpdir)
            # do the code for successfull cd
            m = tr('Remote directory exists in the central server')
        except Exception:
            ok = False
            m = tr('Remote directory does not exist')
        finally:
            ftp.close()
        if not ok:
            raise QgsProcessingException(m)

        # Remove existing QGIS project files with subprocess to avoid a nasty bug
        # in Userland context
        if os.path.isdir('/storage/internal/geopoppy') and psys().lower().startswith('linux'):
            cmd = [
                'rm',
                '-v',
                '{}/*.qgs*'.format(
                    os.path.abspath(localdir)
                )
            ]
            feedback.pushInfo(tr('USELAND CONTEXT: Remove old QGIS project files to avoid bug'))
            feedback.pushInfo(" ".join(cmd))
            myenv = {**os.environ}
            run_command(cmd, myenv, feedback)

        # import time
        # time.sleep(1)

        # Run FTP sync
        feedback.pushInfo(tr('Local directory') + ' %s' % localdir)
        feedback.pushInfo(tr('FTP directory') + ' %s' % ftpdir)
        excludedirs = parameters[self.FTP_EXCLUDE_REMOTE_SUBDIRS].strip()
        direction = 'from'  # we get data FROM FTP
        print("LOCAL DIR = %s" % localdir)
        print("FTP   DIR = %s" % ftpdir)

        ok, msg = ftp_sync(ftphost, ftpport, ftplogin, password, localdir, ftpdir, direction, excludedirs, feedback)
        if not ok:
            raise QgsProcessingException(msg)

        # Adapt QGIS project to Geopoppy
        # Mainly change database connection parameters (central -> clone)
        if adapt_qgis_projects:
            feedback.pushInfo(tr('ADAPT QGIS PROJECTS FOR OFFLINE USE'))
            ok, msg = setQgisProjectOffline(localdir, connection_name_central, feedback)
            if not ok:
                raise QgsProcessingException(msg)

        status = 1
        msg = tr("QGIS projects and file successfully synchronized from the central FTP server")
        output = {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }
        return output
