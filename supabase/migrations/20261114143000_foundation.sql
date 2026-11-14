-- Internal service schema. No browser grants or user-facing policies in Phase 1.
BEGIN;
CREATE TABLE public.agents (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL UNIQUE,
 status text NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','idle','running','error')),
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE public.channels (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL,
 platform text NOT NULL, external_id text,
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(platform,external_id));
CREATE TABLE public.content_ideas (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), channel_id uuid REFERENCES public.channels(id),
 topic text NOT NULL CHECK(length(topic) BETWEEN 3 AND 300), concept jsonb,
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE public.video_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), idea_id uuid NOT NULL REFERENCES public.content_ideas(id),
 agent_id uuid REFERENCES public.agents(id), provider text NOT NULL,
 status text NOT NULL CHECK(status IN ('queued','running','succeeded','failed')),
 result jsonb, error text, created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz);
CREATE TABLE public.publications (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), job_id uuid NOT NULL REFERENCES public.video_jobs(id),
 channel_id uuid NOT NULL REFERENCES public.channels(id), external_id text,
 status text NOT NULL CHECK(status IN ('draft','scheduled','published','failed')),
 published_at timestamptz, UNIQUE(channel_id,external_id));
CREATE TABLE public.performance_metrics (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), publication_id uuid NOT NULL REFERENCES public.publications(id),
 measured_at timestamptz NOT NULL, views bigint NOT NULL DEFAULT 0 CHECK(views>=0),
 likes bigint NOT NULL DEFAULT 0 CHECK(likes>=0),
 UNIQUE(publication_id,measured_at));
CREATE TABLE public.ai_usage (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), job_id uuid NOT NULL REFERENCES public.video_jobs(id),
 provider text NOT NULL, model text NOT NULL,
 input_tokens bigint NOT NULL DEFAULT 0 CHECK(input_tokens>=0),
 output_tokens bigint NOT NULL DEFAULT 0 CHECK(output_tokens>=0),
 cost_usd numeric(18,8) NOT NULL CHECK(cost_usd>=0 AND cost_usd < 'Infinity'::numeric),
 cost_kind text NOT NULL CHECK(cost_kind IN ('mock','reserved','estimated','actual')),
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE public.revenue (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), channel_id uuid NOT NULL REFERENCES public.channels(id),
 amount numeric(18,8) NOT NULL CHECK(amount>=0 AND amount < 'Infinity'::numeric),
 currency text NOT NULL CHECK(currency ~ '^[A-Z]{3}$'), source text NOT NULL,
 external_id text NOT NULL, received_at timestamptz NOT NULL,
 UNIQUE(source,external_id));
CREATE TABLE public.audit_events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), job_id uuid REFERENCES public.video_jobs(id),
 action text NOT NULL, details jsonb NOT NULL DEFAULT '{}',
 created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX content_ideas_channel_id_idx ON public.content_ideas(channel_id);
CREATE INDEX video_jobs_idea_id_idx ON public.video_jobs(idea_id);
CREATE INDEX video_jobs_agent_id_idx ON public.video_jobs(agent_id);
CREATE INDEX publications_job_id_idx ON public.publications(job_id);
CREATE INDEX ai_usage_job_id_idx ON public.ai_usage(job_id);
CREATE INDEX revenue_channel_id_idx ON public.revenue(channel_id);
CREATE INDEX audit_events_job_id_idx ON public.audit_events(job_id);
ALTER TABLE public.agents ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.agents FROM PUBLIC, anon, authenticated;
ALTER TABLE public.channels ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.channels FROM PUBLIC, anon, authenticated;
ALTER TABLE public.content_ideas ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.content_ideas FROM PUBLIC, anon, authenticated;
ALTER TABLE public.video_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.video_jobs FROM PUBLIC, anon, authenticated;
ALTER TABLE public.publications ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.publications FROM PUBLIC, anon, authenticated;
ALTER TABLE public.performance_metrics ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.performance_metrics FROM PUBLIC, anon, authenticated;
ALTER TABLE public.ai_usage ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ai_usage FROM PUBLIC, anon, authenticated;
ALTER TABLE public.revenue ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.revenue FROM PUBLIC, anon, authenticated;
ALTER TABLE public.audit_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.audit_events FROM PUBLIC, anon, authenticated;
COMMIT;
