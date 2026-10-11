ALTER TABLE public.tasks
    ADD COLUMN hermes_session_id text,
    ADD CONSTRAINT tasks_hermes_session_id_format
        CHECK (hermes_session_id IS NULL OR hermes_session_id ~ '^(rh-[a-f0-9]{64}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$');
