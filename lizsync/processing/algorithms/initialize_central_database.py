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

from qgis.core import (
    QgsProcessingException,
    QgsProcessingParameterString,
    QgsProcessingParameterBoolean,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString
)
from .tools import (
    check_lizsync_installation_status,
    lizsyncConfig,
    getUriFromConnectionName,
    fetchDataFromSqlQuery,
)
from db_manager.db_plugins import createDbPlugin
from ...qgis_plugin_tools.tools.i18n import tr
from ...qgis_plugin_tools.tools.algorithm_processing import BaseProcessingAlgorithm


class InitializeCentralDatabase(BaseProcessingAlgorithm):
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
        return tr('Prepare the central database')

    def group(self):
        return tr('01 Installation')

    def groupId(self):
        return 'lizsync_installation'

    def shortHelpString(self):
        short_help = tr(
            ' Prepare the central server PostgreSQL database with the needed data for LizSync tool.'
            '\n'
            '\n'
            ' LizSync needs to have :'
            '\n'
            ' * A server ID stored in the lizsync.server_metadata table'
            '\n'
            ' * All tables from the given schema must have a unique identifier column (uid) with standard uuid inside'
            '\n'
            ' * All tables from the given schema must be audited (trigger of the audit tool)'
            '\n'
            '\n'
            ' You can pass a list of PostgreSQL central database schemas and this alg will add the necessary data and tools'
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

        # Add server id in metadata
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ADD_SERVER_ID,
                tr('Add server id in metadata table'),
                defaultValue=True,
                optional=False
            )
        )

        # Add uid columns in all the tables of the synchronized schemas
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ADD_UID_COLUMNS,
                tr('Add unique identifiers in all tables'),
                defaultValue=True,
                optional=False
            )
        )

        # Add audit trigger for all tables in the synchronized schemas
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ADD_AUDIT_TRIGGERS,
                tr('Add audit triggers in all tables'),
                defaultValue=True,
                optional=False
            )
        )

        # Schemas to synchronize
        synchronized_schemas = ls.variable('postgresql:central/schemas').strip()
        if not synchronized_schemas:
            synchronized_schemas = 'test'
        self.addParameter(
            QgsProcessingParameterString(
                self.SCHEMAS,
                tr('Restrict to comma separated schema names. NB: schemas public, lizsync & audit are never processed'),
                defaultValue=synchronized_schemas,
                optional=True
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
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING, tr('Output message')
            )
        )

    def checkParameterValues(self, parameters, context):

        # Check that the connection name has been configured
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]

        # Check that it corresponds to an existing connection
        dbpluginclass = createDbPlugin('postgis')
        connections = [c.connectionName() for c in dbpluginclass.connections()]
        if connection_name_central not in connections:
            return False, tr('The configured connection name does not exists in QGIS')

        # Check connection
        ok, uri, msg = getUriFromConnectionName(connection_name_central, True)
        if not ok:
            return False, msg

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
        msg = tr("Schema lizsync does not exist in database !")
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
        output = {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }

        # Parameters
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        add_uid_columns = self.parameterAsBool(parameters, self.ADD_UID_COLUMNS, context)
        add_server_id = self.parameterAsBool(parameters, self.ADD_SERVER_ID, context)
        add_audit_triggers = self.parameterAsBool(parameters, self.ADD_AUDIT_TRIGGERS, context)
        synchronized_schemas = parameters[self.SCHEMAS]

        # store parameters
        ls = lizsyncConfig()
        ls.setVariable('postgresql:central/name', connection_name_central)
        ls.setVariable('postgresql:central/schemas', synchronized_schemas)
        ls.save()

        # First run all tests
        test_list = ['structure', 'server id', 'uid columns', 'audit triggers']
        status, tests = check_lizsync_installation_status(
            connection_name_central,
            test_list,
            synchronized_schemas
        )
        if status:
            msg = tr('Everything is OK. No action needed')
            return {
                self.OUTPUT_STATUS: 1,
                self.OUTPUT_STRING: msg
            }

        # compile SQL schemas
        schemas = [
            "'{0}'".format(a.strip())
            for a in synchronized_schemas.split(',')
            if a.strip() not in ('public', 'lizsync', 'audit')
        ]
        schemas_sql = ', '.join(schemas)

        # Check structure
        feedback.pushInfo(tr('CHECK LIZSYNC STRUCTURE'))
        if not tests['structure']['status']:
            m = tr(
                'Lizsync has not been installed in the central database.'
                ' Run the script "Create database structure"'
            )
            raise QgsProcessingException(m)

        feedback.pushInfo(tr('Lizsync structure OK'))

        # ADD SERVER ID IN METADATA TABLE
        if add_server_id and not tests['server id']['status']:
            feedback.pushInfo(tr('ADD SERVER ID IN THE METADATA TABLE'))
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
                        feedback.pushInfo(tr('Server id successfully added') + ' {0}'.format(server_id))
            else:
                m = tr('Error adding server name in server_metadata table.')
                m += ' '
                m += error_message
                raise QgsProcessingException(m)

        # Add UID columns for given schema names
        if add_uid_columns and not tests['uid columns']['status']:
            feedback.pushInfo(tr('ADD UID COLUMNS IN ALL THE TABLES OF THE SPECIFIED SCHEMAS'))
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
                    msg = tr('UID columns have been successfully added in the following tables:')
                    feedback.pushInfo(msg)
                    for n in names:
                        feedback.pushInfo('* ' + n)
                    msg += ', '.join(names)
                else:
                    msg = tr('No UID columns were missing.')
                    feedback.pushInfo(msg)
            else:
                m = error_message
                raise QgsProcessingException(m)

        # ADD MISSING AUDIT TRIGGERS
        if add_audit_triggers and not tests['audit triggers']['status']:
            feedback.pushInfo(tr('ADD AUDIT TRIGGERS IN ALL THE TABLES OF THE GIVEN SCHEMAS'))
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
                    msg = tr('Audit triggers have been successfully added in the following tables:')
                    feedback.pushInfo(msg)
                    for n in names:
                        feedback.pushInfo('* ' + n)
                    msg += ', '.join(names)
                else:
                    msg = tr('No audit triggers were missing.')
                    feedback.pushInfo(msg)
            else:
                raise QgsProcessingException(error_message)

        output = {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }
        return output
