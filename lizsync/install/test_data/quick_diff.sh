CENTRAL=$1
CLONE=$2
CENTRAL_FILE="/tmp/$CENTRAL.sql"
CLONE_FILE="/tmp/$CLONE.sql"
SCHEMA=$3

# SCHEMA
echo "***** SCHEMA **********"
echo "CENTRAL"
pg_dump service=$CENTRAL --schema-only -Fp -n $SCHEMA -f $CENTRAL_FILE
echo "CLONE"
pg_dump service=$CLONE --schema-only -Fp -n $SCHEMA -f $CLONE_FILE
colordiff $CLONE_FILE $CENTRAL_FILE
rm -f $CLONE_FILE $CENTRAL_FILE

# DATA
echo "****** DATA ***********"
# Central
rm -f $CENTRAL_FILE $CLONE_FILE
# Get list of tables
TABLES=$(psql --tuples-only service=$CENTRAL -c "SELECT concat(table_schema,'.', table_name) as out FROM information_schema.tables WHERE True AND table_schema IN ('test') AND table_type = 'BASE TABLE' ORDER BY table_schema, table_name")
for T in $TABLES; do
    echo "-------"
    echo "-- $T"
    echo "-------"
    echo "CENTRAL"
    #psql service=$CENTRAL -c "COPY (SELECT * FROM $T ORDER BY 1) TO '$CENTRAL_FILE'";
    psql service=$CENTRAL -c "\copy (SELECT * FROM $T ORDER BY 1) To '$CENTRAL_FILE' WITH CSV DELIMITER E'\t'"
    echo "CLONE"
    #psql service=$CLONE -c "COPY (SELECT * FROM $T ORDER BY 1) TO '$CLONE_FILE'" ;
    psql service=$CLONE -c "\copy (SELECT * FROM $T ORDER BY 1) To '$CLONE_FILE' WITH CSV DELIMITER E'\t'"
    wdiff $CLONE_FILE $CENTRAL_FILE | colordiff | grep -E "\\[\\-|\\{\\+"
    rm -f $CLONE_FILE $CENTRAL_FILE
    echo ""
done;
