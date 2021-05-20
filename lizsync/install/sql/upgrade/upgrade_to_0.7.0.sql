BEGIN;

CREATE OR REPLACE FUNCTION lizsync.update_central_logs_add_clone_id(p_clone_id text, p_sync_id uuid, p_ids bigint[]) RETURNS BOOLEAN
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


COMMENT ON FUNCTION lizsync.update_central_logs_add_clone_id(p_clone_id text, p_sync_id uuid, p_ids bigint[]) IS 'Update the central database synchronisation logs (table lizsync.logged_actions) by adding the clone ID in the "replayed_by" property of the field "sync_data". The SECURITY DEFINER allows the clone to update the protected lizsync.logged_actions table. DO NOT USE MANUALLY.';


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
        ) AS foo(update_status boolean);

        -- Disconnect dblink
        SELECT dblink_disconnect(dblink_connection_name)
        INTO dblink_msg;

        -- Modify central server synchronisation item central->clone
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



CREATE OR REPLACE FUNCTION lizsync.update_central_logs_add_clone_action_timestamps(temporary_table_name text) RETURNS BOOLEAN
    LANGUAGE plpgsql SECURITY DEFINER
    AS $_$
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
$_$;

COMMENT ON FUNCTION lizsync.update_central_logs_add_clone_action_timestamps(temporary_table_name text) IS 'Update all logs created by the central database after the clone has replayed its local logs in the central database. It is necessary to update the action_tstamp_tx key of lizsync.logged_actions sync_data column. The SECURITY DEFINER allows the clone to update the protected lizsync.logged_actions table. DO NOT USE MANUALLY.';

-- replay_clone_logs_to_central()
CREATE OR REPLACE FUNCTION lizsync.replay_clone_logs_to_central() RETURNS TABLE(replay_count integer)
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

        -- Create dblink connection
        dblink_connection_name = (md5(((random())::text || (clock_timestamp())::text)))::text;
        -- RAISE NOTICE 'dblink_connection_name %', dblink_connection_name;
        SELECT dblink_connect(
            dblink_connection_name,
            'central_server'
        )
        INTO dblink_msg;

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
        ) AS foo(update_status boolean);

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
    TRUNCATE lizsync.logged_actions
    RESTART IDENTITY;

    -- Return
    RETURN QUERY
    SELECT p_counter;
END;
$_$;


-- FUNCTION replay_clone_logs_to_central()
COMMENT ON FUNCTION lizsync.replay_clone_logs_to_central() IS 'Replay all logs from the clone to the central database. It returns the number of actions replayed. After this, the clone audit logs are truncated.';



COMMIT;


