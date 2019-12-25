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
    QgsProcessingParameterFileDestination,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber,
    QgsExpressionContextUtils
)

import os, subprocess
from datetime import date, datetime
from .tools import *
import zipfile
import tempfile

class PackageCentralDatabase(QgsProcessingAlgorithm):
    """
    Package central database into ZIP package
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.
    SCHEMAS = 'SCHEMAS'
    ZIP_FILE = 'ZIP_FILE'
    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'package_master_database'

    def displayName(self):
        return self.tr('Create a package from central database')

    def group(self):
        return self.tr('Package and deploy')

    def groupId(self):
        return 'lizsync_package'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return PackageCentralDatabase()

    def checkParameterValues(self, parameters, context):

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

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # INPUTS
        self.addParameter(
            QgsProcessingParameterString(
                self.SCHEMAS,
                self.tr('List of schemas to package. (schemas public, lizsync & audit are never processed)'),
                defaultValue='test',
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.ZIP_FILE,
                self.tr('Output archive file (ZIP)'),
                fileFilter='zip',
                optional=False
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


    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        msg = ''

        connection_name = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_central')

        # Create temporary files
        sql_file_list = [
            '01_before.sql',
            '02_data.sql',
            '03_after.sql',
            'sync_id.txt',
            'sync_schemas.txt'
        ]
        sql_files = {}
        tmpdir = tempfile.mkdtemp()
        for k in sql_file_list:
            path = os.path.join(tmpdir, k)
            sql_files[k] = path
        feedback.pushInfo(str(sql_files))

        # Get the list of input schemas
        schemas = [
            '"{0}"'.format(a.strip())
            for a in parameters[self.SCHEMAS].split(',')
            if a.strip() not in ('public', 'lizsync', 'audit')
        ]
        schemas_sql =  ', '.join(schemas)

        # 1/ 01_before.sql
        ####
        feedback.pushInfo(self.tr('Create script 01_before.sql'))
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


        # Add missing UID columns into central server tables
        # only for given list of schemas
        ####
        schemas = [
            "'{0}'".format(a.strip())
            for a in parameters[self.SCHEMAS].split(',')
            if a.strip() not in ('public', 'lizsync', 'audit')
        ]
        schemas_sql =  ', '.join(schemas)
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
        [header, data, rowCount, ok, error_message] = fetchDataFromSqlQuery(
            connection_name,
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
                msg = self.tr('UID columns have been successfully added in the following tables:')
                feedback.pushInfo(msg)
                for n in names:
                    feedback.pushInfo('* ' + n)
                msg+= ', '.join(names)
            else:
                msg = self.tr('No UID columns have been added.')
                feedback.pushInfo(msg)

        # 2/ 02_data.sql
        ####
        feedback.pushInfo(self.tr('Create script 02_data.sql'))
        # Create pg_dump command
        [uri, error_message] = getUriFromConnectionName(connection_name)
        if not uri:
            raise Exception(self.tr('Error getting database connection information'))
        if uri.service():
            cmdo = [
                'service={0}'.format(uri.service())
            ]
        else:
            cmdo = [
                '-h {0}'.format(uri.host()),
                '-p {0}'.format(uri.port()),
                '-d {0}'.format(uri.database()),
                '-U {0}'.format(uri.username()),
                '-W'
            ]

        cmd = [
            'pg_dump'
        ] + cmdo + [
            '--no-acl',
            '--no-owner',
            '-Fp',
            '-f {0}'.format(sql_files['02_data.sql'])
        ]
        # Add given schemas
        for s in schemas:
            cmd.append('-n {0}'.format(s))

        # Run command
        try:
            feedback.pushInfo('PG_DUMP = %s' % ' '.join(cmd) )

            # Add password if needed
            myenv = { **os.environ }
            if not uri.service():
                myenv = {**{'PGPASSWORD': uri.password()}, **os.environ }

            subprocess.run(
                " ".join(cmd),
                shell=True,
                env=myenv
            )

        except:
            raise Exception(self.tr('Error dumping database'))
        finally:
            feedback.pushInfo(self.tr('Database has been dumped'))


        # 3/ 03_after.sql
        ####
        feedback.pushInfo(self.tr('Create script 03_after.sql'))
        sql = ''

        # 6/ Add audit trigger in all table in given schemas
        schemas = [
            "'{0}'".format(a.strip())
            for a in parameters[self.SCHEMAS].split(',')
            if a.strip() not in ('public', 'lizsync', 'audit')
        ]
        schemas_sql = ', '.join(schemas)
        sql+= '''
            SELECT count(*) AS nb
            FROM (
                SELECT audit.audit_table((quote_ident(table_schema) || '.' || quote_ident(table_name))::text)
                FROM information_schema.tables
                WHERE table_schema IN ( {0} )
                AND table_type = 'BASE TABLE'
                AND (quote_ident(table_schema) || '.' || quote_ident(table_name))::text
                    NOT IN (
                        SELECT (tgrelid::regclass)::text
                        FROM pg_trigger
                        WHERE tgname LIKE 'audit_trigger_%'
                    )
            ) foo;
        '''.format(
            schemas_sql
        )
        # write content into temp file
        with open(sql_files['03_after.sql'], 'w') as f:
            f.write(sql)


        # 4/ Add schemas into file
        ####
        schemas = [
            "{0}".format(a.strip())
            for a in parameters[self.SCHEMAS].split(',')
            if a.strip() not in ('public', 'lizsync', 'audit')
        ]
        schema_list =  ','.join(schemas)
        with open(sql_files['sync_schemas.txt'], 'w') as f:
            f.write(schema_list)


        # 5/ Add new sync history item in the central database
        # and get sync_id
        ####
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
        [header, data, rowCount, ok, error_message] = fetchDataFromSqlQuery(
            connection_name,
            sql
        )
        if ok:
            status = 1
            sync_id = ''
            for a in data:
                sync_id = a[0]
            if sync_id:
                msg = self.tr('New synchronization item has been added in the central database')
                msg+= ' : syncid = {0}'.format(sync_id)
                feedback.pushInfo(msg)
                with open(sql_files['sync_id.txt'], 'w') as f:
                    f.write(sync_id)
            else:
                msg = self.tr('No synchronization item could be added !')
                feedback.pushInfo(msg)
        else:
            msg = self.tr('No synchronization item could be added !')
            msg+= ' ' + error_message
            feedback.pushInfo(msg)

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
                    break
        msg = self.tr('Package has been successfully created !')

        return {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }
