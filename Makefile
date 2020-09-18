start_tests:
	@echo 'Start docker-compose'
	@cd .docker && ./start.sh with-qgis

run_tests:
	@echo 'Running tests, containers must be running'
	@cd .docker && ./exec.sh
	@flake8

stop_tests:
	@echo 'Stopping/killing containers'
	@cd .docker && ./stop.sh

tests: start_tests run_tests stop_tests

test_migration:
	@cd .docker && ./start.sh
	@cd .docker && ./install_migrate_generate.sh
	@cd .docker && ./stop.sh

schemaspy:
	@cd .docker && ./start.sh
	rm -rf docs/database/
	mkdir docs/database/
	@cd .docker && ./install_db.sh
	@cd .docker && ./schemaspy.sh
	@cd .docker && ./stop.sh

reformat_sql:
	@cd .docker && ./start.sh
	@cd .docker && ./install_db.sh
	@cd .docker && ./reformat_sql_install.sh
	@cd .docker && ./stop.sh

flake8:
	@docker run --rm -w /plugin -v $(shell pwd):/plugin etrimaille/flake8:3.8.2

github-pages:
	@docker run --rm -w /plugin -v $(shell pwd):/plugin etrimaille/pymarkdown docs/user_guide/geopoppy-android.md docs/user_guide/geopoppy-android.html
	@docker run --rm -w /plugin -v $(shell pwd):/plugin etrimaille/pymarkdown docs/user_guide/qgis-lizsync-plugin.md docs/user_guide/qgis-lizsync-plugin.html

processing-doc:
	cd .docker && ./processing_doc.sh
	@docker run --rm -w /plugin -v $(shell pwd):/plugin 3liz/pymarkdown:latest docs/processing/README.md docs/processing/index.html
