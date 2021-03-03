BEGIN;

-- REPLACE synchronized_schemas by synchronized_tables
---
ALTER TABLE lizsync.synchronized_schemas RENAME TO synchronized_tables;
ALTER TABLE lizsync.synchronized_tables RENAME COLUMN sync_schemas TO sync_tables;
ALTER TABLE lizsync.synchronized_tables RENAME CONSTRAINT synchronized_schemas_pkey TO synchronized_tables_pkey;
COMMENT ON TABLE lizsync.synchronized_tables IS 'List of tables to synchronise per clone server id. This list works as a white list. Only listed tables will be synchronised for each server ids.';


-- MOVE AUDIT TABLES AND FUNCTIONS INTO lizsync SCHEMA
---
CREATE EXTENSION IF NOT EXISTS hstore;

--
-- Audited data. Lots of information is available, it's just a matter of how much

DROP TABLE IF EXISTS lizsync.logged_actions;
CREATE TABLE lizsync.logged_actions (
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

COMMENT ON TABLE lizsync.logged_actions IS 'History of auditable actions on audited tables, from lizsync.if_modified_func()';
COMMENT ON COLUMN lizsync.logged_actions.event_id IS 'Unique identifier for each auditable event';
COMMENT ON COLUMN lizsync.logged_actions.schema_name IS 'Database schema audited table for this event is in';
COMMENT ON COLUMN lizsync.logged_actions.table_name IS 'Non-schema-qualified table name of table event occured in';
COMMENT ON COLUMN lizsync.logged_actions.relid IS 'Table OID. Changes with drop/create. Get with ''tablename''::regclass';
COMMENT ON COLUMN lizsync.logged_actions.session_user_name IS 'Login / session user whose statement caused the audited event';
COMMENT ON COLUMN lizsync.logged_actions.action_tstamp_tx IS 'Transaction start timestamp for tx in which audited event occurred';
COMMENT ON COLUMN lizsync.logged_actions.action_tstamp_stm IS 'Statement start timestamp for tx in which audited event occurred';
COMMENT ON COLUMN lizsync.logged_actions.action_tstamp_clk IS 'Wall clock time at which audited event''s trigger call occurred';
COMMENT ON COLUMN lizsync.logged_actions.transaction_id IS 'Identifier of transaction that made the change. May wrap, but unique paired with action_tstamp_tx.';
COMMENT ON COLUMN lizsync.logged_actions.client_addr IS 'IP address of client that issued query. Null for unix domain socket.';
COMMENT ON COLUMN lizsync.logged_actions.client_port IS 'Remote peer IP port address of client that issued query. Undefined for unix socket.';
COMMENT ON COLUMN lizsync.logged_actions.client_query IS 'Top-level query that caused this auditable event. May be more than one statement.';
COMMENT ON COLUMN lizsync.logged_actions.application_name IS 'Application name set when this audit event occurred. Can be changed in-session by client.';
COMMENT ON COLUMN lizsync.logged_actions.action IS 'Action type; I = insert, D = delete, U = update, T = truncate';
COMMENT ON COLUMN lizsync.logged_actions.row_data IS 'Record value. Null for statement-level trigger. For INSERT this is the new tuple. For DELETE and UPDATE it is the old tuple.';
COMMENT ON COLUMN lizsync.logged_actions.changed_fields IS 'New values of fields changed by UPDATE. Null except for row-level UPDATE events.';
COMMENT ON COLUMN lizsync.logged_actions.statement_only IS '''t'' if audit event is from an FOR EACH STATEMENT trigger, ''f'' for FOR EACH ROW';
COMMENT ON COLUMN lizsync.logged_actions.sync_data IS 'Data used by the sync tool. origin = db name of the change, replayed_by = list of db name where the audit item has already been replayed, sync_id=id of the synchronisation item';

CREATE INDEX logged_actions_relid_idx ON lizsync.logged_actions(relid);
CREATE INDEX logged_actions_action_tstamp_tx_stm_idx ON lizsync.logged_actions(action_tstamp_stm);
CREATE INDEX logged_actions_action_idx ON lizsync.logged_actions(action);

CREATE TABLE lizsync.logged_relations (
    relation_name text not null,
    uid_column text not null,
    PRIMARY KEY (relation_name, uid_column)
);

COMMENT ON TABLE lizsync.logged_relations IS 'Table used to store unique identifier columns for table or views, so that events can be replayed';
COMMENT ON COLUMN lizsync.logged_relations.relation_name IS 'Relation (table or view) name (with schema if needed)';
COMMENT ON COLUMN lizsync.logged_relations.uid_column IS 'Name of a column that is used to uniquely identify a row in the relation';

CREATE OR REPLACE FUNCTION lizsync.if_modified_func() RETURNS TRIGGER AS $body$
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
$body$
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public;


COMMENT ON FUNCTION lizsync.if_modified_func() IS $body$
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



CREATE OR REPLACE FUNCTION lizsync.audit_table(target_table regclass, audit_rows boolean, audit_query_text boolean, ignored_cols text[]) RETURNS void AS $body$
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
$body$
language 'plpgsql';

COMMENT ON FUNCTION lizsync.audit_table(regclass, boolean, boolean, text[]) IS $body$
Add auditing support to a table.

Arguments:
   target_table:     Table name, schema qualified if not on search_path
   audit_rows:       Record each row change, or only audit at a statement level
   audit_query_text: Record the text of the client query that triggered the audit event?
   ignored_cols:     Columns to exclude from update diffs, ignore updates that change only ignored cols.
$body$;

-- Pg doesn't allow variadic calls with 0 params, so provide a wrapper
CREATE OR REPLACE FUNCTION lizsync.audit_table(target_table regclass, audit_rows boolean, audit_query_text boolean) RETURNS void AS $body$
SELECT lizsync.audit_table($1, $2, $3, ARRAY[]::text[]);
$body$ LANGUAGE SQL;

-- And provide a convenience call wrapper for the simplest case
-- of row-level logging with no excluded cols and query logging enabled.
--
CREATE OR REPLACE FUNCTION lizsync.audit_table(target_table regclass) RETURNS void AS $body$
SELECT lizsync.audit_table($1, BOOLEAN 't', BOOLEAN 't');
$body$ LANGUAGE 'sql';

COMMENT ON FUNCTION lizsync.audit_table(regclass) IS $body$
Add auditing support to the given table. Row-level changes will be logged with full client query text. No cols are ignored.
$body$;


CREATE OR REPLACE FUNCTION lizsync.replay_event(pevent_id int) RETURNS void AS $body$
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
$body$
LANGUAGE plpgsql;

COMMENT ON FUNCTION lizsync.replay_event(int) IS $body$
Replay a logged event.

Arguments:
   pevent_id:  The event_id of the event in lizsync.logged_actions to replay
$body$;

CREATE OR REPLACE FUNCTION lizsync.audit_view(target_view regclass, audit_query_text BOOLEAN, ignored_cols text[], uid_cols text[]) RETURNS void AS $body$
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
$body$
LANGUAGE plpgsql;

COMMENT ON FUNCTION lizsync.audit_view(regclass, BOOLEAN, text[], text[]) IS $body$
ADD auditing support TO a VIEW.

Arguments:
   target_view:      TABLE name, schema qualified IF NOT ON search_path
   audit_query_text: Record the text of the client query that triggered the audit event?
   ignored_cols:     COLUMNS TO exclude FROM UPDATE diffs, IGNORE updates that CHANGE only ignored cols.
   uid_cols:         COLUMNS to use to uniquely identify a row from the view (in order to replay UPDATE and DELETE)
$body$;

-- Pg doesn't allow variadic calls with 0 params, so provide a wrapper
CREATE OR REPLACE FUNCTION lizsync.audit_view(target_view regclass, audit_query_text BOOLEAN, uid_cols text[]) RETURNS void AS $body$
SELECT lizsync.audit_view($1, $2, ARRAY[]::text[], uid_cols);
$body$ LANGUAGE SQL;

-- And provide a convenience call wrapper for the simplest case
-- of row-level logging with no excluded cols and query logging enabled.
--
CREATE OR REPLACE FUNCTION lizsync.audit_view(target_view regclass, uid_cols text[]) RETURNS void AS $$
SELECT lizsync.audit_view($1, BOOLEAN 't', uid_cols);
$$ LANGUAGE 'sql';

-- Function to rollback and event
CREATE OR REPLACE FUNCTION lizsync.rollback_event(pevent_id bigint) RETURNS void AS $body$
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
$body$
LANGUAGE plpgsql;

COMMENT ON FUNCTION lizsync.rollback_event(bigint) IS $body$
Rollback a logged event and returns to previous row data

Arguments:
   pevent_id:  The event_id of the event in lizsync.logged_actions to rollback
$body$;


-- ADAPT LIZSYNC FUNCTIONS
--

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
COMMENT ON FUNCTION lizsync.import_central_server_schemas() IS 'Import synchronised schemas from the central database foreign server into central_XXX local schemas to the clone database. This allow to edit data of the central database from the clone.';


-- compare_tables(text, text)
CREATE OR REPLACE FUNCTION lizsync.compare_tables(p_schema_name text, p_table_name text) RETURNS TABLE(uid uuid, status text, clone_table_values public.hstore, central_table_values public.hstore)
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
CREATE OR REPLACE FUNCTION lizsync.create_central_server_fdw(p_central_host text, p_central_port smallint, p_central_database text, p_central_username text, p_central_password text) RETURNS boolean
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
        event_id bigint, action_tstamp_tx timestamp with time zone, action_tstamp_epoch integer,
        ident text, action_type text, origine text, action text, updated_field text,
        uid uuid, original_action_tstamp_tx integer
    )
    ;

END;
$_$;


-- FUNCTION get_central_audit_logs(p_uid_field text, p_excluded_columns text[])
COMMENT ON FUNCTION lizsync.get_central_audit_logs(p_uid_field text, p_excluded_columns text[]) IS 'Get all the logs from the central database: modifications do not come from the clone, have not yet been replayed by the clone, are dated after the last synchronisation, have an event id higher than the last sync maximum event id, and concern the synchronised tables for this clone. Parameters: uid column name and excluded columns';

-- get_clone_audit_logs(text, text[])
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
        UPDATE central_lizsync.logged_actions
        SET sync_data = jsonb_set(
            sync_data,
            '{"replayed_by"}',
            sync_data->'replayed_by' || jsonb_build_object(p_clone_id, p_sync_id),
            true
        )
        WHERE event_id = ANY (p_ids)
        ;

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

        -- Store SQL query to update central logs afterward with original log timestamp
        sqlupdatelogs = '';

        -- Create dblink connection
        dblink_connection_name = (md5(((random())::text || (clock_timestamp())::text)))::text;
        -- RAISE NOTICE 'dblink_connection_name %', dblink_connection_name;
        SELECT dblink_connect(
            dblink_connection_name,
            'central_server'
        )
        INTO dblink_msg;

        -- Loop through logs and replay action
        -- We need to query one by one to be able
        -- to update the sync_data->action_tstamp_tx afterwards
        -- by searching action = sqltemplate
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
            sqltemplate = trim(quote_literal(sqltemplate), '''');
            sqlupdatelogs = concat(
                sqlupdatelogs,
                format('
                    UPDATE lizsync.logged_actions
                    SET sync_data = sync_data || jsonb_build_object(
                        ''action_tstamp_tx'',
                        Cast(''%1$s'' AS TIMESTAMP WITH TIME ZONE)
                    )
                    WHERE True
                    AND sync_data->''replayed_by''->>''%2$s'' = ''%3$s''
                    AND client_query = ''%4$s''
                    AND action = ''%5$s''
                    AND concat(schema_name, ''.'', table_name) = ''%6$s''
                    ;',
                    rec.action_tstamp_tx,
                    p_central_id,
                    p_sync_id,
                    sqltemplate,
                    rec.action_type,
                    rec.ident
                )
            );

        END LOOP;

        -- Update central lizsync.logged_actions
        SELECT dblink_exec(
            dblink_connection_name,
            sqlupdatelogs
        )
        INTO dblink_msg;

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
