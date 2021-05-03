"""Base class for tests using a database."""
import os
import psycopg2
import time
import yaml

import processing

from qgis.core import (
    QgsApplication,
    QgsVectorLayer,
    QgsProcessingException
)
from qgis.testing import unittest

from ..processing.algorithms.tools import fetchDataFromSqlQuery
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

        # Set PostgreSQL connections
        self.central_server = psycopg2.connect(service="test")
        self.central_cursor = self.central_server.cursor()

        self.clone_a_server = psycopg2.connect(service="lizsync_clone_a")
        self.clone_a_cursor = self.clone_a_server.cursor()

        self.clone_b_server = psycopg2.connect(service="lizsync_clone_b")
        self.clone_b_cursor = self.clone_b_server.cursor()

        # Add QGIS processing provider
        self.provider = ProcessingProvider()
        registry = QgsApplication.processingRegistry()
        if not registry.providerById(self.provider.id()):
            registry.addProvider(self.provider)

        self.feedback = LoggerProcessingFeedBack(use_logger=True)
        feedback = self.feedback if DEBUG else None

        # Drop and recreate PostgreSQL test schema
        self.feedback.pushInfo('Recreating schemas…')
        _, ok, error_message = fetchDataFromSqlQuery(
            "test", "DROP SCHEMA IF EXISTS {} CASCADE;".format(SCHEMA_DATA))
        self.assertTrue(ok, error_message)

        _, ok, error_message = fetchDataFromSqlQuery(
            "test", "CREATE SCHEMA IF NOT EXISTS {};".format(SCHEMA_DATA))
        self.assertTrue(ok, error_message)

        # Import data
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
                    _, ok, error_message = fetchDataFromSqlQuery("test", sql)
                    self.assertTrue(ok, error_message)

        # Create database structure
        self.feedback.pushInfo('Creating database structure…')
        params = {
            "CONNECTION_NAME": "test",
            "OVERRIDE": True,
        }
        try:
            result = processing.run(
                "lizsync:create_database_structure", params, feedback=feedback
            )
        except QgsProcessingException as e:
            self.assertTrue(False, e)

        # Initialize central database
        self.feedback.pushInfo('Initializing central database…')
        params = {
            "CONNECTION_NAME_CENTRAL": "test",
            "ADD_UID_COLUMNS": True,
            "ADD_AUDIT_TRIGGERS": True,
            "SCHEMAS": SCHEMA_DATA,
        }
        result = processing.run(
            "lizsync:initialize_central_database", params, feedback=feedback
        )
        self.assertEqual(1, result['OUTPUT_STATUS'])

        # Create a package from the central database
        self.feedback.pushInfo('Packaging master database…')
        zip_archive = "/tmp/archive_test.zip"
        # zip_archive = '/tests_directory/lizsync/zip_archive.zip'
        district_layer = QgsVectorLayer(
            'service=\'test\' key=\'ogc_fid\' estimatedmetadata=true srid=2154 type=Polygon checkPrimaryKeyUnicity=\'1\' table=\"test\".\"montpellier_districts\" (geom) sql=', 'test', 'postgres'
        )
        subdistrict_layer = QgsVectorLayer(
            'service=\'test\' key=\'ogc_fid\' estimatedmetadata=true srid=2154 type=Polygon checkPrimaryKeyUnicity=\'1\' table=\"test\".\"montpellier_sub_districts\" (geom) sql=', 'test', 'postgres'
        )
        pluviometer_layer = QgsVectorLayer(
            'service=\'test\' key=\'ogc_fid\' estimatedmetadata=true srid=2154 type=Point checkPrimaryKeyUnicity=\'1\' table=\"test\".\"pluviometers\" (geom) sql=', 'test', 'postgres'
        )
        params = {
            'CONNECTION_NAME_CENTRAL': 'test',
            'POSTGRESQL_BINARY_PATH': '/usr/bin/',
            'PG_LAYERS': [
                district_layer,
                subdistrict_layer,
                pluviometer_layer,
            ],
            'ZIP_FILE': zip_archive,
            # "ADDITIONNAL_SQL_FILE": "additionnal_sql_commande.sql"
        }

        processing.run(
            "lizsync:package_central_database", params, feedback=feedback
        )

        # Deploy package to clones
        self.feedback.pushInfo('Deploying to clone A…')
        params = {
            "CONNECTION_NAME_CENTRAL": "test",
            "CONNECTION_NAME_CLONE": "lizsync_clone_a",
            "POSTGRESQL_BINARY_PATH": "/usr/bin/",
            "ZIP_FILE": zip_archive
        }
        processing.run(
            "lizsync:deploy_database_server_package", params, feedback=feedback
        )
        self.feedback.pushInfo('Deploying to clone B…')
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
        """Test synchronization scenarios from YAML file"""
        with open(plugin_path("test", "scenarios.yml"), 'r') as stream:
            config = yaml.safe_load(stream)

        for test in config:
            self.feedback.pushInfo('===========================')
            self.feedback.pushInfo('Beginning test : {}…'.format(test['description']))
            for item in test['sequence']:
                if item['type'] == 'sleep':
                    sleep_time = 0.1
                    self.feedback.pushInfo('Sleep %s seconds' % sleep_time)
                    time.sleep(sleep_time)

                elif item['type'] == 'synchro':
                    self.feedback.pushInfo('Run synchro from %s' % item['from'])
                    params = {
                        "CONNECTION_NAME_CENTRAL": "test",
                        "CONNECTION_NAME_CLONE": item['from'],
                    }
                    result = processing.run(
                        "lizsync:synchronize_database", params, feedback=self.feedback
                    )
                    self.assertEqual(1, result['OUTPUT_STATUS'])

                elif item['type'] == 'query':
                    _, ok, error_message = fetchDataFromSqlQuery(item['database'], item['sql'])
                    self.assertTrue(ok, error_message)
                    self.feedback.pushInfo('Query executed on {}: {}'.format(item['database'], item['sql']))

                elif item['type'] == 'compare':
                    self.feedback.pushInfo(
                        'Compare table data between central & {}: "{}"."{}"'.format(
                            item['from'],
                            item['schema'],
                            item['table']
                        )
                    )
                    sql = "SELECT * FROM lizsync.compare_tables('{}', '{}')".format(
                        item['schema'],
                        item['table']
                    )
                    data, ok, error_message = fetchDataFromSqlQuery(item['from'], sql)

                    self.assertEqual(0, len(data))

                elif item['type'] == 'verify':
                    self.feedback.pushInfo('Verify data in database {}'.format(item['database']))
                    data, ok, error_message = fetchDataFromSqlQuery(item['database'], item['sql'])
                    self.assertEqual(data[0][0], item['expected'])

                else:
                    raise NotImplementedError(item['type'])

            self.feedback.pushInfo('Test ended : {}'.format(test['description']))
