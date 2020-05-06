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
 This script initializes the plugin, making it known to QGIS.
"""

__author__ = '3liz'
__date__ = '2018-12-19'
__copyright__ = '(C) 2018 by 3liz'

from typing import Any


# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name

    from .plugin import LizsyncPlugin
    return LizsyncPlugin()


def WPSClassFactory(iface) -> Any:
    """
    :type iface: WPSServerInterface
    """

    from .processing.provider import LizsyncProvider
    iface.registerProvider(LizsyncProvider())
