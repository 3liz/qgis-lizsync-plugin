#!/bin/sh

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


echo "# CREATE SCHEMA IF NEEDED"
psql service=$SERVICE -c "CREATE SCHEMA IF NOT EXISTS $SCHEMA"

echo "# IMPORT DATA"
ogr2ogr -overwrite -f PostgreSQL  "PG:service=$SERVICE active_schema=$SCHEMA" data.gpkg

echo "# LIST TABLES IN SCHEMA"
psql service=$SERVICE -c "\dt $SCHEMA."
