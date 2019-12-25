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
    QgsProcessingOutputString
)
import processing

class SynchronizeDatabase(QgsProcessingAlgorithm):
    """
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    DBHOST = 'DBHOST'
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

    def tr(self, string):
        """
        Returns a translatable string with the self.tr() function.
        """
        return QCoreApplication.translate('Processing', string)

    def createInstance(self, config={}):
        """ Virtual override

            see https://qgis.org/api/classQgsProcessingAlgorithm.html
        """
        return self.__class__()

    def __init__(self):
        super().__init__()

    def name(self):
        return 'partial_sync'

    def displayName(self):
        return self.tr('Two-way database synchronization')

    def group(self):
        return self.tr('Synchronization')

    def groupId(self):
        return 'lizsync_sync'

    def shortHelpString(self):
        #return self.tr("")
        return self.displayName()

    def initAlgorithm(self, config=None):
        # INPUTS
        self.addParameter(
            QgsProcessingParameterString(
                self.DBHOST, 'Database host',
                defaultValue='qgisdb-valabre.lizmap.com',
                optional=False
            )
        )

        # OUTPUTS
        # Add output for message
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING, self.tr('Output message')
            )
        )


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
        if servername == 'central':
            dbhost = parameters[self.DBHOST]
        else:
            dbhost = profil['host']
        exec_result = processing.run("script:geopoppy_execute_sql_on_database", {
            'DBHOST': dbhost,
            'DBPORT': profil['port'],
            'DBNAME': profil['dbname'],
            'DBUSER': profil['user'],
            'DBPASS': profil['password'],
            'INPUT_SQL': sql
        }, context=context, feedback=feedback)
        return exec_result

    def processAlgorithm(self, parameters, context, feedback):

        uid_field = 'uid'

        if not self.check_internet():
            feedback.pushInfo(self.tr('No internet connection'))
            raise Exception(self.tr('No internet connection'))

        # Send some information to the user
        feedback.pushInfo(self.tr('Internet connection OK'))

        # Compute the number of steps to display within the progress bar
        total = 100.0 / 2

        central_id = None
        geopoppy_id = None

        # Get central ID
        sql = 'SELECT server_id FROM sync.server_metadata LIMIT 1;'
        feedback.pushInfo(sql)
        get_sql = self.run_sql(sql, 'central', parameters, context, feedback)
        for feature in get_sql['OUTPUT_LAYER'].getFeatures():
            central_id = feature['server_id']
            feedback.pushInfo('* server id = %s' % central_id)

        # Get geopoppy ID
        sql = 'SELECT server_id FROM sync.server_metadata LIMIT 1;'
        feedback.pushInfo(sql)
        get_sql = self.run_sql(sql, 'geopoppy', parameters, context, feedback)
        for feature in get_sql['OUTPUT_LAYER'].getFeatures():
            geopoppy_id = feature['server_id']
            feedback.pushInfo('* geopoppy id = %s' % geopoppy_id)

        # CENTRAL -> GEOPOPPY
        feedback.pushInfo('****** CENTRAL TO GEOPOPPY *******')
        feedback.pushInfo('*************')

        # Get last synchro
        sql = '''
        SELECT max_action_tstamp_tx::text AS max_action_tstamp_tx,
        max_event_id
        FROM sync.history
        WHERE True
        AND server_from = '{0}'
        AND '{1}' = ANY (server_to)
        AND sync_status = 'done'
        ORDER BY sync_time DESC
        LIMIT 1
        '''.format(
            central_id,
            geopoppy_id
        )
        feedback.pushInfo(sql)
        get_sql = self.run_sql(sql, 'central', parameters, context, feedback)
        last_sync = None
        for feature in get_sql['OUTPUT_LAYER'].getFeatures():
            last_sync = {
                'max_event_id': feature['max_event_id'],
                'max_action_tstamp_tx': feature['max_action_tstamp_tx']
            }
            feedback.pushInfo('* last sync = %s' % last_sync)

        # Get audit log since last sync
        # We also get the SQL to replay via the get_event_sql function
        sql = '''
        SELECT event_id, action_tstamp_tx::text AS action_tstamp_tx,
        sync.get_event_sql(event_id, '{0}') AS action
        FROM audit.logged_actions,
        (
            SELECT sync_schemas
            FROM sync.synchronized_schemas
            WHERE server_id = '{1}'
            LIMIT 1
        ) AS f

        WHERE True

        -- modifications ne proviennent pas du GeoPoppy
        -- UID_GeoPoppy_1
        AND (sync_data->>'origin' != '{1}' OR sync_data->>'origin' IS NULL)

        -- modifications n'ont pas déjà été rejouées sur le GeoPoppy
        -- UID_GeoPoppy_1
        AND (sync_data->'replayed_by' ? '{1}' OR sync_data->'replayed_by' = jsonb_build_object() )

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
            geopoppy_id,
            last_sync['max_action_tstamp_tx'],
            last_sync['max_event_id']
        )
        feedback.pushInfo(sql)
        ids = []
        max_action_tstamp_tx = None
        actions = []
        get_sql = self.run_sql(sql, 'central', parameters, context, feedback)
        if 'OUTPUT_LAYER' in get_sql:
            for feature in get_sql['OUTPUT_LAYER'].getFeatures():
                ids.append(int(feature['event_id']))
                actions.append(feature['action'])
                max_action_tstamp_tx = feature['action_tstamp_tx']
            min_event_id = min(ids)
            max_event_id = max(ids)
            feedback.pushInfo(
                '* min_event_id = {0}, max_event_id = {1}, max_action_tstamp_tx = {2}'.format(
                    min_event_id, max_event_id, max_action_tstamp_tx
               )
            )

            # Insert a new synchronization item in central db
            sql = '''
                INSERT INTO sync.history (
                    server_from, server_to,
                    min_event_id, max_event_id, max_action_tstamp_tx,
                    sync_type, sync_status
                )
                VALUES (
                    '{0}', ARRAY['{1}'],
                    {2}, {3}, '{4}',
                    'partial', 'pending'
                ) RETURNING sync_id
            '''.format(
                central_id, geopoppy_id,
                min_event_id, max_event_id, max_action_tstamp_tx
            )
            feedback.pushInfo(sql)
            get_sql = self.run_sql(sql, 'central', parameters, context, feedback)
            sync_id = None
            for feature in get_sql['OUTPUT_LAYER'].getFeatures():
                sync_id = feature['sync_id']
                feedback.pushInfo(
                    '* new sync item = {0}'.format(sync_id)
                )

            # Replay SQL queries in Geopoppy db
            # We disable triggers to avoid adding more rows to the local audit logged_actions table
            sql = '''
                SET session_replication_role = replica;
                {0};
                SET session_replication_role = DEFAULT;
            '''.format( ';'.join(actions) )
            feedback.pushInfo(sql)
            get_sql = self.run_sql(sql, 'geopoppy', parameters, context, feedback)

            # Modify central server audit logged actions
            sql = '''
                UPDATE audit.logged_actions
                SET sync_data = jsonb_set(
                    sync_data,
                    '{replayed_by}',
                    sync_data->'replayed_by' || jsonb_build_object('{0}', '{1}'),
                    true
                )
                WHERE event_id IN ({2})
            '''.format(
                geopoppy_id,
                sync_id,
                ', '.join('%s' % ids)
            )
            feedback.pushInfo(sql)
            get_sql = self.run_sql(sql, 'central', parameters, context, feedback)

            # Modify central server synchronization item
            sql = '''
                UPDATE sync.history
                SET (sync_status) = ('done')
                WHERE True
                AND sync_id = '{0}'
            '''.format( sync_id )
            feedback.pushInfo(sql)
            get_sql = self.run_sql(sql, 'central', parameters, context, feedback)

        else:
            # No data to sync
            feedback.pushInfo('No data to synchronize from the central server')
        feedback.setProgress(int(1 * total))



        # GEOPOPPY -> CENTRAL
        feedback.pushInfo('****** GEOPOPPY TO CENTRAL *******')
        feedback.pushInfo('*************')

        # Get all geopoppy audit log
        # no filter by date because Geopoppy date cannot be trusted
        # we choose to delete all audit logged_actions when sync is done
        # to start fresh
        sql = '''
        SELECT event_id, action_tstamp_tx::text AS action_tstamp_tx,
        sync.get_event_sql(event_id, '{0}') AS action
        FROM audit.logged_actions
        WHERE True
        ORDER BY event_id;
        '''.format(
            uid_field
        )
        feedback.pushInfo(sql)
        actions = []
        nb=0
        get_sql = self.run_sql(sql, 'geopoppy', parameters, context, feedback)
        if 'OUTPUT_LAYER' in get_sql:
            for feature in get_sql['OUTPUT_LAYER'].getFeatures():
                actions.append(feature['action'])
                nb+=1
            feedback.pushInfo(
                '{} data to synchronize'.format(nb)
            )

            # Insert a new synchronization item in central db
            sql = '''
                INSERT INTO sync.history (
                    server_from, server_to,
                    min_event_id, max_event_id, max_action_tstamp_tx,
                    sync_type, sync_status
                )
                VALUES (
                    '{0}', ARRAY['{1}'],
                    NULL, NULL, NULL,
                    'partial', 'pending'
                ) RETURNING sync_id
            '''.format(
                geopoppy_id,
                central_id
            )
            feedback.pushInfo(sql)
            get_sql = self.run_sql(sql, 'central', parameters, context, feedback)
            sync_id = None
            for feature in get_sql['OUTPUT_LAYER'].getFeatures():
                sync_id = feature['sync_id']
                feedback.pushInfo(
                    '* new sync item = {0}'.format(sync_id)
                )

            # Replay SQL queries to central server db
            # The session variables are used by the audit function
            # to fill the sync_data field
            sql = '''
            SET SESSION "sync.server_from" = '{0}';
            SET SESSION "sync.server_to" = '{1}';
            SET SESSION "sync.sync_id" = '{2}';
            {3}
            '''.format(
                geopoppy_id,
                central_id,
                sync_id,
                ';'.join(actions)
            )
            feedback.pushInfo(sql)
            get_sql = self.run_sql(sql, 'central', parameters, context, feedback)

            # Delete all data from Geopoppy audit logged_actions
            sql = '''
                TRUNCATE audit.logged_actions RESTART IDENTITY;
            '''
            feedback.pushInfo(sql)
            get_sql = self.run_sql(sql, 'geopoppy', parameters, context, feedback)

            # Modify central server synchronization item
            sql = '''
                UPDATE sync.history
                SET (sync_status) = ('done')
                WHERE True
                AND sync_id = '{0}'
            '''.format( sync_id )
            feedback.pushInfo(sql)
            get_sql = self.run_sql(sql, 'central', parameters, context, feedback)


        feedback.setProgress(int(2 * total))

        feedback.pushInfo('*************')
        return {self.OUTPUT_STRING: 'Synchronization done'}
