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

-- SCHEMA audit
COMMENT ON SCHEMA audit IS 'Out-of-table audit/history logging tables and trigger functions';


-- FUNCTION audit_table(target_table regclass)
COMMENT ON FUNCTION audit.audit_table(target_table regclass) IS '
Add auditing support to the given table. Row-level changes will be logged with full client query text. No cols are ignored.
';


-- FUNCTION audit_table(target_table regclass, audit_rows boolean, audit_query_text boolean, ignored_cols text[])
COMMENT ON FUNCTION audit.audit_table(target_table regclass, audit_rows boolean, audit_query_text boolean, ignored_cols text[]) IS '
Add auditing support to a table.

Arguments:
   target_table:     Table name, schema qualified if not on search_path
   audit_rows:       Record each row change, or only audit at a statement level
   audit_query_text: Record the text of the client query that triggered the audit event?
   ignored_cols:     Columns to exclude from update diffs, ignore updates that change only ignored cols.
';


-- FUNCTION audit_view(target_view regclass, audit_query_text boolean, ignored_cols text[], uid_cols text[])
COMMENT ON FUNCTION audit.audit_view(target_view regclass, audit_query_text boolean, ignored_cols text[], uid_cols text[]) IS '
ADD auditing support TO a VIEW.

Arguments:
   target_view:      TABLE name, schema qualified IF NOT ON search_path
   audit_query_text: Record the text of the client query that triggered the audit event?
   ignored_cols:     COLUMNS TO exclude FROM UPDATE diffs, IGNORE updates that CHANGE only ignored cols.
   uid_cols:         COLUMNS to use to uniquely identify a row from the view (in order to replay UPDATE and DELETE)
';


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


-- FUNCTION replay_event(pevent_id integer)
COMMENT ON FUNCTION audit.replay_event(pevent_id integer) IS '
Replay a logged event.

Arguments:
   pevent_id:  The event_id of the event in audit.logged_actions to replay
';


-- FUNCTION rollback_event(pevent_id bigint)
COMMENT ON FUNCTION audit.rollback_event(pevent_id bigint) IS '
Rollback a logged event and returns to previous row data

Arguments:
   pevent_id:  The event_id of the event in audit.logged_actions to rollback
';


-- logged_actions
COMMENT ON TABLE audit.logged_actions IS 'History of auditable actions on audited tables, from audit.if_modified_func()';


-- logged_actions.event_id
COMMENT ON COLUMN audit.logged_actions.event_id IS 'Unique identifier for each auditable event';


-- logged_actions.schema_name
COMMENT ON COLUMN audit.logged_actions.schema_name IS 'Database schema audited table for this event is in';


-- logged_actions.table_name
COMMENT ON COLUMN audit.logged_actions.table_name IS 'Non-schema-qualified table name of table event occured in';


-- logged_actions.relid
COMMENT ON COLUMN audit.logged_actions.relid IS 'Table OID. Changes with drop/create. Get with ''tablename''::regclass';


-- logged_actions.session_user_name
COMMENT ON COLUMN audit.logged_actions.session_user_name IS 'Login / session user whose statement caused the audited event';


-- logged_actions.action_tstamp_tx
COMMENT ON COLUMN audit.logged_actions.action_tstamp_tx IS 'Transaction start timestamp for tx in which audited event occurred';


-- logged_actions.action_tstamp_stm
COMMENT ON COLUMN audit.logged_actions.action_tstamp_stm IS 'Statement start timestamp for tx in which audited event occurred';


-- logged_actions.action_tstamp_clk
COMMENT ON COLUMN audit.logged_actions.action_tstamp_clk IS 'Wall clock time at which audited event''s trigger call occurred';


-- logged_actions.transaction_id
COMMENT ON COLUMN audit.logged_actions.transaction_id IS 'Identifier of transaction that made the change. May wrap, but unique paired with action_tstamp_tx.';


-- logged_actions.application_name
COMMENT ON COLUMN audit.logged_actions.application_name IS 'Application name set when this audit event occurred. Can be changed in-session by client.';


-- logged_actions.client_addr
COMMENT ON COLUMN audit.logged_actions.client_addr IS 'IP address of client that issued query. Null for unix domain socket.';


-- logged_actions.client_port
COMMENT ON COLUMN audit.logged_actions.client_port IS 'Remote peer IP port address of client that issued query. Undefined for unix socket.';


-- logged_actions.client_query
COMMENT ON COLUMN audit.logged_actions.client_query IS 'Top-level query that caused this auditable event. May be more than one statement.';


-- logged_actions.action
COMMENT ON COLUMN audit.logged_actions.action IS 'Action type; I = insert, D = delete, U = update, T = truncate';


-- logged_actions.row_data
COMMENT ON COLUMN audit.logged_actions.row_data IS 'Record value. Null for statement-level trigger. For INSERT this is the new tuple. For DELETE and UPDATE it is the old tuple.';


-- logged_actions.changed_fields
COMMENT ON COLUMN audit.logged_actions.changed_fields IS 'New values of fields changed by UPDATE. Null except for row-level UPDATE events.';


-- logged_actions.statement_only
COMMENT ON COLUMN audit.logged_actions.statement_only IS '''t'' if audit event is from an FOR EACH STATEMENT trigger, ''f'' for FOR EACH ROW';


-- logged_actions.sync_data
COMMENT ON COLUMN audit.logged_actions.sync_data IS 'Data used by the sync tool. origin = db name of the change, replayed_by = list of db name where the audit item has already been replayed, sync_id=id of the synchronization item';


-- logged_relations
COMMENT ON TABLE audit.logged_relations IS 'Table used to store unique identifier columns for table or views, so that events can be replayed';


-- logged_relations.relation_name
COMMENT ON COLUMN audit.logged_relations.relation_name IS 'Relation (table or view) name (with schema if needed)';


-- logged_relations.uid_column
COMMENT ON COLUMN audit.logged_relations.uid_column IS 'Name of a column that is used to uniquely identify a row in the relation';


--
-- PostgreSQL database dump complete
--

