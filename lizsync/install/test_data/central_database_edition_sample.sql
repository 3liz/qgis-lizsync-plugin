-- Modify some data in central database
INSERT INTO "test"."montpellier_districts" (fid,uid,url,geom,libquart,quartmno) VALUES (null,'b2ad98a8-1627-7eb4-fc6f-5a7ce2583bd5',null,'01030000206A0800000100000007000000E5E73A572F5727413A0A1522ADF95741FFF671BBEF572741F0C8BED214F95741D64C372B7460274176554998A4F8574179619B20F96927410DE737C6FCF8574179619B20F9692741A4719FD332FA5741C40C5FB54860274112451D2DFBF95741E5E73A572F5727413A0A1522ADF95741','Nouveau quartier','NEWQUART');
UPDATE "test"."montpellier_sub_districts" SET libsquart = 'La gambette' WHERE libsquart = 'Gambetta';
DELETE FROM "test"."montpellier_sub_districts" WHERE libsquart = 'Gares';
UPDATE "test"."pluviometers" SET nom = 'le dix-huit' WHERE nom = 'pluvio18';
UPDATE "test"."pluviometers" SET geom = '01010000206A0800009E6D82E3057527418D1435F092F65741' WHERE nom = 'pluvio3';
INSERT INTO "test"."pluviometers" (id, nom, geom) VALUES (98, 'pluvio98', ST_SetSRID(ST_MakePoint(771164, 6281875),2154));
