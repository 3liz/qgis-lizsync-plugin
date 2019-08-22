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

from PyQt5.QtCore import QCoreApplication
from qgis.core import (
    QgsDataSourceUri
)

def tr(string):
    return QCoreApplication.translate('Processing', string)

def fetchDataFromSqlQuery(connection_name, sql):

    from db_manager.db_plugins.plugin import BaseError
    from db_manager.db_plugins import createDbPlugin
    from db_manager.db_plugins.postgis.connector import PostGisDBConnector

    header = None
    data = []
    header = []
    rowCount = 0
    error_message = None
    connection = None

    # Create plugin class and try to connect
    ok = True
    try:
        dbpluginclass = createDbPlugin( 'postgis', connection_name )
        connection = dbpluginclass.connect()
    except BaseError as e:
        #DlgDbError.showError(e, self.dialog)
        ok = False
        error_message = e.msg
    except:
        ok = False
        error_message = 'Cannot connect to database'

    if not connection:
        return [header, data, rowCount, ok, error_message]

    db = dbpluginclass.database()
    if not db:
        ok = False
        error_message = 'Unable to get database from connection'
        return [header, data, rowCount, ok, error_message]

    # Get URI
    uri = db.uri()
    try:
        connector = PostGisDBConnector(uri)
    except:
        error_message = tr('Cannot connect to database')
        ok = False
        return [header, data, rowCount, ok, error_message]

    c = None
    ok = True
    #print "run query"
    try:
        c = connector._execute(None,str(sql))
        data = []
        header = connector._get_cursor_columns(c)
        if header == None:
            header = []
        if len(header) > 0:
            data = connector._fetchall(c)
        rowCount = c.rowcount
        if rowCount == -1:
            rowCount = len(data)

    except BaseError as e:
        ok = False
        error_message = e.msg
        return [header, data, rowCount, ok, error_message]
    finally:
        if c:
            c.close()
            del c

    # Log errors
    if not ok:
        error_message = tr('Unknown error occured while fetching data')
        return [header, data, rowCount, ok, error_message]
        print(error_message)
        print(sql)

    return [header, data, rowCount, ok, error_message]


def validateTimestamp(timestamp_text):
    from dateutil.parser import parse
    valid = True
    msg = ''
    try:
        parse(timestamp_text)
    except ValueError as e:
        valid = False
        msg = str(e)
    return valid, msg
