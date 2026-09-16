-- A private Buzz project conversation may contain several assigned agents.
-- Each agent retains its own signed link and outbox while sharing the exact
-- project channel. The expression index prevents the same agent identity from
-- being registered twice in one channel.
ALTER TABLE public.conversation_links
    DROP CONSTRAINT conversation_links_channel_id_key;

CREATE UNIQUE INDEX conversation_links_channel_agent_key
    ON public.conversation_links(channel_id, (snapshot->>'agent_pubkey'));
