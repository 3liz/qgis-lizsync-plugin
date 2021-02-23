# Presentation

**LizSync** is a set of tools allowing to perform PostgreSQL **database synchronisation** between a **central** database and one or many **clone** databases.

Two-way synchronisation is done:

* for **data of tables** in chosen schemas,
* between tables having **the same structure**.
* No synchronisation is made on structure changes (adding a column, creating or droping tables, etc.).

## LizSync workflow

* For the 1st time
    * **install** the needed PostgreSQL **structure** in the central database
    * **prepare the central database**:
        - add an **uid column** to every synchronized table
        - add needed **audit triggers**
* Before each campain / when structure has changed
    * **create an archive** from the central database with data from chosen schemas
    * **deploy** it to one or many clones
* Whenever needed
    * **perform** a two-way synchronisation from the clone

There is only one central database but you can have one or many clone databases.

## PostgreSQL structure

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

## Demo

Read the [reference page](../references.md) for some videos.

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
