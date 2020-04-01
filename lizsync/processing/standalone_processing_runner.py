#!/usr/bin/env python3
import os
import sys
import json

# variables
user_profile = os.path.expanduser('~/.local/share/QGIS/QGIS3/profiles/default')
pg_service_file = '/etc/postgresql-common/pg_service.conf'

# Initialize needed paths
# to be able to load processing.core.Processing
qgisPrefixPath = os.environ.get('QGIS_PREFIX_PATH', '/usr/')
qgisConfigPath = os.environ.get('QGIS_CUSTOM_CONFIG_PATH', user_profile)
# QGIS native plugins
sys.path.append(os.path.join(qgisPrefixPath, "share/qgis/python/plugins/"))
# QGIS user plugins
sys.path.append(os.path.join(qgisConfigPath, 'python/plugins/'))

# Initialize PostgreSQL service connection file PGSERVICEFILE
os.environ['PGSERVICEFILE'] = pg_service_file

# Import QGIS AND QT modules
from qgis.core import QgsSettings, QgsApplication
from qgis.analysis import QgsNativeAlgorithms
from qgis.PyQt.QtCore import QCoreApplication, QSettings
from processing.core.Processing import Processing

# Create QGIS app
QgsApplication.setPrefixPath(qgisPrefixPath, True)
app = QgsApplication([], False, qgisConfigPath)

# Set QSettings format and path
# needed so that db_manager plugin can read the settings from QGIS3.ini
QCoreApplication.setOrganizationName(QgsApplication.QGIS_ORGANIZATION_NAME)
QCoreApplication.setOrganizationDomain(QgsApplication.QGIS_ORGANIZATION_DOMAIN)
QCoreApplication.setApplicationName(QgsApplication.QGIS_APPLICATION_NAME)
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, qgisConfigPath)

# Init QGIS
app.initQgis()

# Initialize processing
Processing.initialize()

# Add Processing providers
reg = app.processingRegistry()
# lizsync provider
from lizsync.processing.provider import LizsyncProvider

reg.addProvider(LizsyncProvider())
# Native QGIS provider
# reg.addProvider(QgsNativeAlgorithms())

# Get parameters
input_alg = sys.argv[1]
parameters = sys.argv[2]
print(input_alg)
print(parameters)
input_params = json.loads(parameters)

# Run Alg
from qgis.core import QgsProcessingFeedback

feedback = QgsProcessingFeedback()
from processing import run as processing_run

res = processing_run(
    input_alg,
    input_params,
    feedback=feedback
)
print("RESULT = %s" % json.dumps(res))

# Exit
app.exitQgis()
