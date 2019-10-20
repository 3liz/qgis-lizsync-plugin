--
-- PostgreSQL database dump
--

-- Dumped from database version 9.6.15
-- Dumped by pg_dump version 9.6.15

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

-- audit_table(regclass)
CREATE FUNCTION audit.audit_table(target_table regclass) RETURNS void
    LANGUAGE sql
    AS $_$
SELECT audit.audit_table($1, BOOLEAN 't', BOOLEAN 't');
$_$;


-- FUNCTION audit_table(target_table regclass)
COMMENT ON FUNCTION audit.audit_table(target_table regclass) IS '
Add auditing support to the given table. Row-level changes will be logged with full client query text. No cols are ignored.
';


-- audit_table(regclass, boolean, boolean)
CREATE FUNCTION audit.audit_table(target_table regclass, audit_rows boolean, audit_query_text boolean) RETURNS void
    LANGUAGE sql
    AS $_$
SELECT audit.audit_table($1, $2, $3, ARRAY[]::text[]);
$_$;


-- audit_table(regclass, boolean, boolean, text[])
CREATE FUNCTION audit.audit_table(target_table regclass, audit_rows boolean, audit_query_text boolean, ignored_cols text[]) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
  stm_targets text = 'INSERT OR UPDATE OR DELETE OR TRUNCATE';
  _q_txt text;
  _ignored_cols_snip text = '';
BEGIN

    EXECUTE 'DROP TRIGGER IF EXISTS audit_trigger_row ON ' || target_table::TEXT;
    EXECUTE 'DROP TRIGGER IF EXISTS audit_trigger_stm ON ' || target_table::TEXT;


    IF audit_rows THEN
        IF array_length(ignored_cols,1) > 0 THEN
            _ignored_cols_snip = ', ' || quote_literal(ignored_cols);
        END IF;
        _q_txt = 'CREATE TRIGGER audit_trigger_row AFTER INSERT OR UPDATE OR DELETE ON ' ||
                 target_table::TEXT ||

                 ' FOR EACH ROW EXECUTE PROCEDURE audit.if_modified_func(' ||
                 quote_literal(audit_query_text) || _ignored_cols_snip || ');';
        RAISE NOTICE '%',_q_txt;
        EXECUTE _q_txt;
        stm_targets = 'TRUNCATE';
    ELSE
    END IF;

    _q_txt = 'CREATE TRIGGER audit_trigger_stm AFTER ' || stm_targets || ' ON ' ||
             target_table ||
             ' FOR EACH STATEMENT EXECUTE PROCEDURE audit.if_modified_func('||
             quote_literal(audit_query_text) || ');';
    RAISE NOTICE '%',_q_txt;
    EXECUTE _q_txt;

    -- store primary key names
    insert into audit.logged_relations (relation_name, uid_column)
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
COMMENT ON FUNCTION audit.audit_table(target_table regclass, audit_rows boolean, audit_query_text boolean, ignored_cols text[]) IS '
Add auditing support to a table.

Arguments:
   target_table:     Table name, schema qualified if not on search_path
   audit_rows:       Record each row change, or only audit at a statement level
   audit_query_text: Record the text of the client query that triggered the audit event?
   ignored_cols:     Columns to exclude from update diffs, ignore updates that change only ignored cols.
';


-- audit_view(regclass, text[])
CREATE FUNCTION audit.audit_view(target_view regclass, uid_cols text[]) RETURNS void
    LANGUAGE sql
    AS $_$
SELECT audit.audit_view($1, BOOLEAN 't', uid_cols);
$_$;


-- audit_view(regclass, boolean, text[])
CREATE FUNCTION audit.audit_view(target_view regclass, audit_query_text boolean, uid_cols text[]) RETURNS void
    LANGUAGE sql
    AS $_$
SELECT audit.audit_view($1, $2, ARRAY[]::text[], uid_cols);
$_$;


-- audit_view(regclass, boolean, text[], text[])
CREATE FUNCTION audit.audit_view(target_view regclass, audit_query_text boolean, ignored_cols text[], uid_cols text[]) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
  stm_targets text = 'INSERT OR UPDATE OR DELETE';
  _q_txt text;
  _ignored_cols_snip text = '';

