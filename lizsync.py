# -*- coding: utf-8 -*-

"""
/***************************************************************************
 Lizsync
                                 A QGIS plugin
 France only - Plugin dedicated to import and manage water network data by using Lizsync standard
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2018-12-19
        copyright            : (C) 2018 by 3liz
        email                : info@3liz.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

__author__ = '3liz'
__date__ = '2018-12-19'
__copyright__ = '(C) 2018 by 3liz'

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = '$Format:%H$'

import os
import sys
import inspect

from qgis.core import QgsProcessingAlgorithm, QgsApplication
from .processing.provider import LizsyncProvider

cmd_folder = os.path.split(inspect.getfile(inspect.currentframe()))[0]

if cmd_folder not in sys.path:
    sys.path.insert(0, cmd_folder)

from qgis.PyQt.QtCore import QCoreApplication, QTranslator
from .qgis_plugin_tools.tools.i18n import setup_translation

class LizsyncPlugin:

    def __init__(self):
        self.provider = LizsyncProvider()

        locale, file_path = setup_translation()
        if file_path:
            # LOGGER.info('Translation to {}'.format(file_path))
            self.translator = QTranslator()
            self.translator.load(file_path)
            QCoreApplication.installTranslator(self.translator)
        else:
            # LOGGER.info('Translation not found: {}'.format(locale))
            pass


    def initGui(self):
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        QgsApplication.processingRegistry().removeProvider(self.provider)
