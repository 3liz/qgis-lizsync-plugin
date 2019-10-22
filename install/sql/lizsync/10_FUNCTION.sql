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

-- add_uid_columns(text, text)
CREATE FUNCTION lizsync.add_uid_columns(p_schema_name text, p_table_name text) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
  query text;
BEGIN

    BEGIN
        SELECT INTO query
        concat(
            ' ALTER TABLE ' || quote_ident(p_schema_name) || '.' || quote_ident(p_table_name) ||
            ' ADD COLUMN uid uuid DEFAULT md5(random()::text || clock_timestamp()::text)::uuid ' ||
            ' UNIQUE NOT NULL'
        );
        execute query;
        RAISE NOTICE 'uid column created for % %', quote_ident(p_schema_name), quote_ident(p_table_name);
        RETURN True;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'ERROR - uid column already exists';
        RETURN False;
    END;

END;
$$;


-- get_event_sql(bigint, text)
CREATE FUNCTION lizsync.get_event_sql(pevent_id bigint, puid_column text) RETURNS text
    LANGUAGE plpgsql
    AS $$
DECLARE
  sql text;
BEGIN
    with
    event as (
        select * from audit.logged_actions where event_id = pevent_id
    )
    -- get primary key names
    , where_pks as (
        select array_agg(uid_column) as pkey_fields
        from audit.logged_relations r
        join event on relation_name = (quote_ident(schema_name) || '.' || quote_ident(table_name))
    )
    -- create where clause with uid column
    -- not with primary keys, to manage multi-way sync
    , where_uid as (
        select puid_column || '=' || quote_literal(row_data->puid_column) as where_clause
        from event
    )
    select into sql
        case
            when action = 'I' then
                'INSERT INTO "' || schema_name || '"."' || table_name || '"' ||
                ' ('||(select string_agg(key, ',') from each(row_data) WHERE key != ANY(pkey_fields))||') VALUES ' ||
                '('||(select string_agg(case when value is null then 'null' else quote_literal(value) end, ',') from each(row_data) WHERE key != ANY(pkey_fields))||')'
            when action = 'D' then
                'DELETE FROM "' || schema_name || '"."' || table_name || '"' ||
                ' WHERE ' || where_clause
            when action = 'U' then
                'UPDATE "' || schema_name || '"."' || table_name || '"' ||
                ' SET ' || (select string_agg(key || '=' || case when value is null then 'null' else quote_literal(value) end, ',') from each(changed_fields) WHERE key != ANY(pkey_fields)) ||
                ' WHERE ' || where_clause
        end
    from
        event, where_pks, where_uid
    ;
    RETURN sql;
END;
$$;


-- FUNCTION get_event_sql(pevent_id bigint, puid_column text)
COMMENT ON FUNCTION lizsync.get_event_sql(pevent_id bigint, puid_column text) IS '
Get the SQL to use for replay from a audit log event

Arguments:
   pevent_id:  The event_id of the event in audit.logged_actions to replay
   puid_column: The name of the column with unique uuid values
';


--
-- PostgreSQL database dump complete
--

