## Test script

```bash
# Go to test data folder
cd install/test_data/

# Drop and recreate test databases
dropdb lizsync_central && dropdb lizsync_clone_a && createdb lizsync_central && createdb lizsync_clone_a

# You then need to create 2 PostgreSQL services: lizsync_central and lizsync_clone_a
# Import test data
./import_test_data_into_postgresql.sh lizsync_central test

# Add trigger wich generates a value based on sequence, which must be unique (and will fail if synchronized as is)
psql service=lizsync_central -f test_unique_field_based_on_serial_with_trigger.sql

# Run algs to prepare central database
# Install Lizsync tools on the central database
python3 ../../processing/standalone_processing_runner.py "lizsync:create_database_structure" '{"CONNECTION_NAME_CENTRAL": "lizsync_central", "OVERRIDE_AUDIT": false, "OVERRIDE_LIZSYNC": false}'

# Prepare central database
python3 ../../processing/standalone_processing_runner.py "lizsync:initialize_central_database" '{"CONNECTION_NAME_CENTRAL":"lizsync_central","ADD_SERVER_ID":true,"ADD_UID_COLUMNS":true,"ADD_AUDIT_TRIGGERS":true,"SCHEMAS":"test"}'

# Create a package from the central database
python3 ../../processing/standalone_processing_runner.py "lizsync:package_master_database" '{"CONNECTION_NAME_CENTRAL":"lizsync_central","POSTGRESQL_BINARY_PATH":"/usr/bin/","SCHEMAS":"test","ZIP_FILE":"/home/mdouchin/Documents/3liz/Valabre/GeoPoppy/Logiciel/qgis_3liz_fake_ftp_remote_server/test/archives/archive.zip", "ADDITIONNAL_SQL_FILE": "/home/mdouchin/Documents/3liz/qgis/QGIS3/plugins/lizsync/install/test_data/additionnal_sql_commande.sql"}'

# Deploy a database package to the clonepython3
python3 ../../processing/standalone_processing_runner.py "lizsync:deploy_database_server_package" '{"CONNECTION_NAME_CENTRAL":"lizsync_central","CONNECTION_NAME_CLONE":"lizsync_clone_a","POSTGRESQL_BINARY_PATH":"/usr/bin/","ZIP_FILE":"/home/mdouchin/Documents/3liz/Valabre/GeoPoppy/Logiciel/qgis_3liz_fake_ftp_remote_server/test/archives/archive.zip"}'

# Edit data in both databases
# Two SQL scripts are provided, which you can adapt beforehand:
psql service=lizsync_central -f central_database_edition_sample.sql
psql service=lizsync_clone_a -f clone_a_database_edition_sample.sql

# Test diffs between the 2 test databases:
./quick_diff.sh lizsync_central lizsync_clone_a

# Test data for pluviometers
psql service=lizsync_clone_a -c "SELECT * FROM test.pluviometers WHERE id > 30"
psql service=lizsync_central -c "SELECT * FROM test.pluviometers WHERE id > 30"

# Run Two-way database synchronization
python3 ../../processing/standalone_processing_runner.py "lizsync:synchronize_database" '{"CONNECTION_NAME_CENTRAL": "lizsync_central", "CONNECTION_NAME_CLONE": "lizsync_clone_a"}'
```

