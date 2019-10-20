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

-- logged_actions logged_actions_pkey
ALTER TABLE ONLY audit.logged_actions
    ADD CONSTRAINT logged_actions_pkey PRIMARY KEY (event_id);


-- logged_relations logged_relations_pkey
ALTER TABLE ONLY audit.logged_relations
    ADD CONSTRAINT logged_relations_pkey PRIMARY KEY (relation_name, uid_column);


--
-- PostgreSQL database dump complete
--

