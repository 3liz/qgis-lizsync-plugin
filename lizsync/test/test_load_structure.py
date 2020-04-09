"""Tests for Processing algorithms."""

import psycopg2
import time

from qgis.core import (
    QgsApplication,
    QgsProcessingException,
    Qgis,
)
from qgis.testing import unittest

if Qgis.QGIS_VERSION_INT >= 30800:
    from qgis import processing
else:
    import processing

from ..processing.provider import LizsyncProvider as ProcessingProvider
from ..qgis_plugin_tools.tools.logger_processing import LoggerProcessingFeedBack

__copyright__ = "Copyright 2019, 3Liz"
__license__ = "GPL version 3"
__email__ = "info@3liz.org"
__revision__ = "$Format:%H$"


class TestProcessing(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = psycopg2.connect(
            user="docker", password="docker", host="db", port="5432", database="gis"
        )
        self.cursor = self.connection.cursor()

    def tearDown(self) -> None:
        del self.cursor
        del self.connection
        time.sleep(1)

    def test_load_structure_without_migrations(self):
        """Test we can load the PostGIS structure without migrations."""
        provider = ProcessingProvider()
        QgsApplication.processingRegistry().addProvider(provider)

        feedback = LoggerProcessingFeedBack()
        self.cursor.execute("SELECT version();")
        record = self.cursor.fetchone()
        feedback.pushInfo("PostgreSQL version : {}".format(record[0]))

        self.cursor.execute("SELECT PostGIS_Version();")
        record = self.cursor.fetchone()
        feedback.pushInfo("PostGIS version : {}".format(record[0]))

        params = {
            'CONNECTION_NAME_CENTRAL': 'test',
            'OVERRIDE_AUDIT': True,  # Must be true, for the time in the test.
            'OVERRIDE_LIZSYNC': True,  # Must be true, for the time in the test.
        }
        processing.run("lizsync:create_database_structure", params, feedback=feedback)

        self.cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'audit'"
        )
        records = self.cursor.fetchall()
        result = [r[0] for r in records]
        expected = [
            "logged_relations",
            "logged_actions",
        ]
        self.assertCountEqual(expected, result)

        self.cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'lizsync'"
        )
        records = self.cursor.fetchall()
        result = [r[0] for r in records]
        expected = [
            "history",
            "server_metadata",
            "conflicts",
            "synchronized_schemas",
            "sys_structure_metadonnee",
        ]
        self.assertCountEqual(expected, result)

        feedback.pushDebugInfo("Relaunch the algorithm without override")
        params = {
            "CONNECTION_NAME_CENTRAL": "test",
            'OVERRIDE_AUDIT': False,
            'OVERRIDE_LIZSYNC': False,
        }

        with self.assertRaises(QgsProcessingException):
            processing.run("lizsync:create_database_structure", params, feedback=feedback)

        self.assertTrue(feedback.last.startswith('Unable to execute algorithm'), feedback.last)

        feedback.pushDebugInfo("Update the database")
        params = {"CONNECTION_NAME_CENTRAL": "test", "RUNIT": True}
        results = processing.run(
            "lizsync:upgrade_database_structure", params, feedback=feedback
        )
        self.assertEqual(1, results["OUTPUT_STATUS"], 1)
        self.assertEqual(
            "The database version already matches the plugin version. No upgrade needed.",
            results["OUTPUT_STRING"],
        )
