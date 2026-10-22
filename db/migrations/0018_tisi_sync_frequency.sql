-- 0018: TH_TISI_MANDATORY kept sync_frequency_minutes = 0 from the discovery-only 0005 seed, so the scheduler (which
-- schedules sources with sync_frequency_minutes > 0) never picked it up even after 0016 activated it. 6 hours, like
-- every other live source.
UPDATE sources SET sync_frequency_minutes = 360 WHERE code = 'TH_TISI_MANDATORY';
