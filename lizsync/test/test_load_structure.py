"""Tests for Processing algorithms."""

import os
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
from ..qgis_plugin_tools.tools.resources import metadata_config

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

    def test_load_structure_with_migration(self):
        """Test we can load the PostGIS structure with migrations."""
        VERSION = "0.2.2"
        provider = ProcessingProvider()
        QgsApplication.processingRegistry().addProvider(provider)

        feedback = LoggerProcessingFeedBack()
        params = {
            'CONNECTION_NAME_CENTRAL': 'test',
            'OVERRIDE_AUDIT': True,  # Must be true, for the first time in the test.
            'OVERRIDE_LIZSYNC': True,  # Must be true, for the first time in the test.
        }

        os.environ["DATABASE_RUN_MIGRATION"] = VERSION
        try:
            processing_output = processing.run(
                "lizsync:create_database_structure", params, feedback=feedback
            )
        except QgsProcessingException as e:
            self.assertTrue(False, e)
        del os.environ["DATABASE_RUN_MIGRATION"]

        self.cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'lizsync'"
        )
        records = self.cursor.fetchall()
        result = [r[0] for r in records]
        # Expected tables in the specific version written above at the beginning of the test.
        # DO NOT CHANGE HERE, change below at the end of the test.
        expected = [
            "history",
            "server_metadata",
            "synchronized_schemas",
            "sys_structure_metadonnee",
        ]
        self.assertCountEqual(expected, result)
        expected = "Lizsync database structure has been successfully created to version \"{}\".".format(VERSION)
        self.assertEqual(expected, processing_output["OUTPUT_STRING"])

        sql = '''
            SELECT version
            FROM lizsync.sys_structure_metadonnee
            ORDER BY date_ajout DESC
            LIMIT 1;
        '''
        self.cursor.execute(sql)
        record = self.cursor.fetchone()
        self.assertEqual(VERSION, record[0])

        feedback.pushDebugInfo("Update the database")
        params = {
            "CONNECTION_NAME_CENTRAL": "test",
            "RUNIT": True,
        }
        results = processing.run(
            "lizsync:upgrade_database_structure", params, feedback=feedback
        )
        self.assertEqual(1, results["OUTPUT_STATUS"], 1)
        metadata = metadata_config()
        version = metadata["general"]["version"]
        version = version.replace("-beta", "")
        self.assertEqual(
            "Lizsync database structure has been successfully upgraded to version \"{}\".".format(version),
            results["OUTPUT_STRING"],
        )

        self.cursor.execute(sql)
        record = self.cursor.fetchone()
        self.assertEqual(version, record[0])

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
            'OVERRIDE_AUDIT': True,  # Must be true, for the first time in the test.
            'OVERRIDE_LIZSYNC': True,  # Must be true, for the first time in the test.
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
