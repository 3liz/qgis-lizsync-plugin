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
    QgsProcessingOutputString,
    QgsExpressionContextUtils
)
from .tools import *

class CreateDatabaseStructure(QgsProcessingAlgorithm):
    """
    Create Lizsync structure in Database
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    OVERRIDE_AUDIT = 'OVERRIDE_AUDIT'
    OVERRIDE_LIZSYNC = 'OVERRIDE_LIZSYNC'
    NOM = 'NOM'
    SIREN = 'SIREN'
    CODE = 'CODE'
    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'create_database_structure'

    def displayName(self):
        return self.tr('Create database structure')

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
                self.OVERRIDE_AUDIT,
                self.tr('Drop audit schema and all data ?'),
                defaultValue=False,
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.OVERRIDE_LIZSYNC,
                self.tr('Drop lizsync schema and all data ?'),
                defaultValue=False,
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
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING, self.tr('Output message')
            )
        )

    def checkParameterValues(self, parameters, context):

        # Check that the connection name has been configured
        connection_name = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_central')
        if not connection_name:
            return False, self.tr('You must use the "Configure Lizsync plugin" alg to set the database connection name')

        # Check that it corresponds to an existing connection
        dbpluginclass = createDbPlugin( 'postgis' )
        connections = [c.connectionName() for c in dbpluginclass.connections()]
        if connection_name not in connections:
            return False, self.tr('The configured connection name does not exists in QGIS')

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
        sql = '''
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name = '{0}'
        '''.format(
            schema_name
        )
        connection_name = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_central')
        [header, data, rowCount, ok, error_message] = fetchDataFromSqlQuery(
            connection_name,
            sql
        )
        if not ok:
            return ok, error_message
        if schema_name == 'audit':
            override = parameters[self.OVERRIDE_AUDIT]
        if schema_name == 'lizsync':
            override = parameters[self.OVERRIDE_LIZSYNC]
        msg = schema_name.upper() + ' - ' + self.tr('Schema does not exists. Continue')
        for a in data:
            schema = a[0]
            if schema == schema_name and not override:
                ok = False
                msg = schema_name.upper() + ' - '
                msg+= self.tr("Schema already exists in database ! If you REALLY want to drop and recreate it (and loose all data), check the *Overwrite* checkbox")
        return ok, msg

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        connection_name = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_central')

        # Drop schemas if needed
        override_audit = self.parameterAsBool(parameters, self.OVERRIDE_AUDIT, context)
        override_lizsync = self.parameterAsBool(parameters, self.OVERRIDE_LIZSYNC, context)
        schemas = {
            'audit': override_audit,
            'lizsync': override_lizsync
        }
        for s, override in schemas.items():
            if override:
                feedback.pushInfo(self.tr("Trying to drop schema") + ' ' + s.upper())
                sql = '''
                    DROP SCHEMA IF EXISTS {} CASCADE;
                '''.format(
                    s
                )

                [header, data, rowCount, ok, error_message] = fetchDataFromSqlQuery(
                    connection_name,
                    sql
                )
                if ok:
                    feedback.pushInfo(self.tr("* Schema has been droped") + ' - ' + s.upper())
                else:
                    feedback.pushInfo(error_message)
                    status = 0
                    # raise Exception(msg)
                    return {
                        self.OUTPUT_STATUS: status,
                        self.OUTPUT_STRING: msg
                    }

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
            # 'lizsync/90_GLOSSARY.sql',
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

                [header, data, rowCount, ok, error_message] = fetchDataFromSqlQuery(
                    connection_name,
                    sql
                )
                if ok:
                    feedback.pushInfo('  Success !')
                else:
                    feedback.pushInfo('* ' + error_message)
                    status = 0
                    raise Exception(error_message)
                    # return {
                        # self.OUTPUT_STATUS: status,
                        # self.OUTPUT_STRING: error_message
                    # }

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
        [header, data, rowCount, ok, error_message] = fetchDataFromSqlQuery(
            connection_name,
            sql
        )

        return {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: self.tr('Lizsync database structure has been successfully created.')
        }
