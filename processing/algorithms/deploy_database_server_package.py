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
    QgsExpressionContextUtils
)
from PyQt5.QtSql import QSqlDatabase, QSqlQuery
import os, subprocess, tempfile, zipfile
from pathlib import Path
import processing
from .tools import *
from platform import system as psys

class DeployDatabaseServerPackage(QgsProcessingAlgorithm):
    """
    Exectute SQL on PostgreSQL database
    given host, port, dbname, user and password
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.
    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    CONNECTION_NAME_CLONE = 'CONNECTION_NAME_CLONE'
    POSTGRESQL_BINARY_PATH = 'POSTGRESQL_BINARY_PATH'
    ZIP_FILE = 'ZIP_FILE'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'deploy_database_server_package'

    def displayName(self):
        return self.tr('Deploy database package')

    def group(self):
        return self.tr('02 Package and deploy database data')

    def groupId(self):
        return 'lizsync_package'

    def shortHelpString(self):
        return getShortHelpString(os.path.basename(__file__))

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
        # central database
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

        # Clone database connection parameters
        connection_name_clone = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_clone')
        db_param_b = QgsProcessingParameterString(
            self.CONNECTION_NAME_CLONE,
            self.tr('PostgreSQL connection to the clone database'),
            defaultValue=connection_name_clone,
            optional=False
        )
        db_param_b.setMetadata({
            'widget_wrapper': {
                'class': 'processing.gui.wrappers_postgis.ConnectionWidgetWrapper'
            }
        })
        self.addParameter(db_param_b)

        # PostgreSQL binary path (with psql, pg_dump, pg_restore)
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

        self.addParameter(
            QgsProcessingParameterFile(
                self.ZIP_FILE, 'Full ZIP archive path',
                defaultValue=os.path.join(tempfile.gettempdir(), 'central_database_package.zip'),
                behavior=QgsProcessingParameterFile.File,
                optional=True
            )
        )

        # Clone database connection parameters
        connection_name_clone = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_clone')
        db_param_b = QgsProcessingParameterString(
            self.CONNECTION_NAME_CLONE,
            self.tr('PostgreSQL connection to the CLONE database'),
            defaultValue=connection_name_clone,
            optional=False
        )
        db_param_b.setMetadata({
            'widget_wrapper': {
                'class': 'processing.gui.wrappers_postgis.ConnectionWidgetWrapper'
            }
        })
        self.addParameter(db_param_b)

        # OUTPUTS
        # Add output for message
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING, self.tr('Output message')
            )
        )

    def checkParameterValues(self, parameters, context):

        # Check postgresql binary path
        postgresql_binary_path = parameters[self.POSTGRESQL_BINARY_PATH]
        test_bin = 'psql'
        if psys() == 'Windows':
            test_bin+= '.exe'
        has_bin_file = os.path.isfile(
            os.path.join(
                postgresql_binary_path,
                test_bin
            )
        )
        if not has_bin_file:
            return False, self.tr('The needed PostgreSQL binaries cannot be found in the specified path')

        # Check output zip path
        package_file = parameters[self.ZIP_FILE]
        if not os.path.exists(package_file):
            package_file = os.path.join(
                tempfile.gettempdir(),
                'central_database_package.zip'
            )
        ok = os.path.exists(package_file)

        # Check ZIP archive content
        if not ok:
            return False, self.tr("The ZIP archive does not exists in the specified path") + ": {0}".format(package_file)
        parameters[self.ZIP_FILE] = package_file

        return super(DeployDatabaseServerPackage, self).checkParameterValues(parameters, context)

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        package_file = parameters[self.ZIP_FILE]
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        connection_name_clone = parameters[self.CONNECTION_NAME_CLONE]
        postgresql_binary_path = parameters[self.POSTGRESQL_BINARY_PATH]

        # Check archive
        if not os.path.exists(package_file):
            raise Exception(self.tr('Package not found : %s' % package_file))

        # Check internet
        if not check_internet():
            raise Exception(self.tr('No internet connection'))

        msg = ''
        # Uncompress package
        feedback.pushInfo(self.tr('UNCOMPRESS PACKAGE') + ' {0}'.format(package_file))
        import zipfile
        dir_path = os.path.dirname(os.path.abspath(package_file))
        try:
            with zipfile.ZipFile(package_file) as t:
                zip = t.extractall(dir_path)
                feedback.pushInfo('Package uncompressed successfully')
        except:
            raise Exception(self.tr('Package extraction error'))

        # CLONE DATABASE
        # Get existing data to avoid recreating server_id for this machine
        feedback.pushInfo(self.tr('GET EXISTING METADATA TO AVOID RECREATING SERVER_ID FOR THIS CLONE'))
        clone_id = None
        clone_name = None
        sql = '''
        SELECT table_name
        FROM information_schema.tables
        WHERE table_name = 'server_metadata' and table_schema = 'lizsync';
        '''
        header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            connection_name_clone,
            sql
        )
        has_sync = False
        if ok:
            for a in data:
                if a[0] == 'server_metadata':
                    has_sync = True
                    feedback.pushInfo(self.tr('Clone database already has sync metadata table'))
        else:
            raise Exception(error_message)
        # get existing server_id
        if has_sync:
            sql = '''
            SELECT server_id, server_name
            FROM lizsync.server_metadata
            LIMIT 1;
            '''
            header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                connection_name_clone,
                sql
            )
            if ok:
                for a in data:
                    clone_id = a[0]
                    clone_name = a[1]
                    feedback.pushInfo(self.tr('Clone metadata are already set'))
                    feedback.pushInfo(self.tr('* server id') + ' = {0}'.format(clone_id))
                    feedback.pushInfo(self.tr('* server name') + ' = {0}'.format(clone_name))
            else:
                raise Exception(error_message)

        # Get synchronized schemas
        feedback.pushInfo(self.tr('GET THE LIST OF SYNCHRONIZED SCHEMAS FROM THE FILE sync_schemas.txt'))
        sync_schemas = ''
        with open(os.path.join(dir_path, 'sync_schemas.txt')) as f:
                sync_schemas = f.readline().strip()
        if sync_schemas == '':
            raise Exception(self.tr('No schema to syncronize'))

        # CLONE DATABASE
        # Run SQL scripts from archive with PSQL command
        feedback.pushInfo(self.tr('RUN SQL SCRIPT FROM THE DECOMPRESSED ZIP FILE'))
        a_sql = os.path.join(dir_path, '01_before.sql')
        b_sql = os.path.join(dir_path, '02_data.sql')
        c_sql = os.path.join(dir_path, '03_after.sql')
        d_sql = os.path.join(dir_path, '04_lizsync.sql')
        if not os.path.exists(a_sql) or not os.path.exists(b_sql) or not os.path.exists(c_sql):
            raise Exception(self.tr('SQL files not found'))

        # Build clone database connection parameters for psql
        status, uri, error_message = getUriFromConnectionName(connection_name_clone)
        if not uri:
            msg = self.tr('Error getting database connection information')
            feedback.pushInfo(msg)
            raise Exception(error_message)
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
            ]

        pgbin = 'psql'
        if psys() == 'Windows':
            pgbin+= '.exe'
        pgbin = os.path.join(
            postgresql_binary_path,
            pgbin
        )
        for i in (a_sql, b_sql, c_sql, d_sql):
            try:
                feedback.pushInfo(self.tr('Loading file') + ' {0} ....'.format(i))
                cmd = [
                    pgbin
                ] + cmdo + [
                    '--no-password',
                    '-f {0}'.format(i)
                ]
                # feedback.pushInfo('PSQL = %s' % ' '.join(cmd) )
                # Add password if needed
                myenv = { **os.environ }
                if not uri.service():
                    myenv = {**{'PGPASSWORD': uri.password()}, **os.environ }

                subprocess.run(
                    " ".join(cmd),
                    shell=True,
                    env=myenv
                )
                msg+= '* {0} -> OK'.format(i.replace(dir_path, ''))

                # Delete SQL scripts
                os.remove(i)
            except:
                raise Exception(self.tr('Error loading file') + ' {0}'.format(i))
            finally:
                feedback.pushInfo('* {0} has been loaded'.format(i.replace(dir_path, '')))

        # CLONE DATABASE
        # Add server_id in lizsync.server_metadata if needed
        feedback.pushInfo(self.tr('ADDING THE SERVER ID IN THE CLONE metadata table'))
        if clone_id and clone_name:
            sql = '''
            DELETE FROM lizsync.server_metadata;
            INSERT INTO lizsync.server_metadata (server_id, server_name)
            VALUES ( '{0}', '{1}' )
            RETURNING server_id, server_name
            '''.format(
                clone_id,
                clone_name
            )
        else:
            sql = '''
            DELETE FROM lizsync.server_metadata;
            INSERT INTO lizsync.server_metadata (server_name)
            VALUES ( concat('clone',  ' ', md5((now())::text) ) )
            RETURNING server_id, server_name
            '''
        header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            connection_name_clone,
            sql
        )
        if ok:
            for a in data:
                clone_id = a[0]
                clone_name = a[1]
                feedback.pushInfo(self.tr('Server metadata added in the clone database'))
                feedback.pushInfo(self.tr('* server id') + ' = {0}'.format(clone_id))
                feedback.pushInfo(self.tr('* server name') + ' = {0}'.format(clone_name))
        else:
            msg = self.tr('Error while adding server id in clone metadata table')
            feedback.pushInfo(msg)
            raise Exception(error_message)


        # CENTRAL DATABASE
        # Add an item in lizsync.synchronized_schemas
        # to know afterward wich schemas to use when performing sync
        feedback.pushInfo(self.tr('ADDING THE LIST OF SYNCHRONIZED SCHEMAS FOR THIS CLONE IN THE CENTRAL DATABASE '))
        sql = '''
            DELETE FROM lizsync.synchronized_schemas
            WHERE server_id = '{0}';
            INSERT INTO lizsync.synchronized_schemas
            (server_id, sync_schemas)
            VALUES
            ( '{0}', jsonb_build_array( '{1}' ) );
        '''.format(
            clone_id,
            "', '".join([ a.strip() for a in sync_schemas.split(',') ])
        )
        # feedback.pushInfo(sql)
        header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            connection_name_central,
            sql
        )
        if ok:
            msg = self.tr('List of synchronized schemas added in central database for this clone')
            feedback.pushInfo(msg)
        else:
            msg = self.tr('Error while adding the synchronized schemas in the central database')
            feedback.pushInfo(msg)
            raise Exception(error_message)

        # CENTRAL DATABASE - Add clone Id in the lizsync.history line
        # corresponding to this deployed package
        feedback.pushInfo(self.tr('ADD CLONE ID IN THE CENTRAL DATABASE HISTORY ITEM FOR THIS ARCHIVE DEPLOYEMENT'))
        with open(os.path.join(dir_path, 'sync_id.txt')) as f:
            sync_id = f.readline().strip()
            sql = '''
                UPDATE lizsync.history
                SET server_to = array_append(server_to, '{0}')
                WHERE sync_id = '{1}'
                ;
            '''.format(
                clone_id,
                sync_id
            )
            # feedback.pushInfo(sql)
            header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                connection_name_central,
                sql
            )
            if ok:
                msg = self.tr('History item has been successfully updated for this archive deployement in the central database')
                feedback.pushInfo(msg)
            else:
                msg = self.tr('Error while updating the history item for this archive deployement')
                feedback.pushInfo(msg)
                raise Exception(error_message)

        out = {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: 'SUCCESS'
        }
        return out

