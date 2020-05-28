--
-- PostgreSQL database dump
--

-- Dumped from database version 9.6.17
-- Dumped by pg_dump version 10.10 (Ubuntu 10.10-0ubuntu0.18.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

-- add_uid_columns(text, text)
CREATE FUNCTION lizsync.add_uid_columns(p_schema_name text, p_table_name text) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
  query text;
BEGIN

    BEGIN
        SELECT INTO query
        concat(
            ' ALTER TABLE ' || quote_ident(p_schema_name) || '.' || quote_ident(p_table_name) ||
            ' ADD COLUMN uid uuid DEFAULT md5(random()::text || clock_timestamp()::text)::uuid ' ||
            ' UNIQUE NOT NULL'
        );
        execute query;
        RAISE NOTICE 'uid column created for % %', quote_ident(p_schema_name), quote_ident(p_table_name);
        RETURN True;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'ERROR - uid column already exists';
        RETURN False;
    END;

END;
$$;


-- analyse_audit_logs()
CREATE FUNCTION lizsync.analyse_audit_logs() RETURNS TABLE(ids bigint[], min_event_id bigint, max_event_id bigint, max_action_tstamp_tx timestamp with time zone)
    LANGUAGE plpgsql
    AS $$
DECLARE
    sqltemplate text;
    p_ids bigint[];
    p_min_event_id bigint;
    p_max_event_id bigint;
    p_max_action_tstamp_tx timestamp with time zone;
    central_ids_to_keep integer[];
    clone_ids_to_keep integer[];
BEGIN

    -- Store all central ids before the analyse and removal of rejected logs
    -- Also store min and max event id
    SELECT INTO p_ids, p_min_event_id, p_max_event_id, p_max_action_tstamp_tx
    array_agg(DISTINCT event_id), min(event_id), max(event_id), max(action_tstamp_tx)
    FROM temp_central_audit
    ;

    -- Get the list of ids to keep from each log
    -- We use DISTINCT ON to remove consecutive UPDATE on the same ident, uid and field for each source.
    -- Last is kept
    -- central
    WITH
    ce AS (
        SELECT
        DISTINCT ON (ident, action_type, updated_field, uid)
        tid
        FROM temp_central_audit
        ORDER BY ident, action_type, updated_field, uid, event_id DESC
    )
    SELECT array_agg(tid)
    FROM ce
    INTO central_ids_to_keep
    ;
    -- clone
    WITH
    cl AS (
        SELECT
        DISTINCT ON (ident, action_type, updated_field, uid)
        tid
        FROM temp_clone_audit
        ORDER BY ident, action_type, updated_field, uid, event_id DESC
    )
    SELECT array_agg(tid)
    FROM cl
    INTO clone_ids_to_keep
    ;

    -- DELETE removed lines from temp audit tables
    DELETE FROM temp_central_audit
    WHERE tid != ALL (central_ids_to_keep)
    ;
    DELETE FROM temp_clone_audit
    WHERE tid != ALL (clone_ids_to_keep)
    ;

    -- Compare logs
    -- And get conflicts
    -- Last modified is kept, older is rejected
    INSERT INTO temp_conflicts
    (
        conflict_time,
        object_table, object_uid,
        central_tid, clone_tid,
        central_event_id, central_event_timestamp,
        central_sql, clone_sql,
        rejected,
        rule_applied
    )
    SELECT
        now(),
        ce.ident, ce.uid::uuid,
        ce.tid AS cetid, cl.tid AS cltid,
        ce.event_id, ce.action_tstamp_tx,
        ce.action AS ceaction, cl.action AS claction,
        -- last modified wins
        CASE
            WHEN cl.original_action_tstamp_tx < ce.original_action_tstamp_tx THEN 'clone'
            ELSE 'central'
        END AS rejected,
        'last_modified' AS rule_applied
    FROM temp_central_audit AS ce
    INNER JOIN temp_clone_audit AS cl
        ON ce.ident = cl.ident
        AND ce.uid = cl.uid
        AND ce.action_type = 'U'
        AND cl.action_type = 'U'
        AND ce.updated_field = cl.updated_field
    ORDER BY ce.event_id
    ;

    -- DELETE rejected tid from audit temp tables
    -- central
    DELETE FROM temp_central_audit
    WHERE tid IN (
        SELECT central_tid
        FROM temp_conflicts
        WHERE rejected = 'central'
    )
    ;
    -- clone
    DELETE FROM temp_clone_audit
    WHERE tid IN (
        SELECT clone_tid
        FROM temp_conflicts
        WHERE rejected = 'clone'
    )
    ;

    -- Return data
    RETURN QUERY
    SELECT p_ids, p_min_event_id, p_max_event_id, p_max_action_tstamp_tx;
END;
$$;


-- FUNCTION analyse_audit_logs()
COMMENT ON FUNCTION lizsync.analyse_audit_logs() IS 'Get audit logs from the central database and the clone since the last synchronization. Compare the logs to find and resolved UPDATE conflicts (same table, feature, column): last modified object wins. This function store the resolved conflicts into the table lizsync.conflicts in the central database. Returns central server event ids, minimum event id, maximum event id, maximum action timestamp.';


-- create_central_server_fdw(text, smallint, text, text, text)
CREATE FUNCTION lizsync.create_central_server_fdw(p_central_host text, p_central_port smallint, p_central_database text, p_central_username text, p_central_password text) RETURNS boolean
    LANGUAGE plpgsql
    AS $_$
DECLARE
    sqltemplate text;
BEGIN
    -- Create extension
    CREATE EXTENSION IF NOT EXISTS postgres_fdw;

    -- Create server
    DROP SERVER IF EXISTS central_server CASCADE;
    sqltemplate = '
    CREATE SERVER central_server
    FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (
        host ''%1$s'',
        port ''%2$s'',
        dbname ''%3$s'',
        connect_timeout ''5''
    );
    ';
    EXECUTE format(sqltemplate,
        p_central_host,
        p_central_port,
        p_central_database
    );

    -- User mapping
    sqltemplate = '
    CREATE USER MAPPING FOR CURRENT_USER
    SERVER central_server
    OPTIONS (
        user ''%1$s'',
        password ''%2$s''
    )
    ';
    EXECUTE format(sqltemplate,
        p_central_username,
        p_central_password
    );

    -- Create local schemas
    CREATE SCHEMA IF NOT EXISTS central_audit;
    CREATE SCHEMA IF NOT EXISTS central_lizsync;

    -- Import foreign tables
    -- audit
    IMPORT FOREIGN SCHEMA audit
    FROM SERVER central_server
    INTO central_audit;

    -- lizsync
    IMPORT FOREIGN SCHEMA lizsync
    FROM SERVER central_server
    INTO central_lizsync;

    -- Manually create modified conflicts table
    -- with no id column to avoid issues
    -- https://stackoverflow.com/a/53361066/13220524
    CREATE FOREIGN TABLE central_lizsync.conflicts_bis(
        object_table text,
        object_uid uuid,
        clone_id uuid,
        central_event_id bigint,
        central_event_timestamp timestamp with time zone,
        central_sql text,
        clone_sql text,
        rejected text,
        rule_applied text
     )
    SERVER central_server
    OPTIONS (
        schema_name 'lizsync',
        table_name 'conflicts'
    );

    RETURN True;
END;
$_$;


-- FUNCTION create_central_server_fdw(p_central_host text, p_central_port smallint, p_central_database text, p_central_username text, p_central_password text)
COMMENT ON FUNCTION lizsync.create_central_server_fdw(p_central_host text, p_central_port smallint, p_central_database text, p_central_username text, p_central_password text) IS 'Create foreign server, needed central_audit and central_lizsync schemas, and import all central database tables as foreign tables. This will allow the clone to connect to the central databse';


-- create_temporary_table(text, text)
CREATE FUNCTION lizsync.create_temporary_table(temporary_table text, table_type text) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    sqltemplate text;
BEGIN
    -- Drop table if exists
    EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(temporary_table);
    -- Create temporary table
    IF table_type = 'audit' THEN
        EXECUTE 'CREATE TEMP TABLE ' || quote_ident(temporary_table) || ' (
            tid                       serial,
            event_id                  bigint,
            action_tstamp_tx          timestamp with time zone,
            action_tstamp_epoch       integer,
            ident                     text,
            action_type               text,
            origine                   text,
            action                    text,
            updated_field             text,
            uid                       uuid,
            original_action_tstamp_tx integer
        )
        --ON COMMIT DROP
        ';
    END IF;
    IF table_type = 'conflict' THEN
        EXECUTE 'CREATE TEMP TABLE ' || quote_ident(temporary_table) || ' (
            tid                     serial                   ,
            conflict_time           timestamp with time zone ,
            object_table            text                     ,
            object_uid              uuid                     ,
            central_tid             integer                  ,
            clone_tid               integer                  ,
            central_event_id        integer                  ,
            central_event_timestamp timestamp with time zone ,
            central_sql             text                     ,
            clone_sql               text                     ,
            rejected                text                     ,
            rule_applied            text
        )
        --ON COMMIT DROP
        ';
    END IF;

    RETURN True;
