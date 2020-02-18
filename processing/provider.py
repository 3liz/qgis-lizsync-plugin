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
from .algorithms.configure_plugin import ConfigurePlugin
from .algorithms.create_database_structure import CreateDatabaseStructure
from .algorithms.upgrade_database_structure import UpgradeDatabaseStructure
from .algorithms.initialize_central_database import InitializeCentralDatabase
from .algorithms.package_central_database import PackageCentralDatabase
from .algorithms.deploy_database_server_package import DeployDatabaseServerPackage
from .algorithms.synchronize_database import SynchronizeDatabase
from .algorithms.get_projects_and_files_from_central_ftp import GetProjectsAndFilesFromCentralFtp
from .algorithms.send_projects_and_files_to_clone_ftp import SendProjectsAndFilesToCloneFtp
from .algorithms.synchronize_media_subfolder_to_ftp import SynchronizeMediaSubfolderToFtp



class LizsyncProvider(QgsProcessingProvider):

    def unload(self):
        """
        Unloads the provider. Any tear-down steps required by the provider
        should be implemented here.
        """
        pass

    def loadAlgorithms(self):

        self.addAlgorithm(ConfigurePlugin())
        self.addAlgorithm(CreateDatabaseStructure())
        self.addAlgorithm(UpgradeDatabaseStructure())
        self.addAlgorithm(InitializeCentralDatabase())
        self.addAlgorithm(PackageCentralDatabase())
        self.addAlgorithm(DeployDatabaseServerPackage())
        self.addAlgorithm(SynchronizeDatabase())
        self.addAlgorithm(GetProjectsAndFilesFromCentralFtp())
        self.addAlgorithm(SendProjectsAndFilesToCloneFtp())
        self.addAlgorithm(SynchronizeMediaSubfolderToFtp())

    def id(self):
        return 'lizsync'

    def name(self):
        return self.tr('Lizsync')

    def longName(self):
        return self.tr('Lizsync')
