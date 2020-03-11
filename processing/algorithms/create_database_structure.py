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

import configparser
import os

from db_manager.db_plugins import createDbPlugin
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterString,
    QgsProcessingParameterBoolean,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString
)
from .tools import *
from ...qgis_plugin_tools.tools.i18n import tr

class CreateDatabaseStructure(QgsProcessingAlgorithm):
    """
    Create Lizsync structure in Database
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    OVERRIDE_AUDIT = 'OVERRIDE_AUDIT'
    OVERRIDE_LIZSYNC = 'OVERRIDE_LIZSYNC'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'create_database_structure'

    def displayName(self):
        return tr('Install Lizsync tools on the central database')

    def group(self):
        return tr('01 Installation')

    def groupId(self):
        return 'lizsync_installation'

    def shortHelpString(self):
        short_help = tr(
            ' Install the LizSync schema with tables and function on the central database.'
            '\n'
            '\n'
            ' This script will add'
            '\n'
            ' * An audit schema with auditing functions and tables'
            '\n'
            ' * A lizsync schema with tables and functions'
            '\n'
            '\n'
            'Beware ! If you check the "override" checkboxes, you will loose all existing data in the audit and/or lizsync schema !'

        )
        return short_help

    def createInstance(self):
        return CreateDatabaseStructure()

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

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.OVERRIDE_AUDIT,
                tr('Drop audit schema and all data ?'),
                defaultValue=False,
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.OVERRIDE_LIZSYNC,
                tr('Drop lizsync schema and all data ?'),
                defaultValue=False,
                optional=False
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

        # Check that it corresponds to an existing connection
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        dbpluginclass = createDbPlugin( 'postgis' )
        connections = [c.connectionName() for c in dbpluginclass.connections()]
        if connection_name_central not in connections:
            return False, tr('The configured connection name does not exists in QGIS')

        # Check connection
        ok, uri, msg = getUriFromConnectionName(connection_name_central, True)
        if not ok:
            return False, msg

        # Check audit schema
        ok, msg = self.checkSchema('audit', parameters, context)
        if not ok:
            return False, msg

        # Check audit schema
        ok, msg = self.checkSchema('lizsync', parameters, context)
        if not ok:
            return False, msg

        return super(CreateDatabaseStructure, self).checkParameterValues(parameters, context)

    def checkSchema(self, schema_name, parameters, context):
        # Check if schema exists in database
        sql = '''
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name = '{0}'
        '''.format(
            schema_name
        )
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            connection_name_central,
            sql
        )
        if not ok:
            return ok, error_message

        # Get override parameter for the schema to check
        if schema_name == 'audit':
            override = parameters[self.OVERRIDE_AUDIT]
        if schema_name == 'lizsync':
            override = parameters[self.OVERRIDE_LIZSYNC]

        msg = schema_name.upper() + ' - ' + tr('Schema does not exists. Continue')
        for a in data:
            schema = a[0]
            if schema == schema_name and not override:
                ok = False
                msg = schema_name.upper() + ' - '
                msg+= tr("Schema already exists in database ! If you REALLY want to drop and recreate it (and loose all data), check the *Overwrite* checkbox")
        return ok, msg

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        output = {
            self.OUTPUT_STATUS: 0,
            self.OUTPUT_STRING: ''
        }
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]

        # Drop schemas if needed
        override_audit = self.parameterAsBool(parameters, self.OVERRIDE_AUDIT, context)
        override_lizsync = self.parameterAsBool(parameters, self.OVERRIDE_LIZSYNC, context)
        schemas = {
            'audit': override_audit,
            'lizsync': override_lizsync
        }
        for s, override in schemas.items():
            if override:
                feedback.pushInfo(tr("Trying to drop schema") + ' ' + s.upper())
                sql = '''
                    DROP SCHEMA IF EXISTS {} CASCADE;
                '''.format(
                    s
                )

                header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                    connection_name_central,
                    sql
                )
                if ok:
                    feedback.pushInfo(tr("* Schema has been droped") + ' - ' + s.upper())
                else:
                    feedback.pushInfo(error_message)
                    status = 0
                    m = error_message
                    return returnError(output, m, feedback)

        # Create full structure
        sql_files = [
            '00_initialize_database.sql',
            'audit.sql',
            'lizsync/10_FUNCTION.sql',
            'lizsync/20_TABLE_SEQUENCE_DEFAULT.sql',
            'lizsync/30_VIEW.sql',
            'lizsync/40_INDEX.sql',
            'lizsync/50_TRIGGER.sql',
            'lizsync/60_CONSTRAINT.sql',
            'lizsync/70_COMMENT.sql',
            'lizsync/90_function_current_setting.sql',
            '99_finalize_database.sql',
        ]
        msg = ''
        alg_dir = os.path.dirname(__file__)
        plugin_dir = os.path.join(alg_dir, '../../')

        # Loop sql files and run SQL code
        for sf in sql_files:
            feedback.pushInfo(sf)
            sql_file = os.path.join(plugin_dir, 'install/sql/%s' % sf)
            with open(sql_file, 'r') as f:
                sql = f.read()
                if len(sql.strip()) == 0:
                    feedback.pushInfo('  Skipped (empty file)')
                    continue

                header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                    connection_name_central,
                    sql
                )
                if ok:
                    feedback.pushInfo(tr('SQL file successfully played'))
                else:
                    m = error_message
                    return returnError(output, m, feedback)

        # Add version
        config = configparser.ConfigParser()
        config.read(str(os.path.join(plugin_dir, 'metadata.txt')))
        version = config['general']['version']
        sql = '''
            INSERT INTO lizsync.sys_structure_metadonnee
            (version, date_ajout)
            VALUES (
                '%s', now()::timestamp(0)
            )
        ''' % version
        header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            connection_name_central,
            sql
        )
        if ok:
            feedback.pushInfo(tr('Version added in the lizsync metadata table'))
        else:
            m = error_message
            return returnError(output, m, feedback)

        output = {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: tr('Lizsync database structure has been successfully created.')
        }
        return output
