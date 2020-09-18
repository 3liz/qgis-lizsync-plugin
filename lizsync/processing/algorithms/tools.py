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

import ftplib
import os
import netrc
import psycopg2
import re
import subprocess
import fileinput
from platform import system as psys
from db_manager.db_plugins.plugin import BaseError
from db_manager.db_plugins.postgis.connector import PostGisDBConnector
from qgis.core import (
    QgsApplication,
    QgsDataSourceUri
)
from processing.tools.postgis import uri_from_name

from ...qgis_plugin_tools.tools.i18n import tr
from ...qgis_plugin_tools.tools.resources import plugin_path


def get_ftp_password(host, port, login):
    # Check FTP password
    # Get FTP password
    # First check if it is given in ini file
    ls = lizsyncConfig()
    password = ls.variable('ftp:central/password')
    # If not given, search for it in ~/.netrc
    if not password:
        try:
            auth = netrc.netrc().authenticators(host)
            if auth is not None:
                ftpuser, _, password = auth
        except (netrc.NetrcParseError, IOError):
            m = tr('Could not retrieve password from ~/.netrc file')
            return False, None, m
        if not password:
            m = tr('Could not retrieve password from ~/.netrc file or is empty')
            return False, None, m
        else:
            # Use None to force to use netrc file
            # only for linux (lftp). we need to use password for winscp
            if psys().lower().startswith('linux'):
                password = None

    return True, password, ''


def check_ftp_connection(host, port, login, password=None, timeout=5):
    """
    Check FTP connection with timeout
    """
    if not password:
        ok, password, msg = get_ftp_password(host, port, login)
        if not ok:
            return False, msg

    try:
        ftp = ftplib.FTP()
        ftp.connect(host, port, timeout)
        try:
            ftp.login(login, password)
        except ftplib.all_errors as error:
            msg = tr('Error while connecting to FTP server')
            msg += ' ' + str(error)
            return False, msg
    except ftplib.all_errors as error:
        msg = tr('Error while connecting to FTP server')
        msg += ' ' + str(error)
        return False, msg
    finally:
        ftp.close()

    return True, ''


def get_connection_password_from_ini(uri):
    """
    Get password from lizsync.ini
    And set uri password with it
    """
    password = ''
    ls = lizsyncConfig()
    c_list = ('central', 'clone')
    for c in c_list:
        if uri.host() == ls.variable('postgresql:%s/host' % c) \
        and uri.port() == ls.variable('postgresql:%s/port' % c) \
        and uri.database() == ls.variable('postgresql:%s/dbname' % c) \
        and uri.username() == ls.variable('postgresql:%s/user' % c) \
        and ls.variable('postgresql:%s/password' % c):
            password = ls.variable('postgresql:%s/password' % c)
            break
    return password


def check_postgresql_connection(uri, timeout=5):
    """
    Check connection to PostgreSQL database with timeout
    """
    # Check if password is given. If not, try to read it from lizsync.ini
    if not uri.service():
        password = uri.password()
        if not password:
            password = get_connection_password_from_ini(uri)
        if not password:
            password = os.environ.get('PGPASSWORD')
        if not password:
            pgpassfile = os.path.expanduser('~/.pgpass')
            if not os.path.exists(pgpassfile):
                pgpassfile = os.path.join(os.getenv('APPDATA'), 'postgresql/pgpass.conf')
            if os.path.exists(pgpassfile):
                search_a = '{}:{}:{}:{}:'.format(
                    uri.host(), uri.port(), uri.database(), uri.username()
                )
                search_b = '{}:{}:*:{}:'.format(
                    uri.host(), uri.port(), uri.username()
                )
                dbline = None
                with open(pgpassfile, 'r') as pg:
                    for line in pg:
                        if line.strip().startswith(search_a) or line.startswith(search_b):
                            dbline = line.strip()
                            break
                if dbline:
                    password = dbline.split(':')[-1]
        if password:
            uri.setPassword(password)
        else:
            msg = tr('No password found for the database connection !')
            return False, msg

    # Try to connect with psycopg2
    conn = None
    try:
        if uri.service():
            conn = psycopg2.connect(
                service=uri.service(),
                connect_timeout=timeout
            )
        else:
            conn = psycopg2.connect(
                host=uri.host(), database=uri.database(),
                user=uri.username(), password=uri.password(),
                connect_timeout=timeout
            )
        status = True
        msg = tr('Database connection OK')
    except (Exception, psycopg2.DatabaseError) as error:
        status = False
        msg = str(error)
    finally:
        if conn:
            conn.close()

    return status, msg


