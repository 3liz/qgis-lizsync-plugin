## Introduction

Database structure is documented with SchemaSpy: http://schemaspy.org/.

This tool generates HTML files with information on schemas, tables, functions, constraints and provide graphical representation of the table relations.

## Documentation SchemaSpy

We created a small bash script to generate the documentation

```bash
~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/lizsync
mkdir -p doc/database/schemaspy/
cd doc/database/schemaspy/
chmod +x build_database_documentation.sh
```

Run it by passing correct database connection parameters (password will be asked)

```bash
cd doc/database/schemaspy/
./build_database_documentation.sh -h localhost -p 5432 -d lizsync -u postgres -o html

```

Il will create an `index.html` file in the `html/` folder, which can be opened with a web browser

NB: Get needed binaries here:

* SchemaSpy: https://github.com/schemaspy/schemaspy/releases Par exemple `schemaspy-6.0.0.jar`
* Driver PostgreSQL: https://jdbc.postgresql.org/download.html Par exemple `postgresql-42.2.5.jar`
