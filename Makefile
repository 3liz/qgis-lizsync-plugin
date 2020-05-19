start_tests:
	@echo 'Start docker-compose'
	@cd .docker && ./start.sh

run_tests:
	@echo 'Running tests, containers must be running'
	@cd .docker && ./exec.sh

stop_tests:
	@echo 'Stopping/killing containers'
	@cd .docker && ./stop.sh

tests: start_tests run_tests stop_tests

schemaspy:
	@cd .docker && ./start.sh
	rm -rf docs/
	mkdir docs/
	@cd .docker && ./install_db.sh
	@cd .docker && ./schemaspy.sh
	@cd .docker && ./stop.sh

reformat_sql:
	@cd .docker && ./start.sh
	@cd .docker && ./install_db.sh
	@cd .docker && ./reformat_sql_install.sh
	@cd .docker && ./stop.sh
