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
    WITH
    event AS (
        SELECT * FROM audit.logged_actions WHERE event_id = pevent_id
    )
    -- get primary key names
    , where_pks AS (
        SELECT array_agg(uid_column) as pkey_fields
        FROM audit.logged_relations r
        JOIN event ON relation_name = (quote_ident(schema_name) || '.' || quote_ident(table_name))
    )
    -- create where clause with uid column
    -- not with primary keys, to manage multi-way sync
    , where_uid AS (
        SELECT '"' || puid_column || '" = ' || quote_literal(row_data->puid_column) AS where_clause
        FROM event
    )
    SELECT INTO sql
        CASE
            WHEN action = 'I' THEN
                'INSERT INTO "' || schema_name || '"."' || table_name || '"' ||
                ' ('||(
                    SELECT string_agg('"' || key || '"', ',')
                    FROM each(row_data)
                    WHERE key != ANY(pkey_fields))||') VALUES ' ||
                '('||(
                    SELECT string_agg(CASE WHEN value IS NULL THEN 'NULL' ELSE quote_literal(value) END, ',')
                    FROM EACH(row_data)
                    WHERE key != ANY(pkey_fields))||')'
            WHEN action = 'D' THEN
                'DELETE FROM "' || schema_name || '"."' || table_name || '"' ||
                ' WHERE ' || where_clause
            WHEN action = 'U' then
                'UPDATE "' || schema_name || '"."' || table_name || '"' ||
                ' SET ' || (
                    SELECT string_agg('"' || key || '"' || ' = ' ||
                    CASE
                        WHEN value IS NULL THEN 'NULL'
                        ELSE quote_literal(value)
                    END, ','
                    ) FROM each(changed_fields)
                    WHERE key != ANY(pkey_fields)
                ) ||
                ' WHERE ' || where_clause
        END
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

