--
-- PostgreSQL database dump
--

-- Dumped from database version 10.15 (Debian 10.15-1.pgdg100+1)
-- Dumped by pg_dump version 10.15 (Debian 10.15-1.pgdg100+1)

SET statement_timeout = 0;
SET lock_timeout = 0;

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

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
    central_count integer;
    p_ids bigint[];
    p_min_event_id bigint;
    p_max_event_id bigint;
    p_max_action_tstamp_tx timestamp with time zone;
    central_ids_to_keep integer[];
    clone_ids_to_keep integer[];
BEGIN

    -- Store all central ids before the analyse and removal of rejected logs
    -- Also store min and max event id
    -- Not needed if there is nothing in the central log
    -- If so, we return NULL to let the function replay_central_logs_to_clone return (do nothing)
    SELECT INTO central_count
    count(*) FROM temp_central_audit
    ;
    RAISE NOTICE 'Central modifications count since last sync: %', central_count;
    IF central_count > 0 THEN
        SELECT INTO p_ids, p_min_event_id, p_max_event_id, p_max_action_tstamp_tx
        array_agg(DISTINCT event_id), min(event_id), max(event_id), max(action_tstamp_tx)
        FROM temp_central_audit
        ;
    ELSE
        SELECT INTO p_ids, p_min_event_id, p_max_event_id, p_max_action_tstamp_tx
        NULL, NULL, NULL, NULL
        FROM temp_central_audit
        ;
    END IF;

    -- Get the list of ids to keep from each log
    -- We use DISTINCT ON to remove consecutive UPDATE on the same ident, uid and field for each source.
    -- Last is kept
    -- central
    IF central_count > 0 THEN
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
    END IF;

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
    IF central_count > 0 THEN
        DELETE FROM temp_central_audit
        WHERE tid != ALL (central_ids_to_keep)
        ;
    END IF;

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
            WHEN cl.original_action_tstamp_tx <= ce.original_action_tstamp_tx THEN 'clone'
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


-- audit_table(regclass)
CREATE FUNCTION lizsync.audit_table(target_table regclass) RETURNS void
    LANGUAGE sql
    AS $_$
SELECT lizsync.audit_table($1, BOOLEAN 't', BOOLEAN 't');
$_$;


-- FUNCTION audit_table(target_table regclass)
COMMENT ON FUNCTION lizsync.audit_table(target_table regclass) IS '
Add auditing support to the given table. Row-level changes will be logged with full client query text. No cols are ignored.
';


-- audit_table(regclass, boolean, boolean)
CREATE FUNCTION lizsync.audit_table(target_table regclass, audit_rows boolean, audit_query_text boolean) RETURNS void
    LANGUAGE sql
    AS $_$
SELECT lizsync.audit_table($1, $2, $3, ARRAY[]::text[]);
$_$;


-- audit_table(regclass, boolean, boolean, text[])
CREATE FUNCTION lizsync.audit_table(target_table regclass, audit_rows boolean, audit_query_text boolean, ignored_cols text[]) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
  stm_targets text = 'INSERT OR UPDATE OR DELETE OR TRUNCATE';
  _q_txt text;
  _ignored_cols_snip text = '';
BEGIN

    EXECUTE 'DROP TRIGGER IF EXISTS lizsync_audit_trigger_row ON ' || target_table::TEXT;
    EXECUTE 'DROP TRIGGER IF EXISTS lizsync_audit_trigger_stm ON ' || target_table::TEXT;


    IF audit_rows THEN
        IF array_length(ignored_cols,1) > 0 THEN
            _ignored_cols_snip = ', ' || quote_literal(ignored_cols);
        END IF;
        _q_txt = 'CREATE TRIGGER lizsync_audit_trigger_row AFTER INSERT OR UPDATE OR DELETE ON ' ||
                 target_table::TEXT ||

                 ' FOR EACH ROW EXECUTE PROCEDURE lizsync.if_modified_func(' ||
                 quote_literal(audit_query_text) || _ignored_cols_snip || ');';
        RAISE NOTICE '%',_q_txt;
        EXECUTE _q_txt;
        stm_targets = 'TRUNCATE';
    ELSE
    END IF;

    _q_txt = 'CREATE TRIGGER lizsync_audit_trigger_stm AFTER ' || stm_targets || ' ON ' ||
             target_table ||
             ' FOR EACH STATEMENT EXECUTE PROCEDURE lizsync.if_modified_func('||
             quote_literal(audit_query_text) || ');';
    RAISE NOTICE '%',_q_txt;
    EXECUTE _q_txt;

    -- store primary key names
    insert into lizsync.logged_relations (relation_name, uid_column)
         select target_table, a.attname
           from pg_index i
           join pg_attribute a on a.attrelid = i.indrelid
                              and a.attnum = any(i.indkey)
          where i.indrelid = target_table::regclass
            and i.indisprimary
    ON CONFLICT ON CONSTRAINT logged_relations_pkey
    DO NOTHING
            ;
END;
$$;


-- FUNCTION audit_table(target_table regclass, audit_rows boolean, audit_query_text boolean, ignored_cols text[])
COMMENT ON FUNCTION lizsync.audit_table(target_table regclass, audit_rows boolean, audit_query_text boolean, ignored_cols text[]) IS '
Add auditing support to a table.

Arguments:
   target_table:     Table name, schema qualified if not on search_path
   audit_rows:       Record each row change, or only audit at a statement level
   audit_query_text: Record the text of the client query that triggered the audit event?
   ignored_cols:     Columns to exclude from update diffs, ignore updates that change only ignored cols.
