__copyright__ = "Copyright 2020, 3Liz"
__license__ = "GPL version 3"
__email__ = "info@3liz.org"
__revision__ = "$Format:%H$"

import os

from qgis.core import (
    Qgis,
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
from lizsync.qgis_plugin_tools.tools.resources import (
    plugin_path,
    plugin_test_data_path,
)
from lizsync.qgis_plugin_tools.tools.version import version

from .tools import lizsyncConfig

SCHEMA = 'lizsync'


class CreateDatabaseStructure(BaseDatabaseAlgorithm):
    """
    Creation of the database structure from scratch.
    """

    CONNECTION_NAME = "CONNECTION_NAME"
    OVERRIDE = "OVERRIDE"
    DATABASE_VERSION = "DATABASE_VERSION"

    def name(self):
        return "create_database_structure"

    def displayName(self):
        return tr('Install Lizsync tools on the central database')

    def shortHelpString(self):
        msg = tr(
            "When you are running the plugin for the first time on a new database, you need to install the "
            "database schema.")
        msg += '\n\n'
        msg += tr("It will erase and/or create the schema '{}'.").format(SCHEMA)
        msg += '\n\n'
        msg += self.parameters_help_string()
        return msg

    def initAlgorithm(self, config):
        # LizSync config file from ini
        ls = lizsyncConfig()
        connection_name = ls.variable('postgresql:central/name')

        label = tr('PostgreSQL connection to the central database')
        tooltip = tr(
            'The PostgreSQL connection to the central database.'
        )
        tooltip += tr(
            ' You need to have the right to create a new schema in this database,'
            ' as a schema lizsync will be created and filled with the needed tables and functions'
        )
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
            self.OVERRIDE,
            tr("Erase the schema {} ?").format(SCHEMA),
            defaultValue=False,
        )
        tooltip = tr("** Be careful ** This will remove data in the schema !")
        if Qgis.QGIS_VERSION_INT >= 31600:
            param.setHelp(tooltip)
        else:
            param.tooltip_3liz = tooltip
        self.addParameter(param)

        self.addOutput(
            QgsProcessingOutputString(self.DATABASE_VERSION, tr("Database version"))
        )

    def checkParameterValues(self, parameters, context):
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
            override = self.parameterAsBool(parameters, self.OVERRIDE, context)
            if not override:
                msg = tr(
                    "The schema {} already exists in the database {} ! "
                    "If you really want to remove and recreate the schema (and remove its data),"
                    " use the checkbox.").format(SCHEMA, connection_name)
                return False, msg

        return super().checkParameterValues(parameters, context)

    def processAlgorithm(self, parameters, context, feedback):
        metadata = QgsProviderRegistry.instance().providerMetadata('postgres')
        if Qgis.QGIS_VERSION_INT >= 31400:
            connection_name = self.parameterAsConnectionName(
                parameters, self.CONNECTION_NAME, context)
        else:
            connection_name = self.parameterAsString(
                parameters, self.CONNECTION_NAME, context)

        # store parameters
        ls = lizsyncConfig()
        ls.setVariable('postgresql:central/name', connection_name)
        ls.save()

        connection = metadata.findConnection(connection_name)
        if not connection:
            raise QgsProcessingException(tr("The connection {} does not exist.").format(connection_name))

        # Drop schema if needed
        override = self.parameterAsBool(parameters, self.OVERRIDE, context)
        if override and SCHEMA in connection.schemas():
            feedback.pushInfo(tr("Removing the schema {}…").format(SCHEMA))
            try:
                connection.dropSchema(SCHEMA, True)
            except QgsProviderConnectionException as e:
                raise QgsProcessingException(str(e))

        # Create full structure
        sql_files = [
            "00_initialize_database.sql",
            "{}/10_FUNCTION.sql".format(SCHEMA),
            "{}/20_TABLE_SEQUENCE_DEFAULT.sql".format(SCHEMA),
            "{}/30_VIEW.sql".format(SCHEMA),
            "{}/40_INDEX.sql".format(SCHEMA),
            "{}/50_TRIGGER.sql".format(SCHEMA),
            "{}/60_CONSTRAINT.sql".format(SCHEMA),
            "{}/70_COMMENT.sql".format(SCHEMA),

            "99_finalize_database.sql",
        ]

        plugin_dir = plugin_path()
        plugin_version = version()
        dev_version = False
        run_migration = os.environ.get(
            "TEST_DATABASE_INSTALL_{}".format(SCHEMA.upper())
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
        for sql_file in sql_files:
            feedback.pushInfo(sql_file)
            sql_file = os.path.join(plugin_dir, "install/sql/{}".format(sql_file))
            with open(sql_file, "r") as f:
                sql = f.read()
                if len(sql.strip()) == 0:
                    feedback.pushInfo("  Skipped (empty file)")
                    continue

                try:
                    connection.executeSql(sql)
                except QgsProviderConnectionException as e:
                    raise QgsProcessingException(str(e))
                feedback.pushInfo("  Success !")

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

        self.vacuum_all_tables(connection, feedback)

        sql = """
            INSERT INTO {}.sys_structure_metadonnee
            (version, date_ajout)
            VALUES ('{}', now()::timestamp(0))""".format(SCHEMA, metadata_version)
        try:
            connection.executeSql(sql)
        except QgsProviderConnectionException as e:
            raise QgsProcessingException(str(e))
        feedback.pushInfo("Database version '{}'.".format(metadata_version))

        # Add central server id
        self.add_central_server_id(connection, context, feedback)

        results = {
            self.DATABASE_VERSION: metadata_version,
        }
        return results

    @staticmethod
    def add_central_server_id(connection, context, feedback):
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
        try:
            connection.executeSql(sql)
            feedback.pushInfo(tr('Server id successfully added'))
        except QgsProviderConnectionException as e:
            msg = tr('Error adding server name in server_metadata table.')
            msg += ' '
            msg += str(e)
            raise QgsProcessingException(msg)
