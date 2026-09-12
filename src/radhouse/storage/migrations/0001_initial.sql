CREATE TABLE public.radhouse_metadata (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
    deployment_id text UNIQUE NOT NULL,
    schema_version integer NOT NULL CHECK(schema_version>0),
    migration_sha256 text NOT NULL CHECK(migration_sha256 ~ '^[0-9a-f]{64}$')
);
CREATE TABLE public.actors (
    principal_id text PRIMARY KEY,
    role text NOT NULL CHECK(role IN ('admin','operator','viewer')),
    active boolean NOT NULL DEFAULT true
);
CREATE TABLE public.projects (
    project_id text PRIMARY KEY,
    owner_id text NOT NULL REFERENCES public.actors,
    display_name text NOT NULL,
    state text NOT NULL CHECK(state IN ('active','archived'))
);
CREATE TABLE public.bots (
    bot_id text PRIMARY KEY,
    display_name text NOT NULL,
    role_name text NOT NULL,
    provider_binding text NOT NULL,
    state text NOT NULL CHECK(state IN ('ready','busy','maintenance','unavailable'))
);
CREATE TABLE public.bot_grants (
    principal_id text NOT NULL REFERENCES public.actors,
    bot_id text NOT NULL REFERENCES public.bots,
    PRIMARY KEY(principal_id,bot_id)
);
CREATE TABLE public.project_members (
    principal_id text NOT NULL REFERENCES public.actors,
    project_id text NOT NULL REFERENCES public.projects,
    PRIMARY KEY(principal_id,project_id)
);
CREATE TABLE public.channel_bindings (
    channel text NOT NULL,
    subject text NOT NULL,
    conversation_id text NOT NULL,
    principal_id text NOT NULL REFERENCES public.actors,
    project_id text NOT NULL REFERENCES public.projects,
    revision integer NOT NULL CHECK(revision>0),
    active boolean NOT NULL DEFAULT true,
    PRIMARY KEY(channel,subject,conversation_id)
);
CREATE TABLE public.tasks (
    task_id text PRIMARY KEY,
    owner_id text NOT NULL REFERENCES public.actors,
    bot_id text NOT NULL REFERENCES public.bots,
    project_id text NOT NULL REFERENCES public.projects,
    task_revision integer NOT NULL CHECK(task_revision>0),
    state_revision integer NOT NULL CHECK(state_revision>0),
    phase text NOT NULL CHECK(phase IN ('queued','active','recovering','stopping','closed')),
    outcome text CHECK(outcome IN ('completed','cancelled','failed')),
    budget_remaining integer NOT NULL CHECK(budget_remaining>=0),
    attempt_id text,
    snapshot jsonb NOT NULL,
    CHECK((phase='closed')=(outcome IS NOT NULL))
);
CREATE TABLE public.task_revisions (
    task_id text NOT NULL REFERENCES public.tasks,
    revision integer NOT NULL CHECK(revision>0),
    snapshot jsonb NOT NULL,
    PRIMARY KEY(task_id,revision)
);
CREATE TABLE public.attempts (
    attempt_id text PRIMARY KEY,
    task_id text NOT NULL REFERENCES public.tasks,
    generation integer NOT NULL CHECK(generation>0),
    worker_id text NOT NULL,
    state text NOT NULL,
    is_current boolean NOT NULL,
    snapshot jsonb NOT NULL,
    UNIQUE(task_id,generation),
    UNIQUE(task_id,attempt_id)
);
CREATE UNIQUE INDEX one_current_attempt ON public.attempts(task_id) WHERE is_current;
ALTER TABLE public.tasks ADD CONSTRAINT current_attempt_task
    FOREIGN KEY(task_id,attempt_id) REFERENCES public.attempts(task_id,attempt_id)
    DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE public.claims (
    attempt_id text PRIMARY KEY,
    task_id text NOT NULL,
    bot_id text NOT NULL,
    resource_key text NOT NULL,
    active boolean NOT NULL,
    FOREIGN KEY(task_id,attempt_id) REFERENCES public.attempts(task_id,attempt_id)
);
CREATE UNIQUE INDEX one_active_resource_claim
    ON public.claims(bot_id,resource_key) WHERE active;
CREATE TABLE public.budget_reservations (
    attempt_id text PRIMARY KEY,
    task_id text NOT NULL,
    amount integer NOT NULL CHECK(amount>0),
    FOREIGN KEY(task_id,attempt_id) REFERENCES public.attempts(task_id,attempt_id)
);
CREATE TABLE public.operations (
    operation_key text PRIMARY KEY,
    task_id text NOT NULL,
    attempt_id text NOT NULL,
    state text NOT NULL CHECK(state IN ('prepared','submitted','confirmed','unknown','rejected')),
    snapshot jsonb NOT NULL,
    FOREIGN KEY(task_id,attempt_id) REFERENCES public.attempts(task_id,attempt_id)
);
CREATE TABLE public.agent_dispatches (
    dispatch_key text PRIMARY KEY,
    task_id text NOT NULL,
    attempt_id text NOT NULL,
    state text NOT NULL CHECK(state IN ('prepared','submitted','accepted','unknown','closed')),
    run_id text UNIQUE,
    snapshot jsonb NOT NULL,
    FOREIGN KEY(task_id,attempt_id) REFERENCES public.attempts(task_id,attempt_id)
);
CREATE TABLE public.reviews (
    review_id text PRIMARY KEY,
    task_id text NOT NULL REFERENCES public.tasks,
    reviewer_id text NOT NULL REFERENCES public.actors,
    revision integer NOT NULL CHECK(revision>0),
    state text NOT NULL,
    snapshot jsonb NOT NULL,
    UNIQUE(task_id,review_id)
);
CREATE TABLE public.publications (
    task_id text PRIMARY KEY REFERENCES public.tasks,
    publication_id text NOT NULL UNIQUE,
    review_id text NOT NULL UNIQUE,
    digest text NOT NULL,
    snapshot jsonb NOT NULL,
    FOREIGN KEY(task_id,review_id) REFERENCES public.reviews(task_id,review_id)
);
CREATE TABLE public.commands (
    principal_id text NOT NULL REFERENCES public.actors,
    command_key text NOT NULL,
    task_id text NOT NULL REFERENCES public.tasks,
    snapshot jsonb NOT NULL,
    PRIMARY KEY(principal_id,command_key)
);
CREATE TABLE public.deliveries (
    channel text NOT NULL,
    event_id text NOT NULL,
    task_id text NOT NULL REFERENCES public.tasks,
    principal_id text NOT NULL REFERENCES public.actors,
    snapshot jsonb NOT NULL,
    PRIMARY KEY(channel,event_id)
);
CREATE TABLE public.events (
    cursor bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id text NOT NULL REFERENCES public.tasks,
    kind text NOT NULL,
    state_revision integer NOT NULL CHECK(state_revision>0),
    snapshot jsonb NOT NULL
);
CREATE INDEX task_events_after ON public.events(task_id,cursor);