END;
$$;


-- FUNCTION create_temporary_table(temporary_table text, table_type text)
COMMENT ON FUNCTION lizsync.create_temporary_table(temporary_table text, table_type text) IS 'Create temporary table used during database bidirectionnal synchronization. Parameters: temporary table name, and table type (audit or conflit)';


-- get_central_audit_logs(text, text[])
CREATE FUNCTION lizsync.get_central_audit_logs(p_uid_field text, p_excluded_columns text[]) RETURNS TABLE(event_id bigint, action_tstamp_tx timestamp with time zone, action_tstamp_epoch integer, ident text, action_type text, origine text, action text, updated_field text, uid uuid, original_action_tstamp_tx integer)
    LANGUAGE plpgsql
    AS $_$
DECLARE
    p_clone_id text;
    p_excluded_columns_text text;
    sqltemplate text;
    sqltext text;
    dblink_connection_name text;
    dblink_msg text;
BEGIN

    IF p_excluded_columns IS NULL THEN
        p_excluded_columns_text = '';
    ELSE
        p_excluded_columns_text = array_to_string(p_excluded_columns, '@');
    END IF;

    -- Get clone server id
    SELECT server_id::text INTO p_clone_id
    FROM lizsync.server_metadata
    LIMIT 1;

    IF p_clone_id IS NULL THEN
        RETURN QUERY
        SELECT
            NULL, NULL, NULL, NULL,
            NULL, NULL, NULL, NULL, NULL, NULL
        LIMIT 0;
    END IF;

    -- Create dblink connection
    dblink_connection_name = (md5(((random())::text || (clock_timestamp())::text)))::text;
    SELECT dblink_connect(
        dblink_connection_name,
        'central_server'
    )
    INTO dblink_msg;

    sqltemplate = '

        WITH
        cid AS (
            SELECT server_id::text AS p_central_id
            FROM lizsync.server_metadata
            LIMIT 1
        ),
        last_sync AS (
            SELECT
                max_action_tstamp_tx,
                max_event_id
            FROM lizsync.history
            WHERE True
            AND server_from = (SELECT p_central_id FROM cid)
            AND ''%1$s'' = ANY (server_to)
            AND sync_status = ''done''
            ORDER BY sync_time DESC
            LIMIT 1
        ),
        schemas AS (
            SELECT sync_schemas
            FROM lizsync.synchronized_schemas
            WHERE server_id = ''%1$s''::uuid
            LIMIT 1
        )
        SELECT
            a.event_id,
            a.action_tstamp_tx AS action_tstamp_tx,
            extract(epoch from a.action_tstamp_tx)::integer AS action_tstamp_epoch,
            concat(a.schema_name, ''.'', a.table_name) AS ident,
            a.action AS action_type,
            CASE
                WHEN a.sync_data->>''origin'' IS NULL THEN ''central''
                ELSE ''clone''
            END AS origine,
            Coalesce(
                lizsync.get_event_sql(
                    a.event_id,
                    ''%2$s'',
                    array_to_string(
                        array_cat(
                            string_to_array(''%3$s'',''@''),
                            array_remove(akeys(a.changed_fields), s)
                        ), '',''
                    )
                ),
                ''''
            ) AS action,
            s AS updated_field,
            (a.row_data->''%2$s'')::uuid AS uid,
            CASE
                WHEN a.sync_data->>''action_tstamp_tx'' IS NOT NULL
                AND a.sync_data->>''origin'' IS NOT NULL
                    THEN extract(epoch from Cast(a.sync_data->>''action_tstamp_tx'' AS TIMESTAMP WITH TIME ZONE))::integer
                ELSE extract(epoch from a.action_tstamp_tx)::integer
            END AS original_action_tstamp_tx
        FROM audit.logged_actions AS a
        -- Create as many lines as there are changed fields in UPDATE
        LEFT JOIN skeys(a.changed_fields) AS s ON TRUE,
        last_sync, schemas

        WHERE True

        -- modifications do not come from clone database
        AND (a.sync_data->>''origin'' != ''%1$s'' OR a.sync_data->>''origin'' IS NULL)

        -- modifications have not yet been replayed in the clone database
        AND (NOT (a.sync_data->''replayed_by'' ? ''%1$s'') OR a.sync_data->''replayed_by'' = jsonb_build_object() )

        -- modifications after the last synchronization
        -- MAX_ACTION_TSTAMP_TX Par ex: 2019-04-20 12:00:00+02
        AND a.action_tstamp_tx > last_sync.max_action_tstamp_tx

        -- et pour lesquelles l ID est supérieur
        -- MAX_EVENT_ID
        AND a.event_id > last_sync.max_event_id

        -- et pour les schémas listés
        AND sync_schemas ? schema_name

        ORDER BY a.event_id
        ;
    ';

    sqltext = format(sqltemplate,
        p_clone_id,
        p_uid_field,
        p_excluded_columns_text
    );
    --RAISE NOTICE '%', sqltext;

    RETURN QUERY
    SELECT *
    FROM dblink(
        dblink_connection_name,
        sqltext
    ) AS t(
        event_id bigint, action_tstamp_tx timestamp with time zone, action_tstamp_epoch integer,
        ident text, action_type text, origine text, action text, updated_field text,
        uid uuid, original_action_tstamp_tx integer
    )
    ;

END;
$_$;


-- FUNCTION get_central_audit_logs(p_uid_field text, p_excluded_columns text[])
COMMENT ON FUNCTION lizsync.get_central_audit_logs(p_uid_field text, p_excluded_columns text[]) IS 'Get all the logs from the central database: modifications do not come from the clone, have not yet been replayed by the clone, are dated after the last synchronization, have an event id higher than the last sync maximum event id, and concern the synchronized schemas for this clone. Parameters: uid column name and excluded columns';


-- get_clone_audit_logs(text, text[])
CREATE FUNCTION lizsync.get_clone_audit_logs(p_uid_field text, p_excluded_columns text[]) RETURNS TABLE(event_id bigint, action_tstamp_tx timestamp with time zone, action_tstamp_epoch integer, ident text, action_type text, origine text, action text, updated_field text, uid uuid)
    LANGUAGE plpgsql
    AS $$
DECLARE
    sqltemplate text;
BEGIN
    RETURN QUERY
    SELECT
        a.event_id,
        a.action_tstamp_tx AS action_tstamp_tx,
        extract(epoch from a.action_tstamp_tx)::integer AS action_tstamp_epoch,
        concat(a.schema_name, '.', a.table_name) AS ident,
        a.action AS action_type,
        'clone'::text AS origine,
        Coalesce(
            lizsync.get_event_sql(
                a.event_id,
                p_uid_field,
                array_to_string(
                    array_cat(
                        p_excluded_columns,
                        array_remove(akeys(a.changed_fields), s)
                    ), ','
                )
            ),
            ''
        ) AS action,
        s AS updated_field,
        (a.row_data->p_uid_field)::uuid AS uid
    FROM audit.logged_actions AS a
    -- Create as many lines as there are changed fields in UPDATE
    LEFT JOIN skeys(a.changed_fields) AS s ON TRUE
    WHERE True
    ORDER BY a.event_id
    ;
END;
$$;


-- FUNCTION get_clone_audit_logs(p_uid_field text, p_excluded_columns text[])
COMMENT ON FUNCTION lizsync.get_clone_audit_logs(p_uid_field text, p_excluded_columns text[]) IS 'Get all the modifications made in the clone. Parameters: uid column name and excluded columns';


-- get_event_sql(bigint, text, text[])
CREATE FUNCTION lizsync.get_event_sql(pevent_id bigint, puid_column text, excluded_columns text[]) RETURNS text
    LANGUAGE plpgsql
    AS $$
DECLARE
  sql text;
BEGIN
    IF excluded_columns IS NULL THEN
        excluded_columns:= '{}'::text[];
    END IF;

    WITH
    event AS (
        SELECT * FROM audit.logged_actions WHERE event_id = pevent_id
    )
    -- get primary key names
    , where_pks AS (
        SELECT array_agg(uid_column) as pkey_fields
        FROM audit.logged_relations r
        JOIN event ON relation_name = (quote_ident(schema_name) || '.' || quote_ident(table_name))
    )
    -- create where clause with uid column
    -- not with primary keys, to manage multi-way sync
    , where_uid AS (
        SELECT '"' || puid_column || '" = ' || quote_literal(row_data->puid_column) AS where_clause
        FROM event
    )
    SELECT INTO sql
        CASE
            WHEN action = 'I' THEN
                'INSERT INTO "' || schema_name || '"."' || table_name || '"' ||
                ' (' || (
                    SELECT string_agg(
                        '"' || key || '"',
                        ','
                    )
                    FROM each(row_data)
                    WHERE True
                    AND key != ALL(pkey_fields)
                    AND key != ALL(excluded_columns)
                )
                || ') VALUES ( ' ||
                (
                    SELECT string_agg(
                        CASE WHEN value IS NULL THEN 'NULL' ELSE quote_literal(value) END,
                        ','
                    )
                    FROM EACH(row_data)
                    WHERE True
                    AND key != ALL(pkey_fields)
                    AND key != ALL(excluded_columns)
                )
                || ')'

            WHEN action = 'D' THEN
                'DELETE FROM "' || schema_name || '"."' || table_name || '"' ||
                ' WHERE ' || where_clause

            WHEN action = 'U' THEN
                'UPDATE "' || schema_name || '"."' || table_name || '"' ||
                ' SET ' || (
                    SELECT string_agg(
                        '"' || key || '"' || ' = ' ||
                        CASE
                            WHEN value IS NULL
                                THEN 'NULL'
                            ELSE quote_literal(value)
                        END,
                        ','
                    ) FROM each(changed_fields)
                    WHERE True
                    AND key != ALL(pkey_fields)
                    AND key != ALL(excluded_columns)
                ) ||
                ' WHERE ' || where_clause
        END
    FROM
        event, where_pks, where_uid
    ;
    RETURN sql;
END;
$$;


-- FUNCTION get_event_sql(pevent_id bigint, puid_column text, excluded_columns text[])
COMMENT ON FUNCTION lizsync.get_event_sql(pevent_id bigint, puid_column text, excluded_columns text[]) IS '
Get the SQL to use for replay from a audit log event

Arguments:
   pevent_id:  The event_id of the event in audit.logged_actions to replay
   puid_column: The name of the column with unique uuid values
';


-- import_central_server_schemas()
CREATE FUNCTION lizsync.import_central_server_schemas() RETURNS TABLE(imported_schemas text[])
    LANGUAGE plpgsql
    AS $$
DECLARE
    p_clone_id text;
    p_sync_schema text;
    sqltemplate text;
    rec record;
    p_imported_schemas text[];
BEGIN
    sqltemplate = '';
    p_imported_schemas = ARRAY[]::text[];

    -- Get clone id
    SELECT server_id::text INTO p_clone_id
    FROM lizsync.server_metadata
    LIMIT 1;

    -- Import foreign tables of given schema
    FOR rec IN
        SELECT jsonb_array_elements(sync_schemas)::text AS sync_schema
        FROM central_lizsync.synchronized_schemas
        WHERE server_id::text = p_clone_id
    LOOP
        p_sync_schema = replace(rec.sync_schema, '"', '');
        p_imported_schemas = p_imported_schemas || p_sync_schema;
        sqltemplate = concat(
            sqltemplate,
            'DROP SCHEMA IF EXISTS central_', p_sync_schema, ' CASCADE;',
            'CREATE SCHEMA central_', p_sync_schema, ';',
            'IMPORT FOREIGN SCHEMA ', p_sync_schema, '
            FROM SERVER central_server
            INTO central_', p_sync_schema, ';'
        );
    END LOOP;

    EXECUTE sqltemplate;

    RETURN QUERY
    SELECT p_imported_schemas;
END;
$$;


-- FUNCTION import_central_server_schemas()
COMMENT ON FUNCTION lizsync.import_central_server_schemas() IS 'Import synchronized schemas from the central database foreign server into central_XXX local schemas to the clone database. This allow to edit data of the central database from the clone.';


-- replay_central_logs_to_clone(bigint[], bigint, bigint, timestamp with time zone)
CREATE FUNCTION lizsync.replay_central_logs_to_clone(p_ids bigint[], p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone) RETURNS TABLE(replay_count integer)
    LANGUAGE plpgsql
    AS $$
DECLARE
    sqltemplate text;
    p_central_id text;
    p_clone_id text;
    p_sync_id uuid;
    rec record;
    p_counter integer;
BEGIN
    -- Return if no ids to replay
    IF array_length(p_ids, 1) = 0 THEN
        RETURN QUERY
        SELECT 0;
    END IF;

    -- Get central server id
    SELECT server_id::text INTO p_central_id
    FROM central_lizsync.server_metadata
    LIMIT 1;
    -- RAISE NOTICE 'Central server id = %', p_central_id;

    -- Get clone server id
    SELECT server_id::text INTO p_clone_id
    FROM lizsync.server_metadata
    LIMIT 1;
    -- RAISE NOTICE 'Clone server id = %', p_clone_id;

    -- Add item in CENTRAL history table
    INSERT INTO central_lizsync.history (
        sync_id, sync_time,
        server_from, server_to,
        min_event_id, max_event_id, max_action_tstamp_tx,
        sync_type, sync_status
    )
    VALUES (
        md5(random()::text || clock_timestamp()::text)::uuid, now(),
        p_central_id, ARRAY[p_clone_id],
        p_min_event_id, p_max_event_id, p_max_action_tstamp_tx,
        'partial', 'pending'
    )
    RETURNING sync_id
    INTO p_sync_id
    ;
    -- RAISE NOTICE 'SYNC ID = %', p_sync_id;

    -- Replay SQL queries in clone db
    -- We disable triggers to avoid adding more rows to the local audit logged_actions table
    sqltemplate = '';
    p_counter = 0;
    sqltemplate = concat(sqltemplate, ' SET session_replication_role = replica;');
    FOR rec IN
        SELECT event_id, action
        FROM temp_central_audit
        ORDER BY tid
    LOOP
        p_counter = p_counter + 1;
        -- RAISE NOTICE '%', rec.event_id;
        sqltemplate = concat(sqltemplate, rec.action || ';');
    END LOOP;
    sqltemplate = concat(sqltemplate, ' SET session_replication_role = DEFAULT;');
    -- RAISE NOTICE 'SQL TEMPLATE %', sqltemplate;
    -- RAISE NOTICE 'p_counter %', p_counter;

    --RAISE NOTICE '%', sqltemplate;
    IF p_counter > 0 THEN
        EXECUTE sqltemplate
        ;
    END IF;

    -- Update central audit logged actions
    -- To tell these actions have been replayed by this clone
    UPDATE central_audit.logged_actions
    SET sync_data = jsonb_set(
        sync_data,
        '{"replayed_by"}',
        sync_data->'replayed_by' || jsonb_build_object(p_clone_id, p_sync_id),
        true
    )
    WHERE event_id = ANY (p_ids)
    ;

    -- Modify central server synchronization item central->clone
    -- to mark it as 'done'
    UPDATE central_lizsync.history
    SET sync_status = 'done'
    WHERE True
    AND sync_id = p_sync_id
    ;

    -- Sync done !
    RETURN QUERY
    SELECT p_counter;
END;
$$;


-- FUNCTION replay_central_logs_to_clone(p_ids bigint[], p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone)
COMMENT ON FUNCTION lizsync.replay_central_logs_to_clone(p_ids bigint[], p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone) IS 'Replay the central logs in the clone database, then modifiy the corresponding audit logs in the central server to update the sync_data column. A new item is also created in the central server lizsync.history table. When running the log queries, we disable triggers in the clone to avoid adding more rows to the local audit logged_actions table';


-- replay_clone_logs_to_central()
CREATE FUNCTION lizsync.replay_clone_logs_to_central() RETURNS TABLE(replay_count integer)
    LANGUAGE plpgsql
    AS $_$
DECLARE
    sqltemplate text;
    sqlsession text;
    sqlupdatelogs text;
    p_central_id text;
    p_clone_id text;
    p_sync_id uuid;
    rec record;
    p_counter integer;
    dblink_connection_name text;
    dblink_msg text;
BEGIN
    -- Get the total number of logs to replay
    SELECT count(*) AS nb
    FROM temp_clone_audit
    INTO p_counter;
    -- RAISE NOTICE 'p_counter %', p_counter;

    -- If there are some logs, process them
    IF p_counter > 0 THEN

        -- Get central server id
        SELECT server_id::text INTO p_central_id
        FROM central_lizsync.server_metadata
        LIMIT 1;
        -- RAISE NOTICE 'central id %', p_central_id;

        -- Get clone server id
        SELECT server_id::text INTO p_clone_id
        FROM lizsync.server_metadata
        LIMIT 1;
        -- RAISE NOTICE 'clone id %', p_clone_id;

        -- Add a new item in the central history table
        INSERT INTO central_lizsync.history (
            sync_id, sync_time,
            server_from, server_to,
            min_event_id, max_event_id, max_action_tstamp_tx,
            sync_type, sync_status
        )
        VALUES (
            md5(random()::text || clock_timestamp()::text)::uuid, now(),
            p_clone_id, ARRAY[p_central_id],
            NULL, NULL, NULL,
            'partial', 'pending'
        )
        RETURNING sync_id
        INTO p_sync_id
        ;
        -- RAISE NOTICE 'sync id %', p_sync_id;

        -- Replay SQL queries in central db
        -- The session variables are used by the central server audit function
        -- to fill the sync_data field
        -- do not break line in sqlsession to avoid bugs
        sqlsession = format('SET SESSION "lizsync.server_from" = ''%1$s''; SET SESSION "lizsync.server_to" = ''%2$s''; SET SESSION "lizsync.sync_id" = ''%3$s'';',
            p_clone_id,
            p_central_id,
            p_sync_id
        );

        -- Store SQL query to update central logs afterward with original log timestamp
        sqlupdatelogs = '';

        -- Create dblink connection
        dblink_connection_name = (md5(((random())::text || (clock_timestamp())::text)))::text;
        -- RAISE NOTICE 'dblink_connection_name %', dblink_connection_name;
        SELECT dblink_connect(
            dblink_connection_name,
            'central_server'
        )
        INTO dblink_msg;

        -- Loop through logs and replay action
        -- We need to query one by one to be able
        -- to update the sync_data->action_tstamp_tx afterwards
        -- by searching action = sqltemplate
        FOR rec IN
            SELECT *
            FROM temp_clone_audit
            ORDER BY tid
        LOOP
            -- Run the query in the central database via dblink
            sqltemplate = sqlsession || trim(rec.action) || ';';
            SELECT dblink_exec(
                dblink_connection_name,
                sqltemplate
            )
            INTO dblink_msg;

            -- Concatenate action in sqlupdatelogs
            sqltemplate = trim(quote_literal(sqltemplate), '''');
            sqlupdatelogs = concat(
                sqlupdatelogs,
                format('
                    UPDATE audit.logged_actions
                    SET sync_data = sync_data || jsonb_build_object(
                        ''action_tstamp_tx'',
                        Cast(''%1$s'' AS TIMESTAMP WITH TIME ZONE)
                    )
                    WHERE True
                    AND sync_data->''replayed_by''->>''%2$s'' = ''%3$s''
                    AND client_query = ''%4$s''
                    AND action = ''%5$s''
                    AND concat(schema_name, ''.'', table_name) = ''%6$s''
                    ;',
                    rec.action_tstamp_tx,
                    p_central_id,
                    p_sync_id,
                    sqltemplate,
                    rec.action_type,
                    rec.ident
                )
            );

        END LOOP;

        -- Update central audit.logged_actions
        SELECT dblink_exec(
            dblink_connection_name,
            sqlupdatelogs
        )
        INTO dblink_msg;

        -- Disconnect dblink
        SELECT dblink_disconnect(dblink_connection_name)
        INTO dblink_msg;

        -- Update central history table item
        UPDATE central_lizsync.history
        SET sync_status = 'done'
        WHERE True
        AND sync_id = p_sync_id
        ;

    END IF;


    -- Remove logs from clone audit table
    TRUNCATE audit.logged_actions
    RESTART IDENTITY;

    -- Return
    RETURN QUERY
    SELECT p_counter;
END;
$_$;


-- FUNCTION replay_clone_logs_to_central()
COMMENT ON FUNCTION lizsync.replay_clone_logs_to_central() IS 'Replay all logs from the clone to the central database. It returns the number of actions replayed. After this, the clone audit logs are truncated.';


-- store_conflicts()
CREATE FUNCTION lizsync.store_conflicts() RETURNS TABLE(number_conflicts integer)
    LANGUAGE plpgsql
    AS $$
DECLARE
    sqltemplate text;
    dblink_connection_name text;
    dblink_msg text;
    p_clone_id text;
    p_number_conflicts integer;
BEGIN
    -- Count conflicts to store
    SELECT count(tid) FROM temp_conflicts
    INTO p_number_conflicts
    ;

    -- Get clone server id
    SELECT server_id::text INTO p_clone_id
    FROM lizsync.server_metadata
    LIMIT 1;

    -- Insert into foreign table central_lizsync.conflicts_bis
    -- To let the foreign server use default values
    -- for id and conflict time
    INSERT INTO central_lizsync.conflicts_bis
    ( "object_table", "object_uid",
    "clone_id",
    "central_event_id", "central_event_timestamp",
    "central_sql", "clone_sql",
    "rejected", "rule_applied"
    )
    SELECT
        c.object_table, c.object_uid,
        p_clone_id::uuid,
        c.central_event_id, c.central_event_timestamp,
        c.central_sql, c.clone_sql,
        c.rejected, c.rule_applied
    FROM temp_conflicts AS c
    ORDER BY tid
    ;

    -- Return
    RETURN QUERY
    SELECT p_number_conflicts;
END;
$$;


-- FUNCTION store_conflicts()
COMMENT ON FUNCTION lizsync.store_conflicts() IS 'Store resolved conflicts in the central database lizsync.conflicts table.';


-- synchronize()
CREATE FUNCTION lizsync.synchronize() RETURNS TABLE(number_replayed_to_central integer, number_replayed_to_clone integer, number_conflicts integer)
    LANGUAGE plpgsql
    AS $$
DECLARE
    sqltemplate text;
    p_clone_id text;
    temp_central_audit_table text;
    temp_clone_audit_table text;
    temp_conflicts_table text;
    p_ids bigint[];
    p_min_event_id bigint;
    p_max_event_id bigint;
    p_max_action_tstamp_tx timestamp with time zone;
    p_number_replayed_to_central integer;
    p_number_replayed_to_clone integer;
    p_number_conflicts integer;
    status_bool boolean;
    status_msg text;
    t timestamptz := clock_timestamp();
BEGIN

    temp_central_audit_table = 'temp_central_audit';
    temp_clone_audit_table = 'temp_clone_audit';
    temp_conflicts_table = 'temp_conflicts';

    -- Create temporary tables
    RAISE NOTICE 'Create temporary tables...';
    SELECT lizsync.create_temporary_table(temp_central_audit_table, 'audit')
    INTO status_bool;
    SELECT lizsync.create_temporary_table(temp_clone_audit_table, 'audit')
    INTO status_bool;
    SELECT lizsync.create_temporary_table(temp_conflicts_table, 'conflict')
    INTO status_bool;
    RAISE NOTICE 'Create temporary tables: %', clock_timestamp() - t;

    -- Get audit logs and store them in temporary tables
    -- central
    RAISE NOTICE 'Get modifications from central audit table...';
    EXECUTE '
    INSERT INTO ' || quote_ident(temp_central_audit_table) || '
    (
        event_id, action_tstamp_tx, action_tstamp_epoch,
        ident, action_type, origine, action, updated_field,
        uid, original_action_tstamp_tx
    )
    SELECT
        *
    FROM lizsync.get_central_audit_logs(''uid'', NULL)
    '
    ;
    RAISE NOTICE 'Get modifications from central audit table: %', clock_timestamp() - t;

    -- clone
    RAISE NOTICE 'Get modifications from clone audit table...';
    EXECUTE '
    INSERT INTO ' || quote_ident(temp_clone_audit_table) || '
    (
        event_id, action_tstamp_tx, action_tstamp_epoch,
        ident, action_type, origine, action, updated_field,
        uid, original_action_tstamp_tx
    )
    SELECT
        *,
        action_tstamp_epoch
    FROM lizsync.get_clone_audit_logs(''uid'', NULL)
    '
    ;
    RAISE NOTICE 'Get modifications from clone audit table: %', clock_timestamp() - t;

    -- Analyse logs
    -- find conflicts, useless logs, and remove them from temp tables
    RAISE NOTICE 'Analyse modifications and manage conflicts...';
    SELECT ids, min_event_id, max_event_id, max_action_tstamp_tx
    FROM lizsync.analyse_audit_logs()
    INTO p_ids, p_min_event_id, p_max_event_id, p_max_action_tstamp_tx
    ;
    RAISE NOTICE 'Analyse modifications and manage conflicts: %', clock_timestamp() - t;

    -- Replay logs
    -- central -> clone
    RAISE NOTICE 'Replay modification from central server to clone...';
    SELECT lizsync.replay_central_logs_to_clone(
        p_ids,
        p_min_event_id,
        p_max_event_id,
        p_max_action_tstamp_tx
    )
    INTO p_number_replayed_to_central
    ;
    RAISE NOTICE 'Replay modification from central server to clone: %', clock_timestamp() - t;

    -- clone -> central
    RAISE NOTICE 'Replay modification from clone to central server...';
    SELECT lizsync.replay_clone_logs_to_central()
    INTO p_number_replayed_to_clone
    ;
    RAISE NOTICE 'Replay modification from clone to central server: %', clock_timestamp() - t;

    -- Store conflicts
    RAISE NOTICE 'Store conflicts in the central server...';
    SELECT lizsync.store_conflicts()
    INTO p_number_conflicts;
    RAISE NOTICE 'Store conflicts in the central server: %', clock_timestamp() - t;

    -- Drop temporary tables
    RAISE NOTICE 'Drop temporary tables...';
    EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(temp_central_audit_table);
    EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(temp_clone_audit_table)  ;
    EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(temp_conflicts_table)    ;
    RAISE NOTICE 'Drop temporary tables: %', clock_timestamp() - t;

    -- Return
    RETURN QUERY
    SELECT
        p_number_replayed_to_central,
        p_number_replayed_to_clone,
        p_number_conflicts
    ;
END;
$$;


-- FUNCTION synchronize()
COMMENT ON FUNCTION lizsync.synchronize() IS 'Run the bi-directionnal database synchronization between the clone and the central server';


--
-- PostgreSQL database dump complete
--

