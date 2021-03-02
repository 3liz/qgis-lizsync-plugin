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
from ..qgis_plugin_tools.tools.database import available_migrations
from ..qgis_plugin_tools.tools.logger_processing import LoggerProcessingFeedBack

__copyright__ = "Copyright 2019, 3Liz"
__license__ = "GPL version 3"
__email__ = "info@3liz.org"
__revision__ = "$Format:%H$"

SCHEMA = "lizsync"
VERSION = "0.2.2"


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
        provider = ProcessingProvider()
        registry = QgsApplication.processingRegistry()
        if not registry.providerById(provider.id()):
            registry.addProvider(provider)

        feedback = LoggerProcessingFeedBack()
        params = {
            'CONNECTION_NAME': 'test',
            'OVERRIDE_LIZSYNC': True,  # Must be true, for the first time in the test.
        }

        os.environ["TEST_DATABASE_INSTALL_{}".format(SCHEMA.capitalize())] = VERSION
        alg = "{}:create_database_structure".format(provider.id())
        try:
            processing_output = processing.run(alg, params, feedback=feedback)
        except QgsProcessingException as e:
            self.assertTrue(False, e)
        del os.environ["TEST_DATABASE_INSTALL_{}".format(SCHEMA.capitalize())]

        self.cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = '{}'".format(
                SCHEMA
            )
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
        expected = "*** THE STRUCTURE lizsync HAS BEEN CREATED WITH VERSION '{}'***".format(VERSION)
        self.assertEqual(expected, processing_output["OUTPUT_STRING"])

        sql = """
            SELECT version
            FROM {}.sys_structure_metadonnee
            ORDER BY date_ajout DESC
            LIMIT 1;
        """.format(
            SCHEMA
        )
        self.cursor.execute(sql)
        record = self.cursor.fetchone()
        self.assertEqual(VERSION, record[0])

        feedback.pushDebugInfo("Update the database")
        params = {
            "CONNECTION_NAME": "test",
            "RUNIT": True,
        }
        alg = "{}:upgrade_database_structure".format(provider.id())
        results = processing.run(alg, params, feedback=feedback)
        self.assertEqual(1, results["OUTPUT_STATUS"], 1)
        self.assertEqual(
            "*** THE DATABASE STRUCTURE HAS BEEN UPDATED ***",
            results["OUTPUT_STRING"],
        )

        sql = """
            SELECT version
            FROM {}.sys_structure_metadonnee
            ORDER BY date_ajout DESC
            LIMIT 1;
        """.format(
            SCHEMA
        )
        self.cursor.execute(sql)
        record = self.cursor.fetchone()

        migrations = available_migrations(000000)
        last_migration = migrations[-1]
        metadata_version = (
            last_migration.replace("upgrade_to_", "").replace(".sql", "").strip()
        )
        self.assertEqual(metadata_version, record[0])

        self.cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = '{}'".format(
                SCHEMA
            )
        )
        records = self.cursor.fetchall()
        result = [r[0] for r in records]
        expected = [
            "history",
            "server_metadata",
            "conflicts",
            "synchronized_tables",
            "sys_structure_metadonnee",
            "logged_actions",
            "logged_relations",
        ]
        self.assertCountEqual(expected, result)

    def test_load_structure_without_migrations(self):
        """Test we can load the PostGIS structure without migrations."""
        provider = ProcessingProvider()
        registry = QgsApplication.processingRegistry()
        if not registry.providerById(provider.id()):
            registry.addProvider(provider)

        feedback = LoggerProcessingFeedBack()
        self.cursor.execute("SELECT version();")
        record = self.cursor.fetchone()
        feedback.pushInfo("PostgreSQL version : {}".format(record[0]))

        self.cursor.execute("SELECT PostGIS_Version();")
        record = self.cursor.fetchone()
        feedback.pushInfo("PostGIS version : {}".format(record[0]))

        params = {
            'CONNECTION_NAME': 'test',
            'OVERRIDE_LIZSYNC': True,  # Must be true, for the first time in the test.
        }
        alg = "{}:create_database_structure".format(provider.id())
        processing.run(alg, params, feedback=feedback)

        self.cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = '{}'".format(
                SCHEMA
            )
        )
        records = self.cursor.fetchall()
        result = [r[0] for r in records]
        expected = [
            "history",
            "server_metadata",
            "conflicts",
            "synchronized_tables",
            "sys_structure_metadonnee",
            "logged_actions",
            "logged_relations",
        ]
        self.assertCountEqual(expected, result)

        feedback.pushDebugInfo("Relaunch the algorithm without override")
        params = {
            "CONNECTION_NAME": "test",
            'OVERRIDE_LIZSYNC': False,
        }

        with self.assertRaises(QgsProcessingException):
            processing.run(alg, params, feedback=feedback)

        self.assertTrue(feedback.last.startswith('Unable to execute algorithm'), feedback.last)

        feedback.pushDebugInfo("Update the database")
        params = {"CONNECTION_NAME": "test", "RUNIT": True}
        results = processing.run(
            "lizsync:upgrade_database_structure", params, feedback=feedback
        )
        self.assertEqual(1, results["OUTPUT_STATUS"], 1)
        self.assertEqual(
            "The database version already matches the plugin version. No upgrade needed.",
            results["OUTPUT_STRING"],
        )