BEGIN
    EXECUTE 'DROP TRIGGER IF EXISTS audit_trigger_row ON ' || target_view::text;
    EXECUTE 'DROP TRIGGER IF EXISTS audit_trigger_stm ON ' || target_view::text;

    IF array_length(ignored_cols,1) > 0 THEN
        _ignored_cols_snip = ', ' || quote_literal(ignored_cols);
    END IF;
    _q_txt = 'CREATE TRIGGER audit_trigger_row INSTEAD OF INSERT OR UPDATE OR DELETE ON ' ||
         target_view::TEXT ||
         ' FOR EACH ROW EXECUTE PROCEDURE audit.if_modified_func(' ||
         quote_literal(audit_query_text) || _ignored_cols_snip || ');';
    RAISE NOTICE '%',_q_txt;
    EXECUTE _q_txt;

    -- store uid columns if not already present
  IF (select count(*) from audit.logged_relations where relation_name = (select target_view)::text AND  uid_column= (select unnest(uid_cols))::text) = 0 THEN
      insert into audit.logged_relations (relation_name, uid_column)
       select target_view, unnest(uid_cols);
  END IF;

END;
$$;


-- FUNCTION audit_view(target_view regclass, audit_query_text boolean, ignored_cols text[], uid_cols text[])
COMMENT ON FUNCTION audit.audit_view(target_view regclass, audit_query_text boolean, ignored_cols text[], uid_cols text[]) IS '
ADD auditing support TO a VIEW.

Arguments:
   target_view:      TABLE name, schema qualified IF NOT ON search_path
   audit_query_text: Record the text of the client query that triggered the audit event?
   ignored_cols:     COLUMNS TO exclude FROM UPDATE diffs, IGNORE updates that CHANGE only ignored cols.
   uid_cols:         COLUMNS to use to uniquely identify a row from the view (in order to replay UPDATE and DELETE)
';


-- if_modified_func()
CREATE FUNCTION audit.if_modified_func() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
    audit_row audit.logged_actions;
    include_values boolean;
    log_diffs boolean;
    h_old hstore;
    h_new hstore;
    excluded_cols text[] = ARRAY[]::text[];
BEGIN
    --RAISE WARNING '[audit.if_modified_func] start with TG_ARGV[0]: % ; TG_ARGV[1] : %, TG_OP: %, TG_LEVEL : %, TG_WHEN: % ', TG_ARGV[0], TG_ARGV[1], TG_OP, TG_LEVEL, TG_WHEN;

    IF NOT (TG_WHEN IN ('AFTER' , 'INSTEAD OF')) THEN
        RAISE EXCEPTION 'audit.if_modified_func() may only run as an AFTER trigger';
    END IF;

    audit_row = ROW(
        nextval('audit.logged_actions_event_id_seq'), -- event_id
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
            'origin', current_setting('sync.server_from', true),
            'replayed_by',
            CASE
                WHEN current_setting('sync.server_to', true) IS NOT NULL
                AND current_setting('sync.sync_id', true) IS NOT NULL
                    THEN jsonb_build_object(
                        current_setting('sync.server_to', true),
                        current_setting('sync.sync_id', true)
                    )
                ELSE jsonb_build_object()
            END

        )
    );

    IF NOT TG_ARGV[0]::boolean IS DISTINCT FROM 'f'::boolean THEN
        audit_row.client_query = NULL;
        RAISE WARNING '[audit.if_modified_func] - Trigger func triggered with no client_query tracking';

    END IF;

    IF TG_ARGV[1] IS NOT NULL THEN
        excluded_cols = TG_ARGV[1]::text[];
        RAISE WARNING '[audit.if_modified_func] - Trigger func triggered with excluded_cols: %',TG_ARGV[1];
    END IF;

    IF (TG_OP = 'UPDATE' AND TG_LEVEL = 'ROW') THEN
        h_old = hstore(OLD.*) - excluded_cols;
        audit_row.row_data = h_old;
        h_new = hstore(NEW.*)- excluded_cols;
        audit_row.changed_fields =  h_new - h_old;

        IF audit_row.changed_fields = hstore('') THEN
            -- All changed fields are ignored. Skip this update.
            RAISE WARNING '[audit.if_modified_func] - Trigger detected NULL hstore. ending';
            RETURN NULL;
        END IF;
  INSERT INTO audit.logged_actions VALUES (audit_row.*);
  RETURN NEW;

    ELSIF (TG_OP = 'DELETE' AND TG_LEVEL = 'ROW') THEN
        audit_row.row_data = hstore(OLD.*) - excluded_cols;
  INSERT INTO audit.logged_actions VALUES (audit_row.*);
        RETURN OLD;

    ELSIF (TG_OP = 'INSERT' AND TG_LEVEL = 'ROW') THEN
        audit_row.row_data = hstore(NEW.*) - excluded_cols;
  INSERT INTO audit.logged_actions VALUES (audit_row.*);
        RETURN NEW;

    ELSIF (TG_LEVEL = 'STATEMENT' AND TG_OP IN ('INSERT','UPDATE','DELETE','TRUNCATE')) THEN
        audit_row.statement_only = 't';
        INSERT INTO audit.logged_actions VALUES (audit_row.*);
  RETURN NULL;

    ELSE
        RAISE EXCEPTION '[audit.if_modified_func] - Trigger func added as trigger for unhandled case: %, %',TG_OP, TG_LEVEL;
        RETURN NEW;
    END IF;


