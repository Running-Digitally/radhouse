-- Initial fixture schema, never a production migration or upgrade.
-- The harness must first CREATE its fresh random database, then create and seed:
-- CREATE TABLE public.fixture_ownership (
--   singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
--   run_id text UNIQUE NOT NULL
-- );
-- INSERT INTO public.fixture_ownership(run_id) VALUES (<the harness run id>);
-- Missing ownership, a name/marker mismatch, and any other preexisting public
-- relation are refusals. The runtime DML role is granted no CREATE/schema power.
DO $$
DECLARE
    owned_run text;
    marker_count integer;
BEGIN
    IF to_regclass('public.fixture_ownership') IS NULL THEN
        RAISE EXCEPTION 'fixture ownership missing';
    END IF;
    SELECT min(run_id), count(*) INTO owned_run, marker_count
      FROM public.fixture_ownership WHERE singleton;
    IF marker_count <> 1 OR owned_run !~ '^[0-9a-f]{8,48}$'
       OR current_database() <> 'radhouse_vs0_' || owned_run THEN
        RAISE EXCEPTION 'fixture ownership mismatch';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S','f')
          AND c.relname <> 'fixture_ownership'
    ) THEN
        RAISE EXCEPTION 'fixture database is not fresh';
    END IF;
END $$;

-- The harness executes the same packaged migration used by retained stores
-- only after this ownership and freshness guard passes.
