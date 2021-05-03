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


-- logged_actions
CREATE TABLE lizsync.logged_actions (
    event_id bigint NOT NULL,
    schema_name text NOT NULL,
    table_name text NOT NULL,
    relid oid NOT NULL,
    session_user_name text,
    action_tstamp_tx timestamp with time zone NOT NULL,
    action_tstamp_stm timestamp with time zone NOT NULL,
    action_tstamp_clk timestamp with time zone NOT NULL,
    transaction_id bigint,
    application_name text,
    client_addr inet,
    client_port integer,
    client_query text NOT NULL,
    action text NOT NULL,
    row_data public.hstore,
    changed_fields public.hstore,
    statement_only boolean NOT NULL,
    sync_data jsonb NOT NULL,
    CONSTRAINT logged_actions_action_check CHECK ((action = ANY (ARRAY['I'::text, 'D'::text, 'U'::text, 'T'::text])))
);


-- logged_actions
COMMENT ON TABLE lizsync.logged_actions IS 'History of auditable actions on audited tables, from lizsync.if_modified_func()';


-- logged_actions_event_id_seq
CREATE SEQUENCE lizsync.logged_actions_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


-- logged_actions_event_id_seq
ALTER SEQUENCE lizsync.logged_actions_event_id_seq OWNED BY lizsync.logged_actions.event_id;


-- logged_relations
CREATE TABLE lizsync.logged_relations (
    relation_name text NOT NULL,
    uid_column text NOT NULL
);


-- logged_relations
COMMENT ON TABLE lizsync.logged_relations IS 'Table used to store unique identifier columns for table or views, so that events can be replayed';


-- server_metadata
CREATE TABLE lizsync.server_metadata (
    server_id uuid DEFAULT (md5(((random())::text || (clock_timestamp())::text)))::uuid NOT NULL,
    server_name text DEFAULT (md5(((random())::text || (clock_timestamp())::text)))::uuid NOT NULL
);


-- synchronized_tables
CREATE TABLE lizsync.synchronized_tables (
    server_id uuid NOT NULL,
    sync_tables jsonb NOT NULL
);


-- synchronized_tables
COMMENT ON TABLE lizsync.synchronized_tables IS 'List of tables to synchronise per clone server id. This list works as a white list. Only listed tables will be synchronised for each server ids.';


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


-- logged_actions event_id
ALTER TABLE ONLY lizsync.logged_actions ALTER COLUMN event_id SET DEFAULT nextval('lizsync.logged_actions_event_id_seq'::regclass);


-- sys_structure_metadonnee id
ALTER TABLE ONLY lizsync.sys_structure_metadonnee ALTER COLUMN id SET DEFAULT nextval('lizsync.sys_structure_metadonnee_id_seq'::regclass);


--
-- PostgreSQL database dump complete
--

