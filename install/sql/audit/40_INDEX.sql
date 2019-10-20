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

-- logged_actions_action_idx
CREATE INDEX logged_actions_action_idx ON audit.logged_actions USING btree (action);


-- logged_actions_action_tstamp_tx_stm_idx
CREATE INDEX logged_actions_action_tstamp_tx_stm_idx ON audit.logged_actions USING btree (action_tstamp_stm);


-- logged_actions_relid_idx
CREATE INDEX logged_actions_relid_idx ON audit.logged_actions USING btree (relid);


--
-- PostgreSQL database dump complete
--

