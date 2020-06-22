#!/usr/bin/env bash
export $(grep -v '^#' .env | xargs)

docker exec -it postgis sh \
  -c "runuser -l postgres -c 'dropdb lizsync_clone_a && dropdb lizsync_clone_b'"
docker exec -it postgis sh \
  -c "runuser -l postgres -c 'createdb lizsync_clone_a && createdb lizsync_clone_b'"

docker exec -it qgis sh \
  -c "cd /tests_directory/${PLUGIN_NAME} && qgis_testrunner.sh qgis_plugin_tools.infrastructure.test_runner.test_package"
