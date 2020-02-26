# Add ISO code for any locales you want to support here (space separated)
LOCALES = "en fr"
# Name of the plugin, for the ZIP file
PLUGINNAME = lizsync

help:
	$(MAKE) -C qgis_plugin_tools help

pylint:
	$(MAKE) -C qgis_plugin_tools pylint --ignore=

docker_test:
	$(MAKE) -C qgis_plugin_tools docker_test PLUGINNAME=$(PLUGINNAME)

i18n_%:
	$(MAKE) -C qgis_plugin_tools i18n_$* LOCALES=$(LOCALES)

release_%:
	$(MAKE) -C qgis_plugin_tools release_$* PLUGINNAME=$(PLUGINNAME)
