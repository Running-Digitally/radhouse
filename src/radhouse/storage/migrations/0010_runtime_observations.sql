-- Existing dispatch snapshots retain the exact runtime observation cursor.
-- Legacy snapshots omit these fields. Schema identity fences older readers.
ALTER TABLE public.agent_dispatches ADD CONSTRAINT runtime_observation_cursor CHECK (
    COALESCE(snapshot->>'observation_sequence','0') ~ '^[0-9]{1,19}$'
    AND COALESCE(snapshot->>'observation_sequence','0')::numeric <= 9223372036854775807
    AND (snapshot->>'observation_digest' IS NULL
         OR snapshot->>'observation_digest' ~ '^[a-f0-9]{64}$')
);
