## Create test databases and fill

```bash
dropdb lizsync_central
dropdb lizsync_clone_a
createdb lizsync_central
createdb lizsync_clone_a
```

You then need to create 2 PostgreSQL services: lizsync_central and lizsync_clone_a

## Import test data

Run this command to create a test schema in central database and import the 3 layers

```bash
./import_test_data_into_postgresql.sh lizsync_central test
```

## Run algs to prepare central database

Run in this order:

* `Install Lizsync tools on the central database`
* `Prepare central database`
* `Create a package from the central database`
* `Deploy a database package to the clone`

## Edit data in both databases

Two SQL scripts are provided, which you can adapt beforehand:

```bash
psql service=lizsync_central -f central_database_edition_sample.sql
psql service=lizsync_clone_a -f clone_a_database_edition_sample.sql

```

## Test diffs

* Test diffs between the 2 test databases:

```bash
./quick_diff.sh lizsync_central lizsync_clone_a
```

* Run the alg `Two-way database synchronization between central and clone database`

* Re-test the diffs

```bash
./quick_diff.sh lizsync_central lizsync_clone_a
```


