__copyright__ = "Copyright 2020, 3Liz"
__license__ = "GPL version 3"
__email__ = "info@3liz.org"
__revision__ = "$Format:%H$"

from functools import partial

from qgis.PyQt import (
    QtWidgets,
)
from qgis.PyQt.QtWidgets import (
    QPushButton,
)
from qgis.core import (
    Qgis,
)

from webbrowser import open_new
from processing import execAlgorithmDialog
from lizsync.qgis_plugin_tools.tools.i18n import tr
from lizsync.qgis_plugin_tools.tools.resources import load_ui, plugin_name

FORM_CLASS = load_ui('lizsync_dockwidget_base.ui')


class LizsyncDockWidget(QtWidgets.QDockWidget, FORM_CLASS):

    def __init__(self, iface, parent=None):
        """Constructor."""
        super().__init__(parent)

        self.iface = iface
        self.setupUi(self)

        # Buttons directly linked to an algorithm
        self.algorithms = [
            'create_database_structure',
            'upgrade_database_structure',
            'initialize_central_database',

            'deploy_database_server_package',
            'package_master_database',
            'synchronize_database',

            'send_projects_and_files_to_clone_ftp',
            'get_projects_and_files_from_central_ftp',
            'synchronize_media_subfolder_to_ftp',
        ]
        for alg in self.algorithms:
            button = self.findChild(QPushButton, 'button_{0}'.format(alg))
            if not button:
                continue
            button.clicked.connect(partial(self.runAlgorithm, alg))

        # Buttons not linked to algs
        #
        # Help on database
        button = self.findChild(QPushButton, 'button_help_database')
        if button:
            button.clicked.connect(self.help_database)

    def runAlgorithm(self, name):

        if name not in self.algorithms:
            self.iface.messageBar().pushMessage(
                tr("Error"),
                tr("This algorithm cannot be found") + ' {}'.format(name),
                level=Qgis.Critical
            )
            return

        # Run alg
        param = {}
        alg_name = 'lizsync:{0}'.format(name)
        execAlgorithmDialog(alg_name, param)

    @staticmethod
    def help_database():
        """
        Display the help on database structure
        """
        name = plugin_name().lower()
        open_new(r'https://3liz.github.io/qgis-%s-plugin/' % name)
