DELETE FROM "test"."montpellier_districts"
WHERE quartmno = 'MC';

UPDATE "test"."pluviometers" SET
    "nom" = concat(nom, ' by clone b'),
    geom = ST_Translate(geom, 3, 3)
WHERE "ogc_fid" = '1';
