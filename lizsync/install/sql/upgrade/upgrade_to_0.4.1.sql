    BEGIN;

DROP FUNCTION IF EXISTS lizsync.get_event_sql(target text, pevent_id bigint, puid_column text, excluded_columns text);

CREATE OR REPLACE FUNCTION lizsync.get_event_sql(pevent_id bigint, puid_column text, excluded_columns text[]) RETURNS text
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


CREATE OR REPLACE FUNCTION lizsync.get_central_audit_logs(p_uid_field text, p_excluded_columns text[]) RETURNS TABLE(event_id bigint, action_tstamp_tx timestamp with time zone, action_tstamp_epoch integer, ident text, action_type text, origine text, action text, updated_field text, uid uuid, original_action_tstamp_tx integer)
    LANGUAGE plpgsql
    AS $$
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
$$;


-- FUNCTION get_central_audit_logs(p_uid_field text, p_excluded_columns text[])
COMMENT ON FUNCTION lizsync.get_central_audit_logs(p_uid_field text, p_excluded_columns text[]) IS 'Get all the logs from the central database: modifications do not come from the clone, have not yet been replayed by the clone, are dated after the last synchronization, have an event id higher than the last sync maximum event id, and concern the synchronized schemas for this clone. Parameters: uid column name and excluded columns';


CREATE OR REPLACE FUNCTION lizsync.get_clone_audit_logs(p_uid_field text, p_excluded_columns text[]) RETURNS TABLE(event_id bigint, action_tstamp_tx timestamp with time zone, action_tstamp_epoch integer, ident text, action_type text, origine text, action text, updated_field text, uid uuid)
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


COMMIT;