';


-- audit_view(regclass, text[])
CREATE FUNCTION lizsync.audit_view(target_view regclass, uid_cols text[]) RETURNS void
    LANGUAGE sql
    AS $_$
SELECT lizsync.audit_view($1, BOOLEAN 't', uid_cols);
$_$;


-- audit_view(regclass, boolean, text[])
CREATE FUNCTION lizsync.audit_view(target_view regclass, audit_query_text boolean, uid_cols text[]) RETURNS void
    LANGUAGE sql
    AS $_$
SELECT lizsync.audit_view($1, $2, ARRAY[]::text[], uid_cols);
$_$;


-- audit_view(regclass, boolean, text[], text[])
CREATE FUNCTION lizsync.audit_view(target_view regclass, audit_query_text boolean, ignored_cols text[], uid_cols text[]) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
  stm_targets text = 'INSERT OR UPDATE OR DELETE';
  _q_txt text;
  _ignored_cols_snip text = '';

BEGIN
    EXECUTE 'DROP TRIGGER IF EXISTS lizsync_audit_trigger_row ON ' || target_view::text;
    EXECUTE 'DROP TRIGGER IF EXISTS lizsync_audit_trigger_stm ON ' || target_view::text;

    IF array_length(ignored_cols,1) > 0 THEN
        _ignored_cols_snip = ', ' || quote_literal(ignored_cols);
    END IF;
    _q_txt = 'CREATE TRIGGER lizsync_audit_trigger_row INSTEAD OF INSERT OR UPDATE OR DELETE ON ' ||
         target_view::TEXT ||
         ' FOR EACH ROW EXECUTE PROCEDURE lizsync.if_modified_func(' ||
         quote_literal(audit_query_text) || _ignored_cols_snip || ');';
    RAISE NOTICE '%',_q_txt;
    EXECUTE _q_txt;

    -- store uid columns if not already present
  IF (select count(*) from lizsync.logged_relations where relation_name = (select target_view)::text AND  uid_column= (select unnest(uid_cols))::text) = 0 THEN
      insert into lizsync.logged_relations (relation_name, uid_column)
       select target_view, unnest(uid_cols);
  END IF;

END;
$$;


-- FUNCTION audit_view(target_view regclass, audit_query_text boolean, ignored_cols text[], uid_cols text[])
COMMENT ON FUNCTION lizsync.audit_view(target_view regclass, audit_query_text boolean, ignored_cols text[], uid_cols text[]) IS '
ADD auditing support TO a VIEW.

Arguments:
   target_view:      TABLE name, schema qualified IF NOT ON search_path
   audit_query_text: Record the text of the client query that triggered the audit event?
   ignored_cols:     COLUMNS TO exclude FROM UPDATE diffs, IGNORE updates that CHANGE only ignored cols.
   uid_cols:         COLUMNS to use to uniquely identify a row from the view (in order to replay UPDATE and DELETE)
';


-- compare_tables(text, text)
CREATE FUNCTION lizsync.compare_tables(p_schema_name text, p_table_name text) RETURNS TABLE(uid uuid, status text, clone_table_values public.hstore, central_table_values public.hstore)
    LANGUAGE plpgsql
    AS $_$
DECLARE
    pkeys text[];
    sqltemplate text;
BEGIN

    -- Get array of primary key field(s)
    SELECT array_agg(uid_column) as pkey_fields
    INTO pkeys
    FROM lizsync.logged_relations r
    WHERE relation_name = (quote_ident(p_schema_name) || '.' || quote_ident(p_table_name))
    ;

    -- Compare data
    sqltemplate = '
    SELECT
        coalesce(t1.uid, t2.uid) AS uid,
        CASE
            WHEN t1.uid IS NULL THEN ''not in table 1''
            WHEN t2.uid IS NULL THEN ''not in table 2''
            ELSE ''table 1 != table 2''
        END AS status,
        (hstore(t1.*) - ''%1$s''::text[]) - (hstore(t2) - ''%1$s''::text[]) AS values_in_table_1,
        (hstore(t2.*) - ''%1$s''::text[]) - (hstore(t1) - ''%1$s''::text[]) AS values_in_table_2
    FROM "%2$s"."%3$s" AS t1
    FULL JOIN "central_%2$s"."%3$s" AS t2
        ON t1.uid = t2.uid
    WHERE
        ((hstore(t1.*) - ''%1$s''::text[]) != (hstore(t2.*) - ''%1$s''::text[]))
        OR (t1.uid IS NULL)
        OR (t2.uid IS NULL)
    ';

    RETURN QUERY
    EXECUTE format(sqltemplate,
        pkeys,
        p_schema_name,
        p_table_name
    );

END;
$_$;


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
    CREATE SCHEMA IF NOT EXISTS central_lizsync;

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
COMMENT ON FUNCTION lizsync.create_central_server_fdw(p_central_host text, p_central_port smallint, p_central_database text, p_central_username text, p_central_password text) IS 'Create foreign server, needed central_lizsync schema, and import all central database tables as foreign tables. This will allow the clone to connect to the central databse';


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
            action_tstamp_epoch       numeric,
            ident                     text,
            action_type               text,
            origine                   text,
            action                    text,
            updated_field             text,
            uid                       uuid,
            original_action_tstamp_tx numeric
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
CREATE FUNCTION lizsync.get_central_audit_logs(p_uid_field text, p_excluded_columns text[]) RETURNS TABLE(event_id bigint, action_tstamp_tx timestamp with time zone, action_tstamp_epoch numeric, ident text, action_type text, origine text, action text, updated_field text, uid uuid, original_action_tstamp_tx numeric)
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
        tables AS (
            SELECT sync_tables
            FROM lizsync.synchronized_tables
            WHERE server_id = ''%1$s''::uuid
            LIMIT 1
        )
        SELECT
            a.event_id,
            a.action_tstamp_tx AS action_tstamp_tx,
            extract(epoch from a.action_tstamp_tx)::numeric AS action_tstamp_epoch,
            concat(a.schema_name, ''.'', a.table_name) AS ident,
            a.action AS action_type,
            CASE
                WHEN a.sync_data->>''origin'' IS NULL THEN ''central''
                ELSE ''clone''
            END AS origine,
            Coalesce(
                lizsync.get_event_sql(
                    a.event_id,
                    ''%2$s''::text,
                    array_cat(
                        string_to_array(''%3$s'',''@''),
                        array_remove(akeys(a.changed_fields), s)
                    )
                ),
                ''''
            ) AS action,
            s AS updated_field,
            (a.row_data->''%2$s'')::uuid AS uid,
            CASE
                WHEN a.sync_data->>''action_tstamp_tx'' IS NOT NULL
                AND a.sync_data->>''origin'' IS NOT NULL
                    THEN extract(epoch from Cast(a.sync_data->>''action_tstamp_tx'' AS TIMESTAMP WITH TIME ZONE))::numeric
                ELSE extract(epoch from a.action_tstamp_tx)::numeric
            END AS original_action_tstamp_tx
        FROM lizsync.logged_actions AS a
        -- Create as many lines as there are changed fields in UPDATE
        LEFT JOIN skeys(a.changed_fields) AS s ON TRUE,
        last_sync, tables

        WHERE True

        -- modifications do not come from clone database
        AND (a.sync_data->>''origin'' != ''%1$s'' OR a.sync_data->>''origin'' IS NULL)

        -- modifications have not yet been replayed in the clone database
        AND (NOT (a.sync_data->''replayed_by'' ? ''%1$s'') OR a.sync_data->''replayed_by'' = jsonb_build_object() )

        -- modifications after the last synchronisation
        -- MAX_ACTION_TSTAMP_TX Par ex: 2019-04-20 12:00:00+02
        AND a.action_tstamp_tx > last_sync.max_action_tstamp_tx

        -- Event ID is bigger than last sync event id
        -- MAX_EVENT_ID
        AND a.event_id > last_sync.max_event_id

        -- only for tables synchronised by the clone server ID
        AND sync_tables ? concat(''"'', a.schema_name, ''"."'', a.table_name, ''"'')

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
        event_id bigint, action_tstamp_tx timestamp with time zone, action_tstamp_epoch numeric,
        ident text, action_type text, origine text, action text, updated_field text,
        uid uuid, original_action_tstamp_tx numeric
    )
    ;

END;
$_$;


-- FUNCTION get_central_audit_logs(p_uid_field text, p_excluded_columns text[])
COMMENT ON FUNCTION lizsync.get_central_audit_logs(p_uid_field text, p_excluded_columns text[]) IS 'Get all the logs from the central database: modifications do not come from the clone, have not yet been replayed by the clone, are dated after the last synchronisation, have an event id higher than the last sync maximum event id, and concern the synchronised tables for this clone. Parameters: uid column name and excluded columns';


-- get_clone_audit_logs(text, text[])
CREATE FUNCTION lizsync.get_clone_audit_logs(p_uid_field text, p_excluded_columns text[]) RETURNS TABLE(event_id bigint, action_tstamp_tx timestamp with time zone, action_tstamp_epoch numeric, ident text, action_type text, origine text, action text, updated_field text, uid uuid)
    LANGUAGE plpgsql
    AS $$
DECLARE
    sqltemplate text;
BEGIN
    RETURN QUERY
    SELECT
        a.event_id,
        a.action_tstamp_tx AS action_tstamp_tx,
        extract(epoch from a.action_tstamp_tx)::numeric AS action_tstamp_epoch,
        concat(a.schema_name, '.', a.table_name) AS ident,
        a.action AS action_type,
        'clone'::text AS origine,
        Coalesce(
            lizsync.get_event_sql(
                a.event_id,
                p_uid_field::text,
                array_cat(
                    p_excluded_columns,
                    array_remove(akeys(a.changed_fields), s)
                )
            ),
            ''
        ) AS action,
        s AS updated_field,
        (a.row_data->p_uid_field)::uuid AS uid
    FROM lizsync.logged_actions AS a
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
        SELECT * FROM lizsync.logged_actions WHERE event_id = pevent_id
    )
    -- get primary key names
    , where_pks AS (
        SELECT array_agg(uid_column) as pkey_fields
        FROM lizsync.logged_relations r
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
   pevent_id:  The event_id of the event in lizsync.logged_actions to replay
   puid_column: The name of the column with unique uuid values
';


-- if_modified_func()
CREATE FUNCTION lizsync.if_modified_func() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
    audit_row lizsync.logged_actions;
    include_values boolean;
    log_diffs boolean;
    h_old hstore;
    h_new hstore;
    excluded_cols text[] = ARRAY[]::text[];
BEGIN
    --RAISE WARNING '[lizsync.if_modified_func] start with TG_ARGV[0]: % ; TG_ARGV[1] : %, TG_OP: %, TG_LEVEL : %, TG_WHEN: % ', TG_ARGV[0], TG_ARGV[1], TG_OP, TG_LEVEL, TG_WHEN;

    IF NOT (TG_WHEN IN ('AFTER' , 'INSTEAD OF')) THEN
        RAISE EXCEPTION 'lizsync.if_modified_func() may only run as an AFTER trigger';
    END IF;

    audit_row = ROW(
        nextval('lizsync.logged_actions_event_id_seq'), -- event_id
        TG_TABLE_SCHEMA::text,                        -- schema_name
        TG_TABLE_NAME::text,                          -- table_name
        TG_RELID,                                     -- relation OID for much quicker searches
        session_user::text,                           -- session_user_name
        current_timestamp,                            -- action_tstamp_tx
        statement_timestamp(),                        -- action_tstamp_stm
        clock_timestamp(),                            -- action_tstamp_clk
        txid_current(),                               -- transaction ID
        (SELECT setting FROM pg_settings WHERE name = 'application_name'),
        inet_client_addr(),                           -- client_addr
        inet_client_port(),                           -- client_port
        current_query(),                              -- top-level query or queries (if multistatement) from client
        substring(TG_OP,1,1),                         -- action
        NULL, NULL,                                   -- row_data, changed_fields
        'f',                                          -- statement_only
        jsonb_build_object(
            'origin', current_setting('lizsync.server_from', true),
            'replayed_by',
            CASE
                WHEN current_setting('lizsync.server_to', true) IS NOT NULL
                AND current_setting('lizsync.sync_id', true) IS NOT NULL
                    THEN jsonb_build_object(
                        current_setting('lizsync.server_to', true),
                        current_setting('lizsync.sync_id', true)
                    )
                ELSE jsonb_build_object()
            END

        )
    );

    IF NOT TG_ARGV[0]::boolean IS DISTINCT FROM 'f'::boolean THEN
        audit_row.client_query = NULL;
        RAISE WARNING '[lizsync.if_modified_func] - Trigger func triggered with no client_query tracking';

    END IF;

    IF TG_ARGV[1] IS NOT NULL THEN
        excluded_cols = TG_ARGV[1]::text[];
        RAISE WARNING '[lizsync.if_modified_func] - Trigger func triggered with excluded_cols: %',TG_ARGV[1];
    END IF;

    IF (TG_OP = 'UPDATE' AND TG_LEVEL = 'ROW') THEN
        h_old = hstore(OLD.*) - excluded_cols;
        audit_row.row_data = h_old;
        h_new = hstore(NEW.*)- excluded_cols;
        audit_row.changed_fields =  h_new - h_old;

        IF audit_row.changed_fields = hstore('') THEN
            -- All changed fields are ignored. Skip this update.
            RAISE WARNING '[lizsync.if_modified_func] - Trigger detected NULL hstore. ending';
            RETURN NULL;
        END IF;
  INSERT INTO lizsync.logged_actions VALUES (audit_row.*);
  RETURN NEW;

    ELSIF (TG_OP = 'DELETE' AND TG_LEVEL = 'ROW') THEN
        audit_row.row_data = hstore(OLD.*) - excluded_cols;
  INSERT INTO lizsync.logged_actions VALUES (audit_row.*);
        RETURN OLD;

    ELSIF (TG_OP = 'INSERT' AND TG_LEVEL = 'ROW') THEN
        audit_row.row_data = hstore(NEW.*) - excluded_cols;
  INSERT INTO lizsync.logged_actions VALUES (audit_row.*);
        RETURN NEW;

    ELSIF (TG_LEVEL = 'STATEMENT' AND TG_OP IN ('INSERT','UPDATE','DELETE','TRUNCATE')) THEN
        audit_row.statement_only = 't';
        INSERT INTO lizsync.logged_actions VALUES (audit_row.*);
  RETURN NULL;

    ELSE
        RAISE EXCEPTION '[lizsync.if_modified_func] - Trigger func added as trigger for unhandled case: %, %',TG_OP, TG_LEVEL;
        RETURN NEW;
    END IF;


END;
$$;


-- FUNCTION if_modified_func()
COMMENT ON FUNCTION lizsync.if_modified_func() IS '
Track changes to a table at the statement and/or row level.

Optional parameters to trigger in CREATE TRIGGER call:

param 0: boolean, whether to log the query text. Default ''t''.

param 1: text[], columns to ignore in updates. Default [].

         Updates to ignored cols are omitted from changed_fields.

         Updates with only ignored cols changed are not inserted
         into the audit log.

         Almost all the processing work is still done for updates
         that ignored. If you need to save the load, you need to use
         WHEN clause on the trigger instead.

         No warning or error is issued if ignored_cols contains columns
         that do not exist in the target table. This lets you specify
         a standard set of ignored columns.

There is no parameter to disable logging of values. Add this trigger as
a ''FOR EACH STATEMENT'' rather than ''FOR EACH ROW'' trigger if you do not
want to log row values.

Note that the user name logged is the login role for the session. The audit trigger
cannot obtain the active role because it is reset by the SECURITY DEFINER invocation
of the audit trigger its self.
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
    -- We must first get the unique schemas
    FOR rec IN
        WITH
        synchronized_tables AS (
            SELECT sync_tables
            FROM central_lizsync.synchronized_tables
            WHERE server_id::text = p_clone_id
        ),
        a AS (
            SELECT DISTINCT jsonb_array_elements_text(sync_tables) AS sync_table
            FROM synchronized_tables
        ),
        b AS (
            SELECT regexp_split_to_array(sync_table, E'\\.') AS sync_table_elements
            FROM a
        )
        SELECT sync_table_elements[1] AS t_schema, string_agg(sync_table_elements[2], ',') AS t_tables
        FROM b
        GROUP BY t_schema
    LOOP
        p_sync_schema = trim(replace(rec.t_schema, '"', ''));
        p_imported_schemas = p_imported_schemas || p_sync_schema;
        sqltemplate = concat(
            sqltemplate,
            'DROP SCHEMA IF EXISTS "central_', p_sync_schema, '" CASCADE;',
            'CREATE SCHEMA "central_', p_sync_schema, '";',
            'IMPORT FOREIGN SCHEMA "', p_sync_schema, '"
            LIMIT TO (', rec.t_tables ,')
            FROM SERVER central_server
            INTO "central_', p_sync_schema, '";'
        );
    END LOOP;

    EXECUTE sqltemplate;

    RETURN QUERY
    SELECT p_imported_schemas;
END;
$$;


-- FUNCTION import_central_server_schemas()
COMMENT ON FUNCTION lizsync.import_central_server_schemas() IS 'Import synchronised schemas from the central database foreign server into central_XXX local schemas to the clone database. This allow to edit data of the central database from the clone.';


-- insert_history_item(text, text, bigint, bigint, timestamp with time zone, text, text)
CREATE FUNCTION lizsync.insert_history_item(p_server_from text, p_server_to text, p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone, p_sync_type text, p_sync_status text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE p_sync_id uuid;
BEGIN

    INSERT INTO lizsync.history (
        sync_id, sync_time,
        server_from, server_to,
        min_event_id, max_event_id, max_action_tstamp_tx,
        sync_type, sync_status
    )
    VALUES (
        md5(random()::text || clock_timestamp()::text)::uuid, now(),
        p_server_from,
        CASE WHEN p_server_to IS NOT NULL THEN ARRAY[p_server_to] ELSE NULL END,
        p_min_event_id, p_max_event_id, p_max_action_tstamp_tx,
        p_sync_type, p_sync_status
    )
    RETURNING sync_id
    INTO p_sync_id
    ;

    RETURN p_sync_id;
END;
$$;


-- FUNCTION insert_history_item(p_server_from text, p_server_to text, p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone, p_sync_type text, p_sync_status text)
COMMENT ON FUNCTION lizsync.insert_history_item(p_server_from text, p_server_to text, p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone, p_sync_type text, p_sync_status text) IS 'Add a new history item in the lizsync.history table as the owner of the table. The SECURITY DEFINER allows the clone to update the protected table. DO NOT USE MANUALLY.';


-- replay_central_logs_to_clone(bigint[], bigint, bigint, timestamp with time zone)
CREATE FUNCTION lizsync.replay_central_logs_to_clone(p_ids bigint[], p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone) RETURNS TABLE(replay_count integer)
    LANGUAGE plpgsql
    AS $_$
DECLARE
    sqltemplate text;
    p_central_id text;
    p_clone_id text;
    p_sync_id uuid;
    rec record;
    p_counter integer;
    dblink_connection_name text;
    dblink_msg text;
BEGIN
    -- Do the replay ONLY if there are ids to replay
    -- We do NOT want to insert a new lizsync.history item if p_ids IS NULL
    -- This means there were no changes in the central since last sync
    -- the next sync will still use the last central->clone sync history item data
    RAISE NOTICE 'Check if there are some central logs since last sync: %', p_ids;
    IF p_ids IS NOT NULL THEN

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

        -- Create dblink connection
        dblink_connection_name = (md5(((random())::text || (clock_timestamp())::text)))::text;
        -- RAISE NOTICE 'dblink_connection_name %', dblink_connection_name;
        SELECT dblink_connect(
            dblink_connection_name,
            'central_server'
        )
        INTO dblink_msg;

        -- Add item in CENTRAL history table
        sqltemplate = format(
            'SELECT lizsync.insert_history_item(
                ''%1$s''::text, ''%2$s''::text,
                %3$s, %4$s, Cast(''%5$s'' AS TIMESTAMP WITH TIME ZONE),
                ''partial'', ''pending''
            ) AS sync_id
            ',
            p_central_id, p_clone_id,
            p_min_event_id, p_max_event_id, p_max_action_tstamp_tx
        );
        SELECT sync_id FROM dblink(
            dblink_connection_name,
            sqltemplate
        ) AS foo(sync_id uuid)
        INTO p_sync_id;
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
        -- run this function with dblink as it must be done by the central server with security definer
        -- it allows the clone to write data back to the protected table logged_actions
        sqltemplate = concat(
            'SELECT lizsync.update_central_logs_add_clone_id(',
            quote_literal(p_clone_id),
            ', ',
            quote_literal(p_sync_id), '::uuid',
            ', ',
            '(', quote_literal(p_ids::text), ')::integer[]',
            ')'
        );
        RAISE NOTICE 'UPDATE CLONE ID = %', sqltemplate;

        -- Update central lizsync.logged_actions
        -- we need to use dblink and not dblink_exec
        -- else error "statement returning results not allowed"
        PERFORM * FROM dblink(
            dblink_connection_name,
            sqltemplate
        ) AS foo(update_status boolean)
        ;

        -- Modify central server synchronisation item central->clone
        -- to mark it as 'done'
        sqltemplate = format(
            'SELECT lizsync.update_history_item(''%1$s''::uuid, ''done'', NULL)',
            p_sync_id
        )
        ;

        PERFORM * FROM dblink(
            dblink_connection_name,
            sqltemplate
        ) AS foo(update_status boolean)
        ;

        -- Disconnect dblink
        SELECT dblink_disconnect(dblink_connection_name)
        INTO dblink_msg;

    ELSE
        p_counter = 0;
        RAISE NOTICE 'No central logs since last sync';
    END IF;



    -- Sync done !
    RETURN QUERY
    SELECT p_counter;
END;
$_$;


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
    p_temporary_table text;
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

        -- Create dblink connection
        dblink_connection_name = (md5(((random())::text || (clock_timestamp())::text)))::text;
        -- RAISE NOTICE 'dblink_connection_name %', dblink_connection_name;
        SELECT dblink_connect(
            dblink_connection_name,
            'central_server'
        )
        INTO dblink_msg;

        -- Add a new item in the central history table
        -- p_server_from = clone
        -- p_server_to = central
        sqltemplate = format(
            'SELECT lizsync.insert_history_item(
                ''%1$s''::text, ''%2$s''::text,
                NULL, NULL, NULL,
                ''partial'', ''pending''
            ) AS sync_id
            ',
            p_clone_id,
            p_central_id
        );
        SELECT sync_id FROM dblink(
            dblink_connection_name,
            sqltemplate
        ) AS foo(sync_id uuid)
        INTO p_sync_id;
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
        p_temporary_table = 'temp_' || md5(random()::text || clock_timestamp()::text);

        sqlupdatelogs = '
            CREATE TEMPORARY TABLE ' || p_temporary_table || ' (
                action_tstamp_tx TIMESTAMP WITH TIME ZONE,
                sync_id uuid,
                client_query_hash text,
                action_type text,
                ident text
            ) ON COMMIT DROP;
        ';

        -- Loop through logs and replay action
        -- We need to query one by one to be able
        -- to update the sync_data->action_tstamp_tx afterwards
        -- by searching in the central lizsync.logged_actions the action = sqltemplate
        -- for this sync_id
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
            -- We need it to add the clone actions timestamp in the central log table
            -- since we find the central logs rows to update with a WHERE including action SQL ie sqltemplate
            -- we use a hash on sqltemplate to avoid too big SQL
            sqltemplate = trim(quote_literal(sqltemplate), '''');
            sqlupdatelogs = concat(
                sqlupdatelogs,
                format('
                    INSERT INTO ' || p_temporary_table || '
                    (action_tstamp_tx, sync_id, client_query_hash, action_type, ident)
                    VALUES (
                        Cast(''%1$s'' AS TIMESTAMP WITH TIME ZONE),
                        ''%2$s''::uuid,
                        ''%3$s'',
                        ''%4$s'',
                        ''%5$s''
                    );
                    ',
                    rec.action_tstamp_tx,
                    p_sync_id,
                    md5(sqltemplate)::text,
                    rec.action_type,
                    rec.ident
                )
            );

        END LOOP;

        -- Add the necessary call the to security definer function
        -- making possible from the clone to update the central lizsync.logged_actions
        -- with the key action_tstamp_tx
        sqlupdatelogs = concat(
            sqlupdatelogs,
            'SELECT lizsync.update_central_logs_add_clone_action_timestamps(' || quote_literal(p_temporary_table) || ');'
        );

        -- Update central lizsync.logged_actions
        PERFORM * FROM dblink(
            dblink_connection_name,
            sqlupdatelogs
        ) AS foo(update_status boolean)
        ;

        -- Update central history table item
        sqltemplate = format(
            'SELECT lizsync.update_history_item(''%1$s''::uuid, ''done'', NULL)',
            p_sync_id
        )
        ;

        PERFORM * FROM dblink(
            dblink_connection_name,
            sqltemplate
        ) AS foo(update_status boolean)
        ;

        -- Disconnect dblink
        SELECT dblink_disconnect(dblink_connection_name)
        INTO dblink_msg;

    END IF;


    -- Remove logs from clone audit table
    TRUNCATE lizsync.logged_actions
    RESTART IDENTITY;

    -- Return
    RETURN QUERY
    SELECT p_counter;
END;
$_$;


-- FUNCTION replay_clone_logs_to_central()
COMMENT ON FUNCTION lizsync.replay_clone_logs_to_central() IS 'Replay all logs from the clone to the central database. It returns the number of actions replayed. After this, the clone audit logs are truncated.';


-- replay_event(integer)
CREATE FUNCTION lizsync.replay_event(pevent_id integer) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
  query text;
BEGIN
    with
    event as (
        select * from lizsync.logged_actions where event_id = pevent_id
    )
    -- get primary key names
    , where_pks as (
        select array_to_string(array_agg(uid_column || '=' || quote_literal(row_data->uid_column)), ' AND ') as where_clause
          from lizsync.logged_relations r
          join event on relation_name = (schema_name || '.' || table_name)
    )
    select into query
        case
            when action = 'I' then
                'INSERT INTO ' || schema_name || '.' || table_name ||
                ' ('||(select string_agg(key, ',') from each(row_data))||') VALUES ' ||
                '('||(select string_agg(case when value is null then 'null' else quote_literal(value) end, ',') from each(row_data))||')'
            when action = 'D' then
                'DELETE FROM ' || schema_name || '.' || table_name ||
                ' WHERE ' || where_clause
            when action = 'U' then
                'UPDATE ' || schema_name || '.' || table_name ||
                ' SET ' || (select string_agg(key || '=' || case when value is null then 'null' else quote_literal(value) end, ',') from each(changed_fields)) ||
                ' WHERE ' || where_clause
        end
    from
        event, where_pks
    ;

    execute query;
END;
$$;


-- FUNCTION replay_event(pevent_id integer)
COMMENT ON FUNCTION lizsync.replay_event(pevent_id integer) IS '
Replay a logged event.

Arguments:
   pevent_id:  The event_id of the event in lizsync.logged_actions to replay
';


-- rollback_event(bigint)
CREATE FUNCTION lizsync.rollback_event(pevent_id bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    event record;
    pkeys record;
    last_event record;
    query text;
BEGIN
    -- Get event
    SELECT * INTO event FROM lizsync.logged_actions WHERE event_id = pevent_id;
    -- RAISE NOTICE 'event id = %', event.event_id;

    -- Get the WHERE clause to filter the events feature
    SELECT INTO pkeys
        array_to_string(array_agg(uid_column || '=' || quote_literal(event.row_data->uid_column)), ' AND ') AS where_clause,
        hstore(array_agg(uid_column), array_agg( event.row_data->uid_column)) AS hstore_keys
    FROM lizsync.logged_relations r
    WHERE relation_name = (event.schema_name || '.' || event.table_name)
    ;
    -- RAISE NOTICE 'hstore_keys = %', pkeys.hstore_keys;

    -- Check if this is the last event for the feature. If not cancel the rollback
    SELECT INTO last_event
        (pevent_id = la.event_id) AS is_last,
        la.event_id
    FROM lizsync.logged_actions AS la
    WHERE true
    AND la.schema_name = event.schema_name
    AND la.table_name = event.table_name
    AND la.row_data @> pkeys.hstore_keys
    ORDER BY la.action_tstamp_tx DESC
    LIMIT 1
    ;
    IF NOT last_event.is_last THEN
        RAISE EXCEPTION '[lizsync.rollback_event] - Cannot rollback this event (id = %) because a more recent event (id = %) exists for this feature', pevent_id, last_event.event_id;
        RETURN;
    END IF;


    -- Then apply the rollback
    SELECT INTO query
        CASE
            WHEN action = 'I' THEN
                'DELETE FROM ' || schema_name || '.' || table_name ||
                ' WHERE ' || pkeys.where_clause
            WHEN action = 'D' THEN
                'INSERT INTO ' || schema_name || '.' || table_name ||
                ' ('||(SELECT string_agg(key, ',') FROM each(row_data))||') VALUES ' ||
                '('||(SELECT string_agg(CASE WHEN value IS NULL THEN 'null' ELSE quote_literal(value) END, ',') FROM each(row_data))||')'
            WHEN action = 'U' THEN
                'UPDATE ' || schema_name || '.' || table_name ||
                ' SET ' || (
                    SELECT string_agg(
                        key || '=' || CASE WHEN value IS NULL THEN 'null' ELSE quote_literal(value) END
                        , ','
                    ) FROM each(row_data) WHERE key = ANY (akeys(changed_fields)) ) ||
                ' WHERE ' || pkeys.where_clause

        END
    FROM
        lizsync.logged_actions
    WHERE event_id = pevent_id
    ;

    execute query;
END;
$$;


-- FUNCTION rollback_event(pevent_id bigint)
COMMENT ON FUNCTION lizsync.rollback_event(pevent_id bigint) IS '
Rollback a logged event and returns to previous row data

Arguments:
   pevent_id:  The event_id of the event in lizsync.logged_actions to rollback
';


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
    -- RAISE NOTICE 'Create temporary tables: %', clock_timestamp() - t;

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
    -- RAISE NOTICE 'Get modifications from central audit table: %', clock_timestamp() - t;

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
    -- RAISE NOTICE 'Get modifications from clone audit table: %', clock_timestamp() - t;

    -- Analyse logs
    -- find conflicts, useless logs, and remove them from temp tables
    RAISE NOTICE 'Analyse modifications and manage conflicts...';
    SELECT ids, min_event_id, max_event_id, max_action_tstamp_tx
    FROM lizsync.analyse_audit_logs()
    INTO p_ids, p_min_event_id, p_max_event_id, p_max_action_tstamp_tx
    ;
    -- RAISE NOTICE 'Analyse modifications and manage conflicts: %', clock_timestamp() - t;

    -- Replay logs
    -- central -> clone
    RAISE NOTICE 'Replay modification from central server to clone...';
    SELECT lizsync.replay_central_logs_to_clone(
        p_ids,
        p_min_event_id,
        p_max_event_id,
        p_max_action_tstamp_tx
    )
    INTO p_number_replayed_to_clone
    ;
    -- RAISE NOTICE 'Replay modification from central server to clone: %', clock_timestamp() - t;

    -- clone -> central
    RAISE NOTICE 'Replay modification from clone to central server...';
    SELECT lizsync.replay_clone_logs_to_central()
    INTO p_number_replayed_to_central
    ;
    -- RAISE NOTICE 'Replay modification from clone to central server: %', clock_timestamp() - t;

    -- Store conflicts
    -- RAISE NOTICE 'Store conflicts in the central server...';
    SELECT lizsync.store_conflicts()
    INTO p_number_conflicts;
    -- RAISE NOTICE 'Store conflicts in the central server: %', clock_timestamp() - t;

    -- Drop temporary tables
    RAISE NOTICE 'Drop temporary tables...';
    EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(temp_central_audit_table);
    EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(temp_clone_audit_table)  ;
    EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(temp_conflicts_table)    ;
    -- RAISE NOTICE 'Drop temporary tables: %', clock_timestamp() - t;

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


-- update_central_logs_add_clone_action_timestamps(text)
CREATE FUNCTION lizsync.update_central_logs_add_clone_action_timestamps(temporary_table_name text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
    sqltemplate text;
    p_central_id text;
BEGIN
    -- Get central server id
    SELECT server_id::text INTO p_central_id
    FROM lizsync.server_metadata
    LIMIT 1;

    -- Use the data stored in the temporary table given to update the lizsync.logged_actions
    sqltemplate = '
    UPDATE lizsync.logged_actions
    SET sync_data = sync_data || jsonb_build_object(
        ''action_tstamp_tx'',
        Cast(t.action_tstamp_tx AS TIMESTAMP WITH TIME ZONE)
    )
    FROM ' || quote_ident(temporary_table_name) || ' AS t
    WHERE True
    -- same synchronisation id
    AND sync_data->''replayed_by''->>' || quote_literal(p_central_id) || ' = t.sync_id::text
    -- same query (we compare hash)
    AND md5(client_query)::text = t.client_query_hash
    -- same action type
    AND action = t.action_type
    -- same table
    AND concat(schema_name, ''.'', table_name) = t.ident
    ';
    EXECUTE sqltemplate;

    -- Return
    RETURN True;
END;
$$;


-- FUNCTION update_central_logs_add_clone_action_timestamps(temporary_table_name text)
COMMENT ON FUNCTION lizsync.update_central_logs_add_clone_action_timestamps(temporary_table_name text) IS 'Update all logs created by the central database after the clone has replayed its local logs in the central database. It is necessary to update the action_tstamp_tx key of lizsync.logged_actions sync_data column. The SECURITY DEFINER allows the clone to update the protected lizsync.logged_actions table. DO NOT USE MANUALLY.';


-- update_central_logs_add_clone_id(text, uuid, bigint[])
CREATE FUNCTION lizsync.update_central_logs_add_clone_id(p_clone_id text, p_sync_id uuid, p_ids bigint[]) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
BEGIN

    -- We must update the central logged_actions with the clone id
    -- this allows to know which clone has replayed wich log
    UPDATE lizsync.logged_actions
    SET sync_data = jsonb_set(
        sync_data,
        '{"replayed_by"}',
        sync_data->'replayed_by' || jsonb_build_object(p_clone_id, p_sync_id),
        true
    )
    WHERE event_id = ANY (p_ids)
    ;

    -- Sync done !
    RETURN True;
END;
$$;


-- FUNCTION update_central_logs_add_clone_id(p_clone_id text, p_sync_id uuid, p_ids bigint[])
COMMENT ON FUNCTION lizsync.update_central_logs_add_clone_id(p_clone_id text, p_sync_id uuid, p_ids bigint[]) IS 'Update the central database synchronisation logs (table lizsync.logged_actions) by adding the clone ID in the "replayed_by" property of the field "sync_data". The SECURITY DEFINER allows the clone to update the protected lizsync.logged_actions table. DO NOT USE MANUALLY.';


-- update_history_item(uuid, text, text)
CREATE FUNCTION lizsync.update_history_item(p_sync_id uuid, p_status text, p_server_to text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
BEGIN

    UPDATE lizsync.history
    SET (
        sync_status,
        server_to
    ) = (
        CASE WHEN p_status IS NOT NULL THEN p_status ELSE sync_status END,
        CASE
            WHEN p_server_to IS NOT NULL THEN
                CASE
                    WHEN server_to IS NOT NULL THEN array_append(server_to, p_server_to)
                    ELSE ARRAY[p_server_to]::text[]
                END
            ELSE server_to
        END
    )
    WHERE True
    AND sync_id = p_sync_id
    ;

    RETURN True;
END;
$$;


-- FUNCTION update_history_item(p_sync_id uuid, p_status text, p_server_to text)
COMMENT ON FUNCTION lizsync.update_history_item(p_sync_id uuid, p_status text, p_server_to text) IS 'Update the status of a history item in the lizsync.history table as the owner of the table. The SECURITY DEFINER allows the clone to update the protected table. DO NOT USE MANUALLY.';


-- update_synchronized_table(uuid, text[])
CREATE FUNCTION lizsync.update_synchronized_table(p_server_id uuid, p_tables text[]) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
BEGIN

    INSERT INTO lizsync.synchronized_tables AS s
    (server_id, sync_tables)
    VALUES
    ( p_server_id, (array_to_json(p_tables))::jsonb )
    ON CONFLICT ON CONSTRAINT synchronized_tables_pkey
    DO UPDATE
    SET sync_tables = EXCLUDED.sync_tables || s.sync_tables
    ;

    RETURN True;
END;
$$;


-- FUNCTION update_synchronized_table(p_server_id uuid, p_tables text[])
COMMENT ON FUNCTION lizsync.update_synchronized_table(p_server_id uuid, p_tables text[]) IS 'Insert or Update the table lizsync.synchronized_tables. The SECURITY DEFINER allows the clone to update the protected table. DO NOT USE MANUALLY.';


--
-- PostgreSQL database dump complete
--

