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
# Original

# CENTRAL : Get central database server id
# CLONE   : Get clone database server id
# CENTRAL : Get last synchro made from the central database to this clone
# CENTRAL : Get audit log since last sync, calculate min and max event ids
# CENTRAL : Insert a new synchronization item in central db
# CLONE   : Replay SQL queries in clone db (disable triggers)
# CENTRAL : Modify central server audit logged actions (sync_data replayed by)
# CENTRAL : Modify central server synchronization item central->clone
# CLONE   : Get all clone audit log
# CENTRAL : Insert a new synchronization item in central db
# CENTRAL : Replay SQL queries to central server db (SET SESSION lyzsync.server_from, lyzsync.server_to, lyzsync.sync_id
# CLONE   : Delete all data from clone audit logged_actions
# CENTRAL : Modify central server synchronization item clone->central

# Evolution

# CENTRAL : Get central database server id
# CLONE   : Get clone database server id
# CENTRAL : Get last synchro made from the central database to this clone
# CENTRAL : Get audit log since last sync, calculate min and max event ids
# CENTRAL : Insert a new synchronization item in central

# CLONE   : Get all clone audit log
# CENTRAL : Insert a new synchronization item in central db

# PYTHON  : Compare central and clone logs

# CLONE   : Replay modified SQL queries in clone db (disable triggers)
# CENTRAL : Modify central server audit logged actions (sync_data replayed by)
# CENTRAL : Modify central server synchronization item

# CENTRAL : Replay modified SQL queries to central server db (SET SESSION lyzsync.server_from, lyzsync.server_to, lyzsync.sync_id)
# CLONE   : Delete all data from clone audit logged_actions
# CENTRAL : Modify central server synchronization item clone->central

__author__ = '3liz'
__date__ = '2018-12-19'
__copyright__ = '(C) 2018 by 3liz'

