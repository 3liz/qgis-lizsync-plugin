BEGIN;

CREATE OR REPLACE FUNCTION lizsync.compare_tables(p_schema_name text, p_table_name text) RETURNS TABLE(uid uuid, status text, clone_table_values public.hstore, central_table_values public.hstore)
    LANGUAGE plpgsql
    AS $_$
DECLARE
    pkeys text[];
    sqltemplate text;
BEGIN

    -- Get array of primary key field(s)
    SELECT array_agg(uid_column) as pkey_fields
    INTO pkeys
    FROM audit.logged_relations r
    WHERE relation_name = (quote_ident(p_schema_name) || '.' || quote_ident(p_table_name))
    ;

    -- Compare data
    sqltemplate = '
    SELECT
        coalesce(t1.uid, t2.uid) AS uid,
        CASE
            WHEN t1.uid IS NULL THEN ''not in table 1''
            WHEN t2.uid IS NULL THEN ''not in table 2''
            ELSE ''table 1 != table 2''
        END AS status,
        (hstore(t1.*) - ''%1$s''::text[]) - (hstore(t2) - ''%1$s''::text[]) AS values_in_table_1,
        (hstore(t2.*) - ''%1$s''::text[]) - (hstore(t1) - ''%1$s''::text[]) AS values_in_table_2
    FROM "%2$s"."%3$s" AS t1
    FULL JOIN "central_%2$s"."%3$s" AS t2
        ON t1.uid = t2.uid
    WHERE
        ((hstore(t1.*) - ''%1$s''::text[]) != (hstore(t2.*) - ''%1$s''::text[]))
        OR (t1.uid IS NULL)
        OR (t2.uid IS NULL)
    ';

    RETURN QUERY
    EXECUTE format(sqltemplate,
        pkeys,
        p_schema_name,
        p_table_name
    );

END;
$_$;

COMMIT;
