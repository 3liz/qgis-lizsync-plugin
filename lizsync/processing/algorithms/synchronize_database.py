__copyright__ = 'Copyright 2020, 3Liz'
__license__ = 'GPL version 3'
__email__ = 'info@3liz.org'
__revision__ = '$Format:%H$'

from qgis.core import (
    QgsProcessingParameterString,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber
)
from .tools import (
    lizsyncConfig,
    getUriFromConnectionName,
    fetchDataFromSqlQuery,
    returnError,
)
from ...qgis_plugin_tools.tools.i18n import tr
from ...qgis_plugin_tools.tools.algorithm_processing import BaseProcessingAlgorithm


class SynchronizeDatabase(BaseProcessingAlgorithm):
    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    CONNECTION_NAME_CLONE = 'CONNECTION_NAME_CLONE'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'synchronize_database'

    def displayName(self):
        return tr('Two-way database synchronization')

    def group(self):
        return tr('02 PostgreSQL synchronization')

    def groupId(self):
        return 'lizsync_postgresql_sync'

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

        # Central database connection
        # Needed because we need to check we can connect to central database
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

    def processAlgorithm(self, parameters, context, feedback):
        """
        Run the needed steps for bi-directionnal database synchronization
        """
        output = {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: ''
        }

        # Parameters
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        connection_name_clone = parameters[self.CONNECTION_NAME_CLONE]

        # store parameters
        ls = lizsyncConfig()
        ls.setVariable('postgresql:central/name', connection_name_central)
        ls.setVariable('postgresql:clone/name', connection_name_clone)
        ls.save()

        # Run the database PostgreSQL function lizsync.synchronize()
        feedback.pushInfo(
            tr('Run the bi-directionnal synchronization between the clone and central servers')
        )
        sql = '''
            SELECT *
            FROM lizsync.synchronize()
        '''
        _, data, rowCount, ok, error_message = fetchDataFromSqlQuery(
            connection_name_clone,
            sql
        )
        if not ok:
            m = tr('An error occured during the database synchronization') + ' ' + error_message
            return returnError(output, m, feedback)
        if rowCount == 0:
            m = tr('An unknown error has been raised during the database synchronization')
            return returnError(output, m, feedback)

        for line in data:
            number_replayed_to_central = line[0]
            number_replayed_to_clone = line[1]
            number_conflicts = line[2]

        # Output messages
        a = tr('Two-way database synchronization done')
        b = tr('Number of modifications applied from the central server')
        b+= ' = %s' % number_replayed_to_clone
        c = tr('Number of modifications applied to the central server')
        c+= ' = %s' % number_replayed_to_central
        d = tr('Number of conflicts resolved during the synchronization')
        d+= ' = %s' % number_conflicts
        feedback.pushInfo(a)
        feedback.pushInfo(b)
        feedback.pushInfo(c)
        feedback.pushInfo(d)

        msg = tr('Two-way database synchronization done.')
        output = {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: msg + ' ' + ', '.join([b, c, d])
        }
        return output
