#!/usr/bin/env bash
export $(grep -v '^#' .env | xargs)

echo "Test if PostgreSQL is ready"
until docker exec postgis bash -c "psql service=test -c 'SELECT version()'" 1>  /dev/null 2>&1
do
  echo "."
  sleep 1
done
echo "PostgreSQL is now ready !"

docker exec -it postgis sh \
  -c "runuser -l postgres -c 'dropdb lizsync_clone_a && dropdb lizsync_clone_b'"
docker exec -it postgis sh \
  -c "runuser -l postgres -c 'createdb lizsync_clone_a && createdb lizsync_clone_b'"

docker exec -it qgis sh \
  -c "cd /tests_directory/${PLUGIN_NAME} && qgis_testrunner.sh qgis_plugin_tools.infrastructure.test_runner.test_package"
