ALTER TABLE test.pluviometers ADD COLUMN IF NOT EXISTS zid text UNIQUE;
UPDATE test.pluviometers
SET zid = concat('PREFIX_', ogc_fid::text)
;
ALTER TABLE test.montpellier_districts ADD COLUMN IF NOT EXISTS zid text UNIQUE;
UPDATE test.montpellier_districts
SET zid = concat('PREFIX_', ogc_fid::text)
;
ALTER TABLE test.montpellier_sub_districts ADD COLUMN IF NOT EXISTS zid text UNIQUE;
UPDATE test.montpellier_sub_districts
SET zid = concat('PREFIX_', ogc_fid::text)
;

CREATE OR REPLACE FUNCTION test.zid_auto()
RETURNS TRIGGER
LANGUAGE plpgsql
AS
$$
BEGIN

IF TG_OP = 'INSERT' THEN

    EXECUTE 'SELECT ''PREFIX_''||max(to_number(substring(zid,8),''999999999999''))+1 FROM ' || quote_ident(TG_TABLE_SCHEMA) || '.' || quote_ident(TG_TABLE_NAME)
    INTO NEW.zid;
    RETURN NEW;

END IF;

END;
$$;

CREATE TRIGGER zid_auto_test
BEFORE INSERT ON test.pluviometers
FOR EACH ROW EXECUTE PROCEDURE test.zid_auto();
CREATE TRIGGER zid_auto_test
BEFORE INSERT ON test.montpellier_districts
FOR EACH ROW EXECUTE PROCEDURE test.zid_auto();
CREATE TRIGGER zid_auto_test
BEFORE INSERT ON test.montpellier_sub_districts
FOR EACH ROW EXECUTE PROCEDURE test.zid_auto();
