---
hide:
  - navigation
  - toc
---

# LizSync

**LizSync** is a set of tools allowing performing PostgreSQL **database synchronisation** between a central
database and one or many clone databases.

* The **central database** is the full PostgreSQL database, containing stable data. It is the source of trust.
* The **clone database** is a PostgreSQL database installed on a computer, other server, tablet. It contains a
  **subset of schemas and tables** from the central database. It may be dropped or recreated. It has been
  created by deploying an archive created with the QGIS plugin.

Synchronisation is done for **data of tables** in chosen schemas, between tables having **the same structure**.
No synchronisation is made on structure changes (adding a column, creating or dropping tables, etc.).

It is based on PostgreSQL and QGIS:

* **PostgreSQL**:
    - a schema **lizsync** contains tables and functions helping to manage the sync actions, stores history
      and information on central and clones databases.
* **QGIS** with a set of **processing algorithms** to help the user to:
    - prepare a database for synchronisation,
    - create an archive from database and deploy it on clones,
    - perform the synchronisation.
