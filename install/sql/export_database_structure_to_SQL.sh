#!/bin/sh
#
# Explode PostgreSQL database dump into several files, one per type
# LICENCE: GPL 2
# AUTHOR: 3LIZ
if [ -n "$1" ]; then
  echo "Working on schema $1"
else
  echo "No schema given as first parameter";
  exit;
fi

SCHEMA=$1
OUTDIR=$SCHEMA

# Remove previous SQL files
rm ./"$OUTDIR"/*.sql
mkdir -p "$OUTDIR"

# STRUCTURE
# Dump database structure
pg_dump service=lizsync --schema-only -n $SCHEMA --no-acl --no-owner -Fc -f "$OUTDIR/dump"

# Loop through DB object types and extract SQL
I=10
for ITEM in FUNCTION "TABLE|COMMENT|SEQUENCE|DEFAULT" VIEW INDEX TRIGGER CONSTRAINT; do
    echo $ITEM
    # Extract list of objects for current item
    pg_restore --no-acl --no-owner -l $OUTDIR/dump | grep -E "$ITEM" > "$OUTDIR/$ITEM";
    # Extract SQL for these objects
    pg_restore --no-acl --no-owner -L "$OUTDIR/$ITEM" "$OUTDIR/dump" > "$OUTDIR"/"$I"_"$ITEM".sql;
    # Remove file containing list of objects
    rm "$OUTDIR/$ITEM";
    # Simplify comments inside SQL files
    perl -i -0pe 's/\n--\n-- Name: (TABLE )?(COLUMN )?(.+); Type:.+\n--\n\n/\n-- $3\n/g' "$OUTDIR"/"$I"_"$ITEM".sql;
    # Remove audit trigger (added afterwards)
    if [ $ITEM = 'TRIGGER' ]
    then
        sed -i '/audit_trigger/d' "$OUTDIR"/"$I"_"$ITEM".sql;
    fi
    # Rename
    rename -f 's#\|#_#g' "$OUTDIR"/"$I"_"$ITEM".sql;
    # Increment I
    I=$(($I+10));
done

# Remove dump
rm "$OUTDIR/dump"

# NOMENCLATURE
echo "GLOSSARY"
if [ $SCHEMA = 'lizsync' ]
then
    pg_dump service=lizsync --data-only --inserts --column-inserts -n $SCHEMA --no-acl --no-owner --table "lizsync.glossary" -f "$OUTDIR"/90_GLOSSARY.sql
fi
