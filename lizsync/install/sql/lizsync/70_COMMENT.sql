--
-- PostgreSQL database dump
--

-- Dumped from database version 10.15 (Debian 10.15-1.pgdg100+1)
-- Dumped by pg_dump version 10.15 (Debian 10.15-1.pgdg100+1)

SET statement_timeout = 0;
SET lock_timeout = 0;

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

-- FUNCTION analyse_audit_logs()
COMMENT ON FUNCTION lizsync.analyse_audit_logs() IS 'Get audit logs from the central database and the clone since the last synchronization. Compare the logs to find and resolved UPDATE conflicts (same table, feature, column): last modified object wins. This function store the resolved conflicts into the table lizsync.conflicts in the central database. Returns central server event ids, minimum event id, maximum event id, maximum action timestamp.';


-- FUNCTION audit_table(target_table regclass)
COMMENT ON FUNCTION lizsync.audit_table(target_table regclass) IS '
Add auditing support to the given table. Row-level changes will be logged with full client query text. No cols are ignored.
';


-- FUNCTION audit_table(target_table regclass, audit_rows boolean, audit_query_text boolean, ignored_cols text[])
COMMENT ON FUNCTION lizsync.audit_table(target_table regclass, audit_rows boolean, audit_query_text boolean, ignored_cols text[]) IS '
Add auditing support to a table.

Arguments:
   target_table:     Table name, schema qualified if not on search_path
   audit_rows:       Record each row change, or only audit at a statement level
   audit_query_text: Record the text of the client query that triggered the audit event?
   ignored_cols:     Columns to exclude from update diffs, ignore updates that change only ignored cols.
';


-- FUNCTION audit_view(target_view regclass, audit_query_text boolean, ignored_cols text[], uid_cols text[])
COMMENT ON FUNCTION lizsync.audit_view(target_view regclass, audit_query_text boolean, ignored_cols text[], uid_cols text[]) IS '
ADD auditing support TO a VIEW.

Arguments:
   target_view:      TABLE name, schema qualified IF NOT ON search_path
   audit_query_text: Record the text of the client query that triggered the audit event?
   ignored_cols:     COLUMNS TO exclude FROM UPDATE diffs, IGNORE updates that CHANGE only ignored cols.
   uid_cols:         COLUMNS to use to uniquely identify a row from the view (in order to replay UPDATE and DELETE)
';


-- FUNCTION create_central_server_fdw(p_central_host text, p_central_port smallint, p_central_database text, p_central_username text, p_central_password text)
COMMENT ON FUNCTION lizsync.create_central_server_fdw(p_central_host text, p_central_port smallint, p_central_database text, p_central_username text, p_central_password text) IS 'Create foreign server, needed central_lizsync schema, and import all central database tables as foreign tables. This will allow the clone to connect to the central databse';


-- FUNCTION create_temporary_table(temporary_table text, table_type text)
COMMENT ON FUNCTION lizsync.create_temporary_table(temporary_table text, table_type text) IS 'Create temporary table used during database bidirectionnal synchronization. Parameters: temporary table name, and table type (audit or conflit)';


-- FUNCTION get_central_audit_logs(p_uid_field text, p_excluded_columns text[])
COMMENT ON FUNCTION lizsync.get_central_audit_logs(p_uid_field text, p_excluded_columns text[]) IS 'Get all the logs from the central database: modifications do not come from the clone, have not yet been replayed by the clone, are dated after the last synchronisation, have an event id higher than the last sync maximum event id, and concern the synchronised tables for this clone. Parameters: uid column name and excluded columns';


-- FUNCTION get_clone_audit_logs(p_uid_field text, p_excluded_columns text[])
COMMENT ON FUNCTION lizsync.get_clone_audit_logs(p_uid_field text, p_excluded_columns text[]) IS 'Get all the modifications made in the clone. Parameters: uid column name and excluded columns';


-- FUNCTION get_event_sql(pevent_id bigint, puid_column text, excluded_columns text[])
COMMENT ON FUNCTION lizsync.get_event_sql(pevent_id bigint, puid_column text, excluded_columns text[]) IS '
Get the SQL to use for replay from a audit log event

Arguments:
   pevent_id:  The event_id of the event in lizsync.logged_actions to replay
   puid_column: The name of the column with unique uuid values
';


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


-- FUNCTION import_central_server_schemas()
COMMENT ON FUNCTION lizsync.import_central_server_schemas() IS 'Import synchronised schemas from the central database foreign server into central_XXX local schemas to the clone database. This allow to edit data of the central database from the clone.';


-- FUNCTION insert_history_item(p_server_from text, p_server_to text, p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone, p_sync_type text, p_sync_status text)
COMMENT ON FUNCTION lizsync.insert_history_item(p_server_from text, p_server_to text, p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone, p_sync_type text, p_sync_status text) IS 'Add a new history item in the lizsync.history table as the owner of the table. The SECURITY DEFINER allows the clone to update the protected table. DO NOT USE MANUALLY.';


