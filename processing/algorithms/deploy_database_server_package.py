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
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingUtils,
    QgsProcessingException,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFile,
    QgsProcessingOutputString,
)
from PyQt5.QtSql import QSqlDatabase, QSqlQuery
import os, subprocess
from pathlib import Path
import processing

class DeployDatabaseServerPackage(QgsProcessingAlgorithm):
    """
    Exectute SQL on PostgreSQL database
    given host, port, dbname, user and password
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    DBHOST = 'DBHOST'
    DBPORT = 'DBPORT'
    DBNAME = 'DBNAME'
    DBUSER = 'DBUSER'
    DBPASS = 'DBPASS'
    ARCHIVE = 'ARCHIVE'
    PACKAGE_FILE = ''
    OUTPUT_STRING = 'OUTPUT_STRING'

    servers = {
        'central': {
            'host': 'qgisdb-valabre.lizmap.com', 'port': 5432, 'dbname': 'lizmap_valabre_geopoppy',
            'user': 'geopoppy@valabre', 'password':'gfrkGd5UvrJbCxE'
        },
        'geopoppy': {
            'host': '172.24.1.1', 'port': 5432, 'dbname': 'geopoppy',
            'user': 'docker', 'password':'docker'
        }
    }

    def name(self):
        return 'deploy_database_server_package'

    def displayName(self):
        return self.tr('Deploy database package')

    def group(self):
        return self.tr('Package and deploy')

    def groupId(self):
        return 'lizsync_package'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return DeployDatabaseServerPackage()

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # INPUTS
        self.addParameter(
            QgsProcessingParameterString(
                self.DBHOST, 'Host',
                defaultValue='172.24.1.1',
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.DBPORT, 'Port',
                defaultValue=5432,
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.DBNAME, 'Database',
                defaultValue='geopoppy',
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.DBUSER, 'User',
                defaultValue='docker',
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.DBPASS, 'Password',
                defaultValue='docker',
                optional=False
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.ARCHIVE, 'Full archive path. Leave empty inside GeoPoppy',
                defaultValue='/projects/geopoppy/archives/geopoppy_package.tar.gz',
                optional=True
            )
        )

        # OUTPUTS
        # Add output for message
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING, self.tr('Output message')
            )
        )

    def checkParameterValues(self, parameters, context):
        # Check inputs

        package_file = parameters[self.ARCHIVE]
        if not os.path.exists(package_file):
            package_file = os.path.join(
                '/projects/geopoppy/archives/geopoppy_package.tar.gz',
                'geopoppy_package.tar.gz'
            )
        ok = os.path.exists(package_file)

        # Check database content
        if not ok:
            return False, "The package does not exists: {0}".format(package_file)
        parameters[self.ARCHIVE] = package_file

        return super(GeopoppyDeployServerPackage, self).checkParameterValues(parameters, context)

    def check_internet(self):
        # return True
        import requests
        url='https://www.google.com/'
        timeout=5
        try:
            _ = requests.get(url, timeout=timeout)
            return True
        except requests.ConnectionError:
            return False

    def run_sql(self, sql, servername, parameters, context, feedback):
        profil = self.servers[servername]

        exec_result = processing.run("script:geopoppy_execute_sql_on_database", {
            'DBHOST': profil['host'],
            'DBPORT': profil['port'],
            'DBNAME': profil['dbname'],
            'DBUSER': profil['user'],
            'DBPASS': profil['password'],
            'INPUT_SQL': sql
        }, context=context, feedback=feedback)
        return exec_result

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        dbhost = parameters[self.DBHOST]
        dbport = parameters[self.DBPORT]
        dbname = parameters[self.DBNAME]
        dbuser = parameters[self.DBUSER]
        dbpass = parameters[self.DBPASS]
        package_file = parameters[self.ARCHIVE]

        # Check archive
        if not os.path.exists(package_file):
            raise Exception(self.tr('Package not found : %s' % package_file))

        # Check internet
        if not self.check_internet():
            raise Exception(self.tr('No internet connection'))

        msg = ''
        # Uncompress package
        feedback.pushInfo('Uncompress package {0}'.format(package_file))
        import tarfile
        dir_path = os.path.dirname(os.path.abspath(package_file))
        try:
            with tarfile.open(package_file) as t:
                tar = t.extractall(dir_path)
        except:
            raise Exception(self.tr('Package extraction error'))
        finally:
            print('remove')
            #os.remove(package_file)

        # Get existing data to avoid recreating server_id for this machine
        geopoppy_id = None
        geopoppy_name = None
        feedback.pushInfo('Check if metadata is already in sync schema')
        sql = "SELECT * FROM information_schema.tables WHERE table_name = 'server_metadata' and table_schema = 'sync';"
        get_sql = self.run_sql(sql, 'geopoppy', parameters, context, feedback)
        has_sync = False
        if 'OUTPUT_LAYER' in get_sql:
            for feature in get_sql['OUTPUT_LAYER'].getFeatures():
                if feature['table_name'] == 'server_metadata':
                    has_sync = True
        if has_sync:
            sql = 'SELECT server_id, server_name FROM sync.server_metadata LIMIT 1;'
            get_sql = self.run_sql(sql, 'geopoppy', parameters, context, feedback)
            if 'OUTPUT_LAYER' in get_sql:
                for feature in get_sql['OUTPUT_LAYER'].getFeatures():
                    geopoppy_id = feature['server_id']
                    geopoppy_name = feature['server_name']
                    feedback.pushInfo('* original geopoppy = %s / %s' % (geopoppy_id, geopoppy_name))

        # Get synchronized schemas
        sync_schemas = ''
        with open(os.path.join(dir_path, 'sync_schemas.txt')) as f:
                sync_schemas = f.readline().strip()
        if sync_schemas == '':
            raise Exception(self.tr('No schema to syncronize'))

        # LOCAL SERVER
        # Run SQL scripts from archive
        a_sql = os.path.join(dir_path, '01_before.sql')
        b_sql = os.path.join(dir_path, '02_data.sql')
        c_sql = os.path.join(dir_path, '03_after.sql')
        if not os.path.exists(a_sql) or not os.path.exists(b_sql) or not os.path.exists(c_sql):
            raise Exception(self.tr('SQL files not found'))

        for i in (a_sql, b_sql, c_sql):
            try:
                cmd = [
                    'psql',
                    '-h {0}'.format(dbhost),
                    '-p {0}'.format(dbport),
                    '-d {0}'.format(dbname),
                    '-U {0}'.format(dbuser),
                    '--no-password',
                    '-f {0}'.format(i)
                ]
                feedback.pushInfo('PSQL = %s' % ' '.join(cmd) )
                myenv = {**{'PGPASSWORD': dbpass}, **os.environ }

                subprocess.run(
                    " ".join(cmd),
                    shell=True,
                    env=myenv
                )
                msg+= '* {0} -> OK'.format(i.replace(dir_path, ''))

                # Delete SQL scripts
                os.remove(i)
            except:
                raise Exception(self.tr('Error loading file {0}'.format(i)))
            finally:
                feedback.pushInfo('* {0} has been loaded'.format(i.replace(dir_path, '')))

        # Add server_id in sync.server_metadata if needed
        if geopoppy_id and geopoppy_name:
            sql = '''
            INSERT INTO sync.server_metadata (server_id, server_name)
            VALUES ( '{0}', '{1}' )
            RETURNING server_id, server_name
            '''.format(
                geopoppy_id,
                geopoppy_name
            )
        else:
            sql = '''
            INSERT INTO sync.server_metadata (server_name)
            VALUES ( concat('geopoppy ', '{0}' , ' ', md5((now())::text) ) )
            RETURNING server_id, server_name
            '''.format( sync_schemas )
        get_sql = self.run_sql(sql, 'geopoppy', parameters, context, feedback)
        if 'OUTPUT_LAYER' in get_sql:
            for feature in get_sql['OUTPUT_LAYER'].getFeatures():
                geopoppy_id = feature['server_id']
                geopoppy_name = feature['server_name']
                feedback.pushInfo('* geopoppy id = %s' % geopoppy_id)
                feedback.pushInfo('* geopoppy name = %s' % geopoppy_name)


        # CENTRAL SERVER SIDE - Add an item in sync.synchronized_schemas
        # To know afterward wich schemas to use when performing sync
        sql = '''
            DELETE FROM sync.synchronized_schemas
            WHERE server_id = '{0}';
            INSERT INTO sync.synchronized_schemas
            (server_id, sync_schemas)
            VALUES
            ( '{0}', jsonb_build_array( '{1}' ) );
        '''.format(
            geopoppy_id,
            "', '".join([ a.strip() for a in sync_schemas.split(',') ])
        )
        feedback.pushInfo(sql)
        get_sql = self.run_sql(sql, 'central', parameters, context, feedback)

        # CENTRAL SERVER SIDE - Add geopoppy Id in the sync.history line
        # corresponding to this deployed package
        with open(os.path.join(dir_path, 'sync_id.txt')) as f:
            sync_id = f.readline().strip()
            sql = '''
                UPDATE sync.history
                SET server_to = array_append(server_to, '{0}')
                WHERE sync_id = '{1}'
                ;
            '''.format(
                geopoppy_id,
                sync_id
            )
            feedback.pushInfo(sql)
            get_sql = self.run_sql(sql, 'central', parameters, context, feedback)

        out = {
            self.OUTPUT_STRING: msg
        }
        return out

# ## Add sync item in sync.history table
# sql= '''
    # INSERT INTO sync.history
    # (server_from, min_event_id, max_event_id, max_action_tstamp_tx, sync_type, sync_status)
    # VALUES (
        # (SELECT server_id FROM sync.server_metadata LIMIT 1),
        # (SELECT Coalesce(min(event_id),-1) FROM audit.logged_actions),
        # (SELECT Coalesce(max(event_id),0) FROM audit.logged_actions),
        # (SELECT Coalesce(max(action_tstamp_tx), now()) FROM audit.logged_actions),
        # 'full',
        # 'done'
    # )
    # RETURNING sync_id;
    # '''
# ##sync_id = ?

# ## Add audit schema and functions
# audit.sql

# ## Add audit triggers on all table in the schema $SRV_SCHEMA"
# sql = '''
    # SELECT count(*) nb FROM (
        # SELECT audit.audit_table((quote_ident(table_schema) || '.' || quote_ident(table_name))::text)
        # FROM information_schema.tables
        # WHERE table_schema = '$SRV_SCHEMA'
        # AND table_type = 'BASE TABLE'
        # AND (quote_ident(table_schema) || '.' || quote_ident(table_name))::text NOT IN (
            # SELECT (tgrelid::regclass)::text
            # FROM pg_trigger
            # WHERE tgname LIKE 'audit_trigger_%'
        # )
    # ) foo
    # '''


