# CHANGELOG

## 0.6.1 - 2021-05-17

* Build mobile project algorithm - Fix the datasource checking between the project layers & the central connection configuration

## 0.6.0 - 2021-05-03

* QGIS - Add QGIS 3.16 compatibility: plugin is now only compatible for QGIS >= 3.10
* Synchronization - Manage conflicts for UPDATE at the same second
* Create & Upgrade database structure - use QGIS native db functions instead of DbManager functions
* Build mobile project - Fix datasource change for layers with a username containing integers
* Logs - Add the second bool parameter to the reportError method
* Install - Remove search_path from SQL files
* Tests - Add tests for UPDATE on the same object & the same column
* Docs - Update SchemaSpy database & processing doc

## 0.5.1 - 2021-03-15

* Deploy all - Use the current project instead of asking for the directory & zip paths
* Fix SFTP sync & PostgreSQL dump algorithms in Windows context
* Add the Synchronize database button in the main tab of the dock

## 0.5.0 - 2021-03-04

* Audit - All the auditing tables and functions have been move into the lizsync schema. This allows to use the original audit tool independently of lizsync.
* Package central database - the PostgreSQL data is now only exported for the chosen PostgreSQL layers of the opened QGIS project, not for the full schema(s)
* Let the user add UID columns and audit triggers only for the chosen PostgreSQL layers when creating a package from the central database
* New algorithm which helps to create a mobile version of a QGIS project, by exporting the other vector layers to a Geopackage file, and by modifying the QGIS project PostgreSQL layers to target the clone database
* Send files and project to the clone: add the possibility to use SFTP (file transfer over SSH)
* Remove useless algorithms (fetch from central FTP server, synchronise media subfolders)
* QGIS - Adapt some algorithm for QGIS >= 3.14
* Continuous integration - Move from Travis to Github Actions
* Documentation - Many improvements, such as a new documentation engine (Mkdoc) and style, and more information given in the user guide. See: https://docs.3liz.org/qgis-lizsync-plugin/
* Tested with a clone database installed inside Android tablet by using Termux: https://github.com/mdouchin/termux-postgis-script/
* Other minor improvements and code refactoring

## 0.4.5 - 2020-09-18

* Prepare the central database - Allow to not add automatically the audit triggers
* Create a package - Do not block the creation if some tables of the synchronized schemas are not audited.
* Deploy a package - Apply the audit triggers only on tables audited in the central database
* Deploy a package - Add a checkbox to force the re-creation of the clone server ID in the metadata table (useful to start fresh)
* Add unit tests for database synchronization with scenarios
* Autodocumentation of the algorithms https://docs.3liz.org/qgis-lizsync-plugin/processing/

## 0.4.4 - 2020-06-08

* Interface - Dock: simplify button labels & add tooltips
* Documentation - Publish database schema & user manual (in French): https://docs.3liz.org/qgis-lizsync-plugin
* Continuous integration - improve CI scripts

## 0.4.3 - 2020-05-31

* Tools - pg_dump: detect pg_dump error
* Synchronize database - Fix bug in SQL function

## 0.4.2 - 2020-05-29

* Add more translations into French

## 0.4.1 - 2020-05-08

* Database function - Improve speed of lizsync.synchronize() & add PostgreSQL notices
* Update translations

## 0.4.0 - 2020-05-27

* Synchronization - Move all logic from Python to PostgreSQL functions
* Remove configure plugin algorithm: last used values are now saved by each algorithm
* Create structure - Hide override parameters to avoid data loss
* PostgreSQL - Get password from pgpass file if not found elsewhere
* Install - Add missing upgrade script to 0.3.2 & fix test
* Tests - Update docker-compose project, add schemaspy, add test migration
* Improve script run_test.sh

## 0.3.6 - 2020-05-18

* Send project to clone - parameters: add password and remove clone connection
* Get projects from FTP - Hardcode geopoppy db params && use fileinput to get rid of bug
* Get projects from FTP - Add password and option to adapt project for geopoppy
* Test data - fix encoding for subdistricts layer
* Database sync - Move conflict storing into a function
* Update python version in github action
* Check flake 8 on github

## 0.3.5 - 2020-05-01

* Bidirectionnal synchronization - Make sure to truncate clone audit log, even for rejected actions
* Tools - Get password: if no service is given, try to get password also from PGPASSWORD environment variable
* Run migrations on CI since 0.2.2
* Disable pushing to transifex from PR
* Improve travis
* Switch to 3liz bot for CI

## 0.3.4 - 2020-04-16

* Database synchro - Correctly update central audit.logged_actions for discarded UPDATEs
* Add missing flag for processing provider in metadata.txt
* Minor code cleanup
* Fix travis path when pushing QM to github
* Update translations from Transifex

## 0.3.3 - 2020-04-09

* Synchronize media subfolder - Fix bug with localdir variable not set
* PostgreSQL connection - Get password from ini file if not given
* Improve continuous integration: translations, tests
* Code cleaning and PEP8 fixing

## 0.3.2 - 2020-03-31

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

## 0.3.1 - 2020-03-20

* Tests - move and rename bash script to run_test.sh
* Config - Add list of schemas in saved configuration
* Package - Use parameterAsString for Additional SQL file input
* FTP & Database - Check connections before proceeding
* Synchronize db - remove unwanted parenthesis in simple SET clause
* Deploy package & tools - Quote zip archive file in psql/pg_dump command
* Upgrade - rename SQL file for upgrade to 0.3.0

## 0.3.0 - 2020-03-03

* Package & restore - Add an optional SQL file to run in clone after deploy
* Synchronization - Add new option to exclude columns from bidirectional database sync
* Doc - update README for SQL generator
* Update french translation

## 0.2.3 - 2020-02-28

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

## 0.2.2 - 2020-02-21

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
