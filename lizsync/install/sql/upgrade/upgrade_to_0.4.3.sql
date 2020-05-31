BEGIN;

-- replay_central_logs_to_clone(bigint[], bigint, bigint, timestamp with time zone)
CREATE OR REPLACE FUNCTION lizsync.replay_central_logs_to_clone(p_ids bigint[], p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone) RETURNS TABLE(replay_count integer)
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

    ELSE
        p_counter = 0;
        RAISE NOTICE 'No central logs since last sync';
    END IF;



    -- Sync done !
    RETURN QUERY
    SELECT p_counter;
END;
$$;


-- FUNCTION replay_central_logs_to_clone(p_ids bigint[], p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone)
COMMENT ON FUNCTION lizsync.replay_central_logs_to_clone(p_ids bigint[], p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone) IS 'Replay the central logs in the clone database, then modifiy the corresponding audit logs in the central server to update the sync_data column. A new item is also created in the central server lizsync.history table. When running the log queries, we disable triggers in the clone to avoid adding more rows to the local audit logged_actions table';



-- analyse_audit_logs()
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



COMMIT;
