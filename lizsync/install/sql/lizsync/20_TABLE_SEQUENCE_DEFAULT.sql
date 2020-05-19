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

SET default_tablespace = '';

SET default_with_oids = false;

-- conflicts
CREATE TABLE lizsync.conflicts (
    id bigint NOT NULL,
    conflict_time timestamp with time zone DEFAULT now() NOT NULL,
    object_table text,
    object_uid uuid,
    clone_id uuid,
    central_event_id bigint,
    central_event_timestamp timestamp with time zone,
    central_sql text,
    clone_sql text,
    rejected text,
    rule_applied text
);


-- conflicts
COMMENT ON TABLE lizsync.conflicts IS 'Store conflicts resolution made during bidirectionnal database synchronizations.';


-- conflicts_id_seq
CREATE SEQUENCE lizsync.conflicts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


-- conflicts_id_seq
ALTER SEQUENCE lizsync.conflicts_id_seq OWNED BY lizsync.conflicts.id;


-- history
CREATE TABLE lizsync.history (
    sync_id uuid DEFAULT (md5(((random())::text || (clock_timestamp())::text)))::uuid NOT NULL,
    sync_time timestamp with time zone DEFAULT now() NOT NULL,
    server_from text NOT NULL,
    server_to text[],
    min_event_id integer,
    max_event_id integer,
    max_action_tstamp_tx timestamp with time zone,
    sync_type text NOT NULL,
    sync_status text DEFAULT 'pending'::text NOT NULL
);


-- server_metadata
CREATE TABLE lizsync.server_metadata (
    server_id uuid DEFAULT (md5(((random())::text || (clock_timestamp())::text)))::uuid NOT NULL,
    server_name text DEFAULT (md5(((random())::text || (clock_timestamp())::text)))::uuid NOT NULL
);


-- synchronized_schemas
CREATE TABLE lizsync.synchronized_schemas (
    server_id uuid NOT NULL,
    sync_schemas jsonb NOT NULL
);


-- synchronized_schemas
COMMENT ON TABLE lizsync.synchronized_schemas IS 'List of schemas to synchronize per slave server id. This list works as a white list. Only listed schemas will be synchronized for each server ids.';


-- sys_structure_metadonnee
CREATE TABLE lizsync.sys_structure_metadonnee (
    id integer NOT NULL,
    date_ajout date DEFAULT (now())::date NOT NULL,
    version text NOT NULL,
    description text
);


-- sys_structure_metadonnee
COMMENT ON TABLE lizsync.sys_structure_metadonnee IS 'Database structure metadata used for migration by QGIS plugin';


-- sys_structure_metadonnee_id_seq
CREATE SEQUENCE lizsync.sys_structure_metadonnee_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


-- sys_structure_metadonnee_id_seq
ALTER SEQUENCE lizsync.sys_structure_metadonnee_id_seq OWNED BY lizsync.sys_structure_metadonnee.id;


-- conflicts id
ALTER TABLE ONLY lizsync.conflicts ALTER COLUMN id SET DEFAULT nextval('lizsync.conflicts_id_seq'::regclass);


-- sys_structure_metadonnee id
ALTER TABLE ONLY lizsync.sys_structure_metadonnee ALTER COLUMN id SET DEFAULT nextval('lizsync.sys_structure_metadonnee_id_seq'::regclass);


--
-- PostgreSQL database dump complete
--

