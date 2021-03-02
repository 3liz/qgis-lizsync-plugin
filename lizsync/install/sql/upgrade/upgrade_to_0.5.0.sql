BEGIN;

ALTER TABLE lizsync.synchronized_schemas RENAME TO synchronized_tables;
ALTER TABLE lizsync.synchronized_tables RENAME COLUMN sync_schemas TO sync_tables;
ALTER TABLE lizsync.synchronized_tables RENAME CONSTRAINT synchronized_schemas_pkey TO synchronized_tables_pkey;
COMMENT ON TABLE lizsync.synchronized_tables IS 'List of tables to synchronize per clone server id. This list works as a white list. Only listed tables will be synchronized for each server ids.';
COMMENT ON FUNCTION lizsync.get_central_audit_logs(p_uid_field text, p_excluded_columns text[]) IS 'Get all the logs from the central database: modifications do not come from the clone, have not yet been replayed by the clone, are dated after the last synchronization, have an event id higher than the last sync maximum event id, and concern the synchronized tables for this clone. Parameters: uid column name and excluded columns';

-- get_central_audit_logs(text, text[])
CREATE OR REPLACE FUNCTION lizsync.get_central_audit_logs(p_uid_field text, p_excluded_columns text[]) RETURNS TABLE(event_id bigint, action_tstamp_tx timestamp with time zone, action_tstamp_epoch integer, ident text, action_type text, origine text, action text, updated_field text, uid uuid, original_action_tstamp_tx integer)
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
                    THEN extract(epoch from Cast(a.sync_data->>''action_tstamp_tx'' AS TIMESTAMP WITH TIME ZONE))::integer
                ELSE extract(epoch from a.action_tstamp_tx)::integer
            END AS original_action_tstamp_tx
        FROM audit.logged_actions AS a
        -- Create as many lines as there are changed fields in UPDATE
        LEFT JOIN skeys(a.changed_fields) AS s ON TRUE,
        last_sync, tables

        WHERE True

        -- modifications do not come from clone database
        AND (a.sync_data->>''origin'' != ''%1$s'' OR a.sync_data->>''origin'' IS NULL)

        -- modifications have not yet been replayed in the clone database
        AND (NOT (a.sync_data->''replayed_by'' ? ''%1$s'') OR a.sync_data->''replayed_by'' = jsonb_build_object() )

        -- modifications after the last synchronization
        -- MAX_ACTION_TSTAMP_TX Par ex: 2019-04-20 12:00:00+02
        AND a.action_tstamp_tx > last_sync.max_action_tstamp_tx

        -- Event ID is bigger than last sync event id
        -- MAX_EVENT_ID
        AND a.event_id > last_sync.max_event_id

        -- only for tables synchronized by the clone server ID
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
        event_id bigint, action_tstamp_tx timestamp with time zone, action_tstamp_epoch integer,
        ident text, action_type text, origine text, action text, updated_field text,
        uid uuid, original_action_tstamp_tx integer
    )
    ;

END;
$_$;


-- FUNCTION get_central_audit_logs(p_uid_field text, p_excluded_columns text[])
COMMENT ON FUNCTION lizsync.get_central_audit_logs(p_uid_field text, p_excluded_columns text[]) IS 'Get all the logs from the central database: modifications do not come from the clone, have not yet been replayed by the clone, are dated after the last synchronization, have an event id higher than the last sync maximum event id, and concern the synchronized tables for this clone. Parameters: uid column name and excluded columns';

-- import_central_server_schemas()
CREATE OR REPLACE FUNCTION lizsync.import_central_server_schemas() RETURNS TABLE(imported_schemas text[])
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
COMMENT ON FUNCTION lizsync.import_central_server_schemas() IS 'Import synchronized schemas from the central database foreign server into central_XXX local schemas to the clone database. This allow to edit data of the central database from the clone.';

COMMIT;
