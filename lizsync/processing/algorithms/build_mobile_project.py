__copyright__ = 'Copyright 2020, 3Liz'
__license__ = 'GPL version 3'
__email__ = 'info@3liz.org'
__revision__ = '$Format:%H$'

import shutil
import os
import re
import sys

from qgis.core import (
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterString,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber,
    QgsProcessingParameterMultipleLayers
)
from qgis.PyQt.QtXml import QDomDocument
from .tools import (
    lizsyncConfig,
    getUriFromConnectionName,
)
from ...qgis_plugin_tools.tools.i18n import tr
from ...qgis_plugin_tools.tools.algorithm_processing import BaseProcessingAlgorithm


class BuildMobileProject(BaseProcessingAlgorithm):
    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    PG_LAYERS = 'PG_LAYERS'
    GPKG_LAYERS = 'GPKG_LAYERS'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'build_mobile_project'

    def displayName(self):
        return tr('Build a mobile QGIS project')

    def group(self):
        return tr('03 File synchronization')

    def groupId(self):
        return 'lizsync_file_sync'

    def shortHelpString(self):
        short_help = tr(
            ' This scripts builds a mobile version of the current QGIS project.'
            '\n'
            '\n'
            ' Todo'

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

        # PostgreSQL layers
        self.addParameter(
            QgsProcessingParameterMultipleLayers(
                self.PG_LAYERS,
                tr('PostgreSQL Layers to edit in the field'),
                QgsProcessing.TypeVector,
                optional=False,
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

        return super(BuildMobileProject, self).checkParameterValues(parameters, context)

    def replacePostgresqlDatasource(self, connection_name_central, datasource):
        # Get uri from connection names
        status_central, uri_central, error_message_central = getUriFromConnectionName(
            connection_name_central,
            False
        )
        if not status_central or not uri_central:
            m = error_message_central
            return False, m

        # Check if layer datasource and connection datasource have common data
        if not uri_central.connectionInfo() in datasource:
            m = tr('Central database and layer connection parameters do not match')
            return False, m

        # Build central and clone datasource components to search & replace
        uris = {'central': {}, 'clone': {}}
        if uri_central.service():
            uris['central'] = "service='%s'" % uri_central.service()
        else:
            uris['central'] = "dbname='{}' host={} port={} user='[A_Za-z_@]+'( password='[^ ]+')?".format(
                uri_central.database(),
                uri_central.host(),
                uri_central.port()
            )

        # hard coded datasource for the Android PostgreSQL device database
        # we cannot use service, because QField cannot use a service defined inside Termux
        uris['clone'] = "dbname='gis' host=localhost user='gis' password='gis'"

        # Replace with regex
        regex = re.compile(uris['central'], re.IGNORECASE)
        datasource = regex.sub(
            uris['clone'],
            datasource
        )

        return datasource, 'Success'

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

        # Get current project file
        project = context.project()
        input_path = project.absoluteFilePath()
        output_path = input_path.replace('.qgs', '_mobile.qgs')
        output_directory = project.baseName() + '_mobile/'

        # Save to new file
        feedback.pushInfo(
            tr('Save mobile project')
        )
        if os.path.isfile(output_path):
            os.remove(output_path)
        try:
            shutil.copy(input_path, output_path)
        except IOError as e:
            msg = tr('Unable to copy the current project file')
            msg += ' ' + e
            raise QgsProcessingException(msg)
        except Exception as e:
            msg = tr('Unexpected error') + ' ' + sys.exc_info()
            msg += ' ' + e
            raise QgsProcessingException(msg)
        feedback.pushInfo(
            tr('* Mobile project saved')
        )
        feedback.pushInfo('')

        # Read mobile project file as XML
        feedback.pushInfo(
            tr('Read XML from saved project')
        )
        content = None
        with open(input_path, 'r') as f:
            content = f.read()
        dom = QDomDocument()
        dom.setContent(content)
        feedback.pushInfo(
            tr('* XML successfully read')
        )
        feedback.pushInfo('')

        # Get layers and layers id
        pg_layers = self.parameterAsLayerList(parameters, self.PG_LAYERS, context)
        pg_layers = [layer for layer in pg_layers if layer.providerType() == 'postgres']
        pg_ids = [layer.id() for layer in pg_layers]
        pg_changed = []
        gpkg_layers = self.parameterAsLayerList(parameters, self.GPKG_LAYERS, context)
        gpkg_ids = [layer.id() for layer in gpkg_layers]
        gpkg_changed = []

        # Loop for each layer and change datasource if needed
        feedback.pushInfo(
            tr('Change the datasource of layers to make the QGIS project portable')
        )
        nodelist = dom.elementsByTagName('maplayer')
        for node in (nodelist.at(i) for i in range(nodelist.count())):
            # Get layer id, name, datasource and provider
            layerid = node.firstChildElement('id').text()
            layername = node.firstChildElement('layername').text()
            datasource = node.firstChildElement('datasource').text()

            # PostgreSQL
            if layerid in pg_ids:
                # Replace datasource by field localhost datasource
                new_source, msg = self.replacePostgresqlDatasource(
                    connection_name_central,
                    datasource
                )
                if not new_source:
                    raise QgsProcessingException(msg)
                if new_source != datasource:
                    node.firstChildElement('datasource').firstChild().setNodeValue(new_source)

                    # Add to the list
                    pg_changed.append(layername)

            # GeoPackage
            # We do not change the datasource for PostgreSQL layers chosen for editing
            # To avoid misconfiguration
            if layerid in gpkg_ids and layerid not in pg_ids:
                # Replace datasource with the geopackage file path and layer name
                new_source = './{}/layers.gpkg|layername={}'.format(
                    output_directory,
                    layername
                )
                node.firstChildElement('datasource').firstChild().setNodeValue(new_source)

                # We must also change the provider into ogr
                node.firstChildElement('provider').firstChild().setNodeValue('ogr')

                # Add to the list
                gpkg_changed.append(layername)

        feedback.pushInfo('')

        # Write XML content back
        if pg_changed or gpkg_changed:
            # Convert XML to string
            content = dom.toString()

            # Log changed layers
            feedback.pushInfo(tr('PostgreSQL layers to edit in the field') + ':')
            for layer in pg_changed:
                feedback.pushInfo('* {}'.format(layer))
            feedback.pushInfo('')
            feedback.pushInfo(tr('Other layers converted to GeoPackage') + ':')
            for layer in gpkg_changed:
                feedback.pushInfo('* {}'.format(layer))

            # Write file
            with open(output_path, 'w') as f:
                f.write(content)
            feedback.pushInfo('')

        if not pg_changed:
            msg = tr('No PostgreSQL layers datasource could be changed to target the clone database')
            raise QgsProcessingException(msg)

        # Log
        msg = tr('The current QGIS project mobile version has been successfully saved. Please send it to your field device.')
        feedback.pushInfo(
            msg
        )
        feedback.pushInfo(
            output_path
        )

        output = {
            self.OUTPUT_STATUS: 1,
            self.OUTPUT_STRING: msg
        }
        return output
