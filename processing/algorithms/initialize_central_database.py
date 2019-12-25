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

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = '$Format:%H$'

from PyQt5.QtCore import QCoreApplication
from PyQt5.QtSql import QSqlDatabase, QSqlQuery
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterString,
    QgsProcessingParameterBoolean,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsExpressionContextUtils
)
import processing
import os
from .tools import *
import configparser
from db_manager.db_plugins import createDbPlugin

class InitializeCentralDatabase(QgsProcessingAlgorithm):
    """

    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    SCHEMAS = 'SCHEMAS'
    ADD_UID_COLUMNS = 'ADD_UID_COLUMNS'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'initialize_central_database'

    def displayName(self):
        return self.tr('Initialize the central database')

    def group(self):
        return self.tr('Structure')

    def groupId(self):
        return 'lizsync_structure'

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
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ADD_UID_COLUMNS,
                self.tr('Add unique identifiers in all tables'),
                defaultValue=True,
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.SCHEMAS,
                self.tr('Restrict to comma separated schema names. NB: schemas public, lizsync & audit are never processed'),
                defaultValue='test',
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
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING, self.tr('Output message')
            )
        )

    def checkParameterValues(self, parameters, context):

        # Check that the connection name has been configured
        connection_name = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_central')
        if not connection_name:
            return False, self.tr('You must use the "Configure Lizsync plugin" alg to set the CENTRAL database connection name')

        # Check that it corresponds to an existing connection
        dbpluginclass = createDbPlugin( 'postgis' )
        connections = [c.connectionName() for c in dbpluginclass.connections()]
        if connection_name not in connections:
            return False, self.tr('The configured connection name does not exists in QGIS')

        # Check database content
        ok, msg = self.checkSchema(parameters, context)
        if not ok:
            return False, msg

        return super(InitializeCentralDatabase, self).checkParameterValues(parameters, context)

    def checkSchema(self, parameters, context):
        sql = '''
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name = 'lizsync';
        '''
        connection_name = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_central')
        [header, data, rowCount, ok, error_message] = fetchDataFromSqlQuery(
            connection_name,
            sql
        )
        if not ok:
            return ok, error_message
        ok = False
        msg = self.tr("Schema lizsync does not exist in database !")
        for a in data:
            schema = a[0]
            if schema == 'lizsync':
                ok = True
                msg = ''
        return ok, msg

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        msg = ''
        status = 1

        connection_name = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_central')
        add_uid_columns = self.parameterAsBool(parameters, self.ADD_UID_COLUMNS, context)

        # Add UID columns for given schema names
        schemas = [
            "'{0}'".format(a.strip())
            for a in parameters[self.SCHEMAS].split(',')
            if a.strip() not in ('public', 'lizsync', 'audit')
        ]
        schemas_sql = "'" + ', '.join(schemas) + "'"

        if add_uid_columns:
            sql = '''
                SELECT table_schema, table_name,
                lizsync.add_uid_columns(table_schema, table_name)
                FROM information_schema.tables
                WHERE table_schema IN ( {0} )
                AND table_type = 'BASE TABLE'
                ORDER BY table_schema, table_name
            '''.format(
                ', '.join(schemas)
            )
            [header, data, rowCount, ok, error_message] = fetchDataFromSqlQuery(
                connection_name,
                sql
            )
            if ok:
                status = 1
                names = []
                for a in data:
                    if a[2]:
                        names.append(
                            '{0}.{1}'.format(a[0], a[1])
                        )
                if names:
                    msg = self.tr('UID columns have been successfully added in the following tables:')
                    feedback.pushInfo(msg)
                    for n in names:
                        feedback.pushInfo('* ' + n)
                    msg+= ', '.join(names)
                else:
                    msg = self.tr('No UID columns have been added.')
                    feedback.pushInfo(msg)
            else:
                msg = error_message
                feedback.pushInfo(error_message)
                status = 0

# Add audit on all the tables in the central server
#echo "Add audit triggers on all table in the schema $SRV_SCHEMA"
#psql -h $SRV_DBHOST -d $SRV_DBNAME -U $SRV_DBUSER -c "SELECT count(*) nb FROM (SELECT audit.audit_table((quote_ident(table_schema) || '.' || quote_ident(table_name))::text) FROM information_schema.tables WHERE table_schema = '$SRV_SCHEMA' AND table_type = 'BASE TABLE' AND (quote_ident(table_schema) || '.' || quote_ident(table_name))::text NOT IN (SELECT (tgrelid::regclass)::text FROM pg_trigger WHERE tgname LIKE 'audit_trigger_%' )) foo;"


        return {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }

