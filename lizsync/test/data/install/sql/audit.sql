-- An audit history is important on most tables. Provide an audit trigger that logs to
-- a dedicated audit table for the major relations.
--
-- This file should be generic and not depend on application roles or structures,
-- as it's being listed here:
--
--    https://wiki.postgresql.org/wiki/Audit_trigger_91plus
--
-- This trigger was originally based on
--   http://wiki.postgresql.org/wiki/Audit_trigger
-- but has been completely rewritten.
--
-- Should really be converted into a relocatable EXTENSION, with control and upgrade files.

CREATE EXTENSION IF NOT EXISTS hstore;

CREATE SCHEMA audit;
REVOKE ALL ON SCHEMA audit FROM public;

COMMENT ON SCHEMA audit IS 'Out-of-table audit/history logging tables and trigger functions';

--
-- Audited data. Lots of information is available, it's just a matter of how much
-- you really want to record. See:
--
--   http://www.postgresql.org/docs/9.1/static/functions-info.html
--
-- Remember, every column you add takes up more audit table space and slows audit
-- inserts.
--
-- Every index you add has a big impact too, so avoid adding indexes to the
-- audit table unless you REALLY need them. The hstore GIST indexes are
-- particularly expensive.
--
-- It is sometimes worth copying the audit table, or a coarse subset of it that
-- you're interested in, into a temporary table where you CREATE any useful
-- indexes and do your analysis.
--
DROP TABLE IF EXISTS audit.logged_actions;

CREATE TABLE audit.logged_actions (
    event_id bigserial primary key,
    schema_name text not null,
    table_name text not null,
    relid oid not null,
    session_user_name text,
    action_tstamp_tx TIMESTAMP WITH TIME ZONE NOT NULL,
    action_tstamp_stm TIMESTAMP WITH TIME ZONE NOT NULL,
    action_tstamp_clk TIMESTAMP WITH TIME ZONE NOT NULL,
    transaction_id bigint,
    application_name text,
    client_addr inet,
    client_port integer,
    client_query text NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('I','D','U', 'T')),
    row_data hstore,
    changed_fields hstore,
    statement_only boolean not null,
    sync_data jsonb NOT NULL
);

REVOKE ALL ON audit.logged_actions FROM public;

COMMENT ON TABLE audit.logged_actions IS 'History of auditable actions on audited tables, from audit.if_modified_func()';
COMMENT ON COLUMN audit.logged_actions.event_id IS 'Unique identifier for each auditable event';
COMMENT ON COLUMN audit.logged_actions.schema_name IS 'Database schema audited table for this event is in';
COMMENT ON COLUMN audit.logged_actions.table_name IS 'Non-schema-qualified table name of table event occured in';
COMMENT ON COLUMN audit.logged_actions.relid IS 'Table OID. Changes with drop/create. Get with ''tablename''::regclass';
COMMENT ON COLUMN audit.logged_actions.session_user_name IS 'Login / session user whose statement caused the audited event';
COMMENT ON COLUMN audit.logged_actions.action_tstamp_tx IS 'Transaction start timestamp for tx in which audited event occurred';
COMMENT ON COLUMN audit.logged_actions.action_tstamp_stm IS 'Statement start timestamp for tx in which audited event occurred';
COMMENT ON COLUMN audit.logged_actions.action_tstamp_clk IS 'Wall clock time at which audited event''s trigger call occurred';
COMMENT ON COLUMN audit.logged_actions.transaction_id IS 'Identifier of transaction that made the change. May wrap, but unique paired with action_tstamp_tx.';
COMMENT ON COLUMN audit.logged_actions.client_addr IS 'IP address of client that issued query. Null for unix domain socket.';
COMMENT ON COLUMN audit.logged_actions.client_port IS 'Remote peer IP port address of client that issued query. Undefined for unix socket.';
COMMENT ON COLUMN audit.logged_actions.client_query IS 'Top-level query that caused this auditable event. May be more than one statement.';
COMMENT ON COLUMN audit.logged_actions.application_name IS 'Application name set when this audit event occurred. Can be changed in-session by client.';
COMMENT ON COLUMN audit.logged_actions.action IS 'Action type; I = insert, D = delete, U = update, T = truncate';
COMMENT ON COLUMN audit.logged_actions.row_data IS 'Record value. Null for statement-level trigger. For INSERT this is the new tuple. For DELETE and UPDATE it is the old tuple.';
COMMENT ON COLUMN audit.logged_actions.changed_fields IS 'New values of fields changed by UPDATE. Null except for row-level UPDATE events.';
COMMENT ON COLUMN audit.logged_actions.statement_only IS '''t'' if audit event is from an FOR EACH STATEMENT trigger, ''f'' for FOR EACH ROW';
COMMENT ON COLUMN audit.logged_actions.sync_data IS 'Data used by the sync tool. origin = db name of the change, replayed_by = list of db name where the audit item has already been replayed, sync_id=id of the synchronization item';

CREATE INDEX logged_actions_relid_idx ON audit.logged_actions(relid);
CREATE INDEX logged_actions_action_tstamp_tx_stm_idx ON audit.logged_actions(action_tstamp_stm);
CREATE INDEX logged_actions_action_idx ON audit.logged_actions(action);

CREATE TABLE audit.logged_relations (
    relation_name text not null,
    uid_column text not null,
    PRIMARY KEY (relation_name, uid_column)
);

COMMENT ON TABLE audit.logged_relations IS 'Table used to store unique identifier columns for table or views, so that events can be replayed';
COMMENT ON COLUMN audit.logged_relations.relation_name IS 'Relation (table or view) name (with schema if needed)';
COMMENT ON COLUMN audit.logged_relations.uid_column IS 'Name of a column that is used to uniquely identify a row in the relation';

CREATE OR REPLACE FUNCTION audit.if_modified_func() RETURNS TRIGGER AS $body$
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
$body$
LANGUAGE plpgsql
SECURITY DEFINER
;


COMMENT ON FUNCTION audit.if_modified_func() IS $body$
Track changes to a table at the statement and/or row level.

Optional parameters to trigger in CREATE TRIGGER call:

param 0: boolean, whether to log the query text. Default 't'.

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
a 'FOR EACH STATEMENT' rather than 'FOR EACH ROW' trigger if you do not
want to log row values.

Note that the user name logged is the login role for the session. The audit trigger
cannot obtain the active role because it is reset by the SECURITY DEFINER invocation
of the audit trigger its self.
$body$;



CREATE OR REPLACE FUNCTION audit.audit_table(target_table regclass, audit_rows boolean, audit_query_text boolean, ignored_cols text[]) RETURNS void AS $body$
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
$body$
language 'plpgsql';

COMMENT ON FUNCTION audit.audit_table(regclass, boolean, boolean, text[]) IS $body$
Add auditing support to a table.

Arguments:
   target_table:     Table name, schema qualified if not on search_path
   audit_rows:       Record each row change, or only audit at a statement level
   audit_query_text: Record the text of the client query that triggered the audit event?
   ignored_cols:     Columns to exclude from update diffs, ignore updates that change only ignored cols.
$body$;

-- Pg doesn't allow variadic calls with 0 params, so provide a wrapper
CREATE OR REPLACE FUNCTION audit.audit_table(target_table regclass, audit_rows boolean, audit_query_text boolean) RETURNS void AS $body$
SELECT audit.audit_table($1, $2, $3, ARRAY[]::text[]);
$body$ LANGUAGE SQL;

-- And provide a convenience call wrapper for the simplest case
-- of row-level logging with no excluded cols and query logging enabled.
--
CREATE OR REPLACE FUNCTION audit.audit_table(target_table regclass) RETURNS void AS $body$
SELECT audit.audit_table($1, BOOLEAN 't', BOOLEAN 't');
$body$ LANGUAGE 'sql';

COMMENT ON FUNCTION audit.audit_table(regclass) IS $body$
Add auditing support to the given table. Row-level changes will be logged with full client query text. No cols are ignored.
$body$;


CREATE OR REPLACE FUNCTION audit.replay_event(pevent_id int) RETURNS void AS $body$
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
$body$
LANGUAGE plpgsql;

COMMENT ON FUNCTION audit.replay_event(int) IS $body$
Replay a logged event.

Arguments:
   pevent_id:  The event_id of the event in audit.logged_actions to replay
$body$;

CREATE OR REPLACE FUNCTION audit.audit_view(target_view regclass, audit_query_text BOOLEAN, ignored_cols text[], uid_cols text[]) RETURNS void AS $body$
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
$body$
LANGUAGE plpgsql;

COMMENT ON FUNCTION audit.audit_view(regclass, BOOLEAN, text[], text[]) IS $body$
ADD auditing support TO a VIEW.

Arguments:
   target_view:      TABLE name, schema qualified IF NOT ON search_path
   audit_query_text: Record the text of the client query that triggered the audit event?
   ignored_cols:     COLUMNS TO exclude FROM UPDATE diffs, IGNORE updates that CHANGE only ignored cols.
   uid_cols:         COLUMNS to use to uniquely identify a row from the view (in order to replay UPDATE and DELETE)
$body$;

-- Pg doesn't allow variadic calls with 0 params, so provide a wrapper
CREATE OR REPLACE FUNCTION audit.audit_view(target_view regclass, audit_query_text BOOLEAN, uid_cols text[]) RETURNS void AS $body$
SELECT audit.audit_view($1, $2, ARRAY[]::text[], uid_cols);
$body$ LANGUAGE SQL;

-- And provide a convenience call wrapper for the simplest case
-- of row-level logging with no excluded cols and query logging enabled.
--
CREATE OR REPLACE FUNCTION audit.audit_view(target_view regclass, uid_cols text[]) RETURNS void AS $$
SELECT audit.audit_view($1, BOOLEAN 't', uid_cols);
$$ LANGUAGE 'sql';

-- Function to rollback and event
CREATE OR REPLACE FUNCTION audit.rollback_event(pevent_id bigint) RETURNS void AS $body$
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
$body$
LANGUAGE plpgsql;

COMMENT ON FUNCTION audit.rollback_event(bigint) IS $body$
Rollback a logged event and returns to previous row data

Arguments:
   pevent_id:  The event_id of the event in audit.logged_actions to rollback
$body$;
