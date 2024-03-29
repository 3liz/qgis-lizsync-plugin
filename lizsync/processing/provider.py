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
from qgis.PyQt.QtGui import QIcon

from ..qgis_plugin_tools.tools.i18n import tr
from ..qgis_plugin_tools.tools.resources import resources_path
from .algorithms.create_database_structure import CreateDatabaseStructure
from .algorithms.upgrade_database_structure import UpgradeDatabaseStructure
from .algorithms.initialize_central_database import InitializeCentralDatabase
from .algorithms.package_central_database import PackageCentralDatabase
from .algorithms.deploy_database_server_package import DeployDatabaseServerPackage
from .algorithms.synchronize_database import SynchronizeDatabase
from .algorithms.send_projects_and_files_to_clone_ftp import SendProjectsAndFilesToCloneFtp
from .algorithms.build_mobile_project import BuildMobileProject

from .algorithms.package_all import PackageAll
from .algorithms.deploy_all import DeployAll


class LizsyncProvider(QgsProcessingProvider):

    def loadAlgorithms(self):
        self.addAlgorithm(PackageCentralDatabase())
        self.addAlgorithm(DeployDatabaseServerPackage())
        self.addAlgorithm(SynchronizeDatabase())

        self.addAlgorithm(CreateDatabaseStructure())
        self.addAlgorithm(UpgradeDatabaseStructure())
        self.addAlgorithm(InitializeCentralDatabase())
        self.addAlgorithm(SendProjectsAndFilesToCloneFtp())

        self.addAlgorithm(BuildMobileProject())
        self.addAlgorithm(PackageAll())
        self.addAlgorithm(DeployAll())

    def id(self):
        return 'lizsync'

    def name(self):
        return tr('Lizsync')

    def longName(self):
        return tr('Lizsync')

    def icon(self):
        return QIcon(resources_path('icons', 'icon.png'))
