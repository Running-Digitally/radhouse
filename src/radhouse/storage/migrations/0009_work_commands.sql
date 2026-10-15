-- Work-level receipt links extend the existing principal-scoped command ledger.
-- Commands, their state transition, delivery identity and receipt commit together.
CREATE TABLE public.work_commands (
    principal_id text NOT NULL,
    command_key text NOT NULL,
    work_id text NOT NULL REFERENCES public.work_items,
    snapshot jsonb NOT NULL,
    PRIMARY KEY (principal_id, command_key),
    FOREIGN KEY (principal_id, command_key) REFERENCES public.commands
);
CREATE INDEX work_commands_pending ON public.work_commands(work_id)
    WHERE snapshot->>'application_state' IN ('accepted','unknown');
