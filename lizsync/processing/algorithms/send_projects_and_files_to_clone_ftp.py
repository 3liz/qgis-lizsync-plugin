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
    QgsProcessingParameterDefinition,
    QgsProcessingParameterEnum,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFile,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber,
)

from .tools import (
    checkFtpBinary,
    check_ftp_connection,
    check_paramiko,
    check_ssh_connection,
    ftp_sync,
    get_ftp_password,
    lizsyncConfig,
)

from ...qgis_plugin_tools.tools.i18n import tr
from ...qgis_plugin_tools.tools.algorithm_processing import BaseProcessingAlgorithm
from ...qgis_plugin_tools.tools.resources import plugin_path


class SendProjectsAndFilesToCloneFtp(BaseProcessingAlgorithm):
    """
    Synchronize local data from remote FTP
    via LFTP
    """
    LOCAL_QGIS_PROJECT_FOLDER = 'LOCAL_QGIS_PROJECT_FOLDER'

    WINSCP_BINARY_PATH = 'WINSCP_BINARY_PATH'
    CLONE_FTP_PROTOCOL = 'CLONE_FTP_PROTOCOL'
    CLONE_FTP_HOST = 'CLONE_FTP_HOST'
    CLONE_FTP_PORT = 'CLONE_FTP_PORT'
    CLONE_FTP_LOGIN = 'CLONE_FTP_LOGIN'
    CLONE_FTP_PASSWORD = 'CLONE_FTP_PASSWORD'
    CLONE_FTP_REMOTE_DIR = 'CLONE_FTP_REMOTE_DIR'
    CLONE_QGIS_PROJECT_FOLDER = 'CLONE_QGIS_PROJECT_FOLDER'

    FTP_EXCLUDE_REMOTE_SUBDIRS = 'FTP_EXCLUDE_REMOTE_SUBDIRS'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'send_projects_and_files_to_clone_ftp'

    def displayName(self):
        return tr('Send local QGIS projects and files to the clone FTP server')

    def group(self):
        return tr('03 File synchronization')

    def groupId(self):
        return 'lizsync_file_sync'

    def shortHelpString(self):
        short_help = tr(
            ' Send QGIS projects and files to the clone FTP server remote directory.'
            '\n'
            '\n'
            ' This script can be used by the geomatician in charge of the deployment of data'
            ' to one or several clone(s).'
            '\n'
            '\n'
            ' It synchronizes the files from the given local QGIS project folder'
            ' to the clone remote folder by using the given FTP connexion.'
            ' This means all the files from the clone folder will be overwritten'
            ' by the files from the local QGIS project folder.'
            '\n'
            '\n'
            ' Beware ! This script does not adapt projects for the clone database'
            ' (no modification of the PostgreSQL connexion data inside the QGIS project files) !'
        )
        return short_help

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # LizSync config file from ini
        ls = lizsyncConfig()

        # INPUTS
        # Local directory containing the files to send to the clone by FTP
        local_qgis_project_folder = ls.variable('local/qgis_project_folder')
        self.addParameter(
            QgsProcessingParameterFile(
                self.LOCAL_QGIS_PROJECT_FOLDER,
                tr('Local desktop QGIS project folder'),
                defaultValue=local_qgis_project_folder,
                behavior=QgsProcessingParameterFile.Folder,
                optional=False
            )
        )

        # For Windows, WinSCP binary path
        winscp_binary_path = ls.variable('binaries/winscp')
        if not winscp_binary_path.strip():
            winscp_binary_path = plugin_path('install', 'WinSCP')
        param = QgsProcessingParameterFile(
            self.WINSCP_BINARY_PATH,
            tr('WinSCP binary path'),
            defaultValue=winscp_binary_path,
            behavior=QgsProcessingParameterFile.Folder,
            optional=True
        )
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)

        # Clone FTP connection parameters
        # method
        self.CLONE_FTP_PROTOCOLS = ['SFTP', 'FTP']
        self.addParameter(
            QgsProcessingParameterEnum(
                self.CLONE_FTP_PROTOCOL,
                tr('Clone (S)FTP protocol'),
                options=self.CLONE_FTP_PROTOCOLS,
                defaultValue=0,
                optional=False,
            )
        )
        # host
        clone_ftp_host = ls.variable('ftp:clone/host')
        self.addParameter(
            QgsProcessingParameterString(
                self.CLONE_FTP_HOST,
                tr('Clone FTP Server host'),
                defaultValue=clone_ftp_host,
                optional=False
            )
        )
        # port
        clone_ftp_port = ls.variable('ftp:clone/port')
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CLONE_FTP_PORT,
                tr('Clone FTP Server port'),
                defaultValue=clone_ftp_port,
                optional=False
            )
        )
        # login
        clone_ftp_login = ls.variable('ftp:clone/user')
        self.addParameter(
            QgsProcessingParameterString(
                self.CLONE_FTP_LOGIN,
                tr('Clone FTP Server login'),
                defaultValue=clone_ftp_login,
                optional=False
            )
        )
        # password
        self.addParameter(
            QgsProcessingParameterString(
                self.CLONE_FTP_PASSWORD,
                tr('Clone FTP Server password'),
                optional=True
            )
        )
        # remote directory
        clone_ftp_remote_dir = ls.variable('ftp:clone/remote_directory')
        self.addParameter(
            QgsProcessingParameterString(
                self.CLONE_FTP_REMOTE_DIR,
                tr('Clone FTP Server remote directory'),
                defaultValue=clone_ftp_remote_dir,
                optional=False
            )
        )

        # Exclude some directories from sync
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

        return super(SendProjectsAndFilesToCloneFtp, self).checkParameterValues(parameters, context)

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

        # Parameters
        winscp_binary_path = parameters[self.WINSCP_BINARY_PATH]
        ftpprotocol = self.CLONE_FTP_PROTOCOLS[parameters[self.CLONE_FTP_PROTOCOL]]
        ftphost = parameters[self.CLONE_FTP_HOST]
        ftpport = parameters[self.CLONE_FTP_PORT]
        ftplogin = parameters[self.CLONE_FTP_LOGIN]
        ftppassword = parameters[self.CLONE_FTP_PASSWORD].strip()
        ftpdir = parameters[self.CLONE_FTP_REMOTE_DIR]
        localdir = parameters[self.LOCAL_QGIS_PROJECT_FOLDER]
        excluded_directories = parameters[self.FTP_EXCLUDE_REMOTE_SUBDIRS].strip()

        # store parameters
        ls = lizsyncConfig()
        ls.setVariable('binaries/winscp', winscp_binary_path)
        ls.setVariable('ftp:clone/protocol', ftpprotocol)
        ls.setVariable('ftp:clone/host', ftphost)
        ls.setVariable('ftp:clone/port', ftpport)
        ls.setVariable('ftp:clone/user', ftplogin)
        ls.setVariable('ftp:clone/password', ftppassword)
        ls.setVariable('ftp:clone/remote_directory', ftpdir)
        ls.setVariable('local/qgis_project_folder', localdir)
        ls.setVariable('local/excluded_directories', excluded_directories)
        ls.save()

        # Check localdir
        feedback.pushInfo(tr('CHECK LOCAL PROJECT DIRECTORY'))
        if not localdir or not os.path.isdir(localdir):
            m = tr('QGIS project local directory not found')
            raise QgsProcessingException(m)
        else:
            m = tr('QGIS project local directory ok')
            feedback.pushInfo(m)

        # Check password is given or found in files
        if not ftppassword:
            ok, password, msg = get_ftp_password(ftphost, ftpport, ftplogin)
            if not ok:
                raise QgsProcessingException(msg)
        else:
            password = ftppassword

        # Check connection is possible
        timeout = 5
        ftpdir_exists = False
        if ftpprotocol == 'ftp':
            ok, msg, ftpdir_exists = check_ftp_connection(
                ftphost, ftpport, ftplogin, password, timeout, ftpdir
            )
            if not ok:
                raise QgsProcessingException(msg)
        else:
            if not check_paramiko():
                msg = tr(
                    'The Python module paramiko is not installed. '
                    'The SSH connection will not be tested before running the synchronisation. '
                    'You can install it by running the following commands '
                    'in the Osgeo4w shell, as administrator: '
                    '\n'
                    'py3_env'
                    '\n'
                    'python -m pip install --upgrade pip'
                    '\n'
                    'python -m pip install paramiko'
                )
                # Let this error be silent
                ftpdir_exists = True
                feedback.pushInfo(msg, False)
            else:
                msg = tr('Check SSH connection is possible...')
                feedback.pushInfo(msg)
                ok, msg, ftpdir_exists = check_ssh_connection(
                    ftphost, ftpport, ftplogin, password, timeout, ftpdir
                )
                if not ok:
                    raise QgsProcessingException(msg)

        # Check if ftpdir exists
        feedback.pushInfo(tr('CHECK REMOTE DIRECTORY') + ' %s' % ftpdir)
        if not ftpdir_exists:
            msg = tr('Remote directory does not exist')
            raise QgsProcessingException(msg)
        else:
            feedback.pushInfo(tr('Remote directory exists in the server'))

        # Run FTP sync
        feedback.pushInfo(tr('Local directory') + ' %s' % localdir)
        feedback.pushInfo(tr('FTP directory') + ' %s' % ftpdir)
        direction = 'to'  # we send data TO FTP
        ok, msg = ftp_sync(
            ftpprotocol.lower(),
            ftphost, ftpport, ftplogin, password,
            localdir, ftpdir, direction,
            excluded_directories, feedback
        )
        if not ok:
            raise QgsProcessingException(msg)

        status = 1
        msg = tr("Synchronization successfull")
        output = {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }
        return output
