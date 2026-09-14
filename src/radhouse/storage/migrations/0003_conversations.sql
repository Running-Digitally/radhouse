-- Additive conversation transport state. Task and permission authority remain
-- in the existing controller tables; relay delivery has no execution authority.
CREATE TABLE conversation_links (
    link_id text PRIMARY KEY,
    channel_id text UNIQUE NOT NULL,
    principal_id text NOT NULL REFERENCES actors(principal_id),
    bot_id text NOT NULL REFERENCES bots(bot_id),
    project_id text NOT NULL REFERENCES projects(project_id),
    snapshot jsonb NOT NULL,
    enrollment jsonb,
    cursor_time bigint NOT NULL,
    scan_time bigint,
    scan_id text,
    error_code text,
    UNIQUE (principal_id,bot_id,project_id)
);
CREATE TABLE conversation_messages (
    message_id text PRIMARY KEY,
    link_id text NOT NULL REFERENCES conversation_links(link_id),
    task_id text REFERENCES tasks(task_id),
    snapshot jsonb NOT NULL,
    route jsonb,
    source_event jsonb,
    processed boolean NOT NULL DEFAULT false,
    sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE
);
CREATE INDEX conversation_messages_link ON conversation_messages(link_id,sequence);
CREATE TABLE conversation_outbox (
    delivery_key text PRIMARY KEY,
    link_id text NOT NULL REFERENCES conversation_links(link_id),
    message_id text NOT NULL REFERENCES conversation_messages(message_id),
    event jsonb NOT NULL,
    delivered boolean NOT NULL DEFAULT false,
    error_code text
);