-- FUNCTION replay_central_logs_to_clone(p_ids bigint[], p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone)
COMMENT ON FUNCTION lizsync.replay_central_logs_to_clone(p_ids bigint[], p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone) IS 'Replay the central logs in the clone database, then modifiy the corresponding audit logs in the central server to update the sync_data column. A new item is also created in the central server lizsync.history table. When running the log queries, we disable triggers in the clone to avoid adding more rows to the local audit logged_actions table';


-- FUNCTION replay_clone_logs_to_central()
COMMENT ON FUNCTION lizsync.replay_clone_logs_to_central() IS 'Replay all logs from the clone to the central database. It returns the number of actions replayed. After this, the clone audit logs are truncated.';


-- FUNCTION replay_event(pevent_id integer)
COMMENT ON FUNCTION lizsync.replay_event(pevent_id integer) IS '
Replay a logged event.

Arguments:
   pevent_id:  The event_id of the event in lizsync.logged_actions to replay
';


-- FUNCTION rollback_event(pevent_id bigint)
COMMENT ON FUNCTION lizsync.rollback_event(pevent_id bigint) IS '
Rollback a logged event and returns to previous row data

Arguments:
   pevent_id:  The event_id of the event in lizsync.logged_actions to rollback
';


-- FUNCTION store_conflicts()
COMMENT ON FUNCTION lizsync.store_conflicts() IS 'Store resolved conflicts in the central database lizsync.conflicts table.';


-- FUNCTION synchronize()
COMMENT ON FUNCTION lizsync.synchronize() IS 'Run the bi-directionnal database synchronization between the clone and the central server';


-- FUNCTION update_central_logs_add_clone_id(p_clone_id text, p_sync_id uuid, p_ids bigint[])
COMMENT ON FUNCTION lizsync.update_central_logs_add_clone_id(p_clone_id text, p_sync_id uuid, p_ids bigint[]) IS 'Update the central database synchronisation logs (table lizsync.logged_actions) by adding the clone ID in the "replayed_by" property of the field "sync_data". The SECURITY DEFINER allows the clone to update the protected lizsync.logged_actions table. DO NOT USE MANUALLY.';


-- FUNCTION update_history_item(p_sync_id uuid, p_status text, p_server_to text)
COMMENT ON FUNCTION lizsync.update_history_item(p_sync_id uuid, p_status text, p_server_to text) IS 'Update the status of a history item in the lizsync.history table as the owner of the table. The SECURITY DEFINER allows the clone to update the protected table. DO NOT USE MANUALLY.';


-- FUNCTION update_synchronized_table(p_server_id uuid, p_tables text[])
COMMENT ON FUNCTION lizsync.update_synchronized_table(p_server_id uuid, p_tables text[]) IS 'Insert or Update the table lizsync.synchronized_tables. The SECURITY DEFINER allows the clone to update the protected table. DO NOT USE MANUALLY.';


-- conflicts
COMMENT ON TABLE lizsync.conflicts IS 'Store conflicts resolution made during bidirectionnal database synchronizations.';


-- conflicts.id
COMMENT ON COLUMN lizsync.conflicts.id IS 'Automatic ID';


-- conflicts.conflict_time
COMMENT ON COLUMN lizsync.conflicts.conflict_time IS 'Timestamp of the conflict resolution. Not related to timestamp of logged actions';


-- conflicts.object_table
COMMENT ON COLUMN lizsync.conflicts.object_table IS 'Schema and table name of the conflicted object.';


-- conflicts.object_uid
COMMENT ON COLUMN lizsync.conflicts.object_uid IS 'UID of the conflicted object.';


-- conflicts.clone_id
COMMENT ON COLUMN lizsync.conflicts.clone_id IS 'UID of the source clone database.';


-- conflicts.central_event_id
COMMENT ON COLUMN lizsync.conflicts.central_event_id IS 'Event id of the conflicted central audit log';


-- conflicts.central_event_timestamp
COMMENT ON COLUMN lizsync.conflicts.central_event_timestamp IS 'Event action_tstamp_tx of the conflicted central audit log';


-- conflicts.central_sql
COMMENT ON COLUMN lizsync.conflicts.central_sql IS 'Central SQL action in conflict';


-- conflicts.clone_sql
COMMENT ON COLUMN lizsync.conflicts.clone_sql IS 'Clone SQL action in conflict';


-- conflicts.rejected
COMMENT ON COLUMN lizsync.conflicts.rejected IS 'Rejected object. If "clone", it means the central data has been kept instead';


-- conflicts.rule_applied
COMMENT ON COLUMN lizsync.conflicts.rule_applied IS 'Rule used when managing conflict';


-- logged_actions
COMMENT ON TABLE lizsync.logged_actions IS 'History of auditable actions on audited tables, from lizsync.if_modified_func()';


