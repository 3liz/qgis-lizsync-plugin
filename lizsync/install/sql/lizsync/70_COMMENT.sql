--
-- PostgreSQL database dump
--

-- Dumped from database version 9.6.16
-- Dumped by pg_dump version 9.6.16

SET statement_timeout = 0;
SET lock_timeout = 0;

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

-- FUNCTION get_event_sql(pevent_id bigint, puid_column text, excluded_columns text[])
COMMENT ON FUNCTION lizsync.get_event_sql(pevent_id bigint, puid_column text, excluded_columns text[]) IS '
Get the SQL to use for replay from a audit log event

Arguments:
   pevent_id:  The event_id of the event in audit.logged_actions to replay
   puid_column: The name of the column with unique uuid values
';


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

