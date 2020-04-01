# Add ISO code for any locales you want to support here (space separated)
LOCALES = "en fr"
# Name of the plugin, for the ZIP file
PLUGINNAME = lizsync


start_tests:
	@echo 'Start docker-compose'
	@cd docker && ./start.sh

run_tests:
	@echo 'Running tests, containers must be running'
	@cd docker && ./exec.sh

stop_tests:
	@echo 'Stopping/killing containers'
	@cd docker && ./stop.sh

tests: start_tests run_tests stop_tests
