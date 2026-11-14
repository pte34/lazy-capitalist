BEGIN;
DO $$
DECLARE count_tables int;
BEGIN
 SELECT count(*) INTO count_tables FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND c.relkind='r';
 IF count_tables <> 9 THEN RAISE EXCEPTION 'Expected 9 tables, found %', count_tables; END IF;
 IF EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND c.relkind='r' AND NOT c.relrowsecurity)
 THEN RAISE EXCEPTION 'RLS missing'; END IF;
 IF EXISTS(SELECT 1 FROM pg_tables WHERE schemaname='public' AND
 (has_table_privilege('anon', quote_ident(schemaname)||'.'||quote_ident(tablename), 'SELECT,INSERT,UPDATE,DELETE')
 OR has_table_privilege('authenticated', quote_ident(schemaname)||'.'||quote_ident(tablename), 'SELECT,INSERT,UPDATE,DELETE')))
 THEN RAISE EXCEPTION 'Unexpected browser grants'; END IF;
END $$;
INSERT INTO public.agents(name) VALUES ('Capitalist');
INSERT INTO public.channels(name,platform) VALUES ('Test','demo');
INSERT INTO public.content_ideas(topic,channel_id) SELECT 'Test topic',id FROM public.channels;
INSERT INTO public.video_jobs(idea_id,provider,status) SELECT id,'mock','succeeded' FROM public.content_ideas;
INSERT INTO public.ai_usage(job_id,provider,model,cost_usd,cost_kind) SELECT id,'mock','deterministic',0,'mock' FROM public.video_jobs;
INSERT INTO public.publications(job_id,channel_id,status) SELECT j.id,c.id,'draft' FROM public.video_jobs j CROSS JOIN public.channels c;
INSERT INTO public.performance_metrics(publication_id,measured_at,views) SELECT id,now(),0 FROM public.publications;
INSERT INTO public.revenue(channel_id,amount,currency,source,external_id,received_at) SELECT id,0,'CHF','test','demo-1',now() FROM public.channels;
INSERT INTO public.audit_events(job_id,action) SELECT id,'test_workflow' FROM public.video_jobs;
DO $$
BEGIN
 BEGIN
  INSERT INTO public.ai_usage(job_id,provider,model,cost_usd,cost_kind) SELECT id,'mock','test',-1,'actual' FROM public.video_jobs;
  RAISE EXCEPTION 'Negative cost accepted';
 EXCEPTION WHEN check_violation THEN NULL; END;
 BEGIN
  INSERT INTO public.video_jobs(idea_id,provider,status) VALUES(gen_random_uuid(),'mock','queued');
  RAISE EXCEPTION 'Broken foreign key accepted';
 EXCEPTION WHEN foreign_key_violation THEN NULL; END;
END $$;
-- Check RLS itself with a transient SELECT grant, rolled back at end.
GRANT SELECT ON public.agents TO authenticated;
SET LOCAL ROLE authenticated;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.agents) THEN RAISE EXCEPTION 'RLS leaked rows'; END IF;
END $$;
RESET ROLE;
ROLLBACK;
