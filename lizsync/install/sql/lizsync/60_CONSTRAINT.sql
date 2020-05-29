--
-- PostgreSQL database dump
--

-- Dumped from database version 9.6.17
-- Dumped by pg_dump version 9.6.17

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

-- conflicts conflicts_pkey
ALTER TABLE ONLY lizsync.conflicts
    ADD CONSTRAINT conflicts_pkey PRIMARY KEY (id);


-- history history_pkey
ALTER TABLE ONLY lizsync.history
    ADD CONSTRAINT history_pkey PRIMARY KEY (sync_id);


-- server_metadata server_metadata_pkey
ALTER TABLE ONLY lizsync.server_metadata
    ADD CONSTRAINT server_metadata_pkey PRIMARY KEY (server_id);


-- server_metadata server_metadata_server_name_key
ALTER TABLE ONLY lizsync.server_metadata
    ADD CONSTRAINT server_metadata_server_name_key UNIQUE (server_name);


-- synchronized_schemas synchronized_schemas_pkey
ALTER TABLE ONLY lizsync.synchronized_schemas
    ADD CONSTRAINT synchronized_schemas_pkey PRIMARY KEY (server_id);


-- sys_structure_metadonnee sys_structure_metadonnee_pkey
ALTER TABLE ONLY lizsync.sys_structure_metadonnee
    ADD CONSTRAINT sys_structure_metadonnee_pkey PRIMARY KEY (id);


--
-- PostgreSQL database dump complete
--

