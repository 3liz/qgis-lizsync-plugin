# What is LizSync ?

## Introduction

**LizSync** is a set of tools allowing to perform PostgreSQL **database synchronisations** between a **central** database and one or many **clone** databases.

Two-way synchronisation is done:

* for the **data of chosen tables** in chosen schemas,
* between the same tables of distinct databases having **the same name and structure**.
* No synchronisation is made on structure changes (adding a column, creating or droping tables, etc.).

## LizSync workflow

To start using **LizSync**, you need to:

* **install** the needed PostgreSQL **structure** in the central database
* **prepare the central database**:
    - add an **uid column** to every synchronized table
    - add the needed **audit triggers** for the same tables
* Before each campaign or when the table(s) structure has changed:
    * **create an zip archive** from the central database which contains the data and needed information
    * **deploy** it to one or many clones
* Whenever needed:
    * **perform** a two-way synchronisation from the clone by using the dedicated algorithm

There is **only one central database** but you can have **one or many clone databases**.

All these steps can be performed with **LizSync plugin** for QGIS, by using the dedicated algorithms in the **Processing toolbox**.

!!! tip
    The plugin provides a right panel in QGIS interface which gives a **direct access to the main algorithms**. You can read the auto-generated documentation of all the Processing algorithms in the [processing page](../processing/README.md).

## PostgreSQL database structure

LizSync uses **2 dedicated schemas**:

* **audit**
    - in charge of recording every actions made on tables: **inserts, updates and deletes.**
    - It is a slightly modified version of the [audit trigger tool](https://github.com/Oslandia/audit_trigger/blob/master/audit.sql)
* **lizsync**
    - stores information on central and clones databases (uid),
    - manages the sync actions,
    - maintain an history of synchronisations

## Auditing changes

LizSync uses a modified version of the [audit trigger tool](https://github.com/Oslandia/audit_trigger/blob/master/audit.sql) to **monitor the changes** made in the central and clone databases.

The audit tool stores data in **two tables**:

* **audit.logged_relations**: the list of audited tables and their primary key(s)
* **audit.logged_actions**: the logs of every data modification made on the audited tables

Each **insert, update or delete** triggers the addition of a new line in the `audit.logged_actions` table, with information about the time of the change, author, type of action, etc.

We added a new column `audit.sync_data` to the table `audit.logged_actions` needed by the synchronisation. It contains the unique ID of the origin database, and the synchronisation item key.

We modified the trigger to fill in this new JSON column.

## Key features

* **Two-way sync**: clone 1 <-> central <-> clone B <-> central <-> clone C <-> central
* **Field granularity**: SQL Queries replay only needed changes
* **Manage conflicts**: last date of edition wins (last person in the field)
* **SQL based**: run from any clone DB
```sql
SELECT lizsync.synchronize()
```
* **Processing algs**: can be run in CLI if needed
* **Unit tests**: installation/upgrade/synchronisation

## Demo

Read the [reference page](../references.md) for some videos.
