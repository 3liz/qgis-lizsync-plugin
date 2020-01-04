CENTRAL=lizsync_central
CLONE=lizsync_clone_a
CENTRAL_FILE="/tmp/$CENTRAL.sql"
CLONE_FILE="/tmp/$CLONE.sql"
SCHEMA="test"

# SCHEMA
echo "***********************"
echo "***** SCHEMA **********"
echo "CENTRAL"
pg_dump service=$CENTRAL --schema-only -Fp -n $SCHEMA -f $CENTRAL_FILE
echo "CLONE"
pg_dump service=$CLONE --schema-only -Fp -n $SCHEMA -f $CLONE_FILE
colordiff $CLONE_FILE $CENTRAL_FILE
sudo rm -f $CLONE_FILE $CENTRAL_FILE

# DATA
echo "***********************"
echo "****** DATA ***********"
# Central
sudo rm -f $CENTRAL_FILE
# Get list of tables
TABLES=$(psql --tuples-only service=$CENTRAL -c "SELECT concat(table_schema,'.', table_name) as out FROM information_schema.tables WHERE True AND table_schema IN ('test') AND table_type = 'BASE TABLE' ORDER BY table_schema, table_name")
for T in $TABLES; do
    echo "-------"
    echo "-- $T"
    echo "-------"
    echo "CENTRAL"
    psql service=$CENTRAL -c "COPY (SELECT * FROM $T ORDER BY 1) TO '$CENTRAL_FILE'";
    echo "CLONE"
    psql service=$CLONE -c "COPY (SELECT * FROM $T ORDER BY 1) TO '$CLONE_FILE'" ;
    wdiff $CLONE_FILE $CENTRAL_FILE | colordiff | grep -E "\\[\\-|\\{\\+"
    sudo rm -f $CLONE_FILE $CENTRAL_FILE
    echo ""
done;
