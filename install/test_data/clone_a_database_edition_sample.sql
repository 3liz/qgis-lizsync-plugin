UPDATE "test"."pluviometers" SET "nom" = 'pluvio zero from clone a' WHERE "nom" = 'pluvio0';
UPDATE "test"."montpellier_sub_districts" SET libsquart = libsquart || ' from clone a' WHERE "squartmno" = 'HOS';
INSERT INTO "test"."pluviometers" (id, nom, geom) VALUES (99, 'pluvio99', '01010000206A0800002F0DFEA05C612741B30B19D64FF75741');
DELETE FROM "test"."montpellier_districts" WHERE quartmno = 'HO';