def getUriFromConnectionName(connection_name, must_connect=True):
    # In UserLand context, use directly information
    # given in LizSync.ini file
    if os.path.isdir('/storage/internal/geopoppy') and psys().lower().startswith('linux'):
        return getUriFromConnectionNameUserland(connection_name, must_connect)

    # Otherwise check QGIS QGIS3.ini settings for connection name
    status = True
    uri = uri_from_name(connection_name)

    # Try to connect if asked
    if must_connect:
        ok, msg = check_postgresql_connection(uri)
        return ok, uri, msg
    else:
        return status, uri, ''


def getUriFromConnectionNameUserland(connection_name, must_connect=True):
    # Use LizSync.ini content to find all connection parameters
    ls = lizsyncConfig()
    status = True
    uri = None
    c_list = ('central', 'clone')
    for c in c_list:
        c_name = ls.variable('postgresql:%s/name' % c)
        if c_name == connection_name:
            uri = QgsDataSourceUri()
            if ls.variable('postgresql:%s/service' % c):
                uri.setConnection(
                    ls.variable('postgresql:%s/service' % c),
                    '', '', ''
                )
            else:
                if ls.variable('postgresql:%s/host' % c) \
                        and ls.variable('postgresql:%s/port' % c) \
                        and ls.variable('postgresql:%s/dbname' % c) \
                        and ls.variable('postgresql:%s/user' % c) \
                        and ls.variable('postgresql:%s/password' % c):
                    uri.setConnection(
                        ls.variable('postgresql:%s/host' % c),
                        ls.variable('postgresql:%s/port' % c),
                        ls.variable('postgresql:%s/dbname' % c),
                        ls.variable('postgresql:%s/user' % c),
                        ls.variable('postgresql:%s/password' % c)
                    )
                else:
                    continue
            if must_connect:
                ok, msg = check_postgresql_connection(uri)
                return ok, uri, msg
            else:
                return True, uri, ''
            break

    return status, uri, ''


def fetchDataFromSqlQuery(connection_name, sql):
    data = []
    header = []
    rowCount = 0

    # Get URI
    status, uri, error_message = getUriFromConnectionName(connection_name, True)
    if not uri or not status:
        ok = False
        return header, data, rowCount, ok, error_message
    try:
        connector = PostGisDBConnector(uri)
    except Exception:
        error_message = tr('Cannot connect to database')
        ok = False
        return header, data, rowCount, ok, error_message

    c = None
    ok = True
    # print "run query"
    try:
        c = connector._execute(None, str(sql))
        data = []
        header = connector._get_cursor_columns(c)
        if header is None:
            header = []
        if len(header) > 0:
            data = connector._fetchall(c)
        rowCount = c.rowcount
        if rowCount == -1:
            rowCount = len(data)

    except BaseError as e:
        ok = False
        error_message = e.msg
        return header, data, rowCount, ok, error_message
    finally:
        if c:
            c.close()
            del c

    # Log errors
    if not ok:
        error_message = tr('Unknown error occurred while fetching data')
        return header, data, rowCount, ok, error_message

    return header, data, rowCount, ok, error_message


def run_command(cmd, myenv, feedback):
    """
    Run any command using subprocess
    """
    feedback.pushInfo(" ".join(cmd))
    stop_words = ['warning']
    pattern = re.compile('|'.join(r'\b{}\b'.format(word) for word in stop_words), re.IGNORECASE)
    error_pattern = re.compile('error:')
    rc = None
    status = True
    with subprocess.Popen(
            " ".join(cmd),
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=myenv
    ) as process:
        for line in process.stdout:
            try:
                output = "{}".format(line.rstrip().decode("utf-8"))
            except Exception:
                output = "{}".format(line.rstrip())
            if not pattern.search(output):
                feedback.pushInfo(output)
            if output == '' and process.poll() is not None:
                break
            if output:
                feedback.pushInfo(output)
            if output and error_pattern.search(output):
                status = False
        rc = process.poll()

    return rc, status


