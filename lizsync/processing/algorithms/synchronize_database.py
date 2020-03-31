__copyright__ = 'Copyright 2020, 3Liz'
__license__ = 'GPL version 3'
__email__ = 'info@3liz.org'
__revision__ = '$Format:%H$'

from qgis.core import (
    QgsProcessingParameterString,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber
)
from .tools import *
from ...qgis_plugin_tools.tools.i18n import tr
from ...qgis_plugin_tools.tools.algorithm_processing import BaseProcessingAlgorithm


class SynchronizeDatabase(BaseProcessingAlgorithm):
    """
    """
    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    CONNECTION_NAME_CLONE = 'CONNECTION_NAME_CLONE'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

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

    def getDatabaseId(self, source, feedback):
        '''
        Get database server id
        '''
        connection_name = self.connection_name_central
        if source == 'clone':
            connection_name = self.connection_name_clone
        sql = '''
            SELECT
                server_id
            FROM lizsync.server_metadata
            LIMIT 1;
        '''
        _, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            connection_name,
            sql
        )
        if not ok:
            m = error_message+ ' '+ sql
            feedback.reportError(m)
            return None
        if rowCount != 1:
            m = tr('No database server id found in the server_metadata table')
            feedback.reportError(m)
            return None
        for a in data:
            db_id = a[0]
            feedback.pushInfo(tr('Server id') + ' for %s database = %s' % (source, db_id))
        return db_id

    def getExcludedColumns(self):
        '''
        Get the list of excluded columns from synchronization
        '''
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

        return excluded_columns

    def getLastAuditLogs(self, source):
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
                    extract(epoch from action_tstamp_tx)::integer AS action_tstamp_epoch,
                    concat(schema_name, '.', table_name) AS ident,
                    action,
                    CASE
                        WHEN sync_data->>'origin' IS NULL THEN 'central'
                        ELSE 'clone'
                    END AS origine,
                    Coalesce(
                        lizsync.get_event_sql(
                            event_id,
                            '{uid_field}',
                            array_cat(
                                {excluded_columns},
                                array_remove(akeys(changed_fields), s)
                            )
                        ),
                        ''
                    ) AS action,
                    s AS updated_field,
                    row_data->'{uid_field}' AS uid,
                    CASE
                        WHEN sync_data->>'action_tstamp_tx' IS NOT NULL
                        AND sync_data->>'origin' IS NOT NULL
                            THEN extract(epoch from Cast(sync_data->>'action_tstamp_tx' AS TIMESTAMP WITH TIME ZONE))::integer
                        ELSE extract(epoch from action_tstamp_tx)::integer
                    END AS original_action_tstamp_tx
                FROM audit.logged_actions
                LEFT JOIN skeys(changed_fields) AS s ON TRUE,
                last_sync, schemas

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
                central_id=self.central_id,
                clone_id=self.clone_id,
                uid_field=self.uid_field,
                excluded_columns=self.excluded_columns
            )
            _, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                self.connection_name_central,
                sql
            )
        else:
            # Get all logs from clone database
            sql = '''
                SELECT
                    event_id,
                    action_tstamp_tx::text AS action_tstamp_tx,
                    extract(epoch from action_tstamp_tx)::integer AS action_tstamp_epoch,
                    concat(schema_name, '.', table_name) AS ident,
                    action,
                    'clone' AS origine,
                    Coalesce(
                        lizsync.get_event_sql(
                            event_id,
                            '{uid_field}',
                            array_cat(
                                {excluded_columns},
                                array_remove(akeys(changed_fields), s)
                            )
                        ),
                        ''
                    ) AS action,
                    s AS updated_field,
                    row_data->'{uid_field}' AS uid
                FROM audit.logged_actions
                LEFT JOIN skeys(changed_fields) AS s ON TRUE
                WHERE True
                ORDER BY event_id;
            '''.format(
                uid_field=self.uid_field,
                excluded_columns=self.excluded_columns
            )
            _, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
                self.connection_name_clone,
                sql
            )
        if not ok:
            error_message += ' ' + sql

        return data, rowCount, ok, error_message

    def analyseAuditLogs(self, central_logs, clone_logs, feedback):
        '''
        Parse logs and compare central and clone logs
        Find conflicts and return modified logs
        '''
        # Rule to apply on UPDATE conflict
        # same table, same uid, same column
        # rule = 'clone'
        # rule = 'central'
        # rule = 'last_audited'
        rule = 'last_modified'

        ids, conflicts = [], []
        max_action_tstamp_tx, min_event_id, max_event_id = None, None, None
        central_removed_logs_indexes = []
        logs_indexes_to_remove = {
            'central': [],
            'clone': []
        }

        if len(central_logs) > 0:
            for ai, central in enumerate(central_logs):
                ids.append(int(central[0]))
                max_action_tstamp_tx = central[1]
                # manage UPDATES
                if central[4] == 'U':
                    # Loop throuhg clone log
                    for bi, clone in enumerate(clone_logs):
                        # Search for conflicts
                        if (
                        # Update
                        clone[4] == 'U' \
                        # same table
                        and central[3] == clone[3] \
                        # same field
                        and central[7] == clone[7] \
                        # same feature (same uid)
                        and central[8] == clone[8] \
                        ):
                            if rule =='clone':
                                # Clone always wins
                                looser  = 'central'
                            elif rule == 'central':
                                # Central always wins
                                # BEWARE : central means also "synced from another clone"
                                looser  = 'clone'
                            elif rule == 'last_modified':
                                # Compare original action_tstamp_tx
                                looser = 'clone' if int(clone[2]) < int(central[9]) else 'central'
                            elif rule == 'last_audited':
                                # Compare clone action timestamp with central action timestamp
                                # Beware central one can come from another clone sync
                                looser = 'clone' if int(clone[2]) < int(central[2]) else 'central'

                            # Keep conflict for further information
                            conflict = {
                                'event_id': central[0],
                                'event_timestamp': central[1],
                                'table': central[3],
                                'uid': central[8],
                                'central_sql': central[6],
                                'clone_sql': clone[6],
                                'rejected': looser,
                                'rule_applied': rule
                            }
                            conflicts.append(conflict)

                            # Add loose index for further deletion
                            r = ai if looser == 'central' else bi
                            logs_indexes_to_remove[looser].append(r)

            # Calculate min and max event ids
            min_event_id = min(ids)
            max_event_id = max(ids)

            # Delete lines from logs based on conflict resolution
            for i in sorted(logs_indexes_to_remove['central'], reverse=True):
                del(central_logs[i])
            for i in sorted(logs_indexes_to_remove['clone'], reverse=True):
                del(clone_logs[i])

            # Set needed data
            self.max_action_tstamp_tx = max_action_tstamp_tx
            self.min_event_id = min_event_id
            self.max_event_id = max_event_id
            self.ids = ids

        return central_logs, clone_logs, conflicts

    def replayLogs(self, target, logs, feedback):
        '''
        Replay logs (raw or updated) to the target database
        '''
        feedback.pushInfo(
            tr('Number of features to synchronize') + ' to {} = {}'.format(
                target,
                len(logs)
            )
        )

        if target == 'clone':
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
                self.central_id, self.clone_id,
                self.min_event_id, self.max_event_id, self.max_action_tstamp_tx
            )
            _, data, _, ok, error_message = fetchDataFromSqlQuery(
                self.connection_name_central,
                sql
            )
            if not ok:
                m = error_message+ ' '+ sql
                return False, m

            for a in data:
                sync_id = a[0]
                feedback.pushInfo(
                    'New history item has been created in the central database'
                )

            # Replay SQL queries in clone db
            # We disable triggers to avoid adding more rows to the local audit logged_actions table
            # TODO : write SQL into file and use psql
            sql = ' SET session_replication_role = replica;'
            for a in logs:
                sql+= '''
                {0};
                '''.format(a[6])
            sql+= ' SET session_replication_role = DEFAULT;'
            # feedback.pushInfo(sql)
            _, _, _, ok, error_message = fetchDataFromSqlQuery(
                self.connection_name_clone,
                sql
            )
            if not ok:
                m = error_message+ ' '+ sql
                return False, m

            feedback.pushInfo(
                tr('SQL queries have been replayed from the central to the clone database')
            )

            # Modify central server audit logged actions
            sql = '''
                UPDATE audit.logged_actions
                SET sync_data = jsonb_set(
                    sync_data,
                    '{{"replayed_by"}}',
                    sync_data->'replayed_by' || jsonb_build_object('{clone_id}', '{sync_id}'),
                    true
                )
                WHERE event_id IN ({ids})
            '''.format(
                clone_id=self.clone_id,
                sync_id=sync_id,
                ids=', '.join([str(i) for i in self.ids])
            )
            _, _, _, ok, error_message = fetchDataFromSqlQuery(
                self.connection_name_central,
                sql
            )
            if not ok:
                m = error_message+ ' '+ sql
                return False, m

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
            _, _, _, ok, error_message = fetchDataFromSqlQuery(
                self.connection_name_central,
                sql
            )
            if not ok:
                m = error_message+ ' '+ sql
                return False, m

            feedback.pushInfo(
                tr('History sync_status has been updated to "done" in the central database')
            )

        if target == 'central':

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
                self.clone_id,
                self.central_id
            )
            sync_id = None
            _, data, _, ok, error_message = fetchDataFromSqlQuery(
                self.connection_name_central,
                sql
            )
            if not ok:
                m = error_message+ ' '+ sql
                return False, m
            for a in data:
                sync_id = a[0]
                feedback.pushInfo(
                    tr('New history item has been created in the central database')
                )

            # Replay SQL queries to central server db
            # The session variables are used by the audit function
            # to fill the sync_data field
            sql_session = 'SET SESSION "lizsync.server_from" = \'{}\';'.format(self.clone_id)
            sql_session+= 'SET SESSION "lizsync.server_to" = \'{}\';'.format(self.central_id)
            sql_session+= 'SET SESSION "lizsync.sync_id" = \'{}\';'.format(sync_id)

            # Store SQL query to update central logs afterward with original log timestamp
            sql_update_logs = ''

            # Loop through logs and replay action
            # We need to query one by one to be able to update the sync_data->action_tstamp_tx afterwards
            # by searching action = sql
            for log in logs:
                # Add action SQL
                sql = sql_session + '''{action};'''.format(
                    action=log[6]
                )
                # Replay this SQL containing in the central server
                _, _, _, ok, error_message = fetchDataFromSqlQuery(
                    self.connection_name_central,
                    sql
                )
                if not ok:
                    m = error_message+ ' '+ sql
                    return False, m

                # Add UPDATE clause in SQL query which will be run afterwards
                sql_update_logs+= '''
                UPDATE audit.logged_actions
                SET sync_data = sync_data || jsonb_build_object(
                    'action_tstamp_tx',
                    Cast('{timestamp}' AS TIMESTAMP WITH TIME ZONE)
                )
                WHERE True
                AND sync_data->'replayed_by'->>'{central_id}' = '{sync_id}'
                AND client_query = '{query}'
                AND action = '{action}'
                AND concat(schema_name, '.', table_name) = '{ident}';
                '''.format(
                    timestamp=log[1],
                    central_id=self.central_id,
                    sync_id=sync_id,
                    query=sql.replace("'", "''"),
                    action=log[4],
                    ident=log[3]
                )

            feedback.pushInfo(
                tr('SQL queries have been replayed from the clone to the central database')
            )

            # Update central logs to keep original action timestamp
            sql = sql_update_logs
            _, _, _, ok, error_message = fetchDataFromSqlQuery(
                self.connection_name_central,
                sql
            )
            if not ok:
                m = error_message+ ' '+ sql
                return False, m

            feedback.pushInfo(
                tr('Logged actions sync_data has been updated in the central database with the original timestamp')
            )

            # Delete all data from clone audit logged_actions
            sql = '''
            TRUNCATE audit.logged_actions
            RESTART IDENTITY;
            '''
            _, _, _, ok, error_message = fetchDataFromSqlQuery(
                self.connection_name_clone,
                sql
            )
            if not ok:
                m = error_message+ ' '+ sql
                return False, m

            feedback.pushInfo(
                tr('Logged actions has been deleted in clone database')
            )


            # Modify central server synchronization item clone->central
            sql = '''
                UPDATE lizsync.history
                SET sync_status = 'done'
                WHERE True
                AND sync_id = '{0}'
            '''.format(
                sync_id
            )
            _, _, _, ok, error_message = fetchDataFromSqlQuery(
                self.connection_name_central,
                sql
            )
            if not ok:
                m = error_message+ ' '+ sql
                return False, m

            feedback.pushInfo(
                tr('History sync_status has been updated to "done" in the central database')
            )

        return True, ''

    def processAlgorithm(self, parameters, context, feedback):
        '''
        Run the needed steps for bi-directionnal database synchronization
        '''
        output = {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: ''
        }

        self.uid_field = 'uid'
        self.excluded_columns = self.getExcludedColumns()
        self.connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        self.connection_name_clone = parameters[self.CONNECTION_NAME_CLONE]

        # Compute the number of steps to display within the progress bar
        total = 100.0 / 2

        # Get database servers id
        self.central_id = self.getDatabaseId('central', feedback)
        self.clone_id = self.getDatabaseId('clone', feedback)
        if not self.central_id or not self.clone_id:
            return returnError(output, '', feedback)

        # Get audit logs since last synchronization
        # from central
        feedback.pushInfo(tr('Get central server audit log since last synchronization'))
        central_logs, central_count, central_ok, central_error = self.getLastAuditLogs('central')
        if not central_ok:
            return returnError(output, central_error, feedback)

        # from clone
        feedback.pushInfo(tr('Get clone audit log since last synchronization'))
        clone_logs, clone_count, clone_ok, clone_error = self.getLastAuditLogs('clone')
        if not clone_ok:
            return returnError(output, clone_error, feedback)

        # Analyse logs and handle conflicts
        feedback.pushInfo(tr('Analyse logs and handle conflicts'))
        central_logs, clone_logs, conflicts = self.analyseAuditLogs(
            central_logs,
            clone_logs,
            feedback
        )

        # Replay logs

        # central > clone
        feedback.pushInfo(tr('Replay central logs on clone database'))
        if len(central_logs) > 0:
            ok, msg = self.replayLogs('clone', central_logs, feedback)
            if not ok:
                return returnError(output, msg, feedback)
        else:
            feedback.pushInfo(
                tr('No data to synchronize from the central database')
            )

        # clone > central
        feedback.pushInfo(tr('Replay clone logs on central database'))
        if len(clone_logs) > 0:
            ok, msg = self.replayLogs('central', clone_logs, feedback)
            if not ok:
                return returnError(output, msg, feedback)
        else:
            feedback.pushInfo(
                tr('No data to synchronize from the clone database')
            )

        # Store conflicts
        if len(conflicts) > 0:
            sql = '''
            INSERT INTO lizsync.conflicts
            ("object_table", "object_uid", "clone_id",
            "central_event_id", "central_event_timestamp",
            "central_sql", "clone_sql", "rejected", "rule_applied"
            ) VALUES
            '''
            sep = ''
            for c in conflicts:
                sql+= sep + ''' (
                '{table}', '{uid}', '{clone_id}',
                {event_id}, '{event_timestamp}',
                '{central_sql}', '{clone_sql}', '{rejected}', '{rule_applied}'
                )
                ''' .format(
                    table=c['table'],
                    uid=c['uid'],
                    clone_id=self.clone_id,
                    event_id=c['event_id'],
                    event_timestamp=c['event_timestamp'],
                    central_sql=c['central_sql'].replace("'", "''"),
                    clone_sql=c['clone_sql'].replace("'", "''"),
                    rejected=c['rejected'],
                    rule_applied=c['rule_applied']
                )
                sep = ''',
                '''
            print(sql)

            _, _, _, ok, error_message = fetchDataFromSqlQuery(
                self.connection_name_central,
                sql
            )
            if not ok:
                m = error_message+ ' '+ sql
                return returnError(output, m, feedback)

            feedback.pushInfo(
                tr('Conflict resolution items have been saved in central database into lizsync.conflicts table')
            )

        # feedback.setProgress(int(1 * total))

        output = {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: tr('Two-way database synchronization done')
        }
        return output

