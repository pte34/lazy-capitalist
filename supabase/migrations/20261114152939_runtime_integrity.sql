-- Additive constraints/indexes; v1 and the original public migration stay unchanged.
BEGIN;
SET LOCAL search_path=lc_runtime,pg_catalog;
ALTER TABLE job_metadata ADD CONSTRAINT metadata_job_fk FOREIGN KEY(job_id) REFERENCES video_jobs(id);
ALTER TABLE cost_estimates ADD CONSTRAINT estimates_job_fk FOREIGN KEY(job_id) REFERENCES video_jobs(id);
ALTER TABLE submissions ADD CONSTRAINT submission_job_fk FOREIGN KEY(job_id) REFERENCES video_jobs(id);
ALTER TABLE platform_events ADD CONSTRAINT platform_audit_fk FOREIGN KEY(audit_id) REFERENCES audit_events(id);
ALTER TABLE report_alerts ADD CONSTRAINT alert_event_fk FOREIGN KEY(event_id) REFERENCES audit_events(id);
ALTER TABLE order_budget ADD CONSTRAINT nonnegative_budget CHECK(estimate_micro>=0 AND reserved_micro>=0 AND actual_micro>=0);
ALTER TABLE cost_estimates ADD CONSTRAINT finite_estimate CHECK(estimated_usd>=0 AND estimated_usd < 'Infinity'::numeric);
ALTER TABLE workflow_steps ADD CONSTRAINT step_status CHECK(status IN ('pending','running','succeeded','failed'));
ALTER TABLE workflow_steps ADD CONSTRAINT bounded_step_attempts CHECK(attempts BETWEEN 0 AND 3);
ALTER TABLE report_deliveries ADD CONSTRAINT bounded_delivery_attempts CHECK(attempts BETWEEN 0 AND 3);
CREATE INDEX platform_events_created_idx ON platform_events(created_at);
CREATE INDEX reports_alerts_created_idx ON report_alerts(created_at);
CREATE INDEX metadata_job_fk_idx ON submissions(job_id);
CREATE INDEX platform_channel_idx ON platform_events(platform,channel_id);
INSERT INTO schema_migrations(version) VALUES('runtime_integrity_v2');
COMMIT;
