BEGIN;

-- analyse_audit_logs()
CREATE OR REPLACE FUNCTION lizsync.analyse_audit_logs() RETURNS TABLE(ids bigint[], min_event_id bigint, max_event_id bigint, max_action_tstamp_tx timestamp with time zone)
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


-- create_temporary_table(text, text)
CREATE OR REPLACE FUNCTION lizsync.create_temporary_table(temporary_table text, table_type text) RETURNS boolean
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
DROP FUNCTION IF EXISTS lizsync.get_central_audit_logs(text, text[]);
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
DROP FUNCTION IF EXISTS lizsync.get_clone_audit_logs(text, text[]);
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

-- synchronize()
CREATE OR REPLACE FUNCTION lizsync.synchronize() RETURNS TABLE(number_replayed_to_central integer, number_replayed_to_clone integer, number_conflicts integer)
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

COMMIT;
