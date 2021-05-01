__copyright__ = 'Copyright 2020, 3Liz'
__license__ = 'GPL version 3'
__email__ = 'info@3liz.org'

from qgis.core import (
    QgsAbstractDatabaseProviderConnection,
    QgsProcessingFeedback,
    QgsProviderConnectionException,
)

from lizsync.qgis_plugin_tools.tools.algorithm_processing import (
    BaseProcessingAlgorithm,
)
from lizsync.qgis_plugin_tools.tools.i18n import tr


class BaseDatabaseAlgorithm(BaseProcessingAlgorithm):

    def group(self):
        return tr('01 Installation')

    def groupId(self):
        return 'lizsync_installation'

    @staticmethod
    def vacuum_all_tables(
            connection: QgsAbstractDatabaseProviderConnection, feedback: QgsProcessingFeedback):
        """ Execute a vacuum to recompute the feature count. """
        for table in connection.tables('lizsync'):

            if table.tableName().startswith('v_'):
                # We can't vacuum a view
                continue

            sql = 'VACUUM ANALYSE {}.{};'.format('lizsync', table.tableName())
            feedback.pushDebugInfo(sql)
            try:
                connection.executeSql(sql)
            except QgsProviderConnectionException as e:
                feedback.reportError(str(e))
