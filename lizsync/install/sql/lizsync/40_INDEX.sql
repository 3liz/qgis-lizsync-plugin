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

-- logged_actions_action_idx
CREATE INDEX logged_actions_action_idx ON lizsync.logged_actions USING btree (action);


-- logged_actions_action_tstamp_tx_stm_idx
CREATE INDEX logged_actions_action_tstamp_tx_stm_idx ON lizsync.logged_actions USING btree (action_tstamp_stm);


-- logged_actions_relid_idx
CREATE INDEX logged_actions_relid_idx ON lizsync.logged_actions USING btree (relid);


--
-- PostgreSQL database dump complete
--

