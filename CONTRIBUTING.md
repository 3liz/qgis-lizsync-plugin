# Contributing

This project is hosted on GitHub.

[Visit GitHub](https://github.com/3liz/qgis-pgmetadata-plugin/){: .md-button .md-button--primary }

## Scripts

We provide a [Makefile](./Makefile) which helps the developers to:

* run tests,
* build the documentation (Database structure and Processing algorithms)
* generate the SQL files used for installing the structure in a PostgreSQL database.

## Translation

The UI is available on [Transifex](https://www.transifex.com/3liz-1/lizsync/dashboard/), no development
knowledge is required. [![Transifex 🗺](https://github.com/3liz/qgis-lizsync-plugin/actions/workflows/transifex.yml/badge.svg)](https://github.com/3liz/qgis-lizsync-plugin/actions/workflows/transifex.yml)

## Code

SQL and Python are covered by unittests with Docker.

[![Tests 🎳](https://github.com/3liz/qgis-lizsync-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/3liz/qgis-lizsync-plugin/actions/workflows/ci.yml)

```bash
pip install -r requirements-dev.txt
flake8
make tests
make test_migration
```

On a new database, if you want to install the database by using migrations :

```python
import os
os.environ['TEST_DATABASE_INSTALL_LIZSYNC'] = '0.2.2'  # Enable
del os.environ['TEST_DATABASE_INSTALL_LIZSYNC']  # Disable
```

## Documentation

The documentation is using [MkDocs](https://www.mkdocs.org/) with [Material](https://squidfunk.github.io/mkdocs-material/) :

```bash
pip install -r requirements-doc.txt
mkdocs serve
```

* Processing algorithms documentation can be generated with:

```bash
make processing-doc
```

* PostgreSQL database structure with [SchemaSpy](http://schemaspy.org/)

```bash
make schemaspy
```
