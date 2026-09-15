-- Display titles are mutable presentation metadata. Their revision is separate
-- from task execution/review state so an owner rename cannot invalidate work,
-- result digests or protected decisions.
ALTER TABLE public.tasks
    ADD COLUMN display_title text,
    ADD COLUMN title_source text NOT NULL DEFAULT 'brief',
    ADD COLUMN title_revision integer NOT NULL DEFAULT 1;

UPDATE public.tasks
SET display_title = left(
    regexp_replace(trim(COALESCE(snapshot->>'brief', 'Task')), '[[:space:]]+', ' ', 'g'),
    100
);

ALTER TABLE public.tasks
    ALTER COLUMN display_title SET NOT NULL,
    ADD CONSTRAINT task_display_title_length
        CHECK (char_length(display_title) BETWEEN 1 AND 100),
    ADD CONSTRAINT task_title_source
        CHECK (title_source IN ('brief', 'agent', 'owner')),
    ADD CONSTRAINT task_title_revision
        CHECK (title_revision > 0);