END;
$$;


-- FUNCTION if_modified_func()
COMMENT ON FUNCTION audit.if_modified_func() IS '
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


-- replay_event(integer)
CREATE FUNCTION audit.replay_event(pevent_id integer) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
  query text;
BEGIN
    with
    event as (
        select * from audit.logged_actions where event_id = pevent_id
    )
    -- get primary key names
    , where_pks as (
        select array_to_string(array_agg(uid_column || '=' || quote_literal(row_data->uid_column)), ' AND ') as where_clause
          from audit.logged_relations r
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
COMMENT ON FUNCTION audit.replay_event(pevent_id integer) IS '
Replay a logged event.

Arguments:
   pevent_id:  The event_id of the event in audit.logged_actions to replay
';


-- rollback_event(bigint)
CREATE FUNCTION audit.rollback_event(pevent_id bigint) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    event record;
    pkeys record;
    last_event record;
    query text;
BEGIN
    -- Get event
    SELECT * INTO event FROM audit.logged_actions WHERE event_id = pevent_id;
    -- RAISE NOTICE 'event id = %', event.event_id;

    -- Get the WHERE clause to filter the events feature
    SELECT INTO pkeys
        array_to_string(array_agg(uid_column || '=' || quote_literal(event.row_data->uid_column)), ' AND ') AS where_clause,
        hstore(array_agg(uid_column), array_agg( event.row_data->uid_column)) AS hstore_keys
    FROM audit.logged_relations r
    WHERE relation_name = (event.schema_name || '.' || event.table_name)
    ;
    -- RAISE NOTICE 'hstore_keys = %', pkeys.hstore_keys;

    -- Check if this is the last event for the feature. If not cancel the rollback
    SELECT INTO last_event
        (pevent_id = la.event_id) AS is_last,
        la.event_id
    FROM audit.logged_actions AS la
    WHERE true
    AND la.schema_name = event.schema_name
    AND la.table_name = event.table_name
    AND la.row_data @> pkeys.hstore_keys
    ORDER BY la.action_tstamp_tx DESC
    LIMIT 1
    ;
    IF NOT last_event.is_last THEN
        RAISE EXCEPTION '[audit.rollback_event] - Cannot rollback this event (id = %) because a more recent event (id = %) exists for this feature', pevent_id, last_event.event_id;
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
        audit.logged_actions
    WHERE event_id = pevent_id
    ;

    execute query;
END;
$$;


-- FUNCTION rollback_event(pevent_id bigint)
COMMENT ON FUNCTION audit.rollback_event(pevent_id bigint) IS '
Rollback a logged event and returns to previous row data

Arguments:
   pevent_id:  The event_id of the event in audit.logged_actions to rollback
';


--
-- PostgreSQL database dump complete
--

