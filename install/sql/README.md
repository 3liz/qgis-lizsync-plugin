## Automatic generation of structure SQL files

### Schema audit

The files inside the `audit` folder are taken from https://github.com/Oslandia/audit_trigger/blob/master/audit.sql

### Schema lizsync

Generation of the `lizsync` schema SQL files is made via

```bash

cd install/sql
./export_database_structure_to_SQL.sh lizsync lizsync
```

This script will remove and regenerate the SQL files based on the `pg_dump` tool, by connecting to the database referenced by the PostgreSQL service `lizsync`. You need to pass the parameter `lizsync`, which is the name of the schema, and the name of the target folder (relative to `install/sql`)

It splits the content of the SQL dump into one file per database object type:

* functions
* tables (and comments, sequences, default values)
* views
* indexes
* triggers
* constraints (pk, unique, fk, etc.)

### Schema imports

This schema is created manually via the file [00_initialize_database](install/sql/00_initialize_database.sql)
