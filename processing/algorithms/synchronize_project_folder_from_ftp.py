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
__date__ = '2018-12-19'
__copyright__ = '(C) 2018 by 3liz'

from PyQt5.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingUtils,
    QgsProcessingException,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFile,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber,
    QgsExpressionContextUtils
)

import os, subprocess
from pathlib import Path
import processing
from datetime import date, datetime
from ftplib import FTP
import netrc
import re
from .tools import *

class SynchronizeProjectFolderFromFtp(QgsProcessingAlgorithm):
    """
    Synchronize local data from remote FTP
    via LFTP
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.

    CONNECTION_NAME_CENTRAL = 'CONNECTION_NAME_CENTRAL'
    CONNECTION_NAME_CLONE = 'CONNECTION_NAME_CLONE'

    LOCAL_QGIS_PROJECT_FOLDER = 'LOCAL_QGIS_PROJECT_FOLDER'
    FTP_HOST = 'FTP_HOST'
    FTP_LOGIN = 'FTP_LOGIN'
    FTP_REMOTE_DIR = 'FTP_REMOTE_DIR'
    FTP_EXCLUDE_REMOTE_SUBDIRS = 'FTP_EXCLUDE_REMOTE_SUBDIRS'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    def name(self):
        return 'synchronize_project_folder_from_ftp'

    def displayName(self):
        return self.tr('Synchronize project and data from FTP')

    def group(self):
        return self.tr('03 Synchronize data and files')

    def groupId(self):
        return 'lizsync_sync'

    def shortHelpString(self):
        return getShortHelpString(os.path.basename(__file__))

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return SynchronizeProjectFolderFromFtp()

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # INPUTS
        connection_name_central = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_central')
        db_param_a = QgsProcessingParameterString(
            self.CONNECTION_NAME_CENTRAL,
            self.tr('PostgreSQL connection to the central database'),
            defaultValue=connection_name_central,
            optional=False
        )
        db_param_a.setMetadata({
            'widget_wrapper': {
                'class': 'processing.gui.wrappers_postgis.ConnectionWidgetWrapper'
            }
        })
        self.addParameter(db_param_a)

        # Clone database connection parameters
        connection_name_clone = QgsExpressionContextUtils.globalScope().variable('lizsync_connection_name_clone')
        db_param_b = QgsProcessingParameterString(
            self.CONNECTION_NAME_CLONE,
            self.tr('PostgreSQL connection to the local database'),
            defaultValue=connection_name_clone,
            optional=False
        )
        db_param_b.setMetadata({
            'widget_wrapper': {
                'class': 'processing.gui.wrappers_postgis.ConnectionWidgetWrapper'
            }
        })
        self.addParameter(db_param_b)

        local_qgis_project_folder = QgsExpressionContextUtils.globalScope().variable('lizsync_local_qgis_project_folder')
        self.addParameter(
            QgsProcessingParameterString(
                self.LOCAL_QGIS_PROJECT_FOLDER,
                self.tr('Local QGIS project folder'),
                defaultValue=local_qgis_project_folder,
                optional=False
            )
        )
        ftp_host = QgsExpressionContextUtils.globalScope().variable('lizsync_ftp_host')
        self.addParameter(
            QgsProcessingParameterString(
                self.FTP_HOST,
                self.tr('FTP Server host'),
                defaultValue=ftp_host,
                optional=False
            )
        )
        ftp_login = QgsExpressionContextUtils.globalScope().variable('lizsync_ftp_login')
        self.addParameter(
            QgsProcessingParameterString(
                self.FTP_LOGIN,
                self.tr('FTP Server login'),
                defaultValue=ftp_login,
                optional=False
            )
        )
        ftp_remote_dir = QgsExpressionContextUtils.globalScope().variable('lizsync_ftp_remote_dir')
        self.addParameter(
            QgsProcessingParameterString(
                self.FTP_REMOTE_DIR,
                self.tr('FTP Server remote directory'),
                defaultValue=ftp_remote_dir,
                optional=False
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.FTP_EXCLUDE_REMOTE_SUBDIRS,
                self.tr('FTP list of sub-directory to exclude from synchro, separated by commas.'),
                defaultValue='data',
                optional=False
            )
        )

        # OUTPUTS
        # Add output for message
        self.addOutput(
            QgsProcessingOutputNumber(
                self.OUTPUT_STATUS, self.tr('Output status')
            )
        )
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING, self.tr('Output message')
            )
        )

    def setQgisProjectOffline(self, dir, parameters, context, feedback):

        # Get uri from connection names
        central = parameters[self.CONNECTION_NAME_CENTRAL]
        clone = parameters[self.CONNECTION_NAME_CLONE]
        status_central, uri_central, error_message_central = getUriFromConnectionName(central)
        status_clone, uri_clone, error_message_clone = getUriFromConnectionName(clone)

        if not uri_central:
            raise Exception(error_message_central)
        if not uri_clone:
            raise Exception(error_message_clone)

        uris = {
            'central': {'uri': uri_central},
            'clone'  : {'uri': uri_clone}
        }
        for a in ('central', 'clone'):
            if uri_central.service():
                uris[a]['info'] = {'service': uri_central.service()}
            else:
                uris[a]['info'] = {
                    'host': uri.host(),
                    'port': uri.port(),
                    'dbname': uri.database(),
                    'user': uri.username()
                }

        for file in os.listdir(dir):
            if file.endswith(".qgs"):
                qf = os.path.join(dir, file)
                feedback.pushInfo(self.tr('Process QGIS project file') + ' %s' % qf)
                output = open(qf + 'new', 'w')
                with open(qf) as input:
                    regex = re.compile(r"user='[a-z]+@[a-z_]+'", re.IGNORECASE)
                    for s in input:
                        l = s
                        # Do nothing if no PostgreSQL data
                        if 'table=' in l and ('dbname' not in l or 'service' not in l):
                            output.write(l)
                            continue
                        # Loop through connection parameters and replace
                        items = uris['central']['info'].keys()
                        for k in items:
                            stext = str(uris['central']['info'][k])
                            rtext = str(uris['clone']['info'][k])
                            if stext in l:
                                l = l.replace(stext, rtext)
                        # to improve
                        # alway replace user by clone local user
                        # needed if there are multiple user stored in the qgis project for the same server
                        # because one of them can be different from the central connection name user
                        if "user=" in l:
                            l = regex.sub("user='%s'" % uris['clone']['info'], l)
                        output.write(l)
                    output.close()
                os.remove(qf)
                os.rename(qf + 'new', qf)
                feedback.pushInfo(self.tr('Project modified'))

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """

        # Check internet
        feedback.pushInfo(self.tr('CHECK INTERNET CONNECTION'))
        if not check_internet():
            m = self.tr('No internet connection')
            feedback.pushInfo(m)
            raise Exception(m)

        # Parameters
        ftphost = parameters[self.FTP_HOST]
        ftplogin = parameters[self.FTP_LOGIN]
        ftpport = 21
        ftppass = ''
        remotedir = parameters[self.FTP_REMOTE_DIR]
        localdir = parameters[self.LOCAL_QGIS_PROJECT_FOLDER]

        # Check FTP password
        try:
            auth = netrc.netrc().authenticators(ftphost)
            if auth is not None:
                ftplogin, account, ftppass = auth
        except (netrc.NetrcParseError, IOError):
            raise Exception(self.tr('Could not retrieve password from ~/.netrc file'))
        if not ftppass:
            raise Exception(self.tr('Could not retrieve password from ~/.netrc file or is empty'))

        msg = ''

        # Check localdir
        feedback.pushInfo(self.tr('CHECK LOCAL PROJECT DIRECTORY'))
        if not localdir or not os.path.isdir(localdir):
            m = self.tr('QGIS project local directory not found')
            feedback.pushInfo(m)
            raise Exception(m)
        else:
            m = self.tr('QGIS project local directory ok')

        # Check if remotedir exists
        feedback.pushInfo(self.tr('CHECK REMOTE DIRECTORY') + ' %s' % remotedir )
        ftp = FTP()
        ftp.connect(ftphost, 21)
        ftp.login(ftplogin, ftppass)
        try:
            ftp.cwd(remotedir)
            #do the code for successfull cd
            self.tr('Remote directory exists in the central server')
        except Exception:
            ftp.close()
            m = self.tr('Remote directory does not exist')
            feedback.pushInfo(m)
            raise Exception(m)

        # Run FTP sync
        feedback.pushInfo(self.tr('Local directory') + ' %s' % localdir)
        feedback.pushInfo(self.tr('Remote directory') + ' %s' % remotedir)
        excludedirs = parameters[self.FTP_EXCLUDE_REMOTE_SUBDIRS].strip()
        ftp_sync(ftphost, ftpport, ftplogin, remotedir, localdir, excludedirs, parameters, context, feedback)

        # Adapt QGIS project to Geopoppy
        feedback.pushInfo(self.tr('ADAPT QGIS PROJECTS FOR OFFLINE USE'))
        self.setQgisProjectOffline(localdir, parameters, context, feedback)

        status = 1
        msg = self.tr("Synchronization successfull")
        out = {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }
        return out

