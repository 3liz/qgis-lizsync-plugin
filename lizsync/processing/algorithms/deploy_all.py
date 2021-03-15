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
import tempfile
from platform import system as psys

from qgis.core import (
    Qgis,
    QgsProcessingParameterEnum,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFile,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber,
    QgsProcessingParameterDefinition
)
if Qgis.QGIS_VERSION_INT >= 31400:
    from qgis.core import QgsProcessingParameterProviderConnection

import processing

from .tools import (
    checkFtpBinary,
    check_paramiko,
    lizsyncConfig,
    getUriFromConnectionName,
)

from ...qgis_plugin_tools.tools.i18n import tr
from ...qgis_plugin_tools.tools.algorithm_processing import BaseProcessingAlgorithm
from ...qgis_plugin_tools.tools.resources import plugin_path


class DeployAll(BaseProcessingAlgorithm):
    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    CONNECTION_NAME_CLONE = 'CONNECTION_NAME_CLONE'

    POSTGRESQL_BINARY_PATH = 'POSTGRESQL_BINARY_PATH'
    LOCAL_QGIS_PROJECT_FOLDER = 'LOCAL_QGIS_PROJECT_FOLDER'
    RECREATE_CLONE_SERVER_ID = 'RECREATE_CLONE_SERVER_ID'
    ZIP_FILE = 'ZIP_FILE'

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
        return 'deploy_all'

    def displayName(self):
        return tr('Deploy project and data to a clone')

    def group(self):
        return tr('04 All-in-one')

    def groupId(self):
        return 'lizsync_all_in_one'

    def shortHelpString(self):
        short_help = tr(
            ' Send packaged QGIS projects, files and data to the clone'
            '\n'
            '\n'
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

        # Central database connection name
        connection_name_central = ls.variable('postgresql:central/name')
        label = tr('PostgreSQL connection to the central database')
        if Qgis.QGIS_VERSION_INT >= 31400:
            param = QgsProcessingParameterProviderConnection(
                self.CONNECTION_NAME_CENTRAL,
                label,
                "postgres",
                defaultValue=connection_name_central,
                optional=False,
            )
        else:
            param = QgsProcessingParameterString(
                self.CONNECTION_NAME_CENTRAL,
                label,
                defaultValue=connection_name_central,
                optional=False
            )
            param.setMetadata({
                'widget_wrapper': {
                    'class': 'processing.gui.wrappers_postgis.ConnectionWidgetWrapper'
                }
            })
        tooltip = tr(
            'The PostgreSQL connection to the central database.'
        )
        if Qgis.QGIS_VERSION_INT >= 31600:
            param.setHelp(tooltip)
        else:
            param.tooltip_3liz = tooltip
        self.addParameter(param)

        # Clone database connection parameters
        connection_name_clone = ls.variable('postgresql:clone/name')
        label = tr('PostgreSQL connection to the clone database')
        if Qgis.QGIS_VERSION_INT >= 31400:
            param = QgsProcessingParameterProviderConnection(
                self.CONNECTION_NAME_CLONE,
                label,
                "postgres",
                defaultValue=connection_name_clone,
                optional=False,
            )
        else:
            param = QgsProcessingParameterString(
                self.CONNECTION_NAME_CLONE,
                label,
                defaultValue=connection_name_clone,
                optional=False
            )
            param.setMetadata({
                'widget_wrapper': {
                    'class': 'processing.gui.wrappers_postgis.ConnectionWidgetWrapper'
                }
            })
        tooltip = tr(
            'The PostgreSQL connection to the clone database.'
        )
        if Qgis.QGIS_VERSION_INT >= 31600:
            param.setHelp(tooltip)
        else:
            param.tooltip_3liz = tooltip
        self.addParameter(param)

        # PostgreSQL binary path (with psql, pg_dump, pg_restore)
        postgresql_binary_path = ls.variable('binaries/postgresql')
        param = QgsProcessingParameterFile(
            self.POSTGRESQL_BINARY_PATH,
            tr('PostgreSQL binary path'),
            defaultValue=postgresql_binary_path,
            behavior=QgsProcessingParameterFile.Folder,
            optional=False
        )
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)

        # Local directory containing the files to send to the clone by FTP
        local_qgis_project_folder = ls.variable('local/qgis_project_folder')
        param =QgsProcessingParameterFile(
            self.LOCAL_QGIS_PROJECT_FOLDER,
            tr('Local desktop QGIS project folder'),
            defaultValue=local_qgis_project_folder,
            behavior=QgsProcessingParameterFile.Folder,
            optional=False
        )
        self.addParameter(param)

        # Database ZIP archive file
        database_archive_file = ls.variable('general/database_archive_file')
        if not database_archive_file:
            database_archive_file = os.path.join(
                tempfile.gettempdir(),
                'central_database_package.zip'
            )
        param = QgsProcessingParameterFile(
            self.ZIP_FILE,
            tr('Database ZIP archive path'),
            defaultValue=database_archive_file,
            behavior=QgsProcessingParameterFile.File,
            optional=True,
            extension='zip'
        )
        self.addParameter(param)

        # Recreate clone server id
        param = QgsProcessingParameterBoolean(
            self.RECREATE_CLONE_SERVER_ID,
            tr('Recreate clone server id. Do it only to fully reset the clone ID !'),
            defaultValue=False,
            optional=False
        )
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)

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
        param = QgsProcessingParameterEnum(
            self.CLONE_FTP_PROTOCOL,
            tr('Clone (S)FTP protocol'),
            options=self.CLONE_FTP_PROTOCOLS,
            defaultValue=0,
            optional=False,
        )
        self.addParameter(param)

        # host
        clone_ftp_host = ls.variable('ftp:clone/host')
        param = QgsProcessingParameterString(
            self.CLONE_FTP_HOST,
            tr('Clone FTP Server host'),
            defaultValue=clone_ftp_host,
            optional=False
        )
        self.addParameter(param)

        # port
        clone_ftp_port = ls.variable('ftp:clone/port')
        param = QgsProcessingParameterNumber(
            self.CLONE_FTP_PORT,
            tr('Clone FTP Server port'),
            defaultValue=clone_ftp_port,
            optional=False
        )
        self.addParameter(param)

        # login
        clone_ftp_login = ls.variable('ftp:clone/user')
        param = QgsProcessingParameterString(
            self.CLONE_FTP_LOGIN,
            tr('Clone FTP Server login'),
            defaultValue=clone_ftp_login,
            optional=False
        )
        self.addParameter(param)

        # password
        param = QgsProcessingParameterString(
            self.CLONE_FTP_PASSWORD,
            tr('Clone FTP Server password'),
            optional=True
        )
        self.addParameter(param)

        # remote directory
        clone_ftp_remote_dir = ls.variable('ftp:clone/remote_directory')
        param = QgsProcessingParameterString(
            self.CLONE_FTP_REMOTE_DIR,
            tr('Clone FTP Server remote directory'),
            defaultValue=clone_ftp_remote_dir,
            optional=False
        )
        self.addParameter(param)

        # Exclude some directories from sync
        excluded_directories = ls.variable('local/excluded_directories')
        if not excluded_directories:
            excluded_directories = 'data'
        param = QgsProcessingParameterString(
            self.FTP_EXCLUDE_REMOTE_SUBDIRS,
            tr('List of sub-directory to exclude from synchro, separated by commas.'),
            defaultValue=excluded_directories,
            optional=True
        )
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(param)

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

        # Check postgresql binary path
        postgresql_binary_path = parameters[self.POSTGRESQL_BINARY_PATH]
        test_bin = 'psql'
        if psys().lower().startswith('win'):
            test_bin += '.exe'
        has_bin_file = os.path.isfile(
            os.path.join(
                postgresql_binary_path,
                test_bin
            )
        )
        if not has_bin_file:
            return False, tr('The needed PostgreSQL binaries cannot be found in the specified path')

        # Check zip archive path
        database_archive_file = self.parameterAsString(parameters, self.ZIP_FILE, context)
        if not os.path.exists(database_archive_file):
            database_archive_file = os.path.join(
                tempfile.gettempdir(),
                'central_database_package.zip'
            )
        ok = os.path.exists(database_archive_file)
        if not ok:
            return False, tr("The ZIP archive does not exists in the specified path") + ": {0}".format(database_archive_file)
        parameters[self.ZIP_FILE] = database_archive_file

        # Check connections
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        connection_name_clone = parameters[self.CONNECTION_NAME_CLONE]
        ok, uri, msg = getUriFromConnectionName(connection_name_central, True)
        if not ok:
            return False, msg
        ok, uri, msg = getUriFromConnectionName(connection_name_clone, True)
        if not ok:
            return False, msg

        return super(DeployAll, self).checkParameterValues(parameters, context)

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

        # Deploy database server package
        params = {
            'CONNECTION_NAME_CENTRAL': parameters[self.CONNECTION_NAME_CENTRAL],
            'CONNECTION_NAME_CLONE': parameters[self.CONNECTION_NAME_CLONE],
            'POSTGRESQL_BINARY_PATH': parameters[self.POSTGRESQL_BINARY_PATH],
            'ZIP_FILE': parameters[self.ZIP_FILE],
            'RECREATE_CLONE_SERVER_ID': parameters[self.RECREATE_CLONE_SERVER_ID],
        }
        processing.run(
            "lizsync:deploy_database_server_package",
            params, context=context, feedback=feedback,
            is_child_algorithm=True
        )
        # Check for cancelation
        if feedback.isCanceled():
            return {}

        # Check paramiko is installed if needed
        protocol = self.CLONE_FTP_PROTOCOLS[parameters[self.CLONE_FTP_PROTOCOL]]
        if protocol == 'SFTP' and not check_paramiko():
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
            feedback.reportError(msg)

        # Send projects and files to clone FTP
        params = {
            'LOCAL_QGIS_PROJECT_FOLDER': parameters[self.LOCAL_QGIS_PROJECT_FOLDER],
            'CLONE_FTP_PROTOCOL': parameters[self.CLONE_FTP_PROTOCOL],
            'CLONE_FTP_HOST': parameters[self.CLONE_FTP_HOST],
            'CLONE_FTP_PORT': parameters[self.CLONE_FTP_PORT],
            'CLONE_FTP_LOGIN': parameters[self.CLONE_FTP_LOGIN],
            'CLONE_FTP_PASSWORD': parameters[self.CLONE_FTP_PASSWORD],
            'CLONE_FTP_REMOTE_DIR': parameters[self.CLONE_FTP_REMOTE_DIR],
            'FTP_EXCLUDE_REMOTE_SUBDIRS': parameters[self.FTP_EXCLUDE_REMOTE_SUBDIRS],
        }
        processing.run(
            "lizsync:send_projects_and_files_to_clone_ftp",
            params, context=context, feedback=feedback,
            is_child_algorithm=True
        )
        # Check for cancelation
        if feedback.isCanceled():
            return {}

        # Log
        msg = tr(
            'Every steps needed to deploy QGIS project and data'
            'have been successfully executed.'
        )
        feedback.pushInfo(
            msg
        )
        output = {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: msg
        }
        return output
