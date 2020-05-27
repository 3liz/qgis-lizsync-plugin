"""Base class for tests using a database with data."""

import psycopg2
import time

from qgis.core import (
    QgsApplication,
    Qgis,
)
from qgis.testing import unittest

if Qgis.QGIS_VERSION_INT >= 30800:
    from qgis import processing
else:
    import processing

from ..qgis_plugin_tools.tools.logger_processing import LoggerProcessingFeedBack
from ..processing.provider import LizsyncProvider as ProcessingProvider

__copyright__ = "Copyright 2020, 3Liz"
__license__ = "GPL version 3"
__email__ = "info@3liz.org"
__revision__ = "$Format:%H$"


class DatabaseTestCase(unittest.TestCase):

    """Base class for tests using a database with data."""

    def setUp(self) -> None:
        self.connection = psycopg2.connect(
            user="docker", password="docker", host="db", port="5432", database="gis"
        )
        self.cursor = self.connection.cursor()

        self.provider = ProcessingProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

        self.feedback = LoggerProcessingFeedBack()

        params = {
            "CONNECTION_NAME": "test",
            'OVERRIDE_AUDIT': True,
            'OVERRIDE_LIZSYNC': True,
        }
        processing.run(
            "{}:create_database_structure".format(self.provider.id()), params, feedback=None
        )

        super().setUp()

    def tearDown(self) -> None:
        del self.cursor
        del self.connection
        time.sleep(1)
