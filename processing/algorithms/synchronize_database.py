# -*- coding: utf-8 -*-

"""
***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""

__author__ = '3liz'
__date__ = '2018-12-19'
__copyright__ = '(C) 2018 by 3liz'

from PyQt5.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessingParameterString,
    QgsProcessingOutputString,
    QgsExpressionContextUtils
)
import processing
from .tools import *

class SynchronizeDatabase(QgsProcessingAlgorithm):
    """
    """
    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    CONNECTION_NAME_CLONE = 'CONNECTION_NAME_CLONE'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self, config={}):
        return SynchronizeDatabase()

    def __init__(self):
        super().__init__()

    def name(self):
        return 'synchronize_database'

    def displayName(self):
        return self.tr('Two-way database synchronization between central and clone databases')

    def group(self):
        return self.tr('03 Synchronize data and files')

    def groupId(self):
        return 'lizsync_sync'

    def shortHelpString(self):
        short_help = self.tr(
            ' This scripts run a two-way data synchronization between the central and clone database.'
            '<br>'
            '<br>'
            ' The data to synchronize are listed by reading'
            ' the content of the "audit.logged_actions" of each database,'
            ' since the last synchronization or the last deployement of ZIP package.'
            '<br>'
            '<br>'
            ' This audit data are transformed into INSERT/UPDATE/DELETE SQL queries'
            ' which are played in the databases in this order:'
            '<br>'
            ' 1/ From the CENTRAL to the CLONE database'
            '<br>'
            ' 2/ From the CLONE to the CENTRAL database'
            '<br>'
            '<br>'
            'The central database stores which clone has replayed which audited modification'
            ', and keeps an history of synchronization items.'

        )
        return short_help

    def initAlgorithm(self, config=None):
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

        # OUTPUTS
        # Add output for message
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING, self.tr('Output message')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):

        uid_field = 'uid'
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        connection_name_clone = parameters[self.CONNECTION_NAME_CLONE]
        if not check_internet():
            feedback.pushInfo(self.tr('No internet connection'))
            raise Exception(self.tr('No internet connection'))

        # Send some information to the user
        feedback.pushInfo(self.tr('Internet connection OK'))

        # Compute the number of steps to display within the progress bar
        total = 100.0 / 2

        central_id = None
        clone_id = None

        # Get central database server id
        sql = '''
            SELECT
                server_id
            FROM lizsync.server_metadata
            LIMIT 1;
        '''
        header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            connection_name_central,
            sql
        )
        if not ok:
            feedback.pushInfo(sql)
            raise Exception(error_message)
        for a in data:
            central_id = a[0]
            feedback.pushInfo(self.tr('Server id') +' = %s' % central_id)

        # Get clone database server id
        sql = '''
            SELECT
                server_id
            FROM lizsync.server_metadata
            LIMIT 1;
        '''
        header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            connection_name_clone,
            sql
        )
        if not ok:
            feedback.pushInfo(sql)
            raise Exception(error_message)
        for a in data:
            clone_id = a[0]
            feedback.pushInfo(self.tr('Clone id') + ' = %s' % clone_id)


        # CENTRAL -> CLONE
        feedback.pushInfo('****** CENTRAL TO CLONE *******')

        # Get last synchro
        sql = '''
            SELECT
                max_action_tstamp_tx::text AS max_action_tstamp_tx,
                max_event_id
            FROM lizsync.history
            WHERE True
            AND server_from = '{0}'
            AND '{1}' = ANY (server_to)
            AND sync_status = 'done'
            ORDER BY sync_time DESC
            LIMIT 1
        '''.format(
            central_id,
            clone_id
        )
        last_sync = None
        header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            connection_name_central,
            sql
        )
        if not ok:
            feedback.pushInfo(sql)
            raise Exception(error_message)
        for a in data:
            last_sync = {
                'max_action_tstamp_tx': a[0],
                'max_event_id': a[1]
            }

        # Get audit log since last sync
        # We also get the SQL to replay via the get_event_sql function
        sql = '''
            SELECT
                event_id,
                action_tstamp_tx::text AS action_tstamp_tx,
                lizsync.get_event_sql(event_id, '{0}') AS action
            FROM audit.logged_actions,
            (
                SELECT sync_schemas
                FROM lizsync.synchronized_schemas
                WHERE server_id = '{1}'
                LIMIT 1
            ) AS f

            WHERE True

            -- modifications do not come from clone database
            AND (sync_data->>'origin' != '{1}' OR sync_data->>'origin' IS NULL)

            -- modifications have not yet been replayed in the clone database
            AND (NOT (sync_data->'replayed_by' ? '{1}') OR sync_data->'replayed_by' = jsonb_build_object() )

            -- modifications sont situées après la dernière synchronisation
            -- MAX_ACTION_TSTAMP_TX Par ex: 2019-04-20 12:00:00+02
            AND action_tstamp_tx > '{2}'

            -- et pour lesquelles l'ID est supérieur
            -- MAX_EVENT_ID
            AND event_id > {3}

            -- et pour les schémas listés
            AND sync_schemas ? schema_name

            ORDER BY event_id;
        '''.format(
            uid_field,
            clone_id,
            last_sync['max_action_tstamp_tx'],
            last_sync['max_event_id']
        )
        ids = []
        max_action_tstamp_tx = None
        actions = []
        header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            connection_name_central,
            sql
        )
        if not ok:
            feedback.pushInfo(sql)
            raise Exception(error_message)
        for a in data:
            ids.append(int(a[0]))
            max_action_tstamp_tx = a[1]
            actions.append(a[2])
        if rowCount > 0:
            feedback.pushInfo(
                self.tr('Number of features to synchronize') + ' = {0}'.format(rowCount)
            )
            # Calculate min and max event ids
            min_event_id = min(ids)
            max_event_id = max(ids)

            # Insert a new synchronization item in central db
            sql = '''
                INSERT INTO lizsync.history (
                    server_from, server_to,
                    min_event_id, max_event_id, max_action_tstamp_tx,
                    sync_type, sync_status
                )
                VALUES (
                    '{0}', ARRAY['{1}'],
                    {2}, {3}, '{4}',
                    'partial', 'pending'
                )
                RETURNING
                    sync_id
            '''.format(
                central_id, clone_id,
                min_event_id, max_event_id, max_action_tstamp_tx
            )

            header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                connection_name_central,
                sql
            )
            if not ok:
                feedback.pushInfo(sql)
                raise Exception(error_message)
            for a in data:
                sync_id = a[0]
                feedback.pushInfo(
                    'New history item has been created in the central database'
                )

            # Replay SQL queries in clone db
            # We disable triggers to avoid adding more rows to the local audit logged_actions table
            sql = '''
                SET session_replication_role = replica;
                {0};
                SET session_replication_role = DEFAULT;
            '''.format( ';'.join(actions) )
            # feedback.pushInfo(sql)
            header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                connection_name_clone,
                sql
            )
            if not ok:
                feedback.pushInfo(sql)
                raise Exception(error_message)
            feedback.pushInfo(
                self.tr('SQL queries have been replayed from the central to the clone database')
            )

            # Modify central server audit logged actions
            sql = '''
                UPDATE audit.logged_actions
                SET sync_data = jsonb_set(
                    sync_data,
                    '{{"replayed_by"}}',
                    sync_data->'replayed_by' || jsonb_build_object('{0}', '{1}'),
                    true
                )
                WHERE event_id IN ({2})
            '''.format(
                clone_id,
                sync_id,
                ', '.join([str(i) for i in ids])
            )
            header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                connection_name_central,
                sql
            )
            if not ok:
                feedback.pushInfo(sql)
                raise Exception(error_message)
            feedback.pushInfo(
                self.tr('Logged actions sync_data has been updated in the central database with the clone id')
            )

            # Modify central server synchronization item
            sql = '''
                UPDATE lizsync.history
                SET (sync_status) = ('done')
                WHERE True
                AND sync_id = '{0}'
            '''.format(
                sync_id
            )
            header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                connection_name_central,
                sql
            )
            if not ok:
                feedback.pushInfo(sql)
                raise Exception(error_message)
            feedback.pushInfo(
                self.tr('History sync_status has been updated to "done" in the central database')
            )

        else:
            # No data to sync
            feedback.pushInfo(
                self.tr('No data to synchronize from the central database')
            )

        feedback.setProgress(int(1 * total))


        # CLONE -> CENTRAL
        feedback.pushInfo('****** CLONE TO CENTRAL *******')

        # Get all clone audit log
        # no filter by date because clone date cannot be trusted
        # we choose to delete all audit logged_actions when sync is done
        # to start fresh
        sql = '''
            SELECT
                lizsync.get_event_sql(event_id, '{0}') AS action
            FROM audit.logged_actions
            WHERE True
            ORDER BY event_id;
        '''.format(
            uid_field
        )
        actions = []
        header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            connection_name_clone,
            sql
        )
        if not ok:
            feedback.pushInfo(sql)
            raise Exception(error_message)
        if rowCount > 0:
            feedback.pushInfo(
                self.tr('Number of features to synchronize') + ' = {0}'.format(rowCount)
            )
            for a in data:
                actions.append(a[0])

            # Insert a new synchronization item in central db
            sql = '''
            INSERT INTO lizsync.history (
                server_from, server_to,
                min_event_id, max_event_id, max_action_tstamp_tx,
                sync_type, sync_status
            )
            VALUES (
                '{0}', ARRAY['{1}'],
                NULL, NULL, NULL,
                'partial', 'pending'
            )
            RETURNING
                sync_id
            '''.format(
                clone_id,
                central_id
            )
            sync_id = None
            header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                connection_name_central,
                sql
            )
            if not ok:
                feedback.pushInfo(sql)
                raise Exception(error_message)
            for a in data:
                sync_id = a[0]
                feedback.pushInfo(
                    self.tr('New history item has been created in the central database')
                )

            # Replay SQL queries to central server db
            # The session variables are used by the audit function
            # to fill the sync_data field
            sql = '''
            SET SESSION "lizsync.server_from" = '{0}';
            SET SESSION "lizsync.server_to" = '{1}';
            SET SESSION "lizsync.sync_id" = '{2}';
            {3}
            '''.format(
                clone_id,
                central_id,
                sync_id,
                ';'.join(actions)
            )
            header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                connection_name_central,
                sql
            )
            if not ok:
                feedback.pushInfo(sql)
                raise Exception(error_message)

            # Delete all data from clone audit logged_actions
            sql = '''
            TRUNCATE audit.logged_actions
            RESTART IDENTITY;
            '''
            header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                connection_name_clone,
                sql
            )
            if not ok:
                feedback.pushInfo(sql)
                raise Exception(error_message)

            # Modify central server synchronization item
            sql = '''
                UPDATE lizsync.history
                SET (sync_status) = ('done')
                WHERE True
                AND sync_id = '{0}'
            '''.format(
                sync_id
            )
            header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                connection_name_central,
                sql
            )
            if not ok:
                feedback.pushInfo(sql)
                raise Exception(error_message)
        else:
            # No data to sync
            feedback.pushInfo('No data to synchronize from the clone database')


        feedback.setProgress(int(2 * total))

        feedback.pushInfo('*************')
        return {self.OUTPUT_STRING: 'Synchronization done'}