def check_database_structure(connection_name):
    """
    Check if database structure contains lizsync tables
    """
    sql = ''
    sql += " SELECT t.table_schema, t.table_name"
    sql += " FROM information_schema.tables AS t"
    sql += " WHERE t.table_schema = 'lizsync'"
    sql += " AND t.table_name = 'server_metadata'"
    header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(connection_name, sql)

    # Default output
    status = True
    message = tr('Lizsync structure has been installed')

    # Tests
    if ok:
        if rowCount != 1:
            status = False
            message = tr(
                'Lizsync has not been installed in the central database.'
                ' Run the script "Create database structure"'
            )
    else:
        status = False
        message = error_message

    return status, message


def check_database_server_metadata_content(connection_name):
    """
    Check if database contains data in server_metadata
    """
    sql = ''
    sql += " SELECT server_id "
    sql += " FROM lizsync.server_metadata"
    sql += " LIMIT 1"
    header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(connection_name, sql)

    # Default output
    status = True
    message = tr('Server id is correctly set')

    # Tests
    if ok:
        if rowCount != 1:
            status = False
            message = tr('The server id in the table lizsync.server_metadata is not set')
    else:
        status = False
        message = error_message

    return status, message


def convert_textual_schema_list_to_sql(schemas):
    """
    Parse textual schema list and return SQL compatible list
    for use in WHERE clause
    """
    schemas = [
        "'{0}'".format(a.strip())
        for a in schemas.split(',')
        if a.strip() not in ('public', 'lizsync', 'audit')
    ]
    schemas_sql = ', '.join(schemas)

    return schemas_sql


def check_database_uid_columns(connection_name, schemas='test'):
    """
    Check if tables contains uid columns
    """
    schemas_sql = convert_textual_schema_list_to_sql(schemas)

    status = True
    message = tr('No missing uid columns')

    sql = ''
    sql += " SELECT t.table_schema, t.table_name, (c.column_name IS NOT NULL) AS ok"
    sql += " FROM information_schema.tables AS t"
    sql += " LEFT JOIN information_schema.columns c"
    sql += "     ON True"
    sql += "     AND c.table_schema = t.table_schema"
    sql += "     AND c.table_name = t.table_name"
    sql += "     AND c.column_name = 'uid'"
    sql += " WHERE TRUE"
    sql += " AND t.table_schema IN ( {0} )"
    sql += " AND t.table_type = 'BASE TABLE'"
    sql += " AND c.column_name IS NULL"
    sql += " ORDER BY t.table_schema, t.table_name"
    sqlc = sql.format(
        schemas_sql
    )
    header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(connection_name, sqlc)
    missing = []
    if ok:
        for a in data:
            missing.append('* "{0}"."{1}"'.format(a[0], a[1]))
    if missing:
        message = tr('Some tables do not have the required uid column')
        message += '\n{0}'.format(',\n '.join(missing))
        status = False

    return status, message


def check_database_audit_triggers(connection_name, schemas='test'):
    """
    Checks if tables are audited with triggers
    """
    schemas_sql = convert_textual_schema_list_to_sql(schemas)

    status = True
    message = tr('No missing audit triggers')

    sql = ''
    sql += " SELECT table_schema, table_name"
    sql += " FROM information_schema.tables"
    sql += " WHERE True"
    sql += " AND table_schema IN ( {0} )"
    sql += " AND table_type = 'BASE TABLE'"
    sql += " AND (quote_ident(table_schema) || '.' || quote_ident(table_name))::text NOT IN ("
    sql += "     SELECT (tgrelid::regclass)::text"
    sql += "     FROM pg_trigger"
    sql += "     WHERE TRUE"
    sql += "     AND tgname LIKE 'audit_trigger_%'"
    sql += " )"
    sqlc = sql.format(
        schemas_sql
    )
    header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(connection_name, sqlc)
    missing = []
    if ok:
        if rowCount > 0:
            for a in data:
                missing.append('* "{0}"."{1}"'.format(a[0], a[1]))
            message = tr('Some tables are not monitored by the audit trigger tool')
            message += ':\n{0}'.format(',\n '.join(missing))
            message += '\n' + tr('They will not be synchronized !')
            status = False
    else:
        status = False
        message = error_message

    return status, message


