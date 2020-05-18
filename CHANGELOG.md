# CHANGELOG

### 0.3.6 - 18/05/2020

* Send project to clone - parameters: add password and remove clone connection
* Get projects from FTP - Hardcode geopoppy db params && use fileinput to get rid of bug
* Get projects from FTP - Add password and option to adapt project for geopoppy
* Test data - fix encoding for subdistricts layer
* Database sync - Move conflict storing into a function
* Update python version in github action
* Check flake 8 on github

### 0.3.5 - 01/05/2020

* Bidirectionnal synchronization - Make sure to truncate clone audit log, even for rejected actions
* Tools - Get password: if no service is given, try to get password also from PGPASSWORD environment variable
* Run migrations on CI since 0.2.2
* Disable pushing to transifex from PR
* Improve travis
* Switch to 3liz bot for CI

### 0.3.4 - 16/04/2020

* Database synchro - Correctly update central audit.logged_actions for discarded UPDATEs
* Add missing flag for processing provider in metadata.txt
* Minor code cleanup
* Fix travis path when pushing QM to github
* Update translations from Transifex          

### 0.3.3 - 09/04/2020

* Synchronize media subfolder - Fix bug with localdir variable not set
* PostgreSQL connection - Get password from ini file if not given
* Improve continuous integration: translations, tests
* Code cleaning and PEP8 fixing

### 0.3.2 - 31/03/2020

* Add qgis-plugin-ci configuration to the plugin
* Fix some scripts after moving lizsync directory
* Database Synchronization - Store automatic conflict resolution into table lizsync.conflicts
* Database synchronization - Resolve UPDATE conflicts by a given rule
* Synchronization - Some code refactoring
* Doc - Add docs folder for GitHub pages
* Remove UTF8 encoding in Python files
* Refactor code about loading Processing provider
* Move the plugin to its own folder
* Remove unused files

### 0.3.1 - 20/03/2020

* Tests - move and rename bash script to run_test.sh
* Config - Add list of schemas in saved configuration
* Package - Use parameterAsString for Additional SQL file input
* FTP & Database - Check connections before proceeding
* Synchronize db - remove unwanted parenthesis in simple SET clause
* Deploy package & tools - Quote zip archive file in psql/pg_dump command
* Upgrade - rename SQL file for upgrade to 0.3.0

### 0.3.0 - 03/03/2020

* Package & restore - Add an optional SQL file to run in clone after deploy
* Synchronization - Add new option to exclude columns from bidirectional database sync
* Doc - update README for SQL generator
* Update french translation

### 0.2.3 - 28/02/2020

* Send media to FTP server - Fix bug with missing variable
* Get projects from FTP - remove also Lizmap config file before sync
* Userland context - Use String input parameter for ZIP archive
* Provider - Userland context, only load useful algorithms
* FTP - Use LizSync.ini password if given instead of using ~/.netrc file
* Userland context - Adapt the method to connect to databases: read ini file
* Translation - update strings
* Deploy package - Check previous synchronizations before running this script
* Translation - Fix bug when loading provider and initializing locale
* Translation - Add French language
* Doc - Replace <br> with line endings
* Translation - Add qgis-plugin-tools & Use Transifex
* Config - Add new option database_archive_file & improve config parser
* Fix some more bugs
* Add small doc about test data and scripts
* Fix small bug following last commit
* Config - Use ini configuration for all algorithm instead of QGIS global variables

### 0.2.2 - 21/02/2020

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
