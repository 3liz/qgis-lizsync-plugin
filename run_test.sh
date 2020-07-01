#!/usr/bin/env bash

# Drop and recreate test databases
echo ""
echo "Drop and recreate test databases"
echo "##########################"
dropdb lizsync_central && dropdb lizsync_clone_a && dropdb lizsync_clone_b
createdb lizsync_central && createdb lizsync_clone_a && createdb lizsync_clone_b

# You then need to create 2 PostgreSQL services: lizsync_central and lizsync_clone_a
# Import test data
echo ""
echo "Import test data"
echo "##########################"
lizsync/test/data/import_test_data_into_postgresql.sh lizsync_central test

# Add trigger which generates a value based on sequence, which must be unique (and will fail if synchronized as is)
# psql service=lizsync_central -f test/data/test_unique_field_based_on_serial_with_trigger.sql

# Run algs to prepare central database
# Install Lizsync tools on the central database
echo ""
echo "Install Lizsync tools on the central database"
echo "##########################"
ALGO="lizsync:create_database_structure"
PARAMS='{"CONNECTION_NAME": "lizsync_central", "OVERRIDE_AUDIT": false, "OVERRIDE_LIZSYNC": false}'
python3 lizsync/processing/standalone_processing_runner.py "${ALGO}" "${PARAMS}"


# Prepare central database
echo ""
echo "Prepare central database"
echo "##########################"
ALGO="lizsync:initialize_central_database"
PARAMS='{"CONNECTION_NAME_CENTRAL":"lizsync_central","ADD_SERVER_ID":true,"ADD_UID_COLUMNS":true,"ADD_AUDIT_TRIGGERS":true,"SCHEMAS":"test"}'
python3 lizsync/processing/standalone_processing_runner.py "${ALGO}" "${PARAMS}"


# Create a package from the central database
echo ""
echo "Create a package from the central database"
echo "##########################"
ALGO="lizsync:package_master_database"
PARAMS='{"CONNECTION_NAME_CENTRAL":"lizsync_central","POSTGRESQL_BINARY_PATH":"/usr/bin/","SCHEMAS":"test","ZIP_FILE":"/home/mdouchin/Documents/3liz/Valabre/GeoPoppy/Logiciel/qgis_3liz_fake_ftp_remote_server/test/archives/archive.zip", "ADDITIONAL_SQL_FILE": "/home/mdouchin/Documents/3liz/qgis/QGIS3/plugins/lizsync/test/data/additional_sql_commande.sql"}'
python3 lizsync/processing/standalone_processing_runner.py "${ALGO}" "${PARAMS}"

# Deploy a database package to the clone
echo ""
echo "Deploy a database package to the clone a"
echo "##########################"
ALGO="lizsync:deploy_database_server_package"
PARAMS='{"CONNECTION_NAME_CENTRAL":"lizsync_central","CONNECTION_NAME_CLONE":"lizsync_clone_a","POSTGRESQL_BINARY_PATH":"/usr/bin/","ZIP_FILE":"/home/mdouchin/Documents/3liz/Valabre/GeoPoppy/Logiciel/qgis_3liz_fake_ftp_remote_server/test/archives/archive.zip"}'
python3 lizsync/processing/standalone_processing_runner.py "${ALGO}" "${PARAMS}"

echo ""
echo "Deploy a database package to the clone b"
echo "##########################"
ALGO="lizsync:deploy_database_server_package"
PARAMS='{"CONNECTION_NAME_CENTRAL":"lizsync_central","CONNECTION_NAME_CLONE":"lizsync_clone_b","POSTGRESQL_BINARY_PATH":"/usr/bin/","ZIP_FILE":"/home/mdouchin/Documents/3liz/Valabre/GeoPoppy/Logiciel/qgis_3liz_fake_ftp_remote_server/test/archives/archive.zip"}'
python3 lizsync/processing/standalone_processing_runner.py "${ALGO}" "${PARAMS}"

# Edit data in both databases
echo ""
echo "Edit data in both databases"
echo "##########################"
# Two SQL scripts are provided, which you can adapt beforehand:
psql service=lizsync_central -f lizsync/test/data/central_database_edition_sample.sql
sleep 2
psql service=lizsync_clone_a -f lizsync/test/data/clone_a_database_edition_sample.sql
sleep 2
psql service=lizsync_clone_b -f lizsync/test/data/clone_b_database_edition_sample.sql

exit

# Run Two-way database synchronization
echo ""
echo "Run Two-way database synchronization"
echo "##########################"
ALGO="lizsync:synchronize_database"
PARAMS= '{"CONNECTION_NAME_CENTRAL": "lizsync_central", "CONNECTION_NAME_CLONE": "lizsync_clone_a"}'
python3 lizsync/processing/standalone_processing_runner.py "${ALGO}" "${PARAMS}"

ALGO="lizsync:synchronize_database"
PARAMS='{"CONNECTION_NAME_CENTRAL": "lizsync_central", "CONNECTION_NAME_CLONE": "lizsync_clone_b"}'
python3 lizsync/processing/standalone_processing_runner.py "${ALGO}" "${PARAMS}"
ALGO="lizsync:synchronize_database"
PARAMS='{"CONNECTION_NAME_CENTRAL": "lizsync_central", "CONNECTION_NAME_CLONE": "lizsync_clone_a"}'
python3 lizsync/processing/standalone_processing_runner.py "${ALGO}" "${PARAMS}"
ALGO="lizsync:synchronize_database"
PARAMS='{"CONNECTION_NAME_CENTRAL": "lizsync_central", "CONNECTION_NAME_CLONE": "lizsync_clone_b"}'
python3 lizsync/processing/standalone_processing_runner.py "${ALGO}" "${PARAMS}"

# See diff between databases
echo ""
echo "Display diff between databases"
echo "##########################"
echo "CENTRAL / CLONE A"
echo "##########################"
lizsync/test/data/quick_diff.sh lizsync_central lizsync_clone_a test
echo "##########################"
echo "CENTRAL / CLONE B"
echo "##########################"
lizsync/test/data/quick_diff.sh lizsync_central lizsync_clone_b test
echo "##########################"
echo "CLONE A / CLONE B"
echo "##########################"
lizsync/test/data/quick_diff.sh lizsync_clone_a lizsync_clone_b test
