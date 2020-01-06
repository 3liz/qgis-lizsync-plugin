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
)

import os, subprocess
from pathlib import Path
import processing
from datetime import date, datetime
from ftplib import FTP
from .tools import *

class SendMediaToFtp(QgsProcessingAlgorithm):
    """
    Synchronize local media/upload data to remote FTP
    via LFTP
    """

    # Constants used to refer to parameters and outputs. They will be
    # used when calling the algorithm from another algorithm, or when
    # calling from the QGIS console.
    INPUT_SYNC_DATE = 'INPUT_SYNC_DAT'
    OUTPUT_STRING = 'OUTPUT_STRING'

    servers = {
        'ftp': {
            'host': 'ftp-valabre.lizmap.com', 'port': 21,
            'user': 'geopoppy@valabre.geopoppy', 'password':'gfrkGd5UvrJbCxE'
        },
        'central': {
            'host': 'qgisdb-valabre.lizmap.com', 'port': 5432, 'dbname': 'lizmap_valabre_geopoppy',
            'user': 'geopoppy@valabre', 'password':'gfrkGd5UvrJbCxE'
        },
        'geopoppy': {
            'host': '172.24.1.1', 'port': 5432, 'dbname': 'geopoppy',
            'user': 'docker', 'password':'docker'
        }
    }


    def name(self):
        return 'send_media_to_ftp'

    def displayName(self):
        return self.tr('Send new media to central FTP server')

    def group(self):
        return self.tr('Synchronization')

    def groupId(self):
        return 'lizsync_sync'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return SendMediaToFtp()

    def initAlgorithm(self, config):
        """
        Here we define the inputs and output of the algorithm, along
        with some other properties.
        """
        # INPUTS
        self.addParameter(
            QgsProcessingParameterString(
                self.INPUT_SYNC_DATE, 'Synchronization time',
                defaultValue=datetime.now().isoformat(),
                optional=False
            )
        )

        # OUTPUTS
        # Add output for message
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_STRING, self.tr('Output message')
            )
        )


    def check_internet(self):
        # return True
        import requests
        url='https://www.google.com/'
        timeout=5
        try:
            _ = requests.get(url, timeout=timeout)
            return True
        except requests.ConnectionError:
            return False

    def ftp_sync(self, ftphost, ftpport, ftpuser, ftppass, sourcedir, targetdir, excludedirs, parameters, context, feedback):

        try:

            cmd = []
            cmd.append('lftp')
            cmd.append('ftp://{0}:{1}@{2}'.format(ftpuser, ftppass, ftphost))
            cmd.append('-e')
            cmd.append('"')
            cmd.append('set ftp:ssl-allow no; set ssl:verify-certificate no; ')
            cmd.append('mirror')
            cmd.append('--verbose')
            cmd.append('--use-cache')
            # cmd.append('-e') # pour supprimer tout ce qui n'est pas sur le serveur
            for d in excludedirs.split(','):
                ed = d.strip().strip('/') + '/'
                if ed != '/':
                    cmd.append('-x %s' % ed)
            cmd.append('--ignore-time')
            cmd.append('{0}'.format(sourcedir))
            cmd.append('{0}'.format(targetdir))
            cmd.append('; quit"')
            feedback.pushInfo('LFTP = %s' % ' '.join(cmd) )

            # myenv = {**{'MYVAR': myvar}, **os.environ }
            run_command(cmd, feedback)

        except:
            feedback.pushInfo('Error during FTP sync')
            raise Exception(self.tr('Error during FTP sync'))
        finally:
            feedback.pushInfo('* FTP sync done')

        return True


    def processAlgorithm(self, parameters, context, feedback):
        """
        Here is where the processing itself takes place.
        """

        # Check internet
        feedback.pushInfo('Check internet connection' )
        if not self.check_internet():
            feedback.pushInfo('No internet connection')
            raise Exception(self.tr('No internet connection'))

        # Get connexion info
        profil = self.servers['ftp']
        ftphost = profil['host']
        ftpport = profil['port']
        ftpuser = profil['user']
        ftppass = profil['password']

        msg = ''

        # Get project
        p = context.project()
        pname = p.baseName()

        # Check localdir
        feedback.pushInfo('Check geopoppy project directory' )
        localdir = p.absolutePath()
        if not localdir:
            feedback.pushInfo(self.tr('QGIS project localdir not found'))
            raise Exception(self.tr('QGIS project localdir not found'))

        # Guess remote dir
        remotedir = None
        pv = p.customVariables()
        ## 1/ use the project variable @ftp_remote_dir
        if pv and 'ftp_remote_dir' in pv:
            remotedir = pv['ftp_remote_dir']
        # try with QGIS project name
        if remotedir and not remotedir.startswith('/qgis/dfci_'):
            remotedir = '/qgis/' + pname
        if not remotedir:
            remotedir = '/qgis/' + pname

        # Check if remotedir exists and contains project name
        feedback.pushInfo('Check remote dir %s' % remotedir )
        ftp = FTP()
        ftp.connect(ftphost, 21)
        ftp.login(ftpuser, ftppass)
        try:
            ftp.cwd(remotedir)
            #do the code for successfull cd
        except Exception:
            ftp.close()
            feedback.pushInfo(self.tr('Remote directory does not exist.'))
            raise Exception(self.tr('Remote directory does not exist.'))

        # Check if the project exists in the server
        pfile = pname + '.qgs'
        feedback.pushInfo('Check remote project %s exists' % pfile )
        try:
            flist = ftp.nlst(remotedir)
            if not pfile in flist:
                feedback.pushInfo(self.tr('The same project does not exists in the remote directory.'))
                raise Exception(self.tr('The same project does not exists in the remote directory.'))
        except Exception:
            ftp.close()
            feedback.pushInfo(self.tr('Error while listing directory'))
            raise Exception(self.tr('Error while listing directory'))

        # check if media/upload exists locally

        localdir = localdir + '/media/upload'
        if os.path.isdir(localdir):
            remotedir = remotedir + '/media/upload'
            feedback.pushInfo(remotedir)
            # Run FTP sync
            feedback.pushInfo('localdir = %s' % localdir )
            feedback.pushInfo('remotedir = %s' % remotedir )
            msg+= " localdir = {0}".format(localdir)
            msg+= " remotedir = {0}".format(remotedir)

            # synchronize
            self.ftp_sync(ftphost, ftpport, ftpuser, ftppass, localdir, remotedir, '', parameters, context, feedback)

        out = {
            self.OUTPUT_STRING: msg
        }
        return out