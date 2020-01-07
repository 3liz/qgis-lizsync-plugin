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
    QgsProcessingParameterString,
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

    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    CONNECTION_NAME_CLONE = 'CONNECTION_NAME_CLONE'
    LOCAL_QGIS_PROJECT_FOLDER = 'LOCAL_QGIS_PROJECT_FOLDER'
    FTP_HOST = 'FTP_HOST'
    FTP_LOGIN = 'FTP_LOGIN'
    FTP_REMOTE_DIR = 'FTP_REMOTE_DIR'

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
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        connection_name_clone = parameters[self.CONNECTION_NAME_CLONE]
        lizsync_local_qgis_project_folder = parameters[self.LOCAL_QGIS_PROJECT_FOLDER]
        lizsync_ftp_host = parameters[self.FTP_HOST]
        lizsync_ftp_login = parameters[self.FTP_LOGIN]
        lizsync_ftp_remote_dir = parameters[self.FTP_REMOTE_DIR]

        # Set global variable
        QgsExpressionContextUtils.setGlobalVariable('lizsync_connection_name_central', connection_name_central)
        feedback.pushInfo(self.tr('PostgreSQL connection to central database') + ' = ' + connection_name_central)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_connection_name_clone', connection_name_clone)
        feedback.pushInfo(self.tr('PostgreSQL connection to local clone database') + ' = ' + connection_name_clone)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_local_qgis_project_folder', lizsync_local_qgis_project_folder)
        feedback.pushInfo(self.tr('Local QGIS project folder') + ' = ' + lizsync_local_qgis_project_folder)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_ftp_host', lizsync_ftp_host)
        feedback.pushInfo(self.tr('FTP Server host') + ' = ' + lizsync_ftp_host)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_ftp_login', lizsync_ftp_login)
        feedback.pushInfo(self.tr('FTP Server login') + ' = ' + lizsync_ftp_login)

        QgsExpressionContextUtils.setGlobalVariable('lizsync_ftp_remote_dir', lizsync_ftp_remote_dir)
        feedback.pushInfo(self.tr('FTP Server remote directory') + ' = ' + lizsync_ftp_remote_dir)

        msg = self.tr('Configuration has been saved')
        feedback.pushInfo(msg)
        status = 1

        return {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }
