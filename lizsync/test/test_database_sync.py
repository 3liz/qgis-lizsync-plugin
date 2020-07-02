"""Base class for tests using a database."""
import os
import psycopg2
import time
import yaml

import processing

from qgis.core import (
    QgsApplication,
)
from qgis.testing import unittest

from ..qgis_plugin_tools.tools.database import fetch_data_from_sql_query
from ..qgis_plugin_tools.tools.logger_processing import LoggerProcessingFeedBack
from ..qgis_plugin_tools.tools.resources import plugin_test_data_path, plugin_path
from ..processing.provider import LizsyncProvider as ProcessingProvider

__copyright__ = "Copyright 2020, 3Liz"
__license__ = "GPL version 3"
__email__ = "info@3liz.org"
__revision__ = "$Format:%H$"

SCHEMA_DATA = 'test'
DEBUG = False


class TestSyncDatabase(unittest.TestCase):

    """Base class for tests using a database."""

    def __init__(self, methodName="runTest"):
        super().__init__(methodName)
        self.central_server = None
        self.central_cursor = None
        self.clone_a_server = None
        self.clone_a_cursor = None
        self.clone_b_server = None
        self.clone_b_cursor = None
        self.feedback = None
        self.provider = None

    def setUp(self) -> None:
        super().setUp()
        self.central_server = psycopg2.connect(service="test")
        self.central_cursor = self.central_server.cursor()

        self.clone_a_server = psycopg2.connect(service="lizsync_clone_a")
        self.clone_a_cursor = self.clone_a_server.cursor()

        self.clone_b_server = psycopg2.connect(service="lizsync_clone_b")
        self.clone_b_cursor = self.clone_b_server.cursor()

        self.provider = ProcessingProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

        self.feedback = LoggerProcessingFeedBack()
        feedback = self.feedback if DEBUG else None

        self.feedback.pushInfo('Recreating schemas…')
        _, _, _, ok, error_message = fetch_data_from_sql_query(
            "test", "DROP SCHEMA IF EXISTS {} CASCADE;".format(SCHEMA_DATA))
        self.assertTrue(ok, error_message)

        _, _, _, ok, error_message = fetch_data_from_sql_query(
            "test", "CREATE SCHEMA IF NOT EXISTS {};".format(SCHEMA_DATA))
        self.assertTrue(ok, error_message)

        self.feedback.pushInfo('Importing data…')
        # Load testing data
        for root, directories, files in os.walk(plugin_test_data_path()):
            for file in files:
                if file.lower().endswith('.geojson'):
                    params = {
                        'DATABASE': 'test',
                        'INPUT': plugin_test_data_path(file),
                        'SHAPE_ENCODING': '',
                        'GTYPE': 0,
                        'A_SRS': None,
                        'T_SRS': None,
                        'S_SRS': None,
                        'SCHEMA': SCHEMA_DATA,
                        'TABLE': '',
                        'PK': 'id',
                        'PRIMARY_KEY': None,
                        'GEOCOLUMN': 'geom',
                        'DIM': 0,
                        'SIMPLIFY': '',
                        'SEGMENTIZE': '',
                        'SPAT': None,
                        'CLIP': False,
                        'WHERE': '',
                        'GT': '',
                        'OVERWRITE': True,
                        'APPEND': False,
                        'ADDFIELDS': False,
                        'LAUNDER': False,
                        'INDEX': False,
                        'SKIPFAILURES': False,
                        'PROMOTETOMULTI': False,
                        'PRECISION': True,
                        'OPTIONS': '-lco fid=ogc_fid'
                    }
                    processing.run(
                        "gdal:importvectorintopostgisdatabaseavailableconnections",
                        params,
                        feedback=feedback)

                    # Set the sequence on the table
                    sql = (
                        "SELECT setval(pg_get_serial_sequence('{schema}.{table}', 'id'), "
                        "coalesce(max(id), 0) + 1, false) "
                        "FROM "
                        "{schema}.{table};"
                    ).format(schema=SCHEMA_DATA, table=file.replace('.geojson', ''))
                    _, _, _, ok, error_message = fetch_data_from_sql_query("test", sql)
                    self.assertTrue(ok, error_message)

        self.feedback.pushInfo('Creating database structure…')
        params = {
            "CONNECTION_NAME": "test",
            "OVERRIDE_AUDIT": True,
            "OVERRIDE_LIZSYNC": True,
        }
        result = processing.run(
            "lizsync:create_database_structure", params, feedback=feedback
        )
        self.assertEqual(1, result['OUTPUT_STATUS'])

        self.feedback.pushInfo('Initializing central database…')
        params = {
            "CONNECTION_NAME_CENTRAL": "test",
            "ADD_SERVER_ID": True,
            "ADD_UID_COLUMNS": True,
            "ADD_AUDIT_TRIGGERS": True,
            "SCHEMAS": SCHEMA_DATA,
        }
        result = processing.run(
            "lizsync:initialize_central_database", params, feedback=feedback
        )
        self.assertEqual(1, result['OUTPUT_STATUS'])

        self.feedback.pushInfo('Packaging master database…')
        zip_archive = "/tmp/archive_test.zip"
        # zip_archive = '/tests_directory/lizsync/zip_archive.zip'
        params = {
            "CONNECTION_NAME_CENTRAL": "test",
            "POSTGRESQL_BINARY_PATH": "/usr/bin/",
            "SCHEMAS": SCHEMA_DATA,
            "ZIP_FILE": zip_archive,
            # "ADDITIONNAL_SQL_FILE": "additionnal_sql_commande.sql"
        }
        processing.run(
            "lizsync:package_master_database", params, feedback=feedback
        )

        self.feedback.pushInfo('Deploying to clone A…')
        params = {
            "CONNECTION_NAME_CENTRAL": "test",
            "CONNECTION_NAME_CLONE": "lizsync_clone_a",
            "POSTGRESQL_BINARY_PATH": "/usr/bin/",
            "ZIP_FILE": zip_archive
        }

        self.feedback.pushInfo('Deploying to clone B…')
        processing.run(
            "lizsync:deploy_database_server_package", params, feedback=feedback
        )
        params['CONNECTION_NAME_CLONE'] = 'lizsync_clone_b'
        processing.run(
            "lizsync:deploy_database_server_package", params, feedback=feedback
        )

    def tearDown(self) -> None:
        del self.central_server
        del self.central_cursor
        del self.clone_a_server
        del self.clone_a_cursor
        del self.clone_b_server
        del self.clone_b_cursor
        del self.feedback
        del self.provider
        time.sleep(1)
        super().tearDown()

    def test_yml_file(self):
        """Test reading the YML file."""
        with open(plugin_path("test", "scenarios.yml"), 'r') as stream:
            config = yaml.safe_load(stream)

        for test in config:
            self.feedback.pushInfo('Beginning test : {}…'.format(test['description']))
            for item in test['sequence']:
                if item['type'] == 'sleep':
                    time.sleep(0.5)
                    self.feedback.pushInfo('Sleep 0.5')
                elif item['type'] == 'synchro':
                    params = {
                        "CONNECTION_NAME_CENTRAL": "test",
                        "CONNECTION_NAME_CLONE": item['from'],
                    }
                    result = processing.run(
                        "lizsync:synchronize_database", params, feedback=self.feedback
                    )
                    self.assertEqual(1, result['OUTPUT_STATUS'])
                elif item['type'] == 'query':
                    _, _, _, ok, error_message = fetch_data_from_sql_query(item['database'], item['sql'])
                    self.assertTrue(ok, error_message)
                    self.feedback.pushInfo('Query "{}" executed on {}'.format(item['sql'], item['database']))
                elif item['type'] == 'compare':
                    sql = "SELECT * FROM lizsync.compare_tables('{}', '{}')".format(
                        item['schema'],
                        item['table']
                    )
                    _, _, rowCount, ok, error_message = fetch_data_from_sql_query(item['from'], sql)
                    self.assertEqual(0, rowCount)
                else:
                    raise NotImplementedError(item['type'])
            self.feedback.pushInfo('Test ended : {}'.format(test['description']))
