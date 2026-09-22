-- One small durable coordination snapshot per project. It correlates existing
-- tasks and release artifacts; it does not duplicate task contents or files.
CREATE TABLE public.project_coordination (
    project_id text PRIMARY KEY REFERENCES public.projects(project_id),
    revision integer NOT NULL CHECK(revision > 0),
    phase text NOT NULL,
    active_task_id text REFERENCES public.tasks(task_id),
    snapshot jsonb NOT NULL
);

ALTER TABLE public.local_sessions
    ADD COLUMN remembered boolean NOT NULL DEFAULT false;

-- A project coordinator and its specialist may share the same bounded bot
-- grant while retaining distinct signed Buzz identities.
ALTER TABLE public.conversation_links
    DROP CONSTRAINT conversation_links_principal_id_bot_id_project_id_key;
