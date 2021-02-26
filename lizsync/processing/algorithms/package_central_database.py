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

import os
import tempfile
import zipfile

from platform import system as psys

from qgis.core import (
    Qgis,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber,
)
if Qgis.QGIS_VERSION_INT >= 31400:
    from qgis.core import QgsProcessingParameterProviderConnection

from .tools import (
    check_database_structure,
    check_database_server_metadata_content,
    check_database_uid_columns,
    check_database_audit_triggers,
    add_database_audit_triggers,
    add_database_uid_columns,
    lizsyncConfig,
    getUriFromConnectionName,
    fetchDataFromSqlQuery,
    pg_dump,
)
from ...qgis_plugin_tools.tools.i18n import tr
from ...qgis_plugin_tools.tools.algorithm_processing import BaseProcessingAlgorithm


class PackageCentralDatabase(BaseProcessingAlgorithm):
    """
    Package central database into ZIP package
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.
    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    PG_LAYERS = 'PG_LAYERS'
    ADD_UID_COLUMNS = 'ADD_UID_COLUMNS'
    ADD_AUDIT_TRIGGERS = 'ADD_AUDIT_TRIGGERS'
    POSTGRESQL_BINARY_PATH = 'POSTGRESQL_BINARY_PATH'
    ZIP_FILE = 'ZIP_FILE'
    ADDITIONAL_SQL_FILE = 'ADDITIONAL_SQL_FILE'
    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'package_central_database'

    def displayName(self):
        return tr('Create a package from the central database')

    def group(self):
        return tr('02 PostgreSQL synchronization')

    def groupId(self):
        return 'lizsync_postgresql_sync'

    def shortHelpString(self):
        short_help = tr(
            ' Package data from the central database, for future deployement on one or several clone(s).'
            '\n'
            '\n'
            ' This script backups all data from the given list of tables'
            ' to a ZIP archive, named by default "central_database_package.zip".'
            '\n'
            '\n'
            ' You can add an optionnal SQL file to run in the clone after the deployment of the archive.'
            ' This file must contain valid PostgreSQL queries and can be used to drop some triggers in the clone'
            ' or remove some constraints. For example "DELETE FROM pg_trigger WHERE tgname = \'name_of_trigger\';"'
            '\n'
            '\n'
            ' An internet connection is needed because a synchronization item must be written'
            ' to the central database "lizsync.history" table during the process.'
            ' and obviously data must be downloaded from the central database'
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
        label = tr('PostgreSQL connection to the central database')
        if Qgis.QGIS_VERSION_INT >= 31400:
            param = QgsProcessingParameterProviderConnection(
                self.CONNECTION_NAME_CENTRAL,
                label,
                "postgres",
                defaultValue=connection_name_central,
                optional=False,
            )
        else:
            param = QgsProcessingParameterString(
                self.CONNECTION_NAME_CENTRAL,
                label,
                defaultValue=connection_name_central,
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
        if Qgis.QGIS_VERSION_INT >= 31600:
            param.setHelp(tooltip)
        else:
            param.tooltip_3liz = tooltip
        self.addParameter(param)

        # PostgreSQL binary path (with psql pg_restore, etc.)
        postgresql_binary_path = ls.variable('binaries/postgresql')
        self.addParameter(
            QgsProcessingParameterFile(
                self.POSTGRESQL_BINARY_PATH,
                tr('PostgreSQL binary path'),
                defaultValue=postgresql_binary_path,
                behavior=QgsProcessingParameterFile.Folder,
                optional=False
            )
        )

        # PostgreSQL layers
        self.addParameter(
            QgsProcessingParameterMultipleLayers(
                self.PG_LAYERS,
                tr('PostgreSQL Layers to edit in the field'),
                QgsProcessing.TypeVector,
                optional=False,
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

        # Additionnal SQL file to run on the clone
        additional_sql_file = ls.variable('general/additional_sql_file')
        self.addParameter(
            QgsProcessingParameterFile(
                self.ADDITIONAL_SQL_FILE,
                tr('Additionnal SQL file to run in the clone after the ZIP deployement'),
                defaultValue=additional_sql_file,
                behavior=QgsProcessingParameterFile.File,
                optional=True,
                extension='sql'
            )
        )

        # Output zip file destination
        database_archive_file = ls.variable('general/database_archive_file')
        if not database_archive_file:
            database_archive_file = os.path.join(
                tempfile.gettempdir(),
                'central_database_package.zip'
            )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.ZIP_FILE,
                tr('Output archive file (ZIP)'),
                fileFilter='*.zip',
                optional=False,
                defaultValue=database_archive_file
            )
        )

        # OUTPUTS
        # Add output for message
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

    def checkCentralDatabase(self, parameters, context, feedback, print_messages=False):
        """
        Check if central database
        has been initialized
        """
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        pg_layers = self.parameterAsLayerList(parameters, self.PG_LAYERS, context)
        pg_layers = [layer for layer in pg_layers if layer.providerType() == 'postgres']
        tables = []
        for layer in pg_layers:
            uri = layer.dataProvider().uri()
            tables.append('"' + uri.schema() + '"."' + uri.table() + '"')

        # Check if needed schema and metadata has been created
        if print_messages:
            feedback.pushInfo(tr('CHECK IF LIZSYNC HAS BEEN INSTALLED AND DATABASE INITIALIZED'))
        checks = {}

        # structure
        status, message = check_database_structure(
            connection_name_central
        )
        checks['structure'] = (status, message)

        # server_metadata content
        status, message = check_database_server_metadata_content(
            connection_name_central
        )
        checks['metadata'] = (status, message)

        # uid columns
        status, message = check_database_uid_columns(
            connection_name_central,
            None,
            tables
        )
        checks['uid columns'] = (status, message)

        # audit triggers
        status, message = check_database_audit_triggers(
            connection_name_central,
            None,
            tables
        )
        checks['audit triggers'] = (status, message)

        global_status = True
        for item, item_data in checks.items():
            if print_messages or not item_data[0]:
                feedback.pushInfo(tr(item).upper())
                feedback.pushInfo(item_data[1])
                feedback.pushInfo('')
            # not mandatory for audit triggers
            if not item_data[0]:
                global_status = False

        return global_status, checks

    def checkParameterValues(self, parameters, context):

        # Check postgresql binary path
        postgresql_binary_path = parameters[self.POSTGRESQL_BINARY_PATH]
        test_bin = 'psql'
        if psys().lower().startswith('win'):
            test_bin += '.exe'
        has_bin_file = os.path.isfile(
            os.path.join(
                postgresql_binary_path,
                test_bin
            )
        )
        if not has_bin_file:
            return False, tr('The needed PostgreSQL binaries cannot be found in the specified path')

        # Check connection
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        ok, uri_central, msg = getUriFromConnectionName(connection_name_central, True)
        if not ok:
            return False, msg

        # Check we can retrieve host, port, user and password
        # for central database
        # since they are used inside the clone to connect to the central database with dblink
        # service file are not possible yet
        if uri_central.service():
            msg = tr('Central database connection uses a service file. This is not supported yet')
            return False, msg

        # Check input layers
        layers = self.parameterAsLayerList(parameters, self.PG_LAYERS, context)
        layers = [layer for layer in layers if layer.providerType() == 'postgres']
        if not layers:
            return False, tr('At least one PostgreSQL layer is required')

        return super(PackageCentralDatabase, self).checkParameterValues(parameters, context)

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        msg = ''

        # Parameters
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        postgresql_binary_path = parameters[self.POSTGRESQL_BINARY_PATH]
        add_uid_columns = self.parameterAsBool(parameters, self.ADD_UID_COLUMNS, context)
        add_audit_triggers = self.parameterAsBool(parameters, self.ADD_AUDIT_TRIGGERS, context)
        additional_sql_file = self.parameterAsString(
            parameters,
            self.ADDITIONAL_SQL_FILE,
            context
        )
        zip_file = parameters[self.ZIP_FILE]
        pg_layers = self.parameterAsLayerList(parameters, self.PG_LAYERS, context)
        pg_layers = [layer for layer in pg_layers if layer.providerType() == 'postgres']
        tables = []
        schemas = []
        for layer in pg_layers:
            uri = layer.dataProvider().uri()
            schema = uri.schema()
            tables.append('"' + schema + '"."' + uri.table() + '"')
            if schema not in schemas:
                schemas.append(schema)
        synchronized_schemas = ','.join(schemas)

        # store parameters
        ls = lizsyncConfig()
        ls.setVariable('postgresql:central/name', connection_name_central)
        ls.setVariable('binaries/postgresql', postgresql_binary_path)
        ls.setVariable('postgresql:central/schemas', synchronized_schemas)
        ls.setVariable('general/additional_sql_file', additional_sql_file)
        ls.setVariable('general/database_archive_file', zip_file)
        ls.save()

        # First run some test in database
        test, checks = self.checkCentralDatabase(parameters, context, feedback, True)
        ok = True
        if test:
            message = tr('Every required test has passed successfully !')
            feedback.pushInfo(message)
        else:
            message = tr('Some needed configuration are missing in the central database.')

            # Add missing uid columns
            if add_uid_columns and not checks['uid columns']:
                feedback.pushInfo('')
                status, message = add_database_uid_columns(
                    connection_name_central,
                    None,
                    tables
                )
                if not status:
                    raise QgsProcessingException(message)
                feedback.pushInfo(message)

            # Add missing uid columns
            if add_audit_triggers and not checks['audit triggers']:
                feedback.pushInfo('')
                status, message = add_database_audit_triggers(
                    connection_name_central,
                    None,
                    tables
                )
                if not status:
                    raise QgsProcessingException(message)
                feedback.pushInfo(message)

            # Recheck
            test_2, checks_2 = self.checkCentralDatabase(parameters, context, feedback, False)
            if not test_2:
                ok = False
                message = tr('Some needed configuration are missing in the central database.')
        if not ok:
            raise QgsProcessingException(message)

        # Create temporary files
        sql_file_list = [
            '01_before.sql',
            '02_predata.sql',
            '02_data.sql',
            '03_after.sql',
            '04_lizsync.sql',
            'sync_id.txt',
            'sync_tables.txt'
        ]
        sql_files = {}
        tmpdir = tempfile.mkdtemp()
        for k in sql_file_list:
            path = os.path.join(tmpdir, k)
            sql_files[k] = path
        # feedback.pushInfo(str(sql_files))

        # 1/ 01_before.sql
        ####
        feedback.pushInfo('')
        feedback.pushInfo(tr('CREATE SCRIPT 01_before.sql'))
        sql = 'BEGIN;'

        # Create needed schemas
        # Get the list of input schemas
        schemas_to_create = [
            '"{0}"'.format(a.strip())
            for a in synchronized_schemas.split(',')
            if a.strip() not in ('public', 'lizsync', 'audit')
        ]
        for schema in schemas_to_create:
            sql += '''
                CREATE SCHEMA IF NOT EXISTS {0};
            '''.format(
                schema
            )

        # Drop existing tables
        for table in tables:
            sql += '''
                DROP TABLE IF EXISTS {0} CASCADE;
            '''.format(
                table
            )

        # Drop other sytem schemas
        sql += '''
            DROP SCHEMA IF EXISTS lizsync,audit CASCADE;
        '''

        # Create needed extension
        sql += '''
            CREATE EXTENSION IF NOT EXISTS postgis;
            CREATE EXTENSION IF NOT EXISTS hstore;
            CREATE EXTENSION IF NOT EXISTS dblink;
        '''

        # Add audit tools
        alg_dir = os.path.dirname(__file__)
        plugin_dir = os.path.join(alg_dir, '../../')
        sql_file = os.path.join(plugin_dir, 'install/sql/audit.sql')
        with open(sql_file, 'r') as f:
            sql += f.read()

        sql += '''
            COMMIT;
        '''

        # write content into temp file
        with open(sql_files['01_before.sql'], 'w') as f:
            f.write(sql)
            feedback.pushInfo(tr('File 01_before.sql created'))
        feedback.pushInfo('')

        # 2/a) 02_predata.sql
        ####
        # First we get functions from the needed schemas
        feedback.pushInfo(tr('CREATE SCRIPT 02_predata.sql'))
        # compute the tables options: we need to exclude all tables from schema
        # even if no data is fetched to allow pg_dump to create the needed related functions
        # for example functions used in triggers
        # ex: pg_dump service='test' -Fp --schema-only -n my_schema --no-acl --no-owner -T '"my_schema".*'
        excluded_tables_params = []
        for schema in schemas:
            excluded_tables_params.append(
                '-T "{}".*'.format(schema)
            )
        pstatus, pmessages = pg_dump(
            feedback,
            postgresql_binary_path,
            connection_name_central,
            sql_files['02_predata.sql'] + '.tpl',
            schemas,
            None,
            ['--schema-only'] + excluded_tables_params
        )
        for pmessage in pmessages:
            feedback.pushInfo(pmessage)
        if not pstatus:
            m = ' '.join(pmessages)
            raise QgsProcessingException(m)

        # We need to remove unwanted SQL statements
        with open(sql_files['02_predata.sql'] + '.tpl', 'r') as input_file:
            filedata = input_file.read()
        newdata = filedata
        replacements = [
            ['CREATE SCHEMA ', 'CREATE SCHEMA IF NOT EXISTS '],
            ['CREATE FUNCTION ', 'CREATE OR REPLACE FUNCTION '],
        ]
        for item in replacements:
            newdata = newdata.replace(item[0], item[1])
        with open(sql_files['02_predata.sql'], 'w') as output_file:
            output_file.write(newdata)
        os.remove(sql_files['02_predata.sql'] + '.tpl')
        feedback.pushInfo(tr('File 02_predata.sql created'))
        feedback.pushInfo('')

        # 2/b) 02_data.sql
        ####
        # Then we get the actual data for the needed tables of these schemas
        feedback.pushInfo(tr('CREATE SCRIPT 02_data.sql'))
        pstatus, pmessages = pg_dump(
            feedback,
            postgresql_binary_path,
            connection_name_central,
            sql_files['02_data.sql'],
            schemas,
            tables,
            []
        )
        for pmessage in pmessages:
            feedback.pushInfo(pmessage)
        if not pstatus:
            m = ' '.join(pmessages)
            raise QgsProcessingException(m)
        feedback.pushInfo(tr('File 02_data.sql created'))
        feedback.pushInfo('')

        # 3/ 03_after.sql
        ####
        feedback.pushInfo(tr('CREATE SCRIPT 03_after.sql'))
        sql = ''

        # Add audit trigger for these tables in given schemas
        # only for needed tables
        sql += '''
            SELECT audit.audit_table((quote_ident(table_schema) || '.' || quote_ident(table_name))::text)
            FROM information_schema.tables AS t
            WHERE True
            AND table_type = 'BASE TABLE'
        '''
        sql += " AND concat('\"', t.table_schema, '\".\"', t.table_name, '\"') IN ( "
        sql += ', '.join(["'{}'".format(table) for table in tables])
        sql += ")"
        # feedback.pushInfo(sql)

        # write content into temp file
        with open(sql_files['03_after.sql'], 'w') as f:
            f.write(sql)
            feedback.pushInfo(tr('File 03_after.sql created'))

        feedback.pushInfo('')

        #  4/ 04_lizsync.sql
        # Add lizsync schema structure
        # We get it from central database to be sure everything will be compatible
        feedback.pushInfo(tr('CREATE SCRIPT 04_lizsync.sql'))
        pstatus, pmessages = pg_dump(
            feedback,
            postgresql_binary_path,
            connection_name_central,
            sql_files['04_lizsync.sql'],
            ['lizsync'],
            None,
            ['--schema-only']
        )
        for pmessage in pmessages:
            feedback.pushInfo(pmessage)
        if not pstatus:
            m = ' '.join(pmessages)
            raise QgsProcessingException(m)

        feedback.pushInfo('')

        # 5/ sync_tables.txt
        # Add tables into file
        ####
        # todo: write the list of tables instead
        feedback.pushInfo(tr('ADD SYNCHRONIZED TABLES TO THE FILE sync_tables.txt'))
        with open(sql_files['sync_tables.txt'], 'w') as f:
            f.write(','.join(tables))
            feedback.pushInfo(tr('File sync_tables.txt created'))

        feedback.pushInfo('')

        # 6/ sync_id.txt
        # Add new sync history item in the central database
        # and get sync_id
        ####
        feedback.pushInfo(tr('ADD NEW SYNC HISTORY ITEM IN CENTRAL DATABASE'))
        sql = '''
            INSERT INTO lizsync.history
            (
                server_from, min_event_id, max_event_id,
                max_action_tstamp_tx, sync_type, sync_status
            ) VALUES (
                (SELECT server_id FROM lizsync.server_metadata LIMIT 1),
                (SELECT Coalesce(min(event_id),-1) FROM audit.logged_actions),
                (SELECT Coalesce(max(event_id),0) FROM audit.logged_actions),
                (SELECT Coalesce(max(action_tstamp_tx), now()) FROM audit.logged_actions),
                'full',
                'done'
            )
            RETURNING sync_id;
        '''
        header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            connection_name_central,
            sql
        )
        if ok:
            sync_id = ''
            for a in data:
                sync_id = a[0]
            if sync_id:
                msg = tr('New synchronization history item has been added in the central database')
                msg += ' : syncid = {0}'.format(sync_id)
                feedback.pushInfo(msg)
                with open(sql_files['sync_id.txt'], 'w') as f:
                    f.write(sync_id)
                    feedback.pushInfo(tr('File sync_id.txt created'))
            else:
                m = tr('No synchronization item could be added !')
                m += ' '
                m += msg
                m += ' '
                m += error_message
                raise QgsProcessingException(m)
        else:
            m = tr('No synchronization item could be added !')
            m += ' ' + error_message
            raise QgsProcessingException(m)

        # Additional SQL file to run
        if additional_sql_file and os.path.isfile(additional_sql_file):
            sql_files['99_last.sql'] = additional_sql_file

        feedback.pushInfo('')

        # Create ZIP archive
        try:
            import zlib  # NOQA
            compression = zipfile.ZIP_DEFLATED
        except Exception:
            compression = zipfile.ZIP_STORED

        with zipfile.ZipFile(zip_file, mode='w') as zf:
            for fname, fsource in sql_files.items():
                try:
                    zf.write(
                        fsource,
                        arcname=fname,
                        compress_type=compression
                    )
                except Exception:
                    msg += tr("Error while zipping file") + ': ' + fname
                    raise QgsProcessingException(msg)

        # Remove files
        for fname, fsource in sql_files.items():
            if os.path.exists(fsource):
                os.remove(fsource)

        msg = tr('Package has been successfully created !')
        feedback.pushInfo(msg)

        output = {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: msg
        }
        return output
