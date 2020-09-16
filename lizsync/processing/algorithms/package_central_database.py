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
    QgsProcessingException,
    QgsProcessingParameterString,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber
)

from .tools import (
    check_lizsync_installation_status,
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
    SCHEMAS = 'SCHEMAS'
    POSTGRESQL_BINARY_PATH = 'POSTGRESQL_BINARY_PATH'
    ZIP_FILE = 'ZIP_FILE'
    ADDITIONAL_SQL_FILE = 'ADDITIONAL_SQL_FILE'
    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'package_master_database'

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
            ' This script backups all data from the given list of schemas'
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

        # List of schemas to package and synchronize afterwards
        synchronized_schemas = ls.variable('postgresql:central/schemas')
        if not synchronized_schemas:
            synchronized_schemas = 'test'
        self.addParameter(
            QgsProcessingParameterString(
                self.SCHEMAS,
                tr('List of schemas to package, separated by commas. (schemas public, lizsync & audit are never processed)'),
                defaultValue=synchronized_schemas,
                optional=False
            )
        )

        # Additionnal SQL file to run on the clone
        additional_sql_file = ls.variable('general/additional_sql_file')
        # Userland context
        if os.path.isdir('/storage/internal/geopoppy') and psys().lower().startswith('linux'):
            self.addParameter(
                QgsProcessingParameterString(
                    self.ADDITIONAL_SQL_FILE,
                    tr('Additionnal SQL file to run in the clone after the ZIP deployement'),
                    defaultValue=additional_sql_file,
                    optional=True
                )
            )
        else:
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
        # Userland context
        if os.path.isdir('/storage/internal/geopoppy') and psys().lower().startswith('linux'):
            self.addParameter(
                QgsProcessingParameterString(
                    self.ZIP_FILE,
                    tr('Database ZIP archive path'),
                    defaultValue=database_archive_file,
                    optional=True
                )
            )
        else:
            self.addParameter(
                QgsProcessingParameterFileDestination(
                    self.ZIP_FILE,
                    tr('Output archive file (ZIP)'),
                    fileFilter='zip',
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

    def checkCentralDatabase(self, parameters, feedback):
        """
        Check if central database
        has been initialized
        """
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]

        # Check if needed schema and metadata has been created
        feedback.pushInfo(tr('CHECK IF LIZSYNC HAS BEEN INSTALLED AND DATABASE INITIALIZED'))
        status, tests = check_lizsync_installation_status(
            connection_name_central,
            ['structure', 'server id', 'uid columns', 'audit triggers'],
            parameters[self.SCHEMAS]
        )
        if not status:
            msg = tr('Some needed configuration are missing in the central database. Please correct them before proceeding.')
        else:
            msg = tr('Every test has passed successfully !')
        feedback.pushInfo(msg)

        # Loop through test results
        for name, test in tests.items():
            item_msg = '* {name} - {message}'.format(
                name=name.upper(),
                message=test['message'].replace('"', '')
            )
            feedback.pushInfo(item_msg)
        if not status:
            return False, msg
        else:
            return True, msg

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
        ok, uri, msg = getUriFromConnectionName(connection_name_central, True)
        if not ok:
            return False, msg

        return super(PackageCentralDatabase, self).checkParameterValues(parameters, context)

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        msg = ''

        # Parameters
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        postgresql_binary_path = parameters[self.POSTGRESQL_BINARY_PATH]
        synchronized_schemas = parameters[self.SCHEMAS]
        additional_sql_file = self.parameterAsString(
            parameters,
            self.ADDITIONAL_SQL_FILE,
            context
        )
        zip_file = parameters[self.ZIP_FILE]

        # store parameters
        ls = lizsyncConfig()
        ls.setVariable('postgresql:central/name', connection_name_central)
        ls.setVariable('binaries/postgresql', postgresql_binary_path)
        ls.setVariable('postgresql:central/schemas', synchronized_schemas)
        ls.setVariable('general/additional_sql_file', additional_sql_file)
        ls.setVariable('general/database_archive_file', zip_file)
        ls.save()

        # First run some test in database
        test, m = self.checkCentralDatabase(parameters, feedback)
        if not test:
            raise QgsProcessingException(m)

        # Create temporary files
        sql_file_list = [
            '01_before.sql',
            '02_data.sql',
            '03_after.sql',
            '04_lizsync.sql',
            'sync_id.txt',
            'sync_schemas.txt'
        ]
        sql_files = {}
        tmpdir = tempfile.mkdtemp()
        for k in sql_file_list:
            path = os.path.join(tmpdir, k)
            sql_files[k] = path
        # feedback.pushInfo(str(sql_files))

        # Get the list of input schemas
        schemas = [
            '"{0}"'.format(a.strip())
            for a in synchronized_schemas.split(',')
            if a.strip() not in ('public', 'lizsync', 'audit')
        ]
        schemas_sql = ', '.join(schemas)

        # 1/ 01_before.sql
        ####
        feedback.pushInfo('')
        feedback.pushInfo(tr('CREATE SCRIPT 01_before.sql'))
        sql = 'BEGIN;'

        # Drop existing schemas
        sql += '''
            DROP SCHEMA IF EXISTS {0} CASCADE;
        '''.format(
            schemas_sql
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

        # 2/ 02_data.sql
        ####
        feedback.pushInfo('')
        feedback.pushInfo(tr('CREATE SCRIPT 02_data.sql'))
        pstatus, pmessages = pg_dump(
            feedback,
            postgresql_binary_path,
            connection_name_central,
            sql_files['02_data.sql'],
            schemas,
            []
        )
        for pmessage in pmessages:
            feedback.pushInfo(pmessage)
        if not pstatus:
            m = ' '.join(pmessages)
            raise QgsProcessingException(m)

        # 3/ 03_after.sql
        ####
        feedback.pushInfo('')
        feedback.pushInfo(tr('CREATE SCRIPT 03_after.sql'))
        sql = ''

        # Add audit trigger in all table in given schemas
        schemas = [
            "'{0}'".format(a.strip())
            for a in synchronized_schemas.split(',')
            if a.strip() not in ('public', 'lizsync', 'audit')
        ]
        schemas_sql = ', '.join(schemas)
        sql += '''
            SELECT audit.audit_table((quote_ident(table_schema) || '.' || quote_ident(table_name))::text)
            FROM information_schema.tables
            WHERE table_schema IN ( {0} )
            AND table_type = 'BASE TABLE'
            ;
        '''.format(
            schemas_sql
        )

        # write content into temp file
        with open(sql_files['03_after.sql'], 'w') as f:
            f.write(sql)
            feedback.pushInfo(tr('File 03_after.sql created'))

        #  4/ 04_lizsync.sql
        # Add lizsync schema structure
        # We get it from central database to be sure everything will be compatible
        feedback.pushInfo('')
        feedback.pushInfo(tr('CREATE SCRIPT 04_lizsync.sql'))
        pstatus, pmessages = pg_dump(
            feedback,
            postgresql_binary_path,
            connection_name_central,
            sql_files['04_lizsync.sql'],
            ['lizsync'],
            ['--schema-only']
        )
        for pmessage in pmessages:
            feedback.pushInfo(pmessage)
        if not pstatus:
            m = ' '.join(pmessages)
            raise QgsProcessingException(m)

        # 5/ sync_schemas.txt
        # Add schemas into file
        ####
        feedback.pushInfo('')
        feedback.pushInfo(tr('ADD SCHEMAS TO FILE sync_schemas.txt'))
        schemas = [
            "{0}".format(a.strip())
            for a in synchronized_schemas.split(',')
            if a.strip() not in ('public', 'lizsync', 'audit')
        ]
        schema_list = ','.join(schemas)
        with open(sql_files['sync_schemas.txt'], 'w') as f:
            f.write(schema_list)
            feedback.pushInfo(tr('File sync_schemas.txt created'))

        # 6/ sync_id.txt
        # Add new sync history item in the central database
        # and get sync_id
        ####
        feedback.pushInfo('')
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

        msg = tr('Package has been successfully created !')
        feedback.pushInfo('')
        feedback.pushInfo(msg)

        output = {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: msg
        }
        return output
