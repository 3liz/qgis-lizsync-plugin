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
__date__ = '2019-02-15'
__copyright__ = '(C) 2019 by 3liz'

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = '$Format:%H$'

from PyQt5.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber
)
from .tools import *
from processing.tools import postgis
import os, tempfile

from ...qgis_plugin_tools.tools.i18n import tr

class ConfigurePlugin(QgsProcessingAlgorithm):
    """

    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    POSTGRESQL_BINARY_PATH = 'POSTGRESQL_BINARY_PATH'
    WINSCP_BINARY_PATH = 'WINSCP_BINARY_PATH'

    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    SCHEMAS = 'SCHEMAS'
    CENTRAL_FTP_HOST = 'CENTRAL_FTP_HOST'
    CENTRAL_FTP_PORT = 'CENTRAL_FTP_PORT'
    CENTRAL_FTP_LOGIN = 'CENTRAL_FTP_LOGIN'
    CENTRAL_FTP_PASSWORD = 'CENTRAL_FTP_PASSWORD'
    CENTRAL_FTP_REMOTE_DIR = 'CENTRAL_FTP_REMOTE_DIR'
    LOCAL_QGIS_PROJECT_FOLDER = 'LOCAL_QGIS_PROJECT_FOLDER'

    CONNECTION_NAME_CLONE = 'CONNECTION_NAME_CLONE'
    CLONE_FTP_HOST = 'CLONE_FTP_HOST'
    CLONE_FTP_PORT = 'CLONE_FTP_PORT'
    CLONE_FTP_LOGIN = 'CLONE_FTP_LOGIN'
    CLONE_FTP_PASSWORD = 'CLONE_FTP_PASSWORD'
    CLONE_FTP_REMOTE_DIR = 'CLONE_FTP_REMOTE_DIR'
    CLONE_QGIS_PROJECT_FOLDER = 'CLONE_QGIS_PROJECT_FOLDER'

    ZIP_FILE = 'ZIP_FILE'
    ADDITIONNAL_SQL_FILE = 'ADDITIONNAL_SQL_FILE'
    EXCLUDED_COLUMNS = 'EXCLUDED_COLUMNS'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'configure_plugin'

    def displayName(self):
        return tr('Configure Lizsync plugin')

    def group(self):
        return tr('01 Installation')

    def groupId(self):
        return 'lizsync_installation'

    def shortHelpString(self):
        short_help = tr(
            ' Configure the LizSync plugin'
            '\n'
            '\n'
            ' You must run this script before any other script.'
            '\n'
            ' Every parameter will be used in the other algorithms, as default values for parameters.'
        )
        return short_help

    def createInstance(self):
        return ConfigurePlugin()

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # LizSync config file from ini
        ls = lizsyncConfig()

        # INPUTS
        postgresql_binary_path = ls.variable('binaries/postgresql')
        self.addParameter(
            QgsProcessingParameterFile(
                self.POSTGRESQL_BINARY_PATH,
                tr('PostgreSQL binary path'),
                defaultValue=postgresql_binary_path,
                behavior=QgsProcessingParameterFile.Folder,
                optional=False
            )
        )

        winscp_binary_path = ls.variable('binaries/winscp')
        if not winscp_binary_path.strip():
            winscp_binary_path = plugin_path('install', 'WinSCP')
        self.addParameter(
            QgsProcessingParameterFile(
                self.WINSCP_BINARY_PATH,
                tr('WinSCP binary path (Windows only)'),
                defaultValue=winscp_binary_path,
                behavior=QgsProcessingParameterFile.Folder,
                optional=True
            )
        )

        # Central database connection parameters
        connection_name_central = ls.variable('postgresql:central/name')
        db_param_a = QgsProcessingParameterString(
            self.CONNECTION_NAME_CENTRAL,
            tr('PostgreSQL connection to the CENTRAL database'),
            defaultValue=connection_name_central,
            optional=False
        )
        db_param_a.setMetadata({
            'widget_wrapper': {
                'class': 'processing.gui.wrappers_postgis.ConnectionWidgetWrapper'
            }
        })
        self.addParameter(db_param_a)

        # List of schemas to package
        postgresql_schemas = ls.variable('postgresql:central/schemas')
        if not postgresql_schemas:
            postgresql_schemas='test'
        self.addParameter(
            QgsProcessingParameterString(
                self.SCHEMAS,
                tr('List of schemas to package, separated by commas. (schemas public, lizsync & audit are never processed)'),
                defaultValue=postgresql_schemas,
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
        if not central_ftp_port:
            central_ftp_port = 21
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
        central_ftp_password = ls.variable('ftp:central/password')
        self.addParameter(
            QgsProcessingParameterString(
                self.CENTRAL_FTP_PASSWORD,
                tr('Central FTP Server password'),
                defaultValue=central_ftp_password,
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

        # Clone database connection parameters
        connection_name_clone = ls.variable('postgresql:clone/name')
        db_param_b = QgsProcessingParameterString(
            self.CONNECTION_NAME_CLONE,
            tr('PostgreSQL connection to the CLONE database'),
            defaultValue=connection_name_clone,
            optional=False
        )
        db_param_b.setMetadata({
            'widget_wrapper': {
                'class': 'processing.gui.wrappers_postgis.ConnectionWidgetWrapper'
            }
        })
        self.addParameter(db_param_b)

        clone_ftp_host = ls.variable('ftp:clone/host')
        self.addParameter(
            QgsProcessingParameterString(
                self.CLONE_FTP_HOST,
                tr('Clone FTP Server host'),
                defaultValue=clone_ftp_host,
                optional=False
            )
        )
        clone_ftp_port = ls.variable('ftp:clone/port')
        if not clone_ftp_port:
            clone_ftp_port = 21
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CLONE_FTP_PORT,
                tr('Clone FTP Server port'),
                defaultValue=clone_ftp_port,
                optional=False
            )
        )
        clone_ftp_login = ls.variable('ftp:clone/user')
        self.addParameter(
            QgsProcessingParameterString(
                self.CLONE_FTP_LOGIN,
                tr('Clone FTP Server login'),
                defaultValue=clone_ftp_login,
                optional=False
            )
        )
        clone_ftp_password = ls.variable('ftp:clone/password')
        self.addParameter(
            QgsProcessingParameterString(
                self.CLONE_FTP_PASSWORD,
                tr('Clone FTP Server password'),
                defaultValue=clone_ftp_password,
                optional=True
            )
        )
        clone_ftp_remote_dir = ls.variable('ftp:clone/remote_directory')
        self.addParameter(
            QgsProcessingParameterString(
                self.CLONE_FTP_REMOTE_DIR,
                tr('Clone FTP Server remote directory'),
                defaultValue=clone_ftp_remote_dir,
                optional=False
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

        # Additionnal SQL file to run on the clone
        additionnal_sql_file = ls.variable('general/additionnal_sql_file')
        # Userland context
        if os.path.isdir('/storage/internal/geopoppy') and psys().lower().startswith('linux'):
            self.addParameter(
                QgsProcessingParameterString(
                    self.ADDITIONNAL_SQL_FILE,
                    tr('Additionnal SQL file to run in the clone after the ZIP deployement'),
                    defaultValue=additionnal_sql_file,
                    optional=True
                )
            )
        else:
            self.addParameter(
                QgsProcessingParameterFile(
                    self.ADDITIONNAL_SQL_FILE,
                    tr('Additionnal SQL file to run in the clone after the ZIP deployement'),
                    defaultValue=additionnal_sql_file,
                    behavior=QgsProcessingParameterFile.File,
                    optional=True,
                    extension='sql'
                )
            )

        database_archive_file = ls.variable('general/database_archive_file')
        if not database_archive_file:
            database_archive_file = os.path.join(
                tempfile.gettempdir(),
                'central_database_package.zip'
            )
        # Useland context: use only string
        if os.path.isdir('/storage/internal/geopoppy') and psys().lower().startswith('linux'):
            self.addParameter(
                QgsProcessingParameterString(
                    self.ZIP_FILE,
                    tr('Database ZIP archive default path'),
                    optional=False,
                    defaultValue=database_archive_file
                )
            )
        else:
            self.addParameter(
                QgsProcessingParameterFileDestination(
                    self.ZIP_FILE,
                    tr('Database ZIP archive default path'),
                    fileFilter='zip',
                    optional=False,
                    defaultValue=database_archive_file
                )
            )

        excluded_columns = ls.variable('general/excluded_columns')
        self.addParameter(
            QgsProcessingParameterString(
                self.EXCLUDED_COLUMNS,
                tr('Excluded columns: list of columns that will never be synchronized'),
                optional=True,
                defaultValue=excluded_columns
            )
        )

        # OUTPUTS
        # Add output for status (integer)
        self.addOutput(
            QgsProcessingOutputNumber(
                self.OUTPUT_STATUS,
                tr('Output status')
            )
        )
        # Add output for message
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING,
                tr('Output message')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        winscp_binary_path = parameters[self.WINSCP_BINARY_PATH]
        postgresql_binary_path = parameters[self.POSTGRESQL_BINARY_PATH]

        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        postgresql_schemas = parameters[self.SCHEMAS]
        ftp_central_host = parameters[self.CENTRAL_FTP_HOST]
        ftp_central_port = parameters[self.CENTRAL_FTP_PORT]
        ftp_central_user = parameters[self.CENTRAL_FTP_LOGIN]
        ftp_central_password = parameters[self.CENTRAL_FTP_PASSWORD]
        ftp_central_remote_directory = parameters[self.CENTRAL_FTP_REMOTE_DIR]
        local_qgis_project_folder = parameters[self.LOCAL_QGIS_PROJECT_FOLDER]

        connection_name_clone = parameters[self.CONNECTION_NAME_CLONE]
        ftp_clone_host = parameters[self.CLONE_FTP_HOST]
        ftp_clone_port = parameters[self.CLONE_FTP_PORT]
        ftp_clone_user = parameters[self.CLONE_FTP_LOGIN]
        ftp_clone_password = parameters[self.CLONE_FTP_PASSWORD]
        ftp_clone_remote_directory = parameters[self.CLONE_FTP_REMOTE_DIR]
        clone_qgis_project_folder = parameters[self.CLONE_QGIS_PROJECT_FOLDER]

        database_archive_file = self.parameterAsString(
            parameters,
            self.ZIP_FILE,
            context
        )
        additionnal_sql_file = self.parameterAsString(
            parameters,
            self.ADDITIONNAL_SQL_FILE,
            context
        )
        excluded_columns = parameters[self.EXCLUDED_COLUMNS].strip()

        # LizSync config file from ini
        ls = lizsyncConfig()

        # Set global variable
        ls.setVariable('binaries/postgresql', postgresql_binary_path)
        feedback.pushInfo(tr('PostgreSQL local binary path') + ' = ' + postgresql_binary_path)
        ls.setVariable('binaries/winscp', winscp_binary_path)
        feedback.pushInfo(tr('WinSCP binary path (Windows only)') + ' = ' + winscp_binary_path)

        ls.setVariable('postgresql:central/name', connection_name_central)
        feedback.pushInfo(tr('PostgreSQL connection to central database') + ' = ' + connection_name_central)

        ls.setVariable('postgresql:central/schemas', postgresql_schemas)
        feedback.pushInfo(tr('List of schemas to package, separated by commas. (schemas public, lizsync & audit are never processed)') + ' = ' + postgresql_schemas)

        ls.setVariable('ftp:central/host', ftp_central_host)
        feedback.pushInfo(tr('Central FTP Server host') + ' = ' + ftp_central_host)

        ls.setVariable('ftp:central/port', ftp_central_port)
        feedback.pushInfo(tr('Central FTP Server port') + ' = %s' % ftp_central_port)

        ls.setVariable('ftp:central/user', ftp_central_user)
        feedback.pushInfo(tr('Central FTP Server login') + ' = ' + ftp_central_user)

        ls.setVariable('ftp:central/password', ftp_central_password)
        feedback.pushInfo(tr('Central FTP Server password') + ' = ' + ftp_central_password)

        ls.setVariable('ftp:central/remote_directory', ftp_central_remote_directory)
        feedback.pushInfo(tr('Central FTP Server remote directory') + ' = ' + ftp_central_remote_directory)


        ls.setVariable('postgresql:clone/name', connection_name_clone)
        feedback.pushInfo(tr('PostgreSQL connection to local clone database') + ' = ' + connection_name_clone)

        ls.setVariable('ftp:clone/host', ftp_clone_host)
        feedback.pushInfo(tr('Clone FTP Server host') + ' = ' + ftp_clone_host)

        ls.setVariable('ftp:clone/port', ftp_clone_port)
        feedback.pushInfo(tr('clone FTP Server port') + ' = %s' % ftp_clone_port)

        ls.setVariable('ftp:clone/user', ftp_clone_user)
        feedback.pushInfo(tr('Clone FTP Server login') + ' = ' + ftp_clone_user)

        ls.setVariable('ftp:clone/password', ftp_clone_password)
        feedback.pushInfo(tr('Clone FTP Server login') + ' = ' + ftp_clone_password)

        ls.setVariable('ftp:clone/remote_directory', ftp_clone_remote_directory)
        feedback.pushInfo(tr('Clone FTP Server remote directory') + ' = ' + ftp_clone_remote_directory)

        ls.setVariable('local/qgis_project_folder', local_qgis_project_folder)
        feedback.pushInfo(tr('Local Desktop QGIS project folder') + ' = ' + local_qgis_project_folder)

        ls.setVariable('clone/qgis_project_folder', clone_qgis_project_folder)
        feedback.pushInfo(tr('Clone QGIS project folder') + ' = ' + clone_qgis_project_folder)

        ls.setVariable('general/additionnal_sql_file', additionnal_sql_file)
        feedback.pushInfo(tr('Additionnal SQL file to run in the clone after the ZIP deployement') + ' = ' + additionnal_sql_file)

        ls.setVariable('general/database_archive_file', database_archive_file)
        feedback.pushInfo(tr('Database ZIP archive default path') + ' = ' + database_archive_file)

        ls.setVariable('general/excluded_columns', excluded_columns)
        feedback.pushInfo(tr('Excluded columns: list of columns that will never be synchronized') + ' = ' + excluded_columns)

        ls.save()

        msg = tr('Configuration has been saved')
        feedback.pushInfo(msg)
        status = 1

        return {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }
