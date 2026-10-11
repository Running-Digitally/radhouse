-- One durable scheduling position per task; polling does not grow task history.
CREATE TABLE public.task_coordination (
    task_id text PRIMARY KEY REFERENCES public.tasks(task_id) ON DELETE CASCADE,
    turn bigserial NOT NULL UNIQUE
);
