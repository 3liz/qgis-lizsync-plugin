# User guide

## Architecture and workflow

A **PostgreSQL** database called *central database* contains data in **tables**, organised in **schemas**. No data is stored in the `public` schema.

LizSync tools must be installed in this central database with the [dedicated QGIS processing algorithm](../processing/#install-lizsync-tools-on-the-central-database). This will create a new schema `lizsync` in the central database, containing the needed tables and functions in charge of the synchronisation.

Then, you need to [prepare this database](../processing/#prepare-the-central-database) to add the needed metadata (server id in the table `lizsync.server_metadata`) and optionally prepare some tables for the synchronisation: add a unique id `uid` colums (UUID) and a trigger in charge of logging the table data modifications (insert, update, delete).

When the central database is ready, you can then [create a package from the central database ](../processing/#create-a-package-from-the-central-database). To do so, just open or save a QGIS project containing PostgreSQL layers from the central database, choose the layers to export, and the zip package file path. This action is considered as a full synchronisation. The output zip archive contains the data from the chosen layers, but also the needed information about the central server and the tables which have been exported.

This zip archive can be [deployed to one or many clone PostgreSQL databases](../processing/#deploy-a-database-package-to-the-clone). This action will completely **remove the tables** corresponding to the exported layers, and replace their content with the one inside the archive. It also **re-installs the LizSync tools** in the clone database, which will delete all previous audited data. After this step, the data of the synchronised tables in the clone(s) database will be the same as the one exported at the time of the package creation.

Data of the central and clone(s) database tables can then evolve freely, as soon as the tables structure is not modified (no addition or removal of tables or fields). For example, you can go to the field with QField installed in your tablet (or QGIS in your laptop) and edit data inside the clone database.

You can then **run a bidirectional synchronisation** with the [dedicated QGIS processing algorithm](#two-way-database-synchronization) by choosing the PostgreSQL connections for the central database and the clone database. You can also run a synchronisation by running the SQL query `SELECT lizsync.synchronize()` from a PostgreSQL connection to the clone database. The synchronisation is **a two-step action**, which first gets the data modification from the central server and then pushes the data modifications the clone to the central database.

## Technical considerations

TODO: translate in English

Certains choix **méthodologiques et techniques** ont été faits pour assurer la synchronisation bidirectionnelle.

* la base centrale stocke dans le schéma `lizsync` les données nécessaires aux synchronisations.
* les données du schéma `public` ne sont **jamais synchronisées**
* les tables doivent avoir une **clé primaire de type entier, autoincrémentée**. Cet identifiant pourrait diverger entre la base centrale et les clones. Il n'est utile que localement pour certaines applications (QGIS préfère qu'il y ait une clé primaire entière)
* les tables à synchroniser doivent toutes posséder un champ **uid** de type **uuid** (valeur exemple: `5d3d503c-6d97-f11e-a2a4-5db030060f6d`) avec une valeur par défaut automatique. Ce champ est le pivot de la synchronisation. Il permet de reconnaître de manière unique un objet entre toutes les bases de données.
* les références de **clés étrangères** doivent se baser sur le champ **uid** de la table parente, et non sur la clé primaire, car les clés primaires peuvent diverger entre les bases.
* lors de la synchronisation bidirectionnelle, les modifications de la base centrale sont récupérées, puis comparées à celles du clone pour gérer les conflits d'édition. Elles sont ensuite rejouées sur le clone et la base centrale.
* les modifications de données sont rejouées seulement pour les champs modifiés.


