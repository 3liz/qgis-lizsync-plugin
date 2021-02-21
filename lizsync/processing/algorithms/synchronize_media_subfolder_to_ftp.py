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

import os

from qgis.core import (
    QgsProcessingException,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFile,
    QgsProcessingOutputString,
    QgsProcessingOutputNumber
)

from ftplib import FTP
from .tools import (
    checkFtpBinary,
    check_ftp_connection,
    ftp_sync,
    get_ftp_password,
    lizsyncConfig,
)
from ...qgis_plugin_tools.tools.i18n import tr
from ...qgis_plugin_tools.tools.algorithm_processing import BaseProcessingAlgorithm


class SynchronizeMediaSubfolderToFtp(BaseProcessingAlgorithm):
    """
    Synchronize clone media/upload data to remote FTP
    via LFTP
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.
    LOCAL_QGIS_PROJECT_FOLDER = 'LOCAL_QGIS_PROJECT_FOLDER'
    CENTRAL_FTP_HOST = 'CENTRAL_FTP_HOST'
    CENTRAL_FTP_PORT = 'CENTRAL_FTP_PORT'
    CENTRAL_FTP_LOGIN = 'CENTRAL_FTP_LOGIN'
    CENTRAL_FTP_PASSWORD = 'CENTRAL_FTP_PASSWORD'
    CENTRAL_FTP_REMOTE_DIR = 'CENTRAL_FTP_REMOTE_DIR'

    OUTPUT_STATUS = 'OUTPUT_STATUS'
    OUTPUT_STRING = 'OUTPUT_STRING'

    ftphost = 'ftp-valabre.lizmap.com'

    def name(self):
        return 'synchronize_media_subfolder_to_ftp'

    def displayName(self):
        return tr('Synchronize the clone media subfolder to the central FTP server')

    def group(self):
        return tr('03 File synchronization')

    def groupId(self):
        return 'lizsync_file_sync'

    def shortHelpString(self):
        short_help = tr(
            ' Send media files, such as new images, stored in the clone QGIS "media/upload/" folder,'
            ' TO the central FTP server remote directory "media/upload/"'
            '\n'
            '\n'
            ' These media files can for example have been added by using Lizmap editing form.'
            '\n'
            '\n'
            ' Every file existing in the clone "media/upload/" folder but not in the central server "media/upload/" folder will be sent.'
        )
        return short_help

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # LizSync config file from ini
        ls = lizsyncConfig()

        # INPUTS

        # Local QGIS folder
        local_qgis_project_folder = ls.variable('local/qgis_project_folder')
        self.addParameter(
            QgsProcessingParameterFile(
                self.LOCAL_QGIS_PROJECT_FOLDER,
                tr('Local QGIS project folder'),
                defaultValue=local_qgis_project_folder,
                behavior=QgsProcessingParameterFile.Folder,
                optional=False
            )
        )

        # Central FTP connection parameters
        # host
        central_ftp_host = ls.variable('ftp:central/host')
        self.addParameter(
            QgsProcessingParameterString(
                self.CENTRAL_FTP_HOST,
                tr('Central FTP Server host'),
                defaultValue=central_ftp_host,
                optional=False
            )
        )
        # port
        central_ftp_port = ls.variable('ftp:central/port')
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CENTRAL_FTP_PORT,
                tr('Central FTP Server port'),
                defaultValue=central_ftp_port,
                optional=False
            )
        )
        # login
        central_ftp_login = ls.variable('ftp:central/user')
        self.addParameter(
            QgsProcessingParameterString(
                self.CENTRAL_FTP_LOGIN,
                tr('Central FTP Server login'),
                defaultValue=central_ftp_login,
                optional=False
            )
        )
        # password
        self.addParameter(
            QgsProcessingParameterString(
                self.CENTRAL_FTP_PASSWORD,
                tr('Central FTP Server password'),
                optional=True
            )
        )
        # remote directory
        central_ftp_remote_dir = ls.variable('ftp:central/remote_directory')
        self.addParameter(
            QgsProcessingParameterString(
                self.CENTRAL_FTP_REMOTE_DIR,
                tr('Central FTP Server remote directory'),
                defaultValue=central_ftp_remote_dir,
                optional=False
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

        # Check FTP binary
        status, msg = checkFtpBinary()
        if not status:
            return status, msg

        return super(SynchronizeMediaSubfolderToFtp, self).checkParameterValues(parameters, context)

    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """
        status = 0
        msg = ''
        output = {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }

        # Parameters
        ftphost = parameters[self.CENTRAL_FTP_HOST]
        ftpport = parameters[self.CENTRAL_FTP_PORT]
        ftplogin = parameters[self.CENTRAL_FTP_LOGIN]
        ftppassword = parameters[self.CENTRAL_FTP_PASSWORD].strip()
        ftpdir = parameters[self.CENTRAL_FTP_REMOTE_DIR]
        localdir = parameters[self.LOCAL_QGIS_PROJECT_FOLDER]

        # store parameters
        ls = lizsyncConfig()
        ls.setVariable('ftp:central/host', ftphost)
        ls.setVariable('ftp:central/port', ftpport)
        ls.setVariable('ftp:central/user', ftplogin)
        ls.setVariable('ftp:central/password', ftppassword)
        ls.setVariable('ftp:central/remote_directory', ftpdir)
        ls.setVariable('local/qgis_project_folder', localdir)
        ls.save()

        # Check localdir
        feedback.pushInfo(tr('CHECK LOCAL PROJECT DIRECTORY'))
        if not localdir or not os.path.isdir(localdir):
            m = tr('QGIS project local directory not found')
            raise QgsProcessingException(m)

        # Check ftp
        if not ftppassword:
            ok, password, msg = get_ftp_password(ftphost, ftpport, ftplogin)
            if not ok:
                raise QgsProcessingException(msg)
        else:
            password = ftppassword
        ok, msg = check_ftp_connection(ftphost, ftpport, ftplogin, password)
        if not ok:
            raise QgsProcessingException(msg)

        # Check if ftpdir exists
        ok = True
        feedback.pushInfo(tr('CHECK REMOTE DIRECTORY') + ' %s' % ftpdir)
        ftp = FTP()
        ftp.connect(ftphost, ftpport)
        ftp.login(ftplogin, password)
        try:
            ftp.cwd(ftpdir)
            # do the code for successfull cd
            m = tr('Remote directory exists in the central server')
        except Exception:
            ok = False
            m = tr('Remote directory does not exist')
        finally:
            ftp.close()
        if not ok:
            raise QgsProcessingException(m)

        # Check if media/upload exists locally
        feedback.pushInfo(tr('START FTP DIRECTORY SYNCHRONIZATION TO SERVER') + ' %s' % ftpdir)
        localdir = localdir + '/media/upload'
        ftpdir = ftpdir + '/media/upload'
        feedback.pushInfo(tr('Local directory') + ' %s' % localdir)
        feedback.pushInfo(tr('FTP remote directory') + ' %s' % ftpdir)
        if os.path.isdir(localdir):
            # Run FTP sync
            direction = 'to'
            ok, msg = ftp_sync(ftphost, ftpport, ftplogin, password, localdir, ftpdir, direction, '', feedback)
            if not ok:
                raise QgsProcessingException(m)
        else:
            m = tr('Local directory does not exists. No synchronization needed.')
            feedback.pushInfo(m)

        status = 1
        msg = tr('Media upload subfolder sucessfully synchronized to the central server')
        output = {
            self.OUTPUT_STATUS: status,
            self.OUTPUT_STRING: msg
        }
        return output
