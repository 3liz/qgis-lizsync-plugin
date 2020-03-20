## CHANGELOG

### 20/03/2020 Version 0.3.1

* Tests - move and rename bash script to run_test.sh
* Config - Add list of schemas in saved configuration
* Package - Use parameterAsString for Additionnal SQL file input
* FTP & Database - Check connections before proceeding
* Synchronize db - remove unwanted parenthesis in simple SET clause
* Deploy package & tools - Quote zip archive file in psql/pg_dump command
* Upgrade - rename SQL file for upgrade to 0.3.0

### 03/03/2020 Version 0.3.0

* Package & restore - Add an optionnal SQL file to run in clone after deploy
* Synchronization - Add new option to exclude columns from bidirectionnal database sync
* Doc - update README for SQL generator
* Update french translation

### 28/02/2020 Version 0.2.3

* Send media to FTP server - Fix bug with missing variable
* Get projects from FTP - remove also lizmap config file before sync
* Userland context - Use String input parameter for ZIP archive
* Provider - Userland context, only load usefull algs
* FTP - Use LizSync.ini password if given instead of using ~/.netrc file
* Userland context - Adapt the method to connect to databases: read ini file
* Translation - update strings
* Deploy package - Check previous synchronizations before running this script
* Translation - Fix bug when loading provider and initializing locale
* Translation - Add French language
* Doc - Replace <br> with line endings
* Translation - Add qgis-plugin-tools & Use transifex
* Config - Add new option database_archive_file & improve config parser
* Fix some more bugs
* Add small doc about test data and scripts
* Fix small bug following last commit
* Config - Use ini configuration for all algorithm instead of QGIS global variables

### 21/02/2020 Version 0.2.2:

* Metadata - Change version to 0.2.2
* FTP & adapt QGIS projects - Workaround for Userland context
* Install - Add needed function current_setting for PostgreSQL 9.5
* Add default zip extension for package & deploy archive algs
* Improve tool function for replacing db data in QGIS projects
* Add missing help
* Use a tool method to return algorithm error
* Upgrade database structure - add help
* Synchronize media subfolder - add help
* Two-way database sync - Add help
* Send projects and files to clone FTP - Add help
* Package central db - add help
* Initialize central db - add help
* Tools - Add method to return error and terminate alg & use it in get_projects_and_files_from_central_ftp al
* Remove useless get_data_as_layer alg
* Remove useless execute_sql alg
* Deploy server package - Add help & remove duplicated parameter