def get_database_audit_triggers(connection_name, schemas='test'):
    """
    Get all the tables audited in synchronized schemas
    """
    schemas_sql = convert_textual_schema_list_to_sql(schemas)

    sql = ''
    sql += " SELECT table_schema, table_name"
    sql += " FROM information_schema.tables"
    sql += " WHERE True"
    sql += " AND table_schema IN ( {0} )"
    sql += " AND table_type = 'BASE TABLE'"
    sql += " AND (quote_ident(table_schema) || '.' || quote_ident(table_name))::text IN ("
    sql += "     SELECT (tgrelid::regclass)::text"
    sql += "     FROM pg_trigger"
    sql += "     WHERE TRUE"
    sql += "     AND tgname LIKE 'audit_trigger_%'"
    sql += " )"
    sqlc = sql.format(
        schemas_sql
    )
    header, data, rowCount, ok, error_message = fetchDataFromSqlQuery(connection_name, sqlc)
    tables = []
    message = ''
    if ok:
        if rowCount > 0:
            message = tr('Following tables are monitored by the audit trigger tool')
            for a in data:
                tables.append((a[0], a[1]))
                message += '* "{0}"."{1}"'.format(a[0], a[1])
        else:
            message = tr(
                'No tables are audited in central database for the specified schemas.'
                ' Data synchronization WILL NOT WORK when deploying this generated package'
            )
    else:
        message = error_message

    return ok, message, tables


def checkFtpBinary():
    # Check WinSCP path contains binary
    test = False

    # LizSync config file from ini
    ls = lizsyncConfig()

    # Windows : search for WinSCP
    if psys().lower().startswith('win'):
        test_path = ls.variable('binaries/winscp')
        test_bin = 'WinSCP.com'
        error_message = 'WinSCP binary has not been found in specified path'
        test = True

    # Linux : search for lftp
    if psys().lower().startswith('linux'):
        test_path = '/usr/bin/'
        test_bin = 'lftp'
        error_message = 'LFTP binary has not been found in your system'
        test = True

    # Compute full path to test
    ftp_bin = os.path.join(
        test_path,
        test_bin
    )

    # Run test
    if test and not os.path.isfile(ftp_bin):
        return False, tr(error_message)
    if not test:
        return False, tr('No FTP binary has been found in your system')
    return True, tr('FTP Binary has been found in your system')


def ftp_sync(ftphost, ftpport, ftpuser, ftppass, localdir, ftpdir, direction, excludedirs, feedback):
    # LizSync config file from ini
    ls = lizsyncConfig()

    # LINUX : USE lftp command line
    if psys().lower().startswith('linux'):
        try:
            cmd = []
            cmd.append('lftp')
            pass_str = ''
            if ftppass:
                pass_str = ':{}'.format(ftppass)
            cmd.append('ftp://{ftpuser}{pass_str}@{ftphost}:{ftpport}'.format(
                ftpuser=ftpuser,
                pass_str=pass_str,
                ftphost=ftphost,
                ftpport=ftpport
            )
            )
            cmd.append('-e')
            cmd.append('"')
            cmd.append('set ftp:ssl-allow no; set ssl:verify-certificate no; ')
            cmd.append('mirror')
            if direction == 'to':
                cmd.append('-R')
            cmd.append('--verbose')
            cmd.append('--continue')
            cmd.append('--use-cache')
            # cmd.append('-e') # pour supprimer tout ce qui n'est pas sur le serveur
            for d in excludedirs.split(','):
                ed = d.strip().strip('/') + '/'
                if ed != '/':
                    cmd.append('-x %s' % ed)
            cmd.append('--ignore-time')
            # LFTP NEEDS TO PUT
            # * from -> ftpdir (remote FTP server) BEFORE
            # * to (-R) -> localdir (computer) BEFORE ftpdir (remote FTP server)
            if direction == 'to':
                cmd.append('{} {}'.format(localdir, ftpdir))
            else:
                cmd.append('{} {}'.format(ftpdir, localdir))

            cmd.append('; quit"')
            feedback.pushInfo('LFTP = %s' % ' '.join(cmd))

            myenv = {**os.environ}
            run_command(cmd, myenv, feedback)

        except Exception:
            m = tr('Error during FTP sync')
            return False, m
        finally:
            feedback.pushInfo(tr('FTP sync done'))

    # WINDOWS : USE WinSCP.com tool
    elif psys().lower().startswith('win'):
        try:
            cmd = []
            winscp_bin = os.path.join(
                ls.variable('binaries/winscp'),
                'WinSCP.com'
            ).replace('\\', '/')
            cmd.append('"' + winscp_bin + '"')
            cmd.append('/ini=nul')
            cmd.append('/console')
            cmd.append('/command')
            cmd.append('"option batch off"')
            cmd.append('"option transfer binary"')
            cmd.append('"option confirm off"')
            pass_str = ''
            if ftppass:
                pass_str = ':{}'.format(ftppass)
            cmd.append('"open ftp://{ftpuser}{pass_str}@{ftphost}:{ftpport}"'.format(
                ftpuser=ftpuser,
                pass_str=pass_str,
                ftphost=ftphost,
                ftpport=ftpport
            )
            )
            cmd.append('"')
            cmd.append('synchronize')
            way = 'local'
            if direction == 'to':
                way = 'remote'
            cmd.append(way)
            # WINSCP NEED TO ALWAYS HAVE local directory (computer) BEFORE FTP server remote directory
            cmd.append(
                '{} {}'.format(
                    localdir,
                    ftpdir
                )
            )
            cmd.append('-mirror')
            # cmd.append('-delete') # to delete "to" side files not present in the "from" side
            cmd.append('-criteria=time')
            cmd.append('-resumesupport=on')
            ex = []
            for d in excludedirs.split(','):
                ed = d.strip().strip('/') + '/'
                if ed != '/':
                    # For directory, no need to put * after.
                    # Just use the / at the end, for example: data/
                    ex.append('%s' % ed)
            if ex:
                # | 2010*; 2011*
                # double '""' needed because it's inside already quoted synchronize subcommand
                cmd.append('-filemask=""|' + ';'.join(ex) + '""')
            cmd.append('"')

            cmd.append('"close"')
            cmd.append('"exit"')

            infomsg = 'WinSCP = %s' % ' '.join(cmd)
            feedback.pushInfo(
                infomsg.replace(
                    ':{}@'.format(ftppass),
                    ':********@'
                )
            )

            myenv = {**os.environ}
            run_command(cmd, myenv, feedback)

        except Exception:
            m = tr('Error during FTP sync')
            return False, m
        finally:
            feedback.pushInfo(tr('FTP sync done'))

    return True, 'Success'


def pg_dump(feedback, postgresql_binary_path, connection_name, output_file_name, schemas, additional_parameters=[]):
    messages = []
    status = False

    # Check binary
    pgbin = 'pg_dump'
    if psys().lower().startswith('win'):
        pgbin += '.exe'
    pgbin = os.path.join(
        postgresql_binary_path,
        pgbin
    )
    if not os.path.isfile(pgbin):
        messages.append(tr('PostgreSQL pg_dump tool cannot be found in specified path'))
        return False, messages

    # Get connection parameters
    # And check we can connect
    status, uri, error_message = getUriFromConnectionName(connection_name, True)
    if not uri or not status:
        messages.append(tr('Error getting database connection information'))
        messages.append(error_message)
        return status, messages

    # Create pg_dump command
    if uri.service():
        cmdo = [
            'service={0}'.format(uri.service())
        ]
    else:
        cmdo = [
            '-h {0}'.format(uri.host()),
            '-p {0}'.format(uri.port()),
            '-d {0}'.format(uri.database()),
            '-U {0}'.format(uri.username()),
        ]
    # Escape pgbin for Windows
    if psys().lower().startswith('win'):
        pgbin = '"' + pgbin + '"'
    cmd = [
              pgbin
          ] + cmdo + [
              '--no-acl',
              '--no-owner',
              '-Fp',
              '-f "{0}"'.format(output_file_name)
          ]

    # Add given schemas
    for s in schemas:
        cmd.append('-n {0}'.format(s))

    # Add additional parameters
    if additional_parameters:
        cmd = cmd + additional_parameters

    # Run command
    # print(" ".join(cmd))
    try:
        # messages.append('PG_DUMP = %s' % ' '.join(cmd) )
        # Add password if needed
        myenv = {**os.environ}
        if not uri.service():
            myenv = {**{'PGPASSWORD': uri.password()}, **os.environ}
        rc, status = run_command(cmd, myenv, feedback)

        # subprocess.run(
        # " ".join(cmd),
        # shell=True,
        # env=myenv
        # )
        if status:
            messages.append(tr('Database has been successfull dumped') + ' into {0}'.format(output_file_name))
        else:
            messages.append(tr('Error dumping database') + ' into {0}'.format(output_file_name))
    except Exception:
        status = False
        messages.append(tr('Error dumping database') + ' into {0}'.format(output_file_name))

    return status, messages


def setQgisProjectOffline(qgis_directory, connection_name_central, feedback):
    # Get uri from connection names
    status_central, uri_central, error_message_central = getUriFromConnectionName(connection_name_central, False)

    if not status_central or not uri_central:
        m = error_message_central
        return False, m

    uris = {'central': {}, 'clone': {}}
    if uri_central.service():
        uris['central'] = {
            'service': uri_central.service(),
            'string': "service='%s'" % uri_central.service()
        }
        uris['clone'] = {
            'service': 'geopoppy',
            'string': "service='geopoppy'",
        }
    else:
        uris['central'] = {
            'string': "dbname='{}' host={} port={} user='[A_Za-z_@]+'( password='[^ ]+')?".format(
                uri_central.database(),
                uri_central.host(),
                uri_central.port()
            )
        }
        uris['clone'] = {
            'string': "dbname='geopoppy' host=localhost port=5432 user='geopoppy' password='geopoppy'"
        }

    # Loop through QGIS project files
    files = []
    for filename in os.listdir(qgis_directory):
        if not os.path.isfile(os.path.join(qgis_directory, filename)):
            continue
        if filename.endswith(".qgs") and not filename.endswith("_.qgs"):
            files.append(filename)

    for filename in files:
        qf = os.path.join(qgis_directory, filename)
        feedback.pushInfo(tr('Process QGIS project file') + ' %s' % qf)

        # Replace all datasource with geopoppy datasources
        regex = re.compile(uris['central']['string'], re.IGNORECASE)

        # Replace content in file with fileinput
        feedback.pushInfo(tr('Overwrite QGIS project file with new data') + ' %s' % filename)
        with fileinput.FileInput(qf, inplace=True, backup='.liz') as f:
            for line in f:
                # Check if line contains connection parameters
                if "dbname=" in line or "service=" in line:
                    # Replace content in line
                    line = regex.sub(
                        uris['clone']['string'],
                        line
                    )
                    # fileinput needs to print only line content
                print(line, end='')

    return True, 'Success'


from configparser import ConfigParser
from shutil import copyfile


class lizsyncConfig:

    def __init__(self):
        # Get default config file path
        config_file = os.path.abspath(
            os.path.join(
                QgsApplication.qgisSettingsDirPath(),
                'LizSync.ini'
            )
        )

        # Override config path from environment variable
        epath = os.environ.get('LIZSYNC_CONFIG_FILE')
        if epath:
            config_file = epath

        # Use template if no file found
        if not os.path.exists(config_file):
            # Get template ini file
            dir_path = plugin_path('install')
            template_config_file = os.path.join(dir_path, 'LizSync.ini')
            copyfile(template_config_file, config_file)

        # Read config
        config = ConfigParser()
        self.config_file = config_file
        config.read(self.config_file)
        self.config = config

        # White list of config sections
        self.sections = (
            'general', 'binaries',
            'postgresql:central', 'postgresql:clone',
            'ftp:central', 'ftp:clone',
            'local', 'clone'
        )

    def getAddressFromAlias(self, alias):
        """
        Parse addres like ftp:central/host into ['ftp:central', 'host']
        """
        variables = alias.split('/')
        if len(variables) != 2 or variables[0] not in self.sections:
            return None
        return variables

    def variable(self, alias):
        """
        Get configuration
        """
        address = self.getAddressFromAlias(alias)
        if not address:
            return None
        try:
            val = self.config.get(address[0], address[1])
        except Exception:
            val = None
        return val

    def setVariable(self, alias, value):
        """
        Set configuration
        """
        address = self.getAddressFromAlias(alias)
        if not address:
            return None
        # values must be passed as string
        if address[0] in self.sections and not self.config.has_section(address[0]):
            self.config.add_section(address[0])
        self.config.set(
            address[0],
            address[1],
            str(value)
        )

    def save(self):
        """
        Save config file
        """
        with open(self.config_file, 'w') as f:
            self.config.write(f)
