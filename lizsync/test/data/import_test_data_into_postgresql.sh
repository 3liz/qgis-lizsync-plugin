#!/bin/sh
# Run: ./import_test_data_into_postgresql.sh postgresql_service_name [schema_name]

# Check parameters
echo "# CHECK INPUT PARAMETERS service and schema"
if [ -n "$1" ]; then
  echo "# POSTGRESQL SERVICE: $1"
  SERVICE=$1
else
  echo "ERROR: No PostgreSQL service given as second parameter";
  exit;
fi
if [ -n "$2" ]; then
  echo "# GIVEN SCHEMA: $2"
  SCHEMA=$2
else
  echo "# DEFAULT SCHEMA: test";
  SCHEMA="test"
fi
echo ""

# Run needed actions
echo "# CREATE SCHEMA IF NEEDED"
psql service=$SERVICE -c "DROP SCHEMA IF EXISTS $SCHEMA CASCADE;CREATE SCHEMA IF NOT EXISTS $SCHEMA"

echo "# CREATE EXTENSION postgis IF NEEDED"
psql service=$SERVICE -c "CREATE EXTENSION IF NOT EXISTS postgis"

echo "# IMPORT DATA"
for f in lizsync/install/test_data/data/*.geojson; do ogr2ogr -overwrite -f PostgreSQL  "PG:service=$SERVICE active_schema=$SCHEMA" $f -lco geometry_name=geom -lco fid=ogc_fid; done;

echo "# LIST TABLES IN SCHEMA"
psql service=$SERVICE -c "\dt $SCHEMA."
