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
    QgsProcessingOutputString,
    QgsProcessingOutputNumber,
    QgsExpressionContextUtils
)
from .tools import *
from processing.tools import postgis

class ConfigurePlugin(QgsProcessingAlgorithm):
    """

    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    POSTGRESQL_BINARY_PATH = 'POSTGRESQL_BINARY_PATH'
    WINSCP_BINARY_PATH = 'WINSCP_BINARY_PATH'

    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    CENTRAL_FTP_HOST = 'CENTRAL_FTP_HOST'
    CENTRAL_FTP_PORT = 'CENTRAL_FTP_PORT'
    CENTRAL_FTP_LOGIN = 'CENTRAL_FTP_LOGIN'
    CENTRAL_FTP_REMOTE_DIR = 'CENTRAL_FTP_REMOTE_DIR'
    LOCAL_QGIS_PROJECT_FOLDER = 'LOCAL_QGIS_PROJECT_FOLDER'

    CONNECTION_NAME_CLONE = 'CONNECTION_NAME_CLONE'
    CLONE_FTP_HOST = 'CLONE_FTP_HOST'
    CLONE_FTP_PORT = 'CLONE_FTP_PORT'
    CLONE_FTP_LOGIN = 'CLONE_FTP_LOGIN'
    CLONE_FTP_REMOTE_DIR = 'CLONE_FTP_REMOTE_DIR'
    CLONE_QGIS_PROJECT_FOLDER = 'CLONE_QGIS_PROJECT_FOLDER'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'configure_plugin'

    def displayName(self):
        return self.tr('Configure Lizsync plugin')

    def group(self):
        return self.tr('01 Installation')

    def groupId(self):
        return 'lizsync_installation'

    def shortHelpString(self):
        short_help = (
            ' Configure the LizSync plugin'
            '<br>'
            '<br>'
            ' You must run this script before any other script.'
            '<br>'
            ' Every parameter will be used in the other algorithms, as default values for parameters.'
        )
        return short_help

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ConfigurePlugin()

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # INPUTS
        postgresql_binary_path = QgsExpressionContextUtils.globalScope().variable('lizsync_postgresql_binary_path')
        self.addParameter(
            QgsProcessingParameterFile(
                self.POSTGRESQL_BINARY_PATH,
                self.tr('PostgreSQL binary path'),
                defaultValue=postgresql_binary_path,
                behavior=QgsProcessingParameterFile.Folder,
                optional=False
            )
        )
        winscp_binary_path = QgsExpressionContextUtils.globalScope().variable('lizsync_winscp_binary_path')
        self.addParameter(
            QgsProcessingParameterFile(
                self.WINSCP_BINARY_PATH,
                self.tr('WinSCP binary path (Windows only)'),
                defaultValue=winscp_binary_path,
                behavior=QgsProcessingParameterFile.Folder,
                optional=True
            )
        )

        # Central database connection parameters
        connection_name_central = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_central')
        db_param_a = QgsProcessingParameterString(
            self.CONNECTION_NAME_CENTRAL,
            self.tr('PostgreSQL connection to the CENTRAL database'),
            defaultValue=connection_name_central,
            optional=False
        )
        db_param_a.setMetadata({
            'widget_wrapper': {
                'class': 'processing.gui.wrappers_postgis.ConnectionWidgetWrapper'
            }
        })
        self.addParameter(db_param_a)

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
        if not central_ftp_port:
            central_ftp_port = 21
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

        # Clone database connection parameters
        connection_name_clone = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_clone')
        db_param_b = QgsProcessingParameterString(
            self.CONNECTION_NAME_CLONE,
            self.tr('PostgreSQL connection to the CLONE database'),
            defaultValue=connection_name_clone,
            optional=False
        )
        db_param_b.setMetadata({
            'widget_wrapper': {
                'class': 'processing.gui.wrappers_postgis.ConnectionWidgetWrapper'
            }
        })
        self.addParameter(db_param_b)

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
        if not clone_ftp_port:
            clone_ftp_port = 21
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

        clone_qgis_project_folder = QgsExpressionContextUtils.globalScope().variable('lizsync_clone_qgis_project_folder')
        self.addParameter(
            QgsProcessingParameterFile(
                self.CLONE_QGIS_PROJECT_FOLDER,
                self.tr('Clone QGIS project folder'),
                defaultValue=clone_qgis_project_folder,
                behavior=QgsProcessingParameterFile.Folder,
                optional=False
            )
        )

        # OUTPUTS
        # Add output for status (integer)
        self.addOutput(
            QgsProcessingOutputNumber(
                self.OUTPUT_STATUS,
                self.tr('Output status')
            )
        )
        # Add output for message
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING,
                self.tr('Output message')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        winscp_binary_path = parameters[self.WINSCP_BINARY_PATH]
        postgresql_binary_path = parameters[self.POSTGRESQL_BINARY_PATH]

        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        lizsync_central_ftp_host = parameters[self.CENTRAL_FTP_HOST]
        lizsync_central_ftp_port = parameters[self.CENTRAL_FTP_PORT]
        lizsync_central_ftp_login = parameters[self.CENTRAL_FTP_LOGIN]
        lizsync_central_ftp_remote_dir = parameters[self.CENTRAL_FTP_REMOTE_DIR]
        lizsync_local_qgis_project_folder = parameters[self.LOCAL_QGIS_PROJECT_FOLDER]

        connection_name_clone = parameters[self.CONNECTION_NAME_CLONE]
        lizsync_clone_ftp_host = parameters[self.CLONE_FTP_HOST]
        lizsync_clone_ftp_port = parameters[self.CLONE_FTP_PORT]
        lizsync_clone_ftp_login = parameters[self.CLONE_FTP_LOGIN]
        lizsync_clone_ftp_port = parameters[self.CLONE_FTP_PORT]
        lizsync_clone_ftp_remote_dir = parameters[self.CLONE_FTP_REMOTE_DIR]
        lizsync_clone_qgis_project_folder = parameters[self.CLONE_QGIS_PROJECT_FOLDER]

        # Set global variable
        QgsExpressionContextUtils.setGlobalVariable('lizsync_postgresql_binary_path', postgresql_binary_path)
        feedback.pushInfo(self.tr('PostgreSQL local binary path') + ' = ' + postgresql_binary_path)
        QgsExpressionContextUtils.setGlobalVariable('lizsync_winscp_binary_path', winscp_binary_path)
        feedback.pushInfo(self.tr('WinSCP binary path (Windows only)') + ' = ' + winscp_binary_path)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_connection_name_central', connection_name_central)
        feedback.pushInfo(self.tr('PostgreSQL connection to central database') + ' = ' + connection_name_central)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_central_ftp_host', lizsync_central_ftp_host)
        feedback.pushInfo(self.tr('Central FTP Server host') + ' = ' + lizsync_central_ftp_host)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_central_ftp_port', lizsync_central_ftp_port)
        feedback.pushInfo(self.tr('Central FTP Server port') + ' = %s' % lizsync_central_ftp_port)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_central_ftp_login', lizsync_central_ftp_login)
        feedback.pushInfo(self.tr('Central FTP Server login') + ' = ' + lizsync_central_ftp_login)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_central_ftp_remote_dir', lizsync_central_ftp_remote_dir)
        feedback.pushInfo(self.tr('Central FTP Server remote directory') + ' = ' + lizsync_central_ftp_remote_dir)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_local_qgis_project_folder', lizsync_local_qgis_project_folder)
        feedback.pushInfo(self.tr('Local Desktop QGIS project folder') + ' = ' + lizsync_local_qgis_project_folder)


        QgsExpressionContextUtils.setGlobalVariable('lizsync_connection_name_clone', connection_name_clone)
        feedback.pushInfo(self.tr('PostgreSQL connection to local clone database') + ' = ' + connection_name_clone)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_clone_ftp_host', lizsync_clone_ftp_host)
        feedback.pushInfo(self.tr('Clone FTP Server host') + ' = ' + lizsync_clone_ftp_host)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_clone_ftp_port', lizsync_clone_ftp_port)
        feedback.pushInfo(self.tr('clone FTP Server port') + ' = %s' % lizsync_clone_ftp_port)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_clone_ftp_login', lizsync_clone_ftp_login)
        feedback.pushInfo(self.tr('Clone FTP Server login') + ' = ' + lizsync_clone_ftp_login)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_clone_ftp_remote_dir', lizsync_clone_ftp_remote_dir)
        feedback.pushInfo(self.tr('Clone FTP Server remote directory') + ' = ' + lizsync_clone_ftp_remote_dir)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_clone_qgis_project_folder', lizsync_clone_qgis_project_folder)
        feedback.pushInfo(self.tr('Clone QGIS project folder') + ' = ' + lizsync_clone_qgis_project_folder)

        msg = self.tr('Configuration has been saved')
        feedback.pushInfo(msg)
        status = 1

        return {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }
