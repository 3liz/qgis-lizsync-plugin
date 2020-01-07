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
    QgsVectorLayer,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingUtils,
    QgsProcessingException,
    QgsProcessingParameterString,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber,
    QgsProcessingOutputVectorLayer,
    QgsExpressionContextUtils
)
from .tools import *
from processing.tools import postgis
from db_manager.db_plugins import createDbPlugin

class ExecuteSql(QgsProcessingAlgorithm):
    """

    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    INPUT_SQL = 'INPUT_SQL'
    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    SQL = 'SELECT 1::int AS id'

    def name(self):
        return 'execute_sql'

    def displayName(self):
        return self.tr('Execute SQL')

    def group(self):
        return self.tr('Tools')

    def groupId(self):
        return 'lizsync_tools'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ExecuteSql()

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # INPUTS
        self.addParameter(
            QgsProcessingParameterString(
                self.INPUT_SQL, 'INPUT_SQL',
                optional=True
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

    def checkParameterValues(self, parameters, context):

        # Check that the connection name has been configured
        connection_name = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name')
        if not connection_name:
            return False, self.tr('You must use the "Configure plugin" alg to set the database connection name')

        # Check that it corresponds to an existing connection
        dbpluginclass = createDbPlugin( 'postgis' )
        connections = [c.connectionName() for c in dbpluginclass.connections()]
        if connection_name not in connections:
            return False, self.tr('The configured connection name does not exists in QGIS')

        return super(ExecuteSql, self).checkParameterValues(parameters, context)

    def setSql(self, parameters, context, feedback):

        sql = self.SQL
        if self.INPUT_SQL in parameters:
            input_sql = str(parameters[self.INPUT_SQL]).strip()
            if input_sql:
                sql = input_sql
        self.SQL = sql.replace('\n', ' ').rstrip(';')

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        # Database connection parameters
        connection_name = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name')

        msg = ''
        status = 1

        # Set SQL
        self.setSql(parameters, context, feedback)
        feedback.pushInfo(self.SQL)

        # Run SQL
        header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            connection_name,
            self.SQL
        )
        if ok:
            msg = self.tr('SQL successfully executed')
            feedback.pushInfo(msg)
            status = 1
        else:
            feedback.pushInfo('* ' + error_message)
            status = 0
            raise Exception(error_message)

        return {
            self.OUTPUT_STATUS: 0,
            self.OUTPUT_STRING: msg
        }