from PyQt5.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterString,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber
)
import processing
from .tools import *
from ...qgis_plugin_tools.tools.i18n import tr

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

    def createInstance(self, config={}):
        return SynchronizeDatabase()

    def __init__(self):
        super().__init__()

    def name(self):
        return 'synchronize_database'

    def displayName(self):
        return tr('Two-way database synchronization between central and clone databases')

    def group(self):
        return tr('03 Synchronize data and files')

    def groupId(self):
        return 'lizsync_sync'

    def shortHelpString(self):
        short_help = tr(
            ' This scripts run a two-way data synchronization between the central and clone database.'
            '\n'
            '\n'
            ' The data to synchronize are listed by reading'
            ' the content of the "audit.logged_actions" of each database,'
            ' since the last synchronization or the last deployement of ZIP package.'
            '\n'
            '\n'
            ' This audit data are transformed into INSERT/UPDATE/DELETE SQL queries'
            ' which are played in the databases in this order:'
            '\n'
            ' 1/ From the CENTRAL to the CLONE database'
            '\n'
            ' 2/ From the CLONE to the CENTRAL database'
            '\n'
            '\n'
            'The central database stores which clone has replayed which audited modification'
            ', and keeps an history of synchronization items.'

        )
        return short_help

    def initAlgorithm(self, config=None):
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

        # Clone database connection parameters
        connection_name_clone = ls.variable('postgresql:clone/name')
        db_param_b = QgsProcessingParameterString(
            self.CONNECTION_NAME_CLONE,
            tr('PostgreSQL connection to the clone database'),
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
            QgsProcessingOutputNumber(
                self.OUTPUT_STATUS, tr('Output status')
            )
        )
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING, tr('Output message')
            )
        )

    def checkParameterValues(self, parameters, context):

        # Check connections
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        connection_name_clone = parameters[self.CONNECTION_NAME_CLONE]
        ok, uri, msg = getUriFromConnectionName(connection_name_central, True)
        if not ok:
            return False, msg
        ok, uri, msg = getUriFromConnectionName(connection_name_clone, True)
        if not ok:
            return False, msg

        return super(SynchronizeDatabase, self).checkParameterValues(parameters, context)

    def getLastAuditLogs(self, source='central', central_id, clone_id, excluded_columns):
        '''
        Get logs from audit logged_actions table
        '''
        if source == 'central':
            # Get last synchro made from the central database to this clone
            # Get audit log since this last sync
            # We also get the SQL to replay via the get_event_sql function
            sql = '''
                WITH
                last_sync AS (
                    SELECT
                        max_action_tstamp_tx,
                        max_event_id
                    FROM lizsync.history
                    WHERE True
                    AND server_from = '{central_id}'
                    AND '{clone_id}' = ANY (server_to)
                    AND sync_status = 'done'
                    ORDER BY sync_time DESC
                    LIMIT 1
                ),
                schemas AS (
                    SELECT sync_schemas
                    FROM lizsync.synchronized_schemas
                    WHERE server_id = '{clone_id}'
                    LIMIT 1
                )
                SELECT
                    event_id,
                    action_tstamp_tx::text AS action_tstamp_tx,
                    concat(schema_name, '.', table_name) AS ident,
                    action,
                    CASE
                        WHEN sync_data->>'origin' IS NULL THEN 'central'
                        ELSE 'clone'
                    END AS origine,
                    Coalesce(
                        lizsync.get_event_sql(event_id, '{uid_field}', {excluded_columns}),
                        ''
                    ) AS action
                FROM audit.logged_actions, last_sync, schemas

                WHERE True

                -- modifications do not come from clone database
                AND (sync_data->>'origin' != '{clone_id}' OR sync_data->>'origin' IS NULL)

                -- modifications have not yet been replayed in the clone database
                AND (NOT (sync_data->'replayed_by' ? '{clone_id}') OR sync_data->'replayed_by' = jsonb_build_object() )

                -- modifications sont situées après la dernière synchronisation
                -- MAX_ACTION_TSTAMP_TX Par ex: 2019-04-20 12:00:00+02
                AND action_tstamp_tx > last_sync.max_action_tstamp_tx

                -- et pour lesquelles l'ID est supérieur
                -- MAX_EVENT_ID
                AND event_id > last_sync.max_event_id

                -- et pour les schémas listés
                AND sync_schemas ? schema_name

                ORDER BY event_id;
            '''.format(
                central_id=central_id,
                clone_id=clone_id,
                uid_field='uid',
                excluded_columns=excluded_columns
            )
            ids = []
            max_action_tstamp_tx = None
            actions = []
            header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                connection_name_central,
                sql
            )
        else:
            # Get all logs from clone database
            sql = '''
                SELECT
                    event_id,
                    action_tstamp_tx::text AS action_tstamp_tx,
                    concat(schema_name, '.', table_name) AS ident,
                    action,
                    'clone' AS origine,
                    Coalesce(
                        lizsync.get_event_sql(event_id, '{0}', {1}),
                        ''
                    ) AS action
                FROM audit.logged_actions
                WHERE True
                ORDER BY event_id;
            '''.format(
                uid_field,
                excluded_columns
            )
            header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                connection_name_clone,
                sql
            )
        if not ok:
            error_message += ' ' + sql

        return data, rowCount, ok, error_message

    def analyseAuditLogs(self, central_logs, clone_logs, feedback)
        '''
        Parse logs and compare central and clone logs
        Find conflicts and return modified logs
        '''


        return central_logs, clone_logs

    def replayLogs(self, target='central', feedback):
        '''
        Replay logs (raw or updated) to the target database
        '''
        return

    def processAlgorithm(self, parameters, context, feedback):

        output = {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: ''
        }

        uid_field = 'uid'
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        connection_name_clone = parameters[self.CONNECTION_NAME_CLONE]

        # Send some information to the user
        feedback.pushInfo(tr('Internet connection OK'))

        # Compute the number of steps to display within the progress bar
        total = 100.0 / 2

        central_id = None
        clone_id = None

        # Get the list of excluded columns
        ls = lizsyncConfig()
        var_excluded_columns = ls.variable('general/excluded_columns')
        if var_excluded_columns:
            ec = [
                "'{0}'".format(a.strip())
                for a in var_excluded_columns.split(',')
                if a.strip() not in ('uid')
            ]
            excluded_columns = "ARRAY[{0}]::text[]".format(
                ','.join(ec)
            )
        else:
            excluded_columns = 'NULL'

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
            m = error_message+ ' '+ sql
            return returnError(output, m, feedback)
        for a in data:
            central_id = a[0]
            feedback.pushInfo(tr('Server id') +' = %s' % central_id)

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
            m = error_message+ ' '+ sql
            return returnError(output, m, feedback)
        for a in data:
            clone_id = a[0]
            feedback.pushInfo(tr('Clone id') + ' = %s' % clone_id)


        # Get audit logs since last synchronization
        # from central
        feedback.pushInfo(tr('Get central server audit log since last synchronization'))
        central_logs, central_count, central_ok, central_error_message = self.getLastAuditLogs('central', feedback)
        if not central_ok:
            return returnError(output, central_error_message, feedback)

        # from clone
        feedback.pushInfo(tr('Get clone audit log since last synchronization'))
        clone_logs, clone_count, clone_ok, clone_error_message = self.getLastAuditLogs('clone', feedback)
        if not clone_ok:
            return returnError(output, clone_error_message, feedback)

        # Analyse logs and handle conflicts
        feedback.pushInfo(tr('Analyse logs and handle conflicts'))
        central_logs, clone_logs, ok, error_message = self.analyseAuditLogs(central_id, clone_id)
        if not ok:
            return returnError(output, error_message, feedback)



        for a in data:
            ids.append(int(a[0]))
            max_action_tstamp_tx = a[1]
            actions.append(a[5])
            # store object
            central_to_clone.append(a)

        feedback.pushInfo(
            'CENTRAL : ' + tr('Get audit logs since last synchronization')
        )

        return returnError(output, 'FIN', feedback)

        if rowCount > 0:
            feedback.pushInfo(
                tr('Number of features to synchronize') + ' = {0}'.format(rowCount)
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
                m = error_message+ ' '+ sql
                return returnError(output, m, feedback)
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
                m = error_message+ ' '+ sql
                return returnError(output, m, feedback)
            feedback.pushInfo(
                tr('SQL queries have been replayed from the central to the clone database')
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
                m = error_message+ ' '+ sql
                return returnError(output, m, feedback)
            feedback.pushInfo(
                tr('Logged actions sync_data has been updated in the central database with the clone id')
            )

            # Modify central server synchronization item central->clone
            sql = '''
                UPDATE lizsync.history
                SET sync_status = 'done'
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
                m = error_message+ ' '+ sql
                return returnError(output, m, feedback)
            feedback.pushInfo(
                tr('History sync_status has been updated to "done" in the central database')
            )

        else:
            # No data to sync
            feedback.pushInfo(
                tr('No data to synchronize from the central database')
            )

        feedback.setProgress(int(1 * total))


        # CLONE -> CENTRAL
        feedback.pushInfo('****** CLONE TO CENTRAL *******')

        # sql = '''
            # SELECT
                # event_id,
                # action_tstamp_tx::text AS action_tstamp_tx,
                # concat(schema_name, '.', table_name) AS ident,
                # action,
                # 'clone' AS origine,
                # Coalesce(
                    # lizsync.get_event_sql(event_id, '{0}', {1}),
                    # ''
                # ) AS action
            # FROM audit.logged_actions
            # WHERE True
            # ORDER BY event_id;
        # '''.format(
            # uid_field,
            # excluded_columns
        # )
        # actions = []
        # header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            # connection_name_clone,
            # sql
        # )
        # if not ok:
            # m = error_message+ ' '+ sql
            # return returnError(output, m, feedback)
        if rowCount > 0:
            feedback.pushInfo(
                tr('Number of features to synchronize') + ' = {0}'.format(rowCount)
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
                m = error_message+ ' '+ sql
                return returnError(output, m, feedback)
            for a in data:
                sync_id = a[0]
                feedback.pushInfo(
                    tr('New history item has been created in the central database')
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
                m = error_message+ ' '+ sql
                return returnError(output, m, feedback)

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
                m = error_message+ ' '+ sql
                return returnError(output, m, feedback)

            # Modify central server synchronization item clone->central
            sql = '''
                UPDATE lizsync.history
                SET sync_status = 'done'
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
                m = error_message+ ' '+ sql
                return returnError(output, m, feedback)
        else:
            # No data to sync
            feedback.pushInfo(
                tr('No data to synchronize from the clone database')
            )


        feedback.setProgress(int(2 * total))

        output = {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: tr('Two-way database synchronization done')
        }
        return output

