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

import os

from db_manager.db_plugins import createDbPlugin
from qgis.core import (
    Qgis,
    QgsProcessingParameterString,
    QgsProcessingParameterBoolean,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterDefinition
)
if Qgis.QGIS_VERSION_INT >= 31400:
    from qgis.core import QgsProcessingParameterProviderConnection

from .tools import (
    lizsyncConfig,
    getUriFromConnectionName,
)
from ...qgis_plugin_tools.tools.database import (
    available_migrations,
    fetch_data_from_sql_query,
)
from ...qgis_plugin_tools.tools.i18n import tr
from ...qgis_plugin_tools.tools.algorithm_processing import BaseProcessingAlgorithm
from ...qgis_plugin_tools.tools.resources import (
    plugin_test_data_path,
    plugin_path,
)
from ...qgis_plugin_tools.tools.version import version

SCHEMA = "lizsync"


class CreateDatabaseStructure(BaseProcessingAlgorithm):
    """
    Create Lizsync structure in Database
    """

    CONNECTION_NAME = 'CONNECTION_NAME'
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
            'Beware ! If the schema lizsync or audit already exists in the database, not installation will be made. You will need to manually correct the situation (drop or modifiy the schemas, tables and functions) with SQL commands.'

        )
        return short_help

    def initAlgorithm(self, config):
        # LizSync config file from ini
        ls = lizsyncConfig()

        # INPUTS
        connection_name = ls.variable('postgresql:central/name')
        label = tr('PostgreSQL connection to the central database')
        if Qgis.QGIS_VERSION_INT >= 31400:
            param = QgsProcessingParameterProviderConnection(
                self.CONNECTION_NAME,
                label,
                "postgres",
                defaultValue=connection_name,
                optional=False,
            )
        else:
            param = QgsProcessingParameterString(
                self.CONNECTION_NAME,
                label,
                defaultValue=connection_name,
                optional=False
            )
            param.setMetadata({
                'widget_wrapper': {
                    'class': 'processing.gui.wrappers_postgis.ConnectionWidgetWrapper'
                }
            })
        tooltip = tr(
            'The PostgreSQL connection to the central database.'
        )
        tooltip += tr(
            ' You need to have the right to create a new schema in this database,'
            ' as a schema lizsync will be created and filled with the needed tables and functions'
        )
        if Qgis.QGIS_VERSION_INT >= 31600:
            param.setHelp(tooltip)
        else:
            param.tooltip_3liz = tooltip
        self.addParameter(param)

        # Hidden parameters which allow to drop the schemas
        # Hidden to avoid misuse and data loss
        # Drop schema audit
        p = QgsProcessingParameterBoolean(
            self.OVERRIDE_AUDIT,
            tr('Drop audit schema and all data ?'),
            defaultValue=False,
        )
        p.setFlags(QgsProcessingParameterDefinition.FlagHidden)
        self.addParameter(p)

        # Drop schema lizsync
        p = QgsProcessingParameterBoolean(
            self.OVERRIDE_LIZSYNC,
            tr('Drop lizsync schema and all data ?'),
            defaultValue=False,
        )
        p.setFlags(QgsProcessingParameterDefinition.FlagHidden)
        self.addParameter(p)

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
        connection_name = parameters[self.CONNECTION_NAME]
        dbpluginclass = createDbPlugin('postgis')
        connections = [c.connectionName() for c in dbpluginclass.connections()]
        if connection_name not in connections:
            return False, tr('The configured connection name does not exists in QGIS')

        # Check connection
        ok, uri, msg = getUriFromConnectionName(connection_name, True)
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
        connection_name = self.parameterAsString(
            parameters, self.CONNECTION_NAME, context
        )
        header, data, rowCount, ok, error_message = fetch_data_from_sql_query(
            connection_name,
            sql
        )
        if not ok:
            return ok, error_message

        # Get override parameter for the schema to check
        if schema_name == 'audit':
            if self.OVERRIDE_AUDIT in parameters:
                override = parameters[self.OVERRIDE_AUDIT]
            else:
                override = False
        if schema_name == 'lizsync':
            if self.OVERRIDE_LIZSYNC in parameters:
                override = parameters[self.OVERRIDE_LIZSYNC]
            else:
                override = False

        msg = schema_name.upper() + ' - ' + tr('Schema does not exists. Continue')
        for a in data:
            schema = a[0]
            if schema == schema_name and not override:
                ok = False
                msg = schema_name.upper() + ' - '
                msg += tr("Schema already exists in database !")
        return ok, msg

    def processAlgorithm(self, parameters, context, feedback):
        # Parameters
        connection_name = self.parameterAsString(
            parameters, self.CONNECTION_NAME, context
        )
        override_audit = self.parameterAsBool(parameters, self.OVERRIDE_AUDIT, context)
        override_lizsync = self.parameterAsBool(parameters, self.OVERRIDE_LIZSYNC, context)

        # store parameters
        ls = lizsyncConfig()
        ls.setVariable('postgresql:central/name', connection_name)
        ls.save()

        # Drop schemas if needed
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

                header, data, rowCount, ok, error_message = fetch_data_from_sql_query(
                    connection_name,
                    sql
                )
                if ok:
                    feedback.pushInfo(tr("* Schema has been dropped") + ' - ' + s.upper())
                else:
                    raise QgsProcessingException(error_message)

        # Create full structure
        sql_files = [
            "00_initialize_database.sql",
            "audit.sql",
            "{}/10_FUNCTION.sql".format(SCHEMA),
            "{}/20_TABLE_SEQUENCE_DEFAULT.sql".format(SCHEMA),
            "{}/30_VIEW.sql".format(SCHEMA),
            "{}/40_INDEX.sql".format(SCHEMA),
            "{}/50_TRIGGER.sql".format(SCHEMA),
            "{}/60_CONSTRAINT.sql".format(SCHEMA),
            "{}/70_COMMENT.sql".format(SCHEMA),
            "{}/90_function_current_setting.sql".format(SCHEMA),
            "99_finalize_database.sql",
        ]
        plugin_dir = plugin_path()
        plugin_version = version()
        dev_version = False
        run_migration = os.environ.get(
            "TEST_DATABASE_INSTALL_{}".format(SCHEMA.capitalize())
        )
        if plugin_version in ["master", "dev"] and not run_migration:
            feedback.reportError(
                "Be careful, running the install on a development branch!"
            )
            dev_version = True

        if run_migration:
            plugin_dir = plugin_test_data_path()
            feedback.reportError(
                "Be careful, running migrations on an empty database using {} "
                "instead of {}".format(run_migration, plugin_version)
            )
            plugin_version = run_migration

        # Loop sql files and run SQL code
        for sf in sql_files:
            feedback.pushInfo(sf)
            sql_file = os.path.join(plugin_dir, "install/sql/{}".format(sf))
            with open(sql_file, "r") as f:
                sql = f.read()
                if len(sql.strip()) == 0:
                    feedback.pushInfo("  Skipped (empty file)")
                    continue

                _, _, _, ok, error_message = fetch_data_from_sql_query(
                    connection_name, sql
                )
                if ok:
                    feedback.pushInfo("  Success !")
                else:
                    raise QgsProcessingException(error_message)

        # Add version
        if run_migration or not dev_version:
            metadata_version = plugin_version
        else:
            migrations = available_migrations(000000)
            last_migration = migrations[-1]
            metadata_version = (
                last_migration.replace("upgrade_to_", "").replace(".sql", "").strip()
            )
            feedback.reportError("Latest migration is {}".format(metadata_version))

        sql = """
            INSERT INTO {}.sys_structure_metadonnee
            (version, date_ajout)
            VALUES (
                '{}', now()::timestamp(0)
            )""".format(
            SCHEMA, metadata_version
            )
        fetch_data_from_sql_query(connection_name, sql)
        feedback.pushInfo(
            "Database version '{}'.".format(metadata_version)
        )

        return {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: tr(
                "*** THE STRUCTURE {} HAS BEEN CREATED WITH VERSION '{}'***".format(
                    SCHEMA, metadata_version
                )
            ),
        }
