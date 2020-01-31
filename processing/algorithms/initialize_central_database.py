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
    Initialize central database
    Add server id, uid columns, audit triggers, etc.
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.
    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    SCHEMAS = 'SCHEMAS'
    ADD_SERVER_ID = 'ADD_SERVER_ID'
    ADD_UID_COLUMNS = 'ADD_UID_COLUMNS'
    ADD_AUDIT_TRIGGERS = 'ADD_AUDIT_TRIGGERS'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'initialize_central_database'

    def displayName(self):
        return self.tr('Prepare central database')

    def group(self):
        return self.tr('01 Installation')

    def groupId(self):
        return 'lizsync_installation'

    def shortHelpString(self):
        return getShortHelpString(os.path.basename(__file__))

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return InitializeCentralDatabase()

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # INPUTS
        connection_name_central = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_central')
        db_param_a = QgsProcessingParameterString(
            self.CONNECTION_NAME_CENTRAL,
            self.tr('PostgreSQL connection to the central database'),
            defaultValue=connection_name_central,
            optional=False
        )
        db_param_a.setMetadata({
            'widget_wrapper': {
                'class': 'processing.gui.wrappers_postgis.ConnectionWidgetWrapper'
            }
        })
        self.addParameter(db_param_a)

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ADD_SERVER_ID,
                self.tr('Add server id in metadata table'),
                defaultValue=True,
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ADD_UID_COLUMNS,
                self.tr('Add unique identifiers in all tables'),
                defaultValue=True,
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ADD_AUDIT_TRIGGERS,
                self.tr('Add audit triggers in all tables'),
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
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        if not connection_name_central:
            return False, self.tr('You must use the "Configure Lizsync plugin" alg to set the CENTRAL database connection name')

        # Check that it corresponds to an existing connection
        dbpluginclass = createDbPlugin( 'postgis' )
        connections = [c.connectionName() for c in dbpluginclass.connections()]
        if connection_name_central not in connections:
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
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            connection_name_central,
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

        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        add_uid_columns = self.parameterAsBool(parameters, self.ADD_UID_COLUMNS, context)
        add_server_id = self.parameterAsBool(parameters, self.ADD_SERVER_ID, context)
        add_audit_triggers = self.parameterAsBool(parameters, self.ADD_AUDIT_TRIGGERS, context)

        # First run all tests
        test_list = ['structure', 'server id', 'uid columns', 'audit triggers']
        status, tests = check_lizsync_installation_status(
            connection_name_central,
            test_list,
            parameters[self.SCHEMAS]
        )
        if status:
            msg = self.tr('Everything is OK. No action needed')
            return {
                self.OUTPUT_STATUS: 1,
                self.OUTPUT_STRING: msg
            }

        # compile SQL schemas
        schemas = [
            "'{0}'".format(a.strip())
            for a in parameters[self.SCHEMAS].split(',')
            if a.strip() not in ('public', 'lizsync', 'audit')
        ]
        schemas_sql = ', '.join(schemas)

        # Check structure
        feedback.pushInfo(self.tr('CHECK LIZSYNC STRUCTURE'))
        if not tests['structure']['status']:
            raise Exception(self.tr('Lizsync has not been installed in the central database. Run the script "Create database structure"'))
        feedback.pushInfo(self.tr('Lizsync structure OK'))

        # ADD SERVER ID IN METADATA TABLE
        if add_server_id and not tests['server id']['status']:
            feedback.pushInfo(self.tr('ADD SERVER ID IN THE METADATA TABLE'))
            server_name = 'central'
            sql = '''
            INSERT INTO lizsync.server_metadata (server_name)
            VALUES ( '{server_name}' )
            ON CONFLICT ON CONSTRAINT server_metadata_server_name_key
            DO NOTHING
            RETURNING server_id, server_name
            '''.format(
                server_name=server_name
            )
            header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(connection_name_central, sql)
            server_id = None
            if ok:
                if rowCount == 1:
                    for a in data:
                        server_id = a[0]
                        feedback.pushInfo(self.tr('Server id successfully added') + ' {0}'.format(server_id))
            else:
                msg = self.tr('Error adding server name in server_metadata table.')
                feedback.pushInfo(msg)
                feedback.pushInfo(error_message)
                raise Exception(msg)

        # Add UID columns for given schema names
        if add_uid_columns and not tests['uid columns']['status']:
            feedback.pushInfo(self.tr('ADD UID COLUMNS IN ALL THE TABLES OF THE SPECIFIED SCHEMAS'))
            sql = '''
                SELECT table_schema, table_name,
                lizsync.add_uid_columns(table_schema, table_name)
                FROM information_schema.tables
                WHERE table_schema IN ( {0} )
                AND table_type = 'BASE TABLE'
                ORDER BY table_schema, table_name
            '''.format(
                schemas_sql
            )
            header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                connection_name_central,
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
                    msg = self.tr('No UID columns were missing.')
                    feedback.pushInfo(msg)
            else:
                msg = error_message
                status = 0
                feedback.pushInfo(msg)
                raise Exception(msg)


        # ADD MISSING AUDIT TRIGGERS
        if add_audit_triggers and not tests['audit triggers']['status']:
            feedback.pushInfo(self.tr('ADD AUDIT TRIGGERS IN ALL THE TABLES OF THE GIVEN SCHEMAS'))
            sql = '''
                SELECT table_schema, table_name,
                audit.audit_table((quote_ident(table_schema) || '.' || quote_ident(table_name))::text)
                FROM information_schema.tables
                WHERE table_schema IN ( {0} )
                AND table_type = 'BASE TABLE'
                AND (quote_ident(table_schema) || '.' || quote_ident(table_name))::text
                    NOT IN (
                        SELECT (tgrelid::regclass)::text
                        FROM pg_trigger
                        WHERE tgname LIKE 'audit_trigger_%'
                    )

            '''.format(
                schemas_sql
            )
            header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                connection_name_central,
                sql
            )
            if ok:
                status = 1
                names = []
                for a in data:
                    names.append(
                        '{0}.{1}'.format(a[0], a[1])
                    )
                if names:
                    msg = self.tr('Audit triggers have been successfully added in the following tables:')
                    feedback.pushInfo(msg)
                    for n in names:
                        feedback.pushInfo('* ' + n)
                    msg+= ', '.join(names)
                else:
                    msg = self.tr('No audit triggers were missing.')
                    feedback.pushInfo(msg)
            else:
                msg = error_message
                status = 0
                feedback.pushInfo(msg)
                raise Exception(msg)


        return {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }

