-- Projects explicitly select eligible agents. Existing installations preserve
-- their effective access by backfilling the former member/grant intersection;
-- newly created projects must name their agents.
CREATE TABLE public.project_bots (
    project_id text NOT NULL REFERENCES public.projects(project_id),
    bot_id text NOT NULL REFERENCES public.bots(bot_id),
    PRIMARY KEY(project_id,bot_id)
);

INSERT INTO public.project_bots(project_id,bot_id)
SELECT DISTINCT membership.project_id, grant_row.bot_id
FROM public.project_members AS membership
JOIN public.bot_grants AS grant_row USING(principal_id)
ON CONFLICT DO NOTHING;
