# What is LizSync ?

## Presentation

**LizSync** is a set of tools allowing to perform PostgreSQL **database synchronisations** between a **central** database and one or many **clone** databases:

* The **central database** is the full PostgreSQL database, containing stable data. It is the source of trust.
* The **clone database** is a PostgreSQL database installed on a computer, on another server, on a device (Android). It contains a
  **subset of the schemas and tables** of the central database. It may be dropped or recreated. It has been
  created by deploying an archive created with the QGIS plugin.

Two-way synchronisation is done:

* between the same tables of the central and clone(s) databases having **the same name and structure**,
* only for the **data of chosen tables** in chosen schemas: no synchronisation is made on structure changes (adding a column, creating or dropping tables, etc.).

## Softwares

It is based on **PostgreSQL** and **QGIS**:

* **PostgreSQL**:
    - a schema **lizsync** contains the tables and functions in charge of managing the synchronisation actions, storing the history
      and needed information on the central and clones databases.
* **QGIS** with a set of **processing algorithms** to help the user to:
    - prepare a database for synchronisation,
    - create an archive from database and deploy it on clones,
    - perform the synchronisation.
    - some algorithm allow to prepare a QGIS project for the field work.

## LizSync workflow

To start using **LizSync**, you need to:

* **install** the needed PostgreSQL **structure** in the central database
* **prepare the central database**:
    - add the needed **metadata**, such as the server id
    - add an **uid column** to every table to synchronise
    - add the needed **audit triggers** for the same tables
* Before each field work campaign or when the table(s) structure has changed:
    * **create an zip archive**, called a **package**, from the central database which contains the data and needed information
    * **deploy** it to one or many clones
* Whenever needed:
    * **perform** a two-way synchronisation from the clone by using the dedicated algorithm

There is **only one central database** but you can have **one or many clone databases**.

All these steps can be performed with **LizSync plugin** for QGIS, by using the dedicated algorithms in the **Processing toolbox**.

!!! tip
    The plugin provides a right panel in QGIS interface which gives a **direct access to the main algorithms**. You can read the auto-generated documentation of all the Processing algorithms in the [processing page](../processing/README.md).

## PostgreSQL database structure

LizSync uses **a dedicated schemas**:

* **lizsync**
    - stores information on central and clones databases (uid),
    - records every actions made on tables: **inserts, updates and deletes**,
    - manages the sync actions,
    - maintain an history of synchronisations

## Auditing changes

LizSync uses a modified version of the [audit trigger tool](https://github.com/Oslandia/audit_trigger/blob/master/audit.sql) to **monitor the changes** made in the central and clone databases. There is no `audit` schema created though, as every needed audit table and functions are deployed within the schema `lizsync`. The triggers names begins with `lizsync_audit_trigger_` instead of `audit_trigger_`. It allows to use the original audit trigger tool independently if needed.

The audit tool stores its data in **two tables**:

* **lizsync.logged_relations**: the list of audited tables and their primary key(s)
* **lizsync.logged_actions**: the logs of every data modification made on the audited tables

Each **insert, update or delete** triggers the addition of a new line in the `lizsync.logged_actions` table, with information about the time of the change, author, the type of action, etc.

We added a new column `lizsync.sync_data` to the table `lizsync.logged_actions` needed by the synchronisation. It contains the unique ID of the origin database, and the synchronisation item key. We modified the triggers to fill in this new JSON column.

## Key features

* **Two-way sync**: clone 1 <-> central <-> clone B <-> central <-> clone C <-> central
* **Field granularity**: SQL Queries replay only needed changes
* **Manage conflicts**: last date of edition wins (last person in the field)
* **SQL based**: run from any clone DB
```sql
SELECT lizsync.synchronize()
```
* Based on QGIS **Processing**: algorithms can be run in CLI if needed
* **Unit tests** cover the key features: installation, upgrade, synchronisation

## Demo

Read the [reference page](../references.md) for some videos.
