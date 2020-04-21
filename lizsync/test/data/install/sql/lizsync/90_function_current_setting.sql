-- PostgreSQL 9.5: add fallback current_setting function
CREATE OR REPLACE FUNCTION public.current_setting(myvar text, myretex boolean) RETURNS text AS $$
DECLARE
    mytext text;
BEGIN
    BEGIN
        mytext := current_setting(myvar)::text;
    EXCEPTION
        WHEN SQLSTATE '42704' THEN
            mytext := NULL;
    END;
    RETURN mytext;
END;
$$ LANGUAGE plpgsql;
