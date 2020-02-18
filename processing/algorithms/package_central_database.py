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

from PyQt5.QtCore import QCoreApplication
from db_manager.db_plugins import createDbPlugin
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingUtils,
    QgsProcessingException,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber,
    QgsExpressionContextUtils
)

import os
from datetime import date, datetime
from .tools import *
import zipfile
import tempfile
from platform import system as psys

class PackageCentralDatabase(QgsProcessingAlgorithm):
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
    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'package_master_database'

    def displayName(self):
        return self.tr('Create a package from central database')

    def group(self):
        return self.tr('02 Package and deploy database data')

    def groupId(self):
        return 'lizsync_package'

    def shortHelpString(self):
        short_help = self.tr(
            ' Package data from the central database, for future deployement on one or several clone(s).'
            '<br>'
            '<br>'
            ' This script backups all data from the given list of schemas'
            ' to a ZIP archive, named by default "central_database_package.zip".'
            '<br>'
            '<br>'
            ' An internet connection is needed because a synchronization item must be written'
            ' to the central database "lizsync.history" table during the process.'
            ' and obviously data must be downloaded from the central database'
        )
        return short_help

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return PackageCentralDatabase()


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

        # PostgreSQL binary path (with psql pg_restore, etc.)
        postgresql_binary_path = QgsExpressionContextUtils.globalScope().variable('lizsync_postgresql_binary_path')
        self.addParameter(
            QgsProcessingParameterFile(
                self.POSTGRESQL_BINARY_PATH,
                self.tr('PostgreSQL binary path'),
                defaultValue=postgresql_binary_path,
                behavior=QgsProcessingParameterFile.Folder,
                optional=False
            )
        )

        # List of schemas to package
        self.addParameter(
            QgsProcessingParameterString(
                self.SCHEMAS,
                self.tr('List of schemas to package, separated by commas. (schemas public, lizsync & audit are never processed)'),
                defaultValue='test',
                optional=False
            )
        )

        # Output zip file destination
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.ZIP_FILE,
                self.tr('Output archive file (ZIP)'),
                fileFilter='zip',
                optional=False,
                defaultValue=os.path.join(tempfile.gettempdir(), 'central_database_package.zip')
            )
        )

        # OUTPUTS
        # Add output for message
        self.addOutput(
            QgsProcessingOutputNumber(
                self.OUTPUT_STATUS,
                self.tr('Output status')
            )
        )
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING,
                self.tr('Output message')
            )
        )

    def checkCentralDatabase(self, parameters, feedback):
        '''
        Check if central database
        has been initialized
        '''
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]

        # Check if needed schema and metadata has been created
        feedback.pushInfo(self.tr('CHECK IF LIZSYNC HAS BEEN INSTALLED AND DATABASE INITIALIZED'))
        status, tests = check_lizsync_installation_status(
            connection_name_central,
            ['structure', 'server id', 'uid columns', 'audit triggers'],
            parameters[self.SCHEMAS]
        )
        if not status:
            msg = self.tr('Some needed configuration are missing in the central database. Please correct them before proceeding.')
            feedback.pushInfo(msg)
            for name,test in tests.items():
                if not test['status']:
                    item_msg = '* {name} - {message}'.format(
                        name = name.upper(),
                        message=test['message'].replace('"', '')
                    )
                    feedback.pushInfo(item_msg)
            raise Exception(msg)
        else:
            feedback.pushInfo(self.tr('Every test has passed successfully !'))



    def checkParameterValues(self, parameters, context):

        # Check postgresql binary path
        postgresql_binary_path = parameters[self.POSTGRESQL_BINARY_PATH]
        test_bin = 'psql'
        if psys().lower().startswith('win'):
            test_bin+= '.exe'
        has_bin_file = os.path.isfile(
            os.path.join(
                postgresql_binary_path,
                test_bin
            )
        )
        if not has_bin_file:
            return False, self.tr('The needed PostgreSQL binaries cannot be found in the specified path')

        # Check that the connection name has been configured
        connection_name = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_central')
        if not connection_name:
            return False, self.tr('You must use the "Configure Lizsync plugin" alg to set the CENTRAL database connection name')

        # Check that it corresponds to an existing connection
        dbpluginclass = createDbPlugin( 'postgis' )
        connections = [c.connectionName() for c in dbpluginclass.connections()]
        if connection_name not in connections:
            return False, self.tr('The configured connection name does not exists in QGIS')

        return super(PackageCentralDatabase, self).checkParameterValues(parameters, context)


    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        msg = ''
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        postgresql_binary_path = parameters[self.POSTGRESQL_BINARY_PATH]

        # First run some test in database
        self.checkCentralDatabase(parameters, feedback)

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
            for a in parameters[self.SCHEMAS].split(',')
            if a.strip() not in ('public', 'lizsync', 'audit')
        ]
        schemas_sql =  ', '.join(schemas)

        # 1/ 01_before.sql
        ####
        feedback.pushInfo(self.tr('CREATE SCRIPT 01_before.sql'))
        sql = 'BEGIN;'

        # Drop existing schemas
        sql+= '''
            DROP SCHEMA IF EXISTS {0} CASCADE;
        '''.format(
            schemas_sql
        )
        # Drop other sytem schemas'''
        sql+= '''
            DROP SCHEMA IF EXISTS lizsync,audit CASCADE;
        '''

        # Create needed extension
        sql+= '''
            CREATE EXTENSION IF NOT EXISTS postgis;
            CREATE EXTENSION IF NOT EXISTS hstore;
        '''

        # Add audit tools
        alg_dir = os.path.dirname(__file__)
        plugin_dir = os.path.join(alg_dir, '../../')
        sql_file = os.path.join(plugin_dir, 'install/sql/audit.sql')
        with open(sql_file, 'r') as f:
            sql+= f.read()

        sql+= '''
            COMMIT;
        '''

        # write content into temp file
        with open(sql_files['01_before.sql'], 'w') as f:
            f.write(sql)
            feedback.pushInfo(self.tr('File 01_before.sql created'))

        # 2/ 02_data.sql
        ####
        feedback.pushInfo(self.tr('CREATE SCRIPT 02_data.sql'))
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
            raise Exception(' '.join(pmessages))

        # 3/ 03_after.sql
        ####
        feedback.pushInfo(self.tr('CREATE SCRIPT 03_after.sql'))
        sql = ''

        # Add audit trigger in all table in given schemas
        schemas = [
            "'{0}'".format(a.strip())
            for a in parameters[self.SCHEMAS].split(',')
            if a.strip() not in ('public', 'lizsync', 'audit')
        ]
        schemas_sql = ', '.join(schemas)
        sql+= '''
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
            feedback.pushInfo(self.tr('File 03_after.sql created'))

        # 4/ 04_lizsync.sql
        # Add lizsync schema structure
        # We get it from central database to be sure everything will be compatible
        feedback.pushInfo(self.tr('CREATE SCRIPT 04_lizsync.sql'))
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
            raise Exception(' '.join(pmessages))

        # 5/ sync_schemas.txt
        # Add schemas into file
        ####
        feedback.pushInfo(self.tr('ADD SCHEMAS TO FILE sync_schemas.txt'))
        schemas = [
            "{0}".format(a.strip())
            for a in parameters[self.SCHEMAS].split(',')
            if a.strip() not in ('public', 'lizsync', 'audit')
        ]
        schema_list =  ','.join(schemas)
        with open(sql_files['sync_schemas.txt'], 'w') as f:
            f.write(schema_list)
            feedback.pushInfo(self.tr('File sync_schemas.txt created'))


        # 6/ sync_id.txt
        # Add new sync history item in the central database
        # and get sync_id
        ####
        feedback.pushInfo(self.tr('ADD NEW SYNC HISTORY ITEM IN CENTRAL DATABASE'))
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
            status = 1
            sync_id = ''
            for a in data:
                sync_id = a[0]
            if sync_id:
                msg = self.tr('New synchronization history item has been added in the central database')
                msg+= ' : syncid = {0}'.format(sync_id)
                feedback.pushInfo(msg)
                with open(sql_files['sync_id.txt'], 'w') as f:
                    f.write(sync_id)
                    feedback.pushInfo(self.tr('File sync_id.txt created'))
            else:
                msg = self.tr('No synchronization item could be added !')
                feedback.pushInfo(msg)
                feedback.pushInfo(error_message)
                raise Exception(msg)
        else:
            msg = self.tr('No synchronization item could be added !')
            msg+= ' ' + error_message
            # feedback.pushInfo(msg)
            raise Exception(msg)

        # Create ZIP archive
        try:
            import zlib
            compression = zipfile.ZIP_DEFLATED
        except:
            compression = zipfile.ZIP_STORED
        modes = {
            zipfile.ZIP_DEFLATED: 'deflated',
            zipfile.ZIP_STORED:   'stored'
        }
        status = 1
        msg = ''
        zip_file = parameters[self.ZIP_FILE]
        with zipfile.ZipFile(zip_file, mode='w') as zf:
            for fname, fsource in sql_files.items():
                try:
                    zf.write(
                        fsource,
                        arcname=fname,
                        compress_type=compression
                    )
                except:
                    status = 0
                    msg+= self.tr("Error while zipping file") + ': ' + fname
                    raise Exception(msg)
        msg = self.tr('Package has been successfully created !')
        feedback.pushInfo(msg)

        return {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }
