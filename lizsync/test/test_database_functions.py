"""Tests for load structure with an empty database."""

from .base_test_database import DatabaseTestCase

__copyright__ = "Copyright 2019, 3Liz"
__license__ = "GPL version 3"
__email__ = "info@3liz.org"
__revision__ = "$Format:%H$"


class TestLoadStructureEmptyDatabase(DatabaseTestCase):

    """This class is redundant with test_load_structure,
    but this one is using a setup function."""

    def test_configure_project_with_new_db(self):
        """Test we can load the PostGIS structure using the setup function."""
        self.cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'lizsync'"
        )
        records = self.cursor.fetchall()
        result = [r[0] for r in records]
        expected = [
            "history",
            "server_metadata",
            "conflicts",
            "synchronized_tables",
            "sys_structure_metadonnee",
        ]
        self.assertCountEqual(expected, result)
