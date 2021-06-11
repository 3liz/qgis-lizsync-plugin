-- update_central_logs_add_clone_action_timestamps(text)
CREATE OR REPLACE FUNCTION lizsync.update_central_logs_add_clone_action_timestamps(temporary_table_name text) RETURNS boolean
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
    FROM public.' || quote_ident(temporary_table_name) || ' AS t
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

--
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
            BEGIN;
            CREATE TABLE public.' || p_temporary_table || ' (
                action_tstamp_tx TIMESTAMP WITH TIME ZONE,
                sync_id uuid,
                client_query_hash text,
                action_type text,
                ident text
            );
            GRANT SELECT ON TABLE public.' || p_temporary_table || ' TO "public";
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

        -- Drop the fake temporary table afterwards
        sqlupdatelogs = concat(
            sqlupdatelogs,
            'DROP TABLE IF EXISTS public.' || p_temporary_table || ';',
            'COMMIT;'
        );

        -- Update central lizsync.logged_actions
        -- PERFORM * FROM
        PERFORM dblink_exec(
            dblink_connection_name,
            sqlupdatelogs
        )
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
