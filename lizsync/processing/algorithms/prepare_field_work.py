__copyright__ = 'Copyright 2020, 3Liz'
__license__ = 'GPL version 3'
__email__ = 'info@3liz.org'
__revision__ = '$Format:%H$'

import os

import processing

from qgis.core import (
    QgsProcessing,
    QgsProcessingParameterString,
    QgsProcessingParameterFile,
    QgsProcessingParameterBoolean,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber,
    QgsProcessingParameterMultipleLayers
)
from .tools import (
    lizsyncConfig,
    getUriFromConnectionName,
)
from ...qgis_plugin_tools.tools.i18n import tr
from ...qgis_plugin_tools.tools.algorithm_processing import BaseProcessingAlgorithm


class PrepareFieldWork(BaseProcessingAlgorithm):
    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    POSTGRESQL_BINARY_PATH = 'POSTGRESQL_BINARY_PATH'
    PG_LAYERS = 'PG_LAYERS'
    ADDITIONAL_SQL_FILE = 'ADDITIONAL_SQL_FILE'
    GPKG_LAYERS = 'GPKG_LAYERS'
    OVERWRITE_GPKG = 'OVERWRITE_GPKG'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'prepare_field_work'

    def displayName(self):
        return tr('Prepare field work')

    def group(self):
        return tr('03 GeoPoppy file synchronization')

    def groupId(self):
        return 'lizsync_geopoppy_sync'

    def shortHelpString(self):
        short_help = tr(
            ' This scripts helps to prepare field work: it creates a package with PostgreSQL layers data, '
            'a Geopackage file with the other vector layers data '
            'and creates a mobile version of the current QGIS project'
            '\n'
            '\n'
            ' '

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

        # PostgreSQL binary path (with psql pg_restore, etc.)
        postgresql_binary_path = ls.variable('binaries/postgresql')
        self.addParameter(
            QgsProcessingParameterFile(
                self.POSTGRESQL_BINARY_PATH,
                tr('PostgreSQL binary path'),
                defaultValue=postgresql_binary_path,
                behavior=QgsProcessingParameterFile.Folder,
                optional=False
            )
        )

        # PostgreSQL layers
        self.addParameter(
            QgsProcessingParameterMultipleLayers(
                self.PG_LAYERS,
                tr('PostgreSQL Layers to edit in the field'),
                QgsProcessing.TypeVector,
                optional=False,
            )
        )

        # Additionnal SQL file to run on the clone
        additional_sql_file = ls.variable('general/additional_sql_file')
        self.addParameter(
            QgsProcessingParameterFile(
                self.ADDITIONAL_SQL_FILE,
                tr('Additionnal SQL file to run in the clone after the ZIP deployement'),
                defaultValue=additional_sql_file,
                behavior=QgsProcessingParameterFile.File,
                optional=True,
                extension='sql'
            )
        )

        # Layers to export to Geopackage
        self.addParameter(
            QgsProcessingParameterMultipleLayers(
                self.GPKG_LAYERS,
                tr('Layers to convert into Geopackage'),
                QgsProcessing.TypeVector,
                optional=False,
            )
        )

        # Override existing Geopackage file
        p = QgsProcessingParameterBoolean(
            self.OVERWRITE_GPKG,
            tr('Overwrite the Geopackage file if it exists ?'),
            defaultValue=True,
        )
        self.addParameter(p)

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

        # Check current project has a file
        path = context.project().absoluteFilePath()
        if not path:
            msg = tr('You must save the current project before running this algorithm')
            return False, msg

        # Check current project has been saved
        if context.project().isDirty():
            msg = tr('You must save the current project before running this algorithm')
            return False, msg

        # Check current project path not zipped
        if path.endswith('qgz'):
            msg = tr('QGIS project files with .qgz extension cannot yet be processed. Use .qgs instead')
            return False, msg

        # Check PostgreSQL layers
        layers = self.parameterAsLayerList(parameters, self.PG_LAYERS, context)
        layers = [layer for layer in layers if layer.providerType() == 'postgres']
        if not layers:
            return False, tr('At least one PostgreSQL layer is required')

        # Check connections
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]
        ok, uri, msg = getUriFromConnectionName(connection_name_central, True)
        if not ok:
            return False, msg

        return super(PrepareFieldWork, self).checkParameterValues(parameters, context)

    def processAlgorithm(self, parameters, context, feedback):
        """
        Run the needed steps for bi-directionnal database synchronization
        """
        output = {
            self.OUTPUT_STATUS: 0,
            self.OUTPUT_STRING: ''
        }

        # Parameters
        connection_name_central = parameters[self.CONNECTION_NAME_CENTRAL]

        # store parameters
        ls = lizsyncConfig()
        ls.setVariable('postgresql:central/name', connection_name_central)
        ls.save()

        # Create mobile output directory
        project = context.project()
        project_directory = project.absolutePath()
        output_directory = project_directory + '/' + project.baseName() + '_mobile'
        if not os.path.isdir(output_directory):
            os.mkdir(output_directory)

        # Package PostgreSQL layers
        zip_archive = os.path.join(output_directory, 'lizsync.zip')
        if os.path.exists(zip_archive):
            os.remove(zip_archive)
        params = {
            'CONNECTION_NAME_CENTRAL': connection_name_central,
            'POSTGRESQL_BINARY_PATH': parameters[self.POSTGRESQL_BINARY_PATH],
            'PG_LAYERS': parameters[self.PG_LAYERS],
            'ADDITIONNAL_SQL_FILE': parameters[self.ADDITIONAL_SQL_FILE],
            'ZIP_FILE': zip_archive,
        }
        processing.run(
            "lizsync:package_master_database", params, context=context, feedback=feedback
        )

        # Package other layers into GeoPackage
        gpkg_layers = self.parameterAsLayerList(parameters, self.GPKG_LAYERS, context)
        if gpkg_layers:
            gpkg_output = os.path.join(output_directory, 'layers.gpkg')
            params = {
                'LAYERS': parameters[self.GPKG_LAYERS],
                'OVERWRITE': parameters[self.OVERWRITE_GPKG],
                'SAVE_STYLES': True,
                'OUTPUT': gpkg_output,
            }
            processing.run(
                "native:package", params, context=context, feedback=feedback
            )

        # Create a mobile version of the project
        params = {
            'CONNECTION_NAME_CENTRAL': connection_name_central,
            'PG_LAYERS': parameters[self.PG_LAYERS],
            'GPKG_LAYERS': parameters[self.GPKG_LAYERS],
        }
        processing.run(
            "lizsync:build_mobile_project", params, context=context, feedback=feedback
        )

        # Log
        msg = tr(
            'Every steps needed to create a portable version of your current QGIS '
            'project have been successfully executed.'
        )
        feedback.pushInfo(
            msg
        )

        output = {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: msg
        }
        return output
