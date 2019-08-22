# -*- coding: utf-8 -*-

"""
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
__date__ = '2019-02-15'
__copyright__ = '(C) 2019 by 3liz'

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = '$Format:%H$'

from qgis.core import QgsProcessingProvider
from .algorithms.get_data_as_layer import GetDataAsLayer
from .algorithms.configure_plugin import ConfigurePlugin
from .algorithms.execute_sql import ExecuteSql
from .algorithms.create_database_structure import CreateDatabaseStructure

class LizsyncProvider(QgsProcessingProvider):

    def unload(self):
        """
        Unloads the provider. Any tear-down steps required by the provider
        should be implemented here.
        """
        pass

    def loadAlgorithms(self):

        self.addAlgorithm(GetDataAsLayer())
        self.addAlgorithm(ConfigurePlugin())
        self.addAlgorithm(ExecuteSql())
        self.addAlgorithm(CreateDatabaseStructure())

    def id(self):
        return 'lizsync'

    def name(self):
        return self.tr('Lizsync')

    def longName(self):
        return self.tr('Lizsync')
