UPDATE "test"."pluviometers" SET
    "nom" = concat(nom, ' by clone a'),
    geom = ST_Translate(geom, 5, 10)
WHERE "ogc_fid" = '1';

UPDATE "test"."montpellier_sub_districts" SET
    libsquart = concat(libsquart, ' by clone a')
WHERE "squartmno" = 'HOS';

INSERT INTO "test"."pluviometers" (id, nom, geom)
VALUES (
    99, 'pluvio99', '01010000206A0800002F0DFEA05C612741B30B19D64FF75741'
);
DELETE FROM "test"."montpellier_districts"
WHERE quartmno = 'HO';

UPDATE "test"."montpellier_sub_districts" SET
    libsquart = concat(libsquart, ' by clone A')
WHERE ogc_fid = 22;

