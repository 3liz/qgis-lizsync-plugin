#!/bin/sh
#
# Create documentation based on the SchemaSpy tool
# Ex: ./build_database_documentation.sh -h localhost -p 5432 -d lizsync -u postgres -o html
# LICENCE: GPL 2
# AUTHOR: 3LIZ

while getopts h:p:d:u:o: option
do
case "${option}"
in
h) DBHOST=${OPTARG};;
p) DBPORT=${OPTARG};;
d) DBNAME=${OPTARG};;
u) DBUSER=${OPTARG};;
o) OUTPUTDIR=${OPTARG};;
esac
done

# Create HTML landing page with list of exported schemas
echo "<h3>List of database schemas</h3>" > $OUTPUTDIR/index.html

# On boucle sur les schemas
for SCHEMANAME in lizsync; do

    # Remove existing directory
    rm -rf $OUTPUTDIR/$SCHEMANAME

    # Create directory
    mkdir -p $OUTPUTDIR/$SCHEMANAME

    # Run SchemaSpy for current schema
    java -jar schemaspy-6.0.0.jar -t pgsql-mat -dp postgresql-42.2.4.jar -host $DBHOST -port $DBPORT -db $DBNAME -u $DBUSER -pfp -s $SCHEMANAME -norows -o $OUTPUTDIR/$SCHEMANAME

    # Add schema documentation file to index.html
    echo "<li><a href=$SCHEMANAME/index.html>$SCHEMANAME</a></li>" >> $OUTPUTDIR/index.html

done
