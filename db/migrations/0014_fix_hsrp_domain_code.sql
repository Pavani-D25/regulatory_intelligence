-- 0014: fix a mistake in 0012_restore_vocab.sql, found while running the Thailand-parity test suite from scratch.
-- 0012 copied domain rows from the pre-v4B seed file literally, including 'HSRP' - but migration 0006 had already
-- renamed that topic to the universal 'number_plates' (upper-cased 'NUMBER_PLATES' by 0007's copy into `domains`).
-- On a database where 0006/0007 ran against real seed data, this left both 'HSRP' and 'NUMBER_PLATES' rows in
-- `domains`; on the one database where 0012 was the only source of domain rows (0006/0007 had nothing to rename),
-- it left the wrong code with no 'NUMBER_PLATES' at all. Both are fixed the same way: rename 'HSRP' to
-- 'NUMBER_PLATES' if that code doesn't already exist, otherwise drop the now-duplicate 'HSRP' row.
UPDATE domains SET code = 'NUMBER_PLATES', name = 'Number plates (incl. high security registration plates)'
  WHERE code = 'HSRP' AND NOT EXISTS (SELECT 1 FROM domains WHERE code = 'NUMBER_PLATES');
DELETE FROM domains WHERE code = 'HSRP' AND EXISTS (SELECT 1 FROM domains WHERE code = 'NUMBER_PLATES');