-- logged_actions.event_id
COMMENT ON COLUMN lizsync.logged_actions.event_id IS 'Unique identifier for each auditable event';


-- logged_actions.schema_name
COMMENT ON COLUMN lizsync.logged_actions.schema_name IS 'Database schema audited table for this event is in';


-- logged_actions.table_name
COMMENT ON COLUMN lizsync.logged_actions.table_name IS 'Non-schema-qualified table name of table event occured in';


-- logged_actions.relid
COMMENT ON COLUMN lizsync.logged_actions.relid IS 'Table OID. Changes with drop/create. Get with ''tablename''::regclass';


-- logged_actions.session_user_name
COMMENT ON COLUMN lizsync.logged_actions.session_user_name IS 'Login / session user whose statement caused the audited event';


-- logged_actions.action_tstamp_tx
COMMENT ON COLUMN lizsync.logged_actions.action_tstamp_tx IS 'Transaction start timestamp for tx in which audited event occurred';


-- logged_actions.action_tstamp_stm
COMMENT ON COLUMN lizsync.logged_actions.action_tstamp_stm IS 'Statement start timestamp for tx in which audited event occurred';


-- logged_actions.action_tstamp_clk
COMMENT ON COLUMN lizsync.logged_actions.action_tstamp_clk IS 'Wall clock time at which audited event''s trigger call occurred';


-- logged_actions.transaction_id
COMMENT ON COLUMN lizsync.logged_actions.transaction_id IS 'Identifier of transaction that made the change. May wrap, but unique paired with action_tstamp_tx.';


-- logged_actions.application_name
COMMENT ON COLUMN lizsync.logged_actions.application_name IS 'Application name set when this audit event occurred. Can be changed in-session by client.';


-- logged_actions.client_addr
COMMENT ON COLUMN lizsync.logged_actions.client_addr IS 'IP address of client that issued query. Null for unix domain socket.';


-- logged_actions.client_port
COMMENT ON COLUMN lizsync.logged_actions.client_port IS 'Remote peer IP port address of client that issued query. Undefined for unix socket.';


-- logged_actions.client_query
COMMENT ON COLUMN lizsync.logged_actions.client_query IS 'Top-level query that caused this auditable event. May be more than one statement.';


-- logged_actions.action
COMMENT ON COLUMN lizsync.logged_actions.action IS 'Action type; I = insert, D = delete, U = update, T = truncate';


-- logged_actions.row_data
COMMENT ON COLUMN lizsync.logged_actions.row_data IS 'Record value. Null for statement-level trigger. For INSERT this is the new tuple. For DELETE and UPDATE it is the old tuple.';


-- logged_actions.changed_fields
COMMENT ON COLUMN lizsync.logged_actions.changed_fields IS 'New values of fields changed by UPDATE. Null except for row-level UPDATE events.';


-- logged_actions.statement_only
COMMENT ON COLUMN lizsync.logged_actions.statement_only IS '''t'' if audit event is from an FOR EACH STATEMENT trigger, ''f'' for FOR EACH ROW';


-- logged_actions.sync_data
COMMENT ON COLUMN lizsync.logged_actions.sync_data IS 'Data used by the sync tool. origin = db name of the change, replayed_by = list of db name where the audit item has already been replayed, sync_id=id of the synchronisation item';


-- logged_relations
COMMENT ON TABLE lizsync.logged_relations IS 'Table used to store unique identifier columns for table or views, so that events can be replayed';


-- logged_relations.relation_name
COMMENT ON COLUMN lizsync.logged_relations.relation_name IS 'Relation (table or view) name (with schema if needed)';


-- logged_relations.uid_column
COMMENT ON COLUMN lizsync.logged_relations.uid_column IS 'Name of a column that is used to uniquely identify a row in the relation';


-- synchronized_tables
COMMENT ON TABLE lizsync.synchronized_tables IS 'List of tables to synchronise per clone server id. This list works as a white list. Only listed tables will be synchronised for each server ids.';


-- sys_structure_metadonnee
COMMENT ON TABLE lizsync.sys_structure_metadonnee IS 'Database structure metadata used for migration by QGIS plugin';


-- sys_structure_metadonnee.id
COMMENT ON COLUMN lizsync.sys_structure_metadonnee.id IS 'Unique ID';


-- sys_structure_metadonnee.date_ajout
COMMENT ON COLUMN lizsync.sys_structure_metadonnee.date_ajout IS 'Version addition date';


-- sys_structure_metadonnee.version
COMMENT ON COLUMN lizsync.sys_structure_metadonnee.version IS 'Lizsync schema version number. Ex: 0.1.0';


-- sys_structure_metadonnee.description
COMMENT ON COLUMN lizsync.sys_structure_metadonnee.description IS 'Description of the version if needed';


--
-- PostgreSQL database dump complete
--

