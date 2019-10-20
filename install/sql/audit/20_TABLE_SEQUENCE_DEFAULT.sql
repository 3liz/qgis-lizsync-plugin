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

SET default_tablespace = '';

SET default_with_oids = false;

-- logged_actions
CREATE TABLE audit.logged_actions (
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
COMMENT ON TABLE audit.logged_actions IS 'History of auditable actions on audited tables, from audit.if_modified_func()';


-- logged_actions_event_id_seq
CREATE SEQUENCE audit.logged_actions_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


-- logged_actions_event_id_seq
ALTER SEQUENCE audit.logged_actions_event_id_seq OWNED BY audit.logged_actions.event_id;


-- logged_relations
CREATE TABLE audit.logged_relations (
    relation_name text NOT NULL,
    uid_column text NOT NULL
);


-- logged_relations
COMMENT ON TABLE audit.logged_relations IS 'Table used to store unique identifier columns for table or views, so that events can be replayed';


-- logged_actions event_id
ALTER TABLE ONLY audit.logged_actions ALTER COLUMN event_id SET DEFAULT nextval('audit.logged_actions_event_id_seq'::regclass);


--
-- PostgreSQL database dump complete
--

