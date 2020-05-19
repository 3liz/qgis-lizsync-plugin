#!/usr/bin/env bash
export $(grep -v '^#' .env | xargs)

docker-compose up -d --force-recreate
echo "Wait 10 seconds"
sleep 10
echo "Installation of the plugin ${PLUGIN_NAME}"
docker exec -it qgis sh -c "qgis_setup.sh ${PLUGIN_NAME}"
echo "Setup the database link from QGIS"
docker cp postgis_connexions.ini qgis:/tmp
docker exec qgis bash -c "cat /tmp/postgis_connexions.ini >> /root/.local/share/QGIS/QGIS3/profiles/default/QGIS/QGIS3.ini"
echo "Containers are running"
