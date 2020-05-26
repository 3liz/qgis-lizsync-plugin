__copyright__ = 'Copyright 2020, 3Liz'
__license__ = 'GPL version 3'
__email__ = 'info@3liz.org'
__revision__ = '$Format:%H$'

import os

from db_manager.db_plugins import createDbPlugin
from qgis.core import (
    QgsProcessingException,
    QgsProcessingParameterString,
    QgsProcessingParameterBoolean,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString
)

from .tools import (
    lizsyncConfig,
    getUriFromConnectionName,
    returnError,
)
from ...qgis_plugin_tools.tools.algorithm_processing import BaseProcessingAlgorithm
from ...qgis_plugin_tools.tools.database import (
    available_migrations,
    fetch_data_from_sql_query,
)
from ...qgis_plugin_tools.tools.i18n import tr
from ...qgis_plugin_tools.tools.resources import plugin_path
from ...qgis_plugin_tools.tools.version import format_version_integer, version

SCHEMA = "lizsync"


class UpgradeDatabaseStructure(BaseProcessingAlgorithm):
    """
    Upgrade database by comparing metadata in database
    and plugin version in metadata.txt
    """

    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    RUNIT = 'RUNIT'
    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'upgrade_database_structure'

    def displayName(self):
        return tr('Upgrade LizSync tools in the central database')

    def group(self):
        return tr('01 Installation')

    def groupId(self):
        return 'lizsync_installation'

    def shortHelpString(self):
        short_help = tr(
            ' Upgrade the Lizsync tables and functions in the central database.'
            '\n'
            '\n'
            ' If you have upgraded your QGIS LizSync plugin, you can run this script'
            ' to upgrade your central database to the new plugin version.'
        )
        return short_help

    def initAlgorithm(self, config):
        # LizSync config file from ini
        ls = lizsyncConfig()

        # INPUTS

        # Central database connection name
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

        # Checkbox needed to be check to run the upgrade
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RUNIT,
                tr('Check this box to upgrade. No action will be done otherwise'),
                defaultValue=False,
                optional=False
            )
        )

        # OUTPUTS
        # Add output for status (integer) and message (string)
        self.addOutput(
            QgsProcessingOutputNumber(
                self.OUTPUT_STATUS,
                tr('Output status')
            )
        )
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING,
                tr('Output message')
            )
        )

    def checkParameterValues(self, parameters, context):

        # Check if runit is checked
        runit = self.parameterAsBool(parameters, self.RUNIT, context)
        if not runit:
            msg = tr('You must check the box to run the upgrade !')
            ok = False
            return ok, msg

        # Check that it corresponds to an existing connection
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
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

        return super(UpgradeDatabaseStructure, self).checkParameterValues(parameters, context)

    def checkSchema(self, parameters, context):
        sql = '''
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name = 'lizsync';
        '''
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        [header, data, rowCount, ok, error_message] = fetch_data_from_sql_query(
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
        output = {
            self.OUTPUT_STATUS: 0,
            self.OUTPUT_STRING: ''
        }

        # Parameters
        connection_name = parameters[self.CONNECTION_NAME_CENTRAL]
        runit = self.parameterAsBool(parameters, self.RUNIT, context)

        # store parameters
        ls = lizsyncConfig()
        ls.setVariable('postgresql:central/name', connection_name)

        # Drop schema if needed
        if not runit:
            m = tr('You must check the box to run the upgrade !')
            return returnError(output, m, feedback)

        # get database version
        sql = '''
            SELECT version
            FROM lizsync.sys_structure_metadonnee
            ORDER BY date_ajout DESC
            LIMIT 1;
        '''
        [header, data, rowCount, ok, error_message] = fetch_data_from_sql_query(
            connection_name,
            sql
        )
        if not ok:
            m = error_message
            return returnError(output, m, feedback)
        db_version = None
        for a in data:
            db_version = a[0]
        if not db_version:
            error_message = tr('No installed version found in the database !')
            m = error_message
            return returnError(output, m, feedback)
        feedback.pushInfo(tr('Database structure version') + ' = %s' % db_version)

        # Get plugin version
        plugin_version = version()
        if plugin_version in ["master", "dev"]:
            migrations = available_migrations(000000)
            last_migration = migrations[-1]
            plugin_version = (
                last_migration.replace("upgrade_to_", "").replace(".sql", "").strip()
            )
            feedback.reportError(
                "Be careful, running the migrations on a development branch!"
            )
            feedback.reportError(
                "Latest available migration is {}".format(plugin_version)
            )
        else:
            feedback.pushInfo(tr("Version du plugin") + " = {}".format(plugin_version))

        # Return if nothing to do
        if db_version == plugin_version:
            return {
                self.OUTPUT_STATUS: 1,
                self.OUTPUT_STRING: tr('The database version already matches the plugin version. No upgrade needed.')
            }

        db_version_integer = format_version_integer(db_version)
        sql_files = available_migrations(db_version_integer)

        # Loop sql files and run SQL code
        for sf in sql_files:
            sql_file = os.path.join(plugin_path(), "install/sql/upgrade/{}".format(sf))
            with open(sql_file, "r") as f:
                sql = f.read()
                if len(sql.strip()) == 0:
                    feedback.pushInfo("* " + sf + " -- SKIPPED (EMPTY FILE)")
                    continue

                # Add SQL database version in lizsync.metadata
                new_db_version = (
                    sf.replace("upgrade_to_", "").replace(".sql", "").strip()
                )
                feedback.pushInfo("* NEW DB VERSION " + new_db_version)
                sql += """
                    UPDATE {}.sys_structure_metadonnee
                    SET (version, date_ajout)
                    = ( '{}', now()::timestamp(0) );
                """.format(
                    SCHEMA, new_db_version
                )

                _, _, _, ok, error_message = fetch_data_from_sql_query(
                    connection_name, sql
                )
                if not ok:
                    raise QgsProcessingException(error_message)

                feedback.pushInfo("* " + sf + " -- OK !")

        # Everything is fine, we now update to the plugin version
        sql = """
            UPDATE {}.sys_structure_metadonnee
            SET (version, date_ajout)
            = ( '{}', now()::timestamp(0) );
        """.format(
            SCHEMA, plugin_version
        )

        _, _, _, ok, error_message = fetch_data_from_sql_query(connection_name, sql)
        if not ok:
            raise QgsProcessingException(error_message)

        msg = tr("*** THE DATABASE STRUCTURE HAS BEEN UPDATED ***")
        feedback.pushInfo(msg)

        output = {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: msg
        }
        return output
