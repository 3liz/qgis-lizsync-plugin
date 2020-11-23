# Lizsync

[![Build Status](https://travis-ci.org/3liz/qgis-lizsync-plugin.svg?branch=master)](https://travis-ci.org/3liz/qgis-lizsync-plugin)


## Introduction

**LizSync** is a set of tools allowing to perform PostgreSQL **database synchronization** between a central database and one or many clone databases.

* The **central database** is the full PostgreSQL database, containing stable data. It is the source of trust.
* The **clone database** is a PostgreSQL database installed on a computer, other server, tablet. It contains a **subset of schemas and tables** from the central database. It may be droped or recreated. It has been created by deploying an archive created with the QGIS plugin.

Synchronization is done for **data of tables** in chosen schemas, between tables having **the same structure**. No synchronisation is made on structure changes (adding a column, creating or droping tables, etc.).

It is based on PostgreSQL and QGIS:

* **PostgreSQL**:
    - a schema **audit** contains tables, functions and triggers in charge of recording every actions made on tables: inserts, updates and deletes. It is a (small) adaptation of the [audit trigger tool](https://github.com/Oslandia/audit_trigger/blob/master/audit.sql)
    - a schema **lizsync** contains tables and functions helping to manage the sync actions, stores history and information on central and clones databases.
* **QGIS** with a set of **processing algorithms** to help the user to:
    - prepare a database for synchronization,
    - create an archive from database and deploy it on clones,
    - and perform the synchronization.


## Documentation

You can learn about LizSync concepts and use cases by ready the [full documentation](https://3liz.github.io/qgis-lizsync-plugin/)

## Demo !

Videos on youtube:

* Database structure, preparation, create and deploy ZIP archive: https://youtu.be/l8a1Pn7CpN0
* Data editing and 2-way synchronisation: https://youtu.be/tnWVBJGqD0M


## Scripts

We provide a [Makefile](./Makefile) which helps the developpers to:

* run tests,
* build the documentation (Database structure and Processing algorithms)
* and generate the SQL files used for installing the structure in a PostgreSQL database.


### Tests

* Unit tests can be run with:

```bash
make tests
```

* Database test migration can be run with:

```bash
make test_migration
```

### Documentation

* Processing algorithms documentation can be generated with:

```bash
make processing-doc
```

* HTML pages from repository markdown files, located in the *docs/userguide* directory. After editing the markdown files, use:

```bash
make github-pages
```

* PostgreSQL database structure with [SchemaSpy](http://schemaspy.org/)

```bash
make schemaspy
```

* The documentation index page must be written by hand by editing the file [docs/index.html](docs/index.html).


## Contributors

* Michaël Douchin (3liz)  @mdouchin
* Etienne Trimmaille @Gustry

## Funding

* Valabre: https://www.valabre.com/
* Permagro: https://permagro.odoo.com/

## Licence

GPL V2
