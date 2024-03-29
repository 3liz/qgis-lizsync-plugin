__copyright__ = "Copyright 2020, 3Liz"
__license__ = "GPL version 3"
__email__ = "info@3liz.org"
__revision__ = "$Format:%H$"

import os

from qgis.core import (
    Qgis,
    QgsAbstractDatabaseProviderConnection,
    QgsProcessingException,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterString,
    QgsProviderConnectionException,
    QgsProviderRegistry,
)

if Qgis.QGIS_VERSION_INT >= 31400:
    from qgis.core import QgsProcessingParameterProviderConnection

from lizsync.processing.algorithms.base import BaseDatabaseAlgorithm
from lizsync.qgis_plugin_tools.tools.database import available_migrations
from lizsync.qgis_plugin_tools.tools.i18n import tr
from lizsync.qgis_plugin_tools.tools.resources import plugin_path
from lizsync.qgis_plugin_tools.tools.version import (
    format_version_integer,
    version,
)

from .tools import lizsyncConfig

SCHEMA = 'lizsync'


class UpgradeDatabaseStructure(BaseDatabaseAlgorithm):

    CONNECTION_NAME = "CONNECTION_NAME"
    RUN_MIGRATIONS = "RUN_MIGRATIONS"
    DATABASE_VERSION = "DATABASE_VERSION"

    def name(self):
        return 'upgrade_database_structure'

    def displayName(self):
        return tr('Upgrade LizSync tools in the central database')

    def shortHelpString(self):
        msg = tr(
            "When the plugin is upgraded, a database upgrade may be available as well. The database "
            "migration must be applied as well on the existing database.")
        msg += '\n\n'
        msg += self.parameters_help_string()
        return msg

    def initAlgorithm(self, config):
        # LizSync config file from ini
        ls = lizsyncConfig()
        connection_name = ls.variable('postgresql:central/name')

        label = tr("Connection to the PostgreSQL database")
        tooltip = tr("The database where the schema '{}' is installed.").format(SCHEMA)
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
                optional=False,
            )
            param.setMetadata(
                {
                    "widget_wrapper": {
                        "class": "processing.gui.wrappers_postgis.ConnectionWidgetWrapper"
                    }
                }
            )
        if Qgis.QGIS_VERSION_INT >= 31600:
            param.setHelp(tooltip)
        else:
            param.tooltip_3liz = tooltip
        self.addParameter(param)

        param = QgsProcessingParameterBoolean(
            self.RUN_MIGRATIONS,
            tr("Use this checkbox to upgrade."),
            defaultValue=False,
        )
        tooltip = tr("For security reason, we ask that you explicitly use this checkbox.")
        if Qgis.QGIS_VERSION_INT >= 31600:
            param.setHelp(tooltip)
        else:
            param.tooltip_3liz = tooltip
        self.addParameter(param)

        self.addOutput(
            QgsProcessingOutputString(self.DATABASE_VERSION, tr("Database version"))
        )

    def checkParameterValues(self, parameters, context):
        # Check if run migrations is checked
        run_migrations = self.parameterAsBool(parameters, self.RUN_MIGRATIONS, context)
        if not run_migrations:
            msg = tr("You must use the checkbox to do the upgrade !")
            return False, msg

        if Qgis.QGIS_VERSION_INT >= 31400:
            connection_name = self.parameterAsConnectionName(
                parameters, self.CONNECTION_NAME, context)
        else:
            connection_name = self.parameterAsString(
                parameters, self.CONNECTION_NAME, context)

        metadata = QgsProviderRegistry.instance().providerMetadata('postgres')
        connection = metadata.findConnection(connection_name)
        if not connection:
            raise QgsProcessingException(tr("The connection {} does not exist.").format(connection_name))

        if SCHEMA in connection.schemas():
            override = self.parameterAsBool(parameters, self.RUN_MIGRATIONS, context)
            if not override:
                msg = tr(
                    "The schema {} already exists in the database {} ! "
                    "If you really want to remove and recreate the schema (and remove its data),"
                    " use the checkbox.").format(SCHEMA, connection_name)
                return False, msg

        return super().checkParameterValues(parameters, context)

    def processAlgorithm(self, parameters, context, feedback):
        if Qgis.QGIS_VERSION_INT >= 31400:
            connection_name = self.parameterAsConnectionName(
                parameters, self.CONNECTION_NAME, context)
        else:
            connection_name = self.parameterAsString(
                parameters, self.CONNECTION_NAME, context)

        metadata = QgsProviderRegistry.instance().providerMetadata('postgres')

        connection = metadata.findConnection(connection_name)
        connection: QgsAbstractDatabaseProviderConnection
        if not connection:
            raise QgsProcessingException(tr("The connection {} does not exist.").format(connection_name))

        if not connection.tableExists(SCHEMA, 'sys_structure_metadonnee'):
            raise QgsProcessingException(tr(
                "The table {}.{} does not exist. You must first create the database structure.").format(
                SCHEMA, 'sys_structure_metadonnee'))

        db_version = self.database_version(connection)

        feedback.pushInfo("Current database version '{}'.".format(db_version))

        # Get plugin version
        plugin_version = version()
        if plugin_version in ["master", "dev"]:
            migrations = available_migrations(000000)
            last_migration = migrations[-1]
            plugin_version = (
                last_migration.replace("upgrade_to_", "").replace(".sql", "").strip()
            )
            feedback.reportError(
                tr("Be careful, running the migrations on a development branch!")
            )
            feedback.reportError(
                tr("Latest available migration is {}").format(plugin_version)
            )
        else:
            feedback.pushInfo(tr("Plugin's version is {}").format(plugin_version))

        results = {
            self.DATABASE_VERSION: plugin_version
        }

        # Return if nothing to do
        if db_version == plugin_version:
            feedback.pushInfo(tr(
                "The database version and the plugin version are the same, version {}. There isn't any "
                "upgrade to do.").format(plugin_version))
            return results

        db_version_integer = format_version_integer(db_version)
        sql_files = available_migrations(db_version_integer)

        # Loop sql files and run SQL code
        for sf in sql_files:
            sql_file = os.path.join(plugin_path(), "install/sql/upgrade/{}".format(sf))
            with open(sql_file, "r") as f:
                sql = f.read()
            if len(sql.strip()) == 0:
                feedback.pushInfo("* " + sf + " -- " + tr("SKIPPING, EMPTY FILE"))
                continue

            try:
                connection.executeSql(sql)
            except QgsProviderConnectionException as e:
                raise QgsProcessingException(str(e))

            new_db_version = (sf.replace("upgrade_to_", "").replace(".sql", "").strip())
            self.update_database_version(connection, new_db_version)
            feedback.pushInfo("Database version {} -- OK !".format(new_db_version))

        self.vacuum_all_tables(connection, feedback)

        self.update_database_version(connection, plugin_version)
        feedback.pushInfo("Database upgraded to the current plugin version {}!".format(plugin_version))

        return results

    @staticmethod
    def update_database_version(connection: QgsAbstractDatabaseProviderConnection, plugin_version: str):
        """ Update the database version. """
        sql = (
            "UPDATE {}.sys_structure_metadonnee "
            "SET (version, date_ajout) = ( '{}', now()::timestamp(0) );".format(
                SCHEMA, plugin_version))
        try:
            connection.executeSql(sql)
        except QgsProviderConnectionException as e:
            raise QgsProcessingException(str(e))

    @staticmethod
    def database_version(connection: QgsAbstractDatabaseProviderConnection) -> str:
        """ Get database version. """
        sql = (
            "SELECT version "
            "FROM {}.sys_structure_metadonnee "
            # "WHERE status = 1 "
            "ORDER BY date_ajout DESC "
            "LIMIT 1;").format(SCHEMA)
        try:
            data = connection.executeSql(sql)
        except QgsProviderConnectionException as e:
            raise QgsProcessingException(str(e))
        db_version = None
        for row in data:
            db_version = row[0]
        if not db_version:
            error_message = tr("No version has been found in the database !")
            raise QgsProcessingException(error_message)
        return db_version
