--
-- PostgreSQL database dump
--

-- Dumped from database version 9.6.17
-- Dumped by pg_dump version 10.10 (Ubuntu 10.10-0ubuntu0.18.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

-- FUNCTION analyse_audit_logs()
COMMENT ON FUNCTION lizsync.analyse_audit_logs() IS 'Get audit logs from the central database and the clone since the last synchronization. Compare the logs to find and resolved UPDATE conflicts (same table, feature, column): last modified object wins. This function store the resolved conflicts into the table lizsync.conflicts in the central database. Returns central server event ids, minimum event id, maximum event id, maximum action timestamp.';


-- FUNCTION create_central_server_fdw(p_central_host text, p_central_port smallint, p_central_database text, p_central_username text, p_central_password text)
COMMENT ON FUNCTION lizsync.create_central_server_fdw(p_central_host text, p_central_port smallint, p_central_database text, p_central_username text, p_central_password text) IS 'Create foreign server, needed central_audit and central_lizsync schemas, and import all central database tables as foreign tables. This will allow the clone to connect to the central databse';


-- FUNCTION create_temporary_table(temporary_table text, table_type text)
COMMENT ON FUNCTION lizsync.create_temporary_table(temporary_table text, table_type text) IS 'Create temporary table used during database bidirectionnal synchronization. Parameters: temporary table name, and table type (audit or conflit)';


-- FUNCTION get_central_audit_logs(p_uid_field text, p_excluded_columns text[])
COMMENT ON FUNCTION lizsync.get_central_audit_logs(p_uid_field text, p_excluded_columns text[]) IS 'Get all the logs from the central database: modifications do not come from the clone, have not yet been replayed by the clone, are dated after the last synchronization, have an event id higher than the last sync maximum event id, and concern the synchronized schemas for this clone. Parameters: uid column name and excluded columns';


-- FUNCTION get_clone_audit_logs(p_uid_field text, p_excluded_columns text[])
COMMENT ON FUNCTION lizsync.get_clone_audit_logs(p_uid_field text, p_excluded_columns text[]) IS 'Get all the modifications made in the clone. Parameters: uid column name and excluded columns';


-- FUNCTION get_event_sql(target text, pevent_id bigint, puid_column text, excluded_columns text)
COMMENT ON FUNCTION lizsync.get_event_sql(target text, pevent_id bigint, puid_column text, excluded_columns text) IS '
Get the SQL to use for replay from a audit log event

Arguments:
   target : clone or central database
   pevent_id:  The event_id of the event in audit.logged_actions to replay
   puid_column: The name of the column with unique uuid values
   excluded_columns: list of columns names, separated by comma, to exclude from synchronization
';


-- FUNCTION import_central_server_schemas()
COMMENT ON FUNCTION lizsync.import_central_server_schemas() IS 'Import synchronized schemas from the central database foreign server into central_XXX local schemas to the clone database. This allow to edit data of the central database from the clone.';


-- FUNCTION replay_central_logs_to_clone(p_ids bigint[], p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone)
COMMENT ON FUNCTION lizsync.replay_central_logs_to_clone(p_ids bigint[], p_min_event_id bigint, p_max_event_id bigint, p_max_action_tstamp_tx timestamp with time zone) IS 'Replay the central logs in the clone database, then modifiy the corresponding audit logs in the central server to update the sync_data column. A new item is also created in the central server lizsync.history table. When running the log queries, we disable triggers in the clone to avoid adding more rows to the local audit logged_actions table';


-- FUNCTION replay_clone_logs_to_central()
COMMENT ON FUNCTION lizsync.replay_clone_logs_to_central() IS 'Replay all logs from the clone to the central database. It returns the number of actions replayed. After this, the clone audit logs are truncated.';


-- FUNCTION store_conflicts()
COMMENT ON FUNCTION lizsync.store_conflicts() IS 'Store resolved conflicts in the central database lizsync.conflicts table.';


-- FUNCTION synchronize()
COMMENT ON FUNCTION lizsync.synchronize() IS 'Run the bi-directionnal database synchronization between the clone and the central server';


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


-- synchronized_schemas
COMMENT ON TABLE lizsync.synchronized_schemas IS 'List of schemas to synchronize per slave server id. This list works as a white list. Only listed schemas will be synchronized for each server ids.';


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

