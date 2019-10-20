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

-- FUNCTION get_event_sql(pevent_id bigint, puid_column text)
COMMENT ON FUNCTION lizsync.get_event_sql(pevent_id bigint, puid_column text) IS '
Get the SQL to use for replay from a audit log event

Arguments:
   pevent_id:  The event_id of the event in audit.logged_actions to replay
   puid_column: The name of the column with unique uuid values
';


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

