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

class GetDataAsLayer(QgsProcessingAlgorithm):
    """

    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'
    OUTPUT_LAYER = 'OUTPUT_LAYER'
    OUTPUT_LAYER_NAME = 'OUTPUT_LAYER_NAME'
    OUTPUT_LAYER_RESULT_NAME = 'OUTPUT_LAYER_RESULT_NAME'

    SQL = 'SELECT 1::int AS id'
    LAYER_NAME = ''
    GEOM_FIELD = None

    def name(self):
        return 'get_data_as_layer'

    def displayName(self):
        return self.tr('Get data as layer')

    def group(self):
        return self.tr('Tools')

    def groupId(self):
        return 'lizsync_tools'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return self.__class__()

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # INPUTS

        # Name of the layer
        self.addParameter(
            QgsProcessingParameterString(
                self.OUTPUT_LAYER_NAME,
                self.tr('Name of the output layer'),
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

        # Output vector layer
        self.addOutput(
            QgsProcessingOutputVectorLayer(
                self.OUTPUT_LAYER,
                self.tr('Output layer')
            )
        )

        # Output vector layer name (set by the user or the alg)
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_LAYER_RESULT_NAME,
                self.tr('Output layer name')
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

        return super(GetDataAsLayer, self).checkParameterValues(parameters, context)

    def setSql(self, parameters, context, feedback):

        self.SQL = self.SQL.replace('\n', ' ').rstrip(';')

    def setLayerName(self, parameters, context, feedback):

        # Name given by the user
        output_layer_name = parameters[self.OUTPUT_LAYER_NAME]
        self.LAYER_NAME = output_layer_name


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
        # Set output layer name
        self.setLayerName(parameters, context, feedback)

        # Buid QGIS uri to load layer
        id_field = 'id'
        uri = postgis.uri_from_name(connection_name)
        uri.setDataSource("", "(" + self.SQL + ")", self.GEOM_FIELD, "", id_field)
        vlayer = QgsVectorLayer(uri.uri(), "layername", "postgres")
        if not vlayer.isValid():
            feedback.pushInfo(
                self.tr('SQL = \n' + self.SQL)
            )
            raise QgsProcessingException(self.tr("""This layer is invalid!
                Please check the PostGIS log for error messages."""))

        # Load layer
        context.temporaryLayerStore().addMapLayer(vlayer)
        context.addLayerToLoadOnCompletion(
            vlayer.id(),
            QgsProcessingContext.LayerDetails(
                self.LAYER_NAME,
                context.project(),
                self.OUTPUT_LAYER
            )
        )

        return {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg,
            self.OUTPUT_LAYER: vlayer.id(),
            self.OUTPUT_LAYER_RESULT_NAME: self.LAYER_NAME
        }
