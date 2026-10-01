-- Additive outcome layer. Existing queued tasks remain the durable execution wakeup.
-- No legacy task or project-wide snapshot is inferred to be verified work.
CREATE TABLE public.work_items (
    work_id text PRIMARY KEY,
    owner_id text NOT NULL REFERENCES public.actors,
    project_id text NOT NULL REFERENCES public.projects,
    accountable_bot_id text NOT NULL REFERENCES public.bots,
    state text NOT NULL CHECK(state IN ('queued','active','waiting','paused','stopping','completed','failed','cancelled')),
    scope_revision integer NOT NULL CHECK(scope_revision > 0),
    state_revision integer NOT NULL CHECK(state_revision > 0),
    snapshot jsonb NOT NULL
);
CREATE INDEX work_items_owner_project ON public.work_items(owner_id, project_id);
CREATE TABLE public.work_steps (
    work_id text NOT NULL REFERENCES public.work_items,
    scope_revision integer NOT NULL CHECK(scope_revision > 0),
    step_key text NOT NULL,
    task_id text NOT NULL UNIQUE REFERENCES public.tasks,
    PRIMARY KEY(work_id, scope_revision, step_key)
);
CREATE TABLE public.work_artifacts (
    artifact_id text PRIMARY KEY,
    work_id text NOT NULL REFERENCES public.work_items,
    task_id text NOT NULL REFERENCES public.tasks,
    attempt_id text NOT NULL REFERENCES public.attempts,
    sha256 text NOT NULL CHECK(sha256 ~ '^[a-f0-9]{64}$'),
    content text NOT NULL,
    snapshot jsonb NOT NULL,
    UNIQUE(work_id, task_id, sha256)
);
CREATE TABLE public.work_verifications (
    verification_id text PRIMARY KEY,
    work_id text NOT NULL REFERENCES public.work_items,
    task_id text NOT NULL REFERENCES public.tasks,
    artifact_id text REFERENCES public.work_artifacts,
    snapshot jsonb NOT NULL,
    UNIQUE(work_id, task_id)
);
