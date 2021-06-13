-- if_modified_func()
CREATE OR REPLACE FUNCTION lizsync.if_modified_func() RETURNS trigger
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

        -- LizSync specific data field
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
            END,
            -- when the clone has created/updated/deleted the data in the clone database
            'action_tstamp_tx',
            Cast(current_setting('lizsync.clone_action_tstamp_tx', true) AS TIMESTAMP WITH TIME ZONE)
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

LizSync has added its own sync_data column to store the needed information for synchronisation purpose.
';



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
    final_counter integer;
    p_temporary_table text;
    dblink_connection_name text;
    dblink_msg text;
    current_status boolean;
    event_ids_on_error bigint[];
BEGIN
    -- Default values
    final_counter = 0;
    current_status = True;
    event_ids_on_error = array[]::bigint[];

    -- Get the total number of logs to replay
    SELECT count(*) AS nb
    FROM temp_clone_audit
    INTO p_counter;
    -- RAISE NOTICE 'p_counter %', p_counter;

    -- If there are some logs, process them
    IF p_counter > 0 THEN

        BEGIN
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

        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'LizSync: % %', SQLSTATE, SQLERRM;
            -- set status
            current_status = False;
            RETURN QUERY SELECT -1::integer;
        END;

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
        BEGIN
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
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'LizSync: % %', SQLSTATE, SQLERRM;
            -- set status
            current_status = False;
            RETURN QUERY SELECT -1::integer;
        END;

        -- Replay SQL queries in central db
        -- The session variables are used by the central server audit function
        -- to fill the sync_data field
        sqlsession = format(
            'SET SESSION "lizsync.server_from" = ''%1$s''; SET SESSION "lizsync.server_to" = ''%2$s''; SET SESSION "lizsync.sync_id" = ''%3$s'';',
            p_clone_id,
            p_central_id,
            p_sync_id
        );

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
            -- We add a session variable with the action timestamp in the clone
            -- This will let us compare clone and central timestamp when UPDATE conflicts appear
            sqltemplate = concat(
                sqlsession,
                format(
                    'SET SESSION "lizsync.clone_action_tstamp_tx" = ''%1$s'';',
                    rec.action_tstamp_tx
                ),
                trim(rec.action) || ';'
            );

            BEGIN
                SELECT dblink_exec(
                    dblink_connection_name,
                    sqltemplate
                )
                INTO dblink_msg;

                -- increase counter
                final_counter = final_counter + 1;
            EXCEPTION WHEN OTHERS THEN
                RAISE NOTICE 'LizSync: % %', SQLSTATE, SQLERRM;
                -- set status
                current_status = False;

                -- add event id to keep because on error
                event_ids_on_error = event_ids_on_error || rec.event_id;
                CONTINUE;
            END;

        END LOOP;

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

    -- Remove successfully replayed logs from clone audit table
    DELETE FROM lizsync.logged_actions
    WHERE NOT (event_id = ANY (event_ids_on_error))
    ;

    -- Set sequence to the minimum required
    PERFORM setval(
        '"lizsync"."logged_actions_event_id_seq"',
        (SELECT max(event_id) FROM lizsync.logged_actions)
    );

    -- Return
    RETURN QUERY SELECT final_counter;
END;
$_$;


-- FUNCTION replay_clone_logs_to_central()
COMMENT ON FUNCTION lizsync.replay_clone_logs_to_central() IS 'Replay all logs from the clone to the central database. It returns the number of actions replayed. After this, the clone audit logs are truncated.';

-- Drop useless function
DROP FUNCTION IF EXISTS lizsync.update_central_logs_add_clone_action_timestamps(temporary_table_name text);
