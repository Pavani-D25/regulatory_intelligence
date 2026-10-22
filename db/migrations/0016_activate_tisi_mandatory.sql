-- 0016: TH_TISI_MANDATORY now has a working crawler (regtrack/sources/thailand_tisi.py, TH-3), so it should
-- no longer sit at the "discovery-only, no scraper yet" is_active=false that 0007_thailand.sql seeded for
-- every Thailand source. Without this, the scheduler's main() loop (which only schedules is_active sources)
-- would silently never pick this one up even once it is running.
UPDATE sources SET is_active = true WHERE code = 'TH_TISI_MANDATORY';
